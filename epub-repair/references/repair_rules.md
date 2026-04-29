# EPUB Repair Rules

## Workflow Policy

This skill is a two-step workflow:

1. Diagnose immediately after upload/download, write no files, and reply with a short problem overview.
2. Repair only after the user confirms, then generate a new fixed EPUB file.

During step 1, every answer to the user should end by asking whether to start repair.

Step 1 output policy:

- Use `diagnose_epub.py --summary-only`.
- Do not create Markdown, JSON, temporary, or verification files.
- Reply to the user with an overview of directory text, directory structure, and body text problems.

Step 2 output policy:

- Use `repair_epub.py --repair-safe --repair-punctuation-safe --repair-directory-safe --epub-only`.
- Generate only the new fixed EPUB in the normal workflow.
- Do not create `diagnosis.md`, `repair-log.json`, `verify/`, or `*.fixed.diagnosis.md`.
- Use the command's stdout verification summary to tell the user what changed.

## Diagnostics

The diagnostic pass checks:

- Whether the EPUB is a readable ZIP archive.
- Whether `META-INF/container.xml` exists.
- Whether the OPF package path can be resolved.
- Manifest item count and missing manifest files.
- Spine item count and missing or unresolved spine idrefs.
- NCX TOC entry count and missing linked files.
- EPUB 3 nav file presence and missing linked files when detectable.
- HTML/XHTML files containing double-escaped numeric entities.
- HTML/XHTML files with common mojibake markers such as replacement characters.
- Chinese-context ASCII punctuation candidates.
- Chinese-context `?` markers, which are reported as suspected OCR/text loss.

## Directory Recognition

Directory recognition is diagnosis-first. It provides evidence for the user-facing problem overview; it is not final truth by itself.

The recognition algorithm should:

- Prefer the book's own directory page.
- If no directory page exists, fall back to the existing NCX/nav labels.
- Detect likely directory pages by headings such as `目录`.
- Extract plausible preface, part, and chapter lines.
- Filter out long summary paragraphs.
- Include recognized directory counts and structural status in the Step 1 user reply.

Recognized directory output format:

- Level 1:
  - preface-like entries such as `写给中国读者`, `专家导读`, and `序言`
  - every `第.*部分` line
- Level 2:
  - every `第.*章` line when at least one part exists
  - display these as indented child entries below the nearest preceding level-1 part
- If no part exists, chapters are level-1 entries.
- Do not include long summary paragraphs in the recognized directory.

The skill may repair `toc.ncx` hierarchy in the normal workflow only when the user has confirmed repair and `--repair-directory-safe` is used. OPF, spine, and EPUB3 nav must not be rebuilt unless nav support is implemented with the same link-preservation checks.

## Safe Directory Repair

Safe directory repair is normal repair behavior after user confirmation when `--repair-directory-safe` is requested.

Input evidence:

- Recognized directory from the book's own directory page.
- Existing NCX/nav labels and links.
- Diagnosis notes such as flat NCX, missing links, unmatched entries, or suspicious labels.
- Optional user corrections.

Directory repair must obey:

- Do not delete existing directory items unless the user explicitly says they are duplicates or non-directory noise.
- Do not invent new parts, chapters, or titles. Missing NCX/nav entries may be supplemented only when the book directory page already contains the item; recover links by searching book TOC snippets, headings, and spine/html body text. If no direct hit exists, use the nearest defensible spine location and record that the title came from the book directory page.
- Do not summarize or rename chapters for style.
- Prefer the book directory page. If it is missing or too damaged, use the existing NCX/nav structure.
- First correct obvious typo, encoding/OCR, punctuation, and full-width/half-width issues in labels.
- Then repair hierarchy only:
  - preface-like entries and parts are level 1;
  - chapters are level 2 under the nearest preceding part when parts exist;
  - chapters are level 1 when no parts exist.
- Preserve original reading order and every existing link target.
- Preserve existing links where they are already valid; for supplemented items, search the original text before assigning a link, and prefer the nearest matched spine/html location over leaving the book-directory item out of the NCX/nav.
- Return uncertain items in an `uncertain` list instead of guessing.
- Keep uncertain existing entries in the output directory in original order instead of dropping them.
- Do not run directory repair if manifest, spine, TOC, or nav references are already missing.
- Do not write OPF or spine changes as part of directory repair.

## Prompt-Based Directory Repair

