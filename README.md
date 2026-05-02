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
| `japan-local-coupon` | Find currently valid Japanese coupons and campaigns with source-backed expiry checks. |
| `apple-health-export-analysis` | Analyze unzipped Apple Health exports with a 30-day default window and cross-metric health-management insights. |

## Installation

This repo is organized as one skill per top-level directory. Each skill contains
its own `SKILL.md`, optional `scripts/`, optional `references/`, and optional
`agents/openai.yaml` metadata.

### OpenClaw or Codex-Compatible Installer

Use the GitHub repo plus skill path:

```powershell
python install-skill-from-github.py --repo IceJagger2026/skills-os --path epub-repair --name epub-repair --method git
```

For the Japan local coupon skill:

```powershell
python install-skill-from-github.py --repo IceJagger2026/skills-os --path japan-local-coupon --name japan-local-coupon --method git
```

For the Apple Health export analysis skill:

```powershell
python install-skill-from-github.py --repo IceJagger2026/skills-os --path apple-health-export-analysis --name apple-health-export-analysis --method git
```

If your installer accepts a URL instead of `owner/repo`, use:

```powershell
python install-skill-from-github.py --url https://github.com/IceJagger2026/skills-os --path epub-repair --name epub-repair --method git
```

### Hermes or Custom Runtime

Hermes can install from the machine-readable catalog:

```text
https://raw.githubusercontent.com/IceJagger2026/skills-os/main/skills.json
```

The catalog gives each skill's `name`, repo `path`, `entrypoint`, Python
requirements, and installer hints. A minimal Hermes installer only needs to:

1. Read `skills.json`.
2. Pick the skill by `name`.
3. Clone or download `path`.
4. Register `path/SKILL.md` as the skill entrypoint.
5. Execute bundled scripts relative to that skill directory.

For a Git-only install without a custom catalog parser:

```powershell
git clone --filter=blob:none --sparse https://github.com/IceJagger2026/skills-os.git
cd skills-os
git sparse-checkout set epub-repair
```

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
