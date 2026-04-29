# skills-os

Personal Codex skills repository.

This repository is public, so it should contain reusable skill instructions,
scripts, and non-sensitive references only. Keep private data, local paths,
tokens, book files, generated outputs, and personal workflow details out of
commits.

## Skills

| Skill | Purpose |
| --- | --- |
| `epub-repair` | Diagnose and safely repair one EPUB file through a diagnosis-first workflow. |

## Repository Rules

- Do not commit secrets, API keys, access tokens, private SSH keys, cookies, or
  `.env` files.
- Do not commit personal source files or generated artifacts such as EPUB/PDF
  files, repaired books, reports, logs, or verification output.
- Prefer generic examples like `/path/to/book.epub` instead of machine-specific
  paths or account names.
- Keep skill descriptions public-safe: avoid private project names, chat IDs,
  personal contacts, and internal infrastructure details.

## Pre-Commit Checks

Run these before publishing changes:

```powershell
git status --short
python -m py_compile epub-repair\scripts\diagnose_epub.py epub-repair\scripts\repair_epub.py epub-repair\scripts\epub_repair_common.py
rg -n --hidden -g '!**/.git/**' -g '!**/__pycache__/**' -g '!README.md' "(?i)(token|secret|password|passwd|api[_-]?key|authorization|bearer|private|ssh|chat_id|email|phone|C:\\Users|/Users/|/home/)"
```
