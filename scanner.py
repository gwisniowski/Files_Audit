import hashlib
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

TOOL_MARK = "zarządzane przez narzędzie:"

TOOL_MANAGED = {
    "\\.ollama\\": "modele Ollamy, usuwaj poleceniem `ollama rm <nazwa modelu>`",
    "\\.cache\\huggingface\\": "cache Hugging Face, usuwaj narzędziem `huggingface-cli delete-cache`",
    "\\virtualbox vms\\": "maszyna wirtualna, usuwaj z poziomu VirtualBox (Usuń → Usuń wszystkie pliki)",
    "\\flutter\\bin\\cache\\": "cache SDK Fluttera, nie usuwaj pojedynczych plików",
}

MB = 1024 * 1024
MIN_DUP_SIZE = 10 * MB    # duplikaty szukamy tylko wśród plików >= 10 MB

JUNK_EXT = {".tmp", ".bak", ".old", ".log", ".dmp", ".crdownload", ".part"}
INSTALLER_EXT = {".exe", ".msi", ".iso"}
INSTALLER_HINTS = ("setup", "set-up", "install")
ARCHIVE_EXT = {".zip", ".rar"}

EXTRACTED_REASON = "obok jest folder o tej samej nazwie (prawdopodobnie rozpakowana zawartość)"

# --- Co pomijamy przy skanowaniu ---------------------------------------------

SKIP_NAMES = {".git", "$recycle.bin", "system volume information", "appdata", "windows.old"}
SKIP_FILES = {"pagefile.sys", "hiberfil.sys", "swapfile.sys"}

# os.path.isjunction istnieje od Pythona 3.12; dla starszych wersji udajemy, że nic nie jest junctionem
_isjunction = getattr(os.path, "isjunction", lambda p: False)


