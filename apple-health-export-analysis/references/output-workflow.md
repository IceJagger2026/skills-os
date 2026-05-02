# Output Workflow

Use this reference whenever running an Apple Health export analysis that creates intermediate or final files.

## Timestamped Run Directory

Create one timestamped folder for every analysis run before writing generated files.

Preferred location:

```text
analysis-runs/YYYYMMDD-HHMMSS/
```

Use local time for the timestamp. Example:

```text
analysis-runs/20260502-213045/
```

If the user asks for a different output location, create the same timestamped folder under that location.

## Files To Put There

Put all generated artifacts in the run directory, including:

- filtered or parsed JSON summaries
- derived metrics JSON
- report Markdown
- report HTML
- temporary CSV extracts
- charts, screenshots, or rendered static assets
- logs from parsing or validation

Do not write generated files into the skill root, repository root, or the user's export folder unless the user explicitly asks for that location.

## Naming

Use stable names inside the timestamped folder:

```text
summary.json
derived.json
daily.csv
report.md
report.html
parse.log
```

Only add suffixes when producing multiple report variants, such as `report-30d.md` and `report-90d.md`.

## Encoding Rules

Prevent mojibake by writing all generated text files with an explicit Unicode encoding.

Required encodings:

- `summary.json`, `derived.json`, and other JSON: UTF-8 without ASCII escaping (`ensure_ascii=False` in Python).
- `daily.csv`: UTF-8 with BOM (`utf-8-sig`) for Windows Excel compatibility.
- `report.md`: UTF-8 without BOM (`utf-8`). This is the most portable Markdown encoding for editors, GitHub, and preview tools.
- `report.html`: UTF-8 without BOM (`utf-8`) and a `<meta charset="utf-8">` tag.
- `parse.log`: UTF-8.

Do not pass non-ASCII report bodies through PowerShell heredocs, command-line arguments, `echo`, `Set-Content` without `-Encoding utf8BOM`, or shell pipes. These paths can replace Chinese text with `?` on Windows.

Preferred pattern:

```python
from pathlib import Path
import html
import json

run_dir = Path("analysis-runs/20260502-213045")

(run_dir / "summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2),
    encoding="utf-8",
)

(run_dir / "daily.csv").write_text(csv_text, encoding="utf-8-sig")

(run_dir / "report.md").write_text(report_markdown, encoding="utf-8")

report_html = (
    '<!doctype html><html lang="zh-CN"><head>'
    '<meta charset="utf-8"><title>Apple Health Analysis</title>'
    '</head><body><pre>'
    + html.escape(report_markdown)
    + '</pre></body></html>'
)
(run_dir / "report.html").write_text(report_html, encoding="utf-8")
```

After writing files that contain non-ASCII text, read them back and check for encoding damage:

```python
for name in ["report.md", "report.html"]:
    text = (run_dir / name).read_text(encoding="utf-8")
    if "\ufffd" in text:
        raise RuntimeError(f"{name} contains replacement characters")
    if text.count("?") > 0 and any(ord(ch) > 127 for ch in report_markdown):
        # A small number of literal question marks may be legitimate, but
        # repeated question marks in Chinese prose usually means mojibake.
        raise RuntimeError(f"{name} may contain mojibake question marks")
```

## Response

When finishing, include the run directory path and the most important generated files. Do not paste large JSON or raw tables into the chat unless the user asks.
