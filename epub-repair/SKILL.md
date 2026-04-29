---
name: epub-repair
description: Diagnose and safely repair a single EPUB file passed by a local path, especially uploaded or downloaded books in a local automation workflow. Use when an EPUB has broken-looking text, punctuation problems, double-escaped numeric entities, or suspicious directory/TOC quality. The workflow is diagnosis first, then repair only after user confirmation.
modified: 2026-04-29 15:45:26 +09:00
modified_by: GPT-5 Codex
---

# EPUB Repair

Use this skill when a calling system receives an EPUB file, saves it locally, and needs an interactive diagnosis-first repair workflow.

The calling system owns transport concerns:

- It downloads or receives the source attachment.
- It passes the local EPUB path to this skill.
- It sends generated outputs back to the user.

## Two-Step Workflow

### Step 1: Immediate Diagnosis, No Files

After the caller uploads or downloads the EPUB to a local path, immediately diagnose it without writing any output files:

```bash
python scripts/diagnose_epub.py /path/to/book.epub --summary-only
```

Read the JSON summary from stdout and reply to the user with a short natural-language problem overview. Cover exactly these three areas:

- Directory text: whether the book directory page was found, whether directory entries were recognized, and whether title text looks suspicious.
- Directory structure: whether NCX/nav is missing, flat, or has broken links.
- Body text: double-escaped numeric entities, Chinese punctuation candidates, mojibake markers, and Chinese-context `?` markers.

Do not create `diagnosis.md`, `repair-log.json`, `verify/`, or any other file in Step 1.

End the Step 1 reply by asking whether the user wants to start repair. Do not repair until the user confirms.

### Step 2: Repair After Confirmation

After the user confirms, repair and generate a new EPUB file:

```bash
python scripts/repair_epub.py /path/to/book.epub --output-dir /path/to/out --repair-safe --repair-punctuation-safe --repair-directory-safe --epub-only
```

Normal Step 2 output:

- `<book-name>.fixed.epub`

Do not generate `diagnosis.md`, `repair-log.json`, or verification Markdown in the normal workflow. The command prints a verification summary to stdout; use it to tell the user what changed.

## Diagnosis Policy

Directory diagnosis:

- Prefer the book's own directory page as source evidence.
- If the book has no directory page, use the existing NCX/nav labels as fallback evidence.
- Do not delete, summarize, or rewrite directory content.
- Directory hierarchy repair is allowed in the normal workflow only when it can be derived from recognized book directory evidence and existing NCX/nav links.

## Safety Rules

- Never overwrite the original EPUB.
- Process one EPUB per invocation.
- Preserve original EPUB resource names, manifest IDs, spine order, TOC links, images, CSS, and metadata.
- Step 1 must not write files.
- Step 2 must generate a new EPUB copy, never modify the original.
- Do not modify directory files unless `--repair-directory-safe` is requested after user confirmation.
- Safe directory repair may rebuild NCX hierarchy only when:
  - the existing directory is flat or missing hierarchy;
  - the book's own directory page or existing NCX/nav labels provide explicit preface, part, and chapter evidence;
  - every original directory link target is preserved;
  - missing NCX/nav entries are supplemented only when the book directory page contains the item, then links are recovered by searching book TOC snippets, headings, and spine/html body text; if no direct hit exists, use the nearest defensible spine location and keep the item title from the book directory page;
  - no missing manifest, spine, TOC, or nav references are present before repair;
  - uncertain entries are retained in original order instead of dropped or guessed.
- Safe repair may fix only:
  - `&amp;#[0-9]+;`
  - `&amp;#x[0-9a-fA-F]+;`
  - conservative ASCII parentheses in Chinese context.
  - NCX hierarchy derived from recognized directory evidence while preserving links.
- Diagnose Chinese-context `?` as suspected OCR/text loss; do not guess replacements.
- Do not write Calibre metadata.
- Do not generate summaries, notes, quotes, or book analysis.

## Verification

After repair, diagnose the fixed EPUB internally and print verification to stdout. Confirm:

- ZIP opens successfully.
- OPF path is found.
- Missing manifest/spine/TOC/nav references are not introduced.
- Double-escaped numeric entity count is reduced.
- ASCII parenthesis candidates are reduced.
- NCX/nav links remain valid; when `--repair-directory-safe` is used, NCX hierarchy depth may increase but original link targets remain present.
- The original EPUB remains unchanged.
- No report Markdown or JSON file is generated in the normal workflow.

## Debug Reports

Only when the user explicitly asks for a written report, run:

```bash
python scripts/diagnose_epub.py /path/to/book.epub --write-report --output-dir /path/to/out
```

Written reports are debug artifacts, not part of the normal workflow.

Read `references/repair_rules.md` before expanding behavior.