Prompt-based directory repair remains optional advanced behavior for cases where rule-based safe repair cannot classify the directory evidence. Use it only if the user explicitly asks for manual/prompt-assisted directory files after seeing the diagnosis summary.

Directory repair prompt template:

```text
你是一个 EPUB 目录修复助手。请只根据我提供的证据整理目录，不要删除、编造或扩写任何新内容。

目标：
1. 先修复目录标题中的明显错别字、转码/OCR 错字、标点符号、全角/半角不一致问题。
2. 再补全目录缺失项。只允许补充“书籍目录页识别结果”中已经存在、但现有 NCX/nav 缺失的目录项。补充时先在书籍目录页摘要、正文标题、spine/html 正文中搜索对应落点；如果没有直接链接证据，也要在原文中按顺序寻找最近且最合理的正文位置补 href，并在 global_notes 中说明这是依据正文搜索/顺序推断补的链接。
3. 再修复目录层级。层级规则是：
   - 写给读者、导读、序言、前言、后记、附录等前置/后置项目作为一级目录。
   - “第...部分 / Part ...”作为一级目录。
   - 如果存在“部分”，所有“第...章 / Chapter ...”应作为最近一个“部分”的二级目录。
   - 如果全书不存在“部分”，章节就是一级目录。
4. 保留原有目录顺序和原有 link/src/href，不要重新排序；补充项插入到书籍目录页证明的位置，并标明 href 来源。
5. 不要编造书中不存在的部分、章节或标题；“补全”只限于书籍目录页已有的目录项，链接必须来自原 EPUB 中已有文件。
6. 不要删除已有目录项；如果你判断某项不是目录项或疑似重复，请放入 uncertain，不要直接丢弃。
7. 如果书籍目录页和现有 NCX/nav 冲突，优先相信书籍目录页；但必须保留现有链接，无法确定的项放入 uncertain。

输入证据：

【书籍目录页识别结果】
{{recognized_directory}}

【现有 NCX/nav 目录项，含原始顺序和链接】
{{existing_toc_items_with_links}}

【诊断备注】
{{diagnosis_notes}}

请输出 JSON，格式如下：
{
  "directory_source_priority": "book_toc_page | existing_ncx_nav",
  "global_notes": ["你做了哪些保守修复"],
  "items": [
    {
      "level": 1,
      "title": "修复后的目录标题",
      "original_title": "原始标题",
      "href": "原始链接，必须保留",
      "href_source": "existing_ncx_nav | book_toc_page | toc_snippet_search | heading_search | body_search | spine_order_inference",
      "children": [
        {
          "level": 2,
          "title": "修复后的章节标题",
          "original_title": "原始章节标题",
          "href": "原始链接，必须保留",
          "href_source": "existing_ncx_nav | book_toc_page | toc_snippet_search | heading_search | body_search | spine_order_inference"
        }
      ]
    }
  ],
  "uncertain": [
    {
      "original_title": "无法确定的原始标题",
      "href": "原始链接",
      "reason": "为什么不能安全归类或修复"
    }
  ]
}
```

## Supported Safe Repairs

- Replace double-escaped numeric HTML entities in HTML/XHTML content:
  - `&amp;#8226;` -> `&#8226;`
  - `&amp;#x2022;` -> `&#x2022;`
- Keep the numeric entity form instead of converting to Unicode text. This preserves compatibility with EPUB readers and avoids changing document encoding assumptions.
- Normalize ASCII parentheses in Chinese contexts:
  - `茶壶山风波(1)` -> `茶壶山风波（1）`
  - `(原稿144页倒数第二段)` -> `（原稿144页倒数第二段）`

- Rebuild safe directory hierarchy in NCX when explicit directory evidence is available:
  - preface-like entries and parts become level 1;
  - chapter entries become level 2 under the nearest preceding part when parts exist;
  - chapter entries become level 1 when no parts exist;
  - original link targets are preserved;
  - uncertain entries are kept in original order.

## Ambiguous Text Policy

Do not automatically replace `?` inside Chinese text. In observed samples, these markers often represent missing or corrupted source characters rather than true question marks. Report them with context and leave the text unchanged.

## Non-goals

- Batch processing.
- Calibre database updates.
- Metadata enrichment.
- Chapter rewriting.
- TOC reconstruction that drops links, invents entries, or changes OPF/spine.
- Prompt-produced NCX/nav rewriting without user confirmation.
- HTML beautification.
- Book summaries or notes.
- Transport or chat platform API handling.
