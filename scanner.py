import os
import sys
import time
import hashlib
from collections import defaultdict
from pathlib import Path

MB = 1024 * 1024

JUNK_EXT = {".tmp", ".bak", ".old", ".log", ".dmp", ".crdownload", ".part"}
INSTALLER_EXT = {".exe", ".msi", ".iso"}
ARCHIVE_EXT = {".zip", ".rar"}

def scan_files(root):
    """Przechodzi po folderach i zwraca (ścieżka, rozmiar) każdego pliku."""
    for dirpath , dirnames, filenames in os.walk(root):
        for name in filenames:
            full = os.path.join(dirpath, name)
            try:
                st = os.stat(full)
            except OSError:
                continue
            yield {"path": full, "size": st.st_size, "mtime": st.st_mtime}

def human(n):
    """Zamienia bajty na czytelny tekst, np. 1.5 GB."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"

#Funkcja obliczająca hash zawartosci pliku(do sprawdzenia duplikatów)
def file_hash(path, limit=None):
    """Zwraca hash pliku. Z limit=N tylko z pierwszych N bajtów."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            if limit:
                h.update(fh.read(limit))
            else:
                while True:
                    chunk = fh.read(1024 * 1024)
                    if not chunk:
                        break
                    h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()

#Funkcja szukająca duplikatów
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
        for f in same_size :
            q = file_hash(f["path"], limit= 64 * 1024)
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
                

#Funkcje Heurystyki, każda zwraca powod lub none
def reason_big(f, min_mb=100):
    if f["size"] > min_mb * MB:
        return f"duży plik ({human(f['size'])})"

def reason_stale(f, days=365):
    age_days= (time.time() - f["mtime"]) / 86400
    if f["size"] >= MB and age_days > days:
        return f"nie zmieniany od {int(age_days)} dni"

def reason_junk(f):
    ext=os.path.splitext(f["path"])[1].lower()
    if ext in JUNK_EXT:
        return f"typowy plik tymczasowy ({ext})"

def reason_installer(f):
    ext=os.path.splitext(f["path"])[1].lower()
    if ext in INSTALLER_EXT and f["size"] >= 5 * MB:
        return f"instalator lub obraz dysku ({ext})"

def reason_archive(f):
    ext=os.path.splitext(f["path"])[1].lower()
    if ext in ARCHIVE_EXT and f["size"] >= 1 * MB:
        return f"archiwum ({ext})"


HEURISTICS = [reason_big, reason_stale, reason_junk, reason_installer, reason_archive]

def find_candidates(root, check_duplicates=True):
    by_path = {}
    all_files = []

    for f in scan_files(root):
        if f["size"] >=MB:
            all_files.append(f)

        reasons = [r for r in (check(f) for check in HEURISTICS) if r]
        if reasons :
            f["reasons"] = reasons
            by_path[f["path"]] = f

    if check_duplicates:
        for number, group in enumerate(find_duplicate_groups(all_files), start=1):
            for f in group:
                f.setdefault("reasons", [])
                f["reasons"].append(f"duplikat ({len(group)} kopie, grupa D{number})")
                by_path[f["path"]] = f

    return list(by_path.values())


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else Path.home() / "Programy"
    candidates = find_candidates(root)
    candidates.sort(key = lambda f: (len(f["reasons"]), f["size"]), reverse=True)

    total = sum(f["size"] for f in candidates)
    print(f"kandydatow: {len(candidates)}, razem: {human(total)}\n") 
    for f in candidates[:20]:
        print(f"{human(f['size']):>10} {f['path']}")
        print(f"            powody: {'; '.join(f['reasons'])}")     