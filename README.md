# Files_Audit

A Python tool that scans your disk for large, old, duplicated or temporary files, asks a **local LLM (via [Ollama](https://ollama.com))** what looks safe to clean up, and writes a Markdown report with its suggestions.

**It never deletes anything.** The output is a report; every decision stays with you.

## How it works

1. **Scan** – walks the disk, skipping system folders, and picks candidates using simple heuristics:
   - large files
   - old, long-untouched files
   - temporary and junk files
   - installers
   - archives and folders that were already extracted
   - duplicates
2. **Ask the model** – candidates are sent to a local Ollama model in batches. For each file it returns a verdict with a short reason:
   - `USUN` – can probably be removed
   - `SPRAWDZ` – check it yourself
   - `ZOSTAW` – keep it
3. **Apply guardrails** – hard rules override the model and can only make a verdict *safer*. A `USUN` is downgraded to `SPRAWDZ` when the file:
   - is a type that is usually your own work (documents, images, source code: `.docx`, `.pdf`, `.xlsx`, `.jpg`, `.py`, `.cs`, ...)
   - comes from a folder that may have been modified after extraction
   - is managed by another tool (it should be removed with that tool's own commands)
4. **Report** – results are grouped by verdict and sorted by size, with the reasons the file was picked and the model's opinion.

Because the model is local, no file names or paths leave your machine.

## Requirements

- Python 3.14 (developed and tested on 3.14.1); no third-party packages, standard library only
- [Ollama](https://ollama.com) running locally with at least one model pulled, e.g.:

  ```
  ollama pull qwen3:4b
  ```

- Windows is the primary target (the default scan covers the system drive and the Temp folder).

## Usage

Scan specific folders:

```
python main.py C:\Studia --out raport.md
```

Scan the whole system drive (default) while skipping some folders:

```
python main.py --exclude "C:\Games" --exclude "D:\Backup"
```

Quick run without the model (just the list of candidates):

```
python main.py C:\Studia --no-llm
```

### Options

| Option | Description | Default |
|---|---|---|
| `paths` | folders to scan | system drive + Temp |
| `--model` | Ollama model name | set in `llm.py` |
| `--max-items` | how many candidates to analyze | `200` |
| `--batch-size` | items per model request | `40` |
| `--no-llm` | skip the model, only list candidates | off |
| `--exclude` | folder to skip (repeatable) | none |
| `--no-duplicates` | skip duplicate detection (faster) | off |
| `--out` | report file | `raport.md` |

## Example report

The paths below are made up for illustration.

```markdown
# Raport porządków na dysku

- Data: 2026-10-31 14:20
- Skanowane: C:\, C:\Users\user\AppData\Local\Temp
- Model: qwen3:4b

> To tylko sugestie. Żaden plik nie został ruszony.

## Model sugeruje: można usunąć (1 poz., razem 1.2 GB)

- **[USUN]** `C:\Users\user\Downloads\setup_old_installer.exe` — 1.2 GB
  - wytypowano: duży plik; instalator; starszy niż rok
  - model: stary instalator, program jest już zainstalowany
```

## Project structure

| File | Role |
|---|---|
| `main.py` | CLI, batching, guardrails, report generation |
| `scanner.py` | disk walk, heuristics, duplicate detection |
| `llm.py` | communication with Ollama |

## Why local?

The tool looks at your private files, so a local model keeps that data on your machine. It also costs nothing to run.

## Limitations

- A small local model can be wrong, which is why the report is only a set of suggestions and the guardrails exist.
- Verdicts are based on file names, paths, sizes and dates, not on file contents.
- Full-disk scans with duplicate detection can take a while; use `--no-duplicates` or `--exclude` to speed them up.