def _system_prefixes():
    prefixes = []
    for var in ("SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
        value = os.environ.get(var)
        if value:
            prefixes.append(os.path.normcase(os.path.abspath(value)))
    return prefixes


SKIP_PREFIXES = _system_prefixes()


def add_skip(path):
    """Dodaje folder do pominięcia (z opcji --exclude)."""
    SKIP_PREFIXES.append(os.path.normcase(os.path.abspath(path)))


def should_skip(dirpath, name):
    full = os.path.join(dirpath, name)
    if name.lower() in SKIP_NAMES:
        return True
    if os.path.islink(full) or _isjunction(full):
        return True
    norm = os.path.normcase(os.path.abspath(full))
    return any(norm == p or norm.startswith(p + os.sep) for p in SKIP_PREFIXES)


# --- Narzędzia ---------------------------------------------------------------

def human(n):
    """Zamienia bajty na czytelny tekst, np. 1.5 GB."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def scan_files(root):
    """Przechodzi po folderach i zwraca słownik {path, size, mtime} dla każdego pliku."""
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root):
        # dirnames[:] podmienia zawartość TEJ SAMEJ listy, więc os.walk nie wejdzie do pominiętych folderów
        dirnames[:] = [d for d in dirnames if not should_skip(dirpath, d)]
        for name in filenames:
            if name.lower() in SKIP_FILES:
                continue
            seen += 1
            if seen % 100_000 == 0:
                print(f"  przejrzano {seen} plików...")
            full = os.path.join(dirpath, name)
            try:
                st = os.stat(full)
            except OSError:
                continue
            yield {"path": full, "size": st.st_size, "mtime": st.st_mtime}


# --- Heurystyki: każda zwraca powód (tekst) albo None -------------------------

def reason_tool_managed(f):
    low = f["path"].lower()
    for key, advice in TOOL_MANAGED.items():
        if key in low:
            return f"{TOOL_MARK} {advice}"
        
def reason_big(f, min_mb=100):
    if f["size"] >= min_mb * MB:
        return f"duży plik ({human(f['size'])})"


def reason_stale(f, days=365):
    age_days = (time.time() - f["mtime"]) / 86400
    if f["size"] >= MB and age_days > days:
        return f"nie zmieniany od {int(age_days)} dni"


def reason_junk(f):
    ext = os.path.splitext(f["path"])[1].lower()
    if ext in JUNK_EXT:
        return f"typowy plik tymczasowy ({ext})"


def reason_installer(f):
    if f["size"] < 5 * MB:
        return None
    name = os.path.basename(f["path"]).lower()
    ext = os.path.splitext(name)[1]
    if ext in {".iso", ".msi"} or (ext == ".exe" and any(h in name for h in INSTALLER_HINTS)):
        return f"instalator lub obraz dysku ({ext})"


def reason_archive(f):
    ext = os.path.splitext(f["path"])[1].lower()
    if ext in ARCHIVE_EXT and f["size"] >= MB:
        return f"archiwum ({ext})"


def reason_extracted_archive(f):
    base, ext = os.path.splitext(f["path"])
    if ext.lower() in ARCHIVE_EXT and os.path.isdir(base):
        return EXTRACTED_REASON


HEURISTICS = [reason_big, reason_stale, reason_junk, reason_installer,
              reason_archive, reason_extracted_archive, reason_tool_managed]


# --- Duplikaty ---------------------------------------------------------------

def file_hash(path, limit=None):
    """Zwraca hash pliku. Z limit=N tylko z pierwszych N bajtów."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            if limit:
                h.update(fh.read(limit))
            else:
                while True:
                    chunk = fh.read(1024 * 1024)   # po 1 MB
                    if not chunk:
                        break
                    h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def find_duplicate_groups(files):
    """Zwraca listę grup plików o identycznej zawartości."""
    by_size = defaultdict(list)
    for f in files:
        by_size[f["size"]].append(f)

    groups = []
    for same_size in by_size.values():
        if len(same_size) < 2:
            continue

        by_quick = defaultdict(list)
        for f in same_size:
            q = file_hash(f["path"], limit=64 * 1024)
            if q:
                by_quick[q].append(f)

        for same_quick in by_quick.values():
            if len(same_quick) < 2:
                continue

            by_full = defaultdict(list)
            for f in same_quick:
                h = file_hash(f["path"])
                if h:
                    by_full[h].append(f)

            groups.extend(g for g in by_full.values() if len(g) > 1)
    return groups


# --- Mapa zajętości folderów -------------------------------------------------

def add_folder_size(sizes, root, path, size, depth=3):
    """Dolicza rozmiar pliku do folderów-przodków (do głębokości `depth` od root)."""
    rel = os.path.relpath(os.path.dirname(path), root)
    parts = [] if rel == "." else rel.split(os.sep)
    for level in range(min(len(parts), depth) + 1):
        sizes[os.path.join(root, *parts[:level])] += size


# --- Główna funkcja ----------------------------------------------------------

def find_candidates(root, check_duplicates=True, folder_sizes=None):
    by_path = {}
    dup_pool = []

    for f in scan_files(root):
        if folder_sizes is not None:
            add_folder_size(folder_sizes, root, f["path"], f["size"])
        if f["size"] >= MIN_DUP_SIZE:
            dup_pool.append(f)
        reasons = [r for r in (check(f) for check in HEURISTICS) if r]
        if reasons:
            f["reasons"] = reasons
            by_path[f["path"]] = f

    if check_duplicates:
        for number, group in enumerate(find_duplicate_groups(dup_pool), start=1):
            for f in group:
                f.setdefault("reasons", [])
                f["reasons"].append(f"duplikat ({len(group)} kopie, grupa D{number})")
                by_path[f["path"]] = f

    return list(by_path.values())


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else str(Path.home() / "Downloads")
    candidates = find_candidates(root, check_duplicates=False)
    candidates.sort(key=lambda f: (len(f["reasons"]), f["size"]), reverse=True)

    total = sum(f["size"] for f in candidates)
    print(f"Kandydatów: {len(candidates)}, razem: {human(total)}\n")
    for f in candidates[:20]:
        print(f"{human(f['size']):>10} {f['path']}")
        print(f"            powody: {'; '.join(f['reasons'])}")