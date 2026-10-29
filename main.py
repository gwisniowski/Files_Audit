import argparse
import os
import tempfile
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from scanner import find_candidates, human, add_skip, TOOL_MARK, EXTRACTED_REASON
from llm import ask_batch, MODEL

# Typy plików, które zwykle są Twoją pracą. Model nie może ich oznaczyć jako USUN.
PROTECTED_EXT = {".docx", ".doc", ".xlsx", ".pptx", ".pdf", ".odt",
                 ".jpg", ".jpeg", ".png", ".py", ".cs", ".java", ".sln", ".csproj"}


def chunks(items, size):
    """Dzieli listę na kawałki po `size` elementów."""
    for i in range(0, len(items), size):
        yield items[i:i + size]


def limit_per_folder(candidates, root, depth=4, max_per_folder=15):
    """Zostawia co najwyżej max_per_folder kandydatów z jednego folderu (liczonego do głębokości depth)."""
    counts = {}
    result = []
    for f in candidates:
        parts = os.path.relpath(f["path"], root).split(os.sep)[:depth]
        folder = os.sep.join(parts)
        counts[folder] = counts.get(folder, 0) + 1
        if counts[folder] <= max_per_folder:
            result.append(f)
    return result


def apply_guardrails(f):
    """Twarde reguły nadrzędne nad modelem. Mogą tylko złagodzić werdykt USUN."""
    if f.get("verdict") != "USUN":
        return

    note = None
    if EXTRACTED_REASON in f["reasons"]:
        note = "zawartość folderu mogła zostać zmieniona po rozpakowaniu"
    elif os.path.splitext(f["path"])[1].lower() in PROTECTED_EXT:
        note = "to typ pliku, który zwykle jest Twoją pracą (dokument, zdjęcie, kod)"

    elif any(r.startswith(TOOL_MARK) for r in f["reasons"]):
        note = "tymi plikami zarządza inne narzędzie, usuwaj je jego poleceniami"

    if note:
        f["verdict"] = "SPRAWDZ"
        original = f.get("model_reason", "")
        f["model_reason"] = f"[program zmienił USUN na SPRAWDZ: {note}] Pierwotna opinia modelu: {original}"


def write_report(path, candidates, roots, model):
    titles = {
        "USUN": "Model sugeruje: można usunąć",
        "SPRAWDZ": "Model sugeruje: sprawdź samodzielnie",
        "ZOSTAW": "Model sugeruje: zostaw",
        "BRAK": "Bez opinii modelu",
    }
    groups = {key: [] for key in titles}
    for f in candidates:
        groups[f.get("verdict", "BRAK")].append(f)

    with open(path, "w", encoding="utf-8") as out:
        out.write("# Raport porządków na dysku\n\n")
        out.write(f"- Data: {datetime.now():%Y-%m-%d %H:%M}\n")
        out.write(f"- Skanowane: {', '.join(str(r) for r in roots)}\n")
        out.write(f"- Model: {model}\n\n")
        out.write("> To tylko sugestie. Żaden plik nie został ruszony.\n\n")

        for key, title in titles.items():
            items = groups[key]
            if not items:
                continue
            total = sum(f["size"] for f in items)
            out.write(f"## {title} ({len(items)} poz., razem {human(total)})\n\n")
            for f in sorted(items, key=lambda f: f["size"], reverse=True):
                out.write(f"- **[{key}]** `{f['path']}` — {human(f['size'])}\n")
                out.write(f"  - wytypowano: {'; '.join(f['reasons'])}\n")
                if f.get("model_reason"):
                    out.write(f"  - model: {f['model_reason']}\n")
            out.write("\n")


def parse_args():
    ap = argparse.ArgumentParser(description="Doradca porządków na dysku (nic nie usuwa).")
    ap.add_argument("paths", nargs="*", help="foldery do przeskanowania (domyślnie: cały dysk systemowy + Temp)")
    ap.add_argument("--model", default=MODEL, help="model Ollamy")
    ap.add_argument("--max-items", type=int, default=200, help="ilu kandydatów analizować")
    ap.add_argument("--batch-size", type=int, default=40, help="ile pozycji na jedno zapytanie")
    ap.add_argument("--no-llm", action="store_true", help="tylko lista, bez pytania modelu")
    ap.add_argument("--exclude", action="append", default=[], help="folder do pominięcia (można podać kilka razy)")
    ap.add_argument("--no-duplicates", action="store_true", help="pomiń szukanie duplikatów (szybciej)")
    ap.add_argument("--out", default="raport.md", help="plik raportu")
    return ap.parse_args()


def main():
    start = time.perf_counter()
    args = parse_args()

    for path in args.exclude:
        add_skip(path)

    if args.paths:
        roots = args.paths
    else:
        # cały dysk systemowy + folder Temp (AppData jest pomijany, ale w Temp zbierają się śmieci)
        roots = [Path.home().anchor, tempfile.gettempdir()]

    candidates = []
    for root in roots:
        print(f"Skanuję: {root}")
        found = find_candidates(root, check_duplicates=not args.no_duplicates)
        found.sort(key=lambda f: (len(f["reasons"]), f["size"]), reverse=True)
        candidates.extend(limit_per_folder(found, root))

    candidates.sort(key=lambda f: (len(f["reasons"]), f["size"]), reverse=True)
    candidates = candidates[:args.max_items]
    for i, f in enumerate(candidates, start=1):
        f["id"] = i
    print(f"Kandydatów: {len(candidates)}, razem {human(sum(f['size'] for f in candidates))}")

    if not args.no_llm:
        try:
            for batch in chunks(candidates, args.batch_size):
                print(f"Pytam model: pozycje {batch[0]['id']}-{batch[-1]['id']}...")
                answers = ask_batch(batch, model=args.model)
                for f in batch:
                    if f["id"] in answers:
                        f["verdict"], f["model_reason"] = answers[f["id"]]
                        apply_guardrails(f)
        except OSError as e:
            print(f"Nie udało się połączyć z Ollamą ({e}). Zapisuję raport bez opinii modelu.")

    print(Counter(f.get("verdict", "BRAK") for f in candidates))
    write_report(args.out, candidates, roots, "(bez modelu)" if args.no_llm else args.model)
    print(f"Gotowe. Raport: {Path(args.out).resolve()}")
    print(f"Czas: {time.perf_counter() - start:.0f} s")


if __name__ == "__main__":
    main()