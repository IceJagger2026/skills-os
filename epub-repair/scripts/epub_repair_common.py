#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import posixpath
import re
import sys
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urldefrag
from xml.etree import ElementTree as ET


DOUBLE_ESCAPED_NUMERIC_RE = re.compile(rb"&amp;#(?:\d+|x[0-9a-fA-F]+);")
MOJIBAKE_RE = re.compile(r"[\ufffd]|锟|Ã|Â")
HTML_EXTENSIONS = {".html", ".htm", ".xhtml"}
TEXT_EXTENSIONS = HTML_EXTENSIONS | {".xml", ".opf", ".ncx"}
XHTML_MEDIA_TYPES = {"application/xhtml+xml", "text/html"}
CHINESE_RE = re.compile(r"[\u4e00-\u9fff]")
PART_TITLE_RE = re.compile(r"^第[一二三四五六七八九十百千万0-9０-９]+部分")
CHAPTER_TITLE_RE = re.compile(r"^第[一二三四五六七八九十百千万0-9０-９]+章")
INTRO_TITLE_RE = re.compile(r"^(写给中国读者|专家导读|序言)$")
ASCII_QUESTION_BETWEEN_CHINESE_RE = re.compile(r"(?<=[\u4e00-\u9fff])\?(?=[\u4e00-\u9fff])")
ASCII_PAREN_CANDIDATE_RE = re.compile(r"\(([^()\n\r]{1,40})\)")


@dataclass
class HtmlIssue:
    path: str
    double_escaped_numeric_entities: int = 0
    mojibake_markers: int = 0
    examples: list[str] = field(default_factory=list)


@dataclass
class TocCandidate:
    kind: str
    text: str
    source_path: str


@dataclass
class TocDiagnostics:
    ncx_max_depth: int = 0
    ncx_is_flat: bool = False
    ncx_leaf_count: int = 0
    ncx_leaf_items: list[dict[str, str]] = field(default_factory=list)
    book_toc_path: str | None = None
    book_toc_candidates: list[TocCandidate] = field(default_factory=list)
    matched_chapters: int = 0
    unmatched_chapters: list[str] = field(default_factory=list)
    unclassified_leafs: list[str] = field(default_factory=list)


@dataclass
class PunctuationExample:
    path: str
    context: str


@dataclass
class PunctuationDiagnostics:
    ascii_question_between_chinese: int = 0
    ascii_question_examples: list[PunctuationExample] = field(default_factory=list)
    ascii_paren_candidates: int = 0
    ascii_paren_examples: list[PunctuationExample] = field(default_factory=list)
    cn_comma_after_chinese: int = 0
    cn_period_after_chinese: int = 0
    cn_colon_after_chinese: int = 0
    cn_semicolon_after_chinese: int = 0


@dataclass
class Diagnosis:
    input_path: str
    checked_at: str
    zip_ok: bool = False
    error: str | None = None
    container_path: str = "META-INF/container.xml"
    opf_path: str | None = None
    opf_found: bool = False
    ncx_path: str | None = None
    nav_path: str | None = None
    manifest_items: int = 0
    manifest_missing: list[str] = field(default_factory=list)
    spine_items: int = 0
    spine_missing_idrefs: list[str] = field(default_factory=list)
    spine_missing_files: list[str] = field(default_factory=list)
    toc_entries: int = 0
    toc_missing: list[str] = field(default_factory=list)
    nav_entries: int = 0
    nav_missing: list[str] = field(default_factory=list)
    html_files: int = 0
    html_issues: list[HtmlIssue] = field(default_factory=list)
    toc_diagnostics: TocDiagnostics = field(default_factory=TocDiagnostics)
    punctuation_diagnostics: PunctuationDiagnostics = field(default_factory=PunctuationDiagnostics)

    @property
    def double_escaped_file_count(self) -> int:
        return sum(1 for issue in self.html_issues if issue.double_escaped_numeric_entities)

    @property
    def double_escaped_total(self) -> int:
        return sum(issue.double_escaped_numeric_entities for issue in self.html_issues)

    @property
    def mojibake_file_count(self) -> int:
        return sum(1 for issue in self.html_issues if issue.mojibake_markers)


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def local_name(epub_path: Path) -> str:
    name = epub_path.name
    if name.lower().endswith(".epub"):
        return name[:-5]
    return epub_path.stem


def default_output_dir(epub_path: Path) -> Path:
    return epub_path.parent


def ensure_epub(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"EPUB not found: {path}")
    if not path.is_file():
        raise ValueError(f"EPUB path is not a file: {path}")
    if path.suffix.lower() != ".epub":
        raise ValueError(f"Expected .epub file, got: {path}")


def zip_names(zf: zipfile.ZipFile) -> set[str]:
    return {info.filename for info in zf.infolist()}


def read_entry_bytes(zf: zipfile.ZipFile, name: str) -> bytes:
    with zf.open(name) as fh:
        return fh.read()


def read_entry_text(zf: zipfile.ZipFile, name: str) -> str:
    data = read_entry_bytes(zf, name)
    for encoding in ("utf-8-sig", "utf-8", "gb18030", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def parse_xml(text: str) -> ET.Element:
    return ET.fromstring(text.encode("utf-8"))


def ns(tag: str) -> str:
    if tag.startswith("{") and "}" in tag:
        return tag[1:].split("}", 1)[0]
    return ""


def local_tag(tag: str) -> str:
    if tag.startswith("{") and "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def join_href(base: str | None, href: str) -> str:
    href = html.unescape(unquote(urldefrag(href)[0]))
    if not base:
        return posixpath.normpath(href)
    base_dir = posixpath.dirname(base)
    return posixpath.normpath(posixpath.join(base_dir, href))


def find_opf_path(zf: zipfile.ZipFile) -> str | None:
    names = zip_names(zf)
    if "META-INF/container.xml" in names:
        try:
            root = parse_xml(read_entry_text(zf, "META-INF/container.xml"))
            for elem in root.iter():
                if local_tag(elem.tag) == "rootfile":
                    full_path = elem.attrib.get("full-path")
                    if full_path:
                        return full_path
        except ET.ParseError:
            return None
    if "content.opf" in names:
        return "content.opf"
    for name in names:
        if name.lower().endswith(".opf"):
            return name
    return None


def parse_opf(zf: zipfile.ZipFile, opf_path: str) -> tuple[dict[str, dict[str, str]], list[str], str | None, str | None]:
    root = parse_xml(read_entry_text(zf, opf_path))
    manifest: dict[str, dict[str, str]] = {}
    spine_idrefs: list[str] = []
    ncx_id = None
    nav_path = None

    for elem in root.iter():
        tag = local_tag(elem.tag)
        if tag == "item":
            item_id = elem.attrib.get("id")
            href = elem.attrib.get("href")
            media_type = elem.attrib.get("media-type", "")
            properties = elem.attrib.get("properties", "")
            if item_id and href:
                full_href = join_href(opf_path, href)
                manifest[item_id] = {
                    "href": full_href,
                    "media_type": media_type,
                    "properties": properties,
                }
                if media_type == "application/x-dtbncx+xml":
                    ncx_id = item_id
                if "nav" in properties.split():
                    nav_path = full_href
        elif tag == "spine":
            ncx_id = elem.attrib.get("toc") or ncx_id
        elif tag == "itemref":
            idref = elem.attrib.get("idref")
            if idref:
                spine_idrefs.append(idref)

    ncx_path = manifest.get(ncx_id or "", {}).get("href") if ncx_id else None
    return manifest, spine_idrefs, ncx_path, nav_path


def ncx_sources(zf: zipfile.ZipFile, ncx_path: str) -> list[str]:
    root = parse_xml(read_entry_text(zf, ncx_path))
    sources = []
    for elem in root.iter():
        if local_tag(elem.tag) == "content":
            src = elem.attrib.get("src")
            if src:
                sources.append(join_href(ncx_path, src))
    return sources


def nav_sources(zf: zipfile.ZipFile, nav_path: str) -> list[str]:
    text = read_entry_text(zf, nav_path)
    hrefs = re.findall(r"""href\s*=\s*["']([^"']+)["']""", text, flags=re.IGNORECASE)
    return [join_href(nav_path, href) for href in hrefs if href and not href.startswith(("http://", "https://", "mailto:"))]


def visible_text(html_text: str) -> str:
    text = re.sub(r"<script\b[^>]*>.*?</script>", "", html_text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b[^>]*>.*?</style>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text)


def normalize_title(text: str) -> str:
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"《[^》]+》", "", text)
    text = re.sub(r"^第[一二三四五六七八九十百千万0-9０-９]+[章节部分]\s*", "", text)
    text = re.sub(r"[“”\"'‘’：:，,。．、\s\t　（）()\[\]【】\-—–·•&#0-9a-zA-Z;]", "", text)
    return text


def heading_text(html_text: str) -> str:
    match = re.search(r"<h[1-6]\b[^>]*>(.*?)</h[1-6]>", html_text, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    return visible_text(match.group(1)).strip()


def ncx_points(zf: zipfile.ZipFile, ncx_path: str) -> list[dict[str, str | int]]:
    root = parse_xml(read_entry_text(zf, ncx_path))
    points: list[dict[str, str | int]] = []

    def walk(elem: ET.Element, depth: int) -> None:
        if local_tag(elem.tag) == "navPoint":
            label = ""
            src = ""
            child_navpoints = [child for child in list(elem) if local_tag(child.tag) == "navPoint"]
            for child in elem.iter():
                if local_tag(child.tag) == "text" and child.text and not label:
                    label = html.unescape(child.text.strip())
                elif local_tag(child.tag) == "content" and not src:
                    src = child.attrib.get("src", "")
            points.append({"label": label, "src": join_href(ncx_path, src) if src else "", "depth": depth, "is_leaf": not child_navpoints})
            for child in child_navpoints:
                walk(child, depth + 1)

    for elem in root.iter():
        if local_tag(elem.tag) == "navMap":
            for child in list(elem):
                if local_tag(child.tag) == "navPoint":
                    walk(child, 1)
            break
    return points


def extract_book_toc_candidates(zf: zipfile.ZipFile, manifest_by_href: dict[str, dict[str, str]]) -> tuple[str | None, list[TocCandidate]]:
    html_names = [name for name in zf.namelist() if is_html_entry(name, manifest_by_href)]
    best_path = None
    best_score = -1
    best_lines: list[str] = []

    for name in html_names:
        text = read_entry_text(zf, name)
        score = 0
        title = heading_text(text)
        if "目录" in title:
            score += 10
        visible = visible_text(text)
        lines = [line.strip() for line in re.findall(r"<p\b[^>]*>(.*?)</p>", text, flags=re.IGNORECASE | re.DOTALL)]
        cleaned = [visible_text(line).strip() for line in lines]
        score += sum(1 for line in cleaned if PART_TITLE_RE.match(line) or CHAPTER_TITLE_RE.match(line))
        if score > best_score:
            best_score = score
            best_path = name
            best_lines = cleaned

    candidates: list[TocCandidate] = []
    if best_path and best_score > 0:
        for line in best_lines:
            line = re.sub(r"\s+", " ", line).strip()
            if not line:
                continue
            if PART_TITLE_RE.match(line):
                candidates.append(TocCandidate("part", line, best_path))
            elif CHAPTER_TITLE_RE.match(line):
                candidates.append(TocCandidate("chapter", line, best_path))
            elif INTRO_TITLE_RE.match(line):
                candidates.append(TocCandidate("intro", line, best_path))
    return best_path, candidates


def match_toc_candidates_to_ncx(candidates: list[TocCandidate], points: list[dict[str, str | int]]) -> tuple[int, list[str], list[str]]:
    leafs = [point for point in points if point.get("src") and point.get("is_leaf")]
    used_leaf_indexes: set[int] = set()
    matched_chapters = 0
    unmatched_chapters: list[str] = []

    for candidate in candidates:
        if candidate.kind not in {"intro", "chapter"}:
            continue
        candidate_norm = normalize_title(candidate.text)
        candidate_fragments = [frag for frag in re.split(r"[：:]", candidate.text, maxsplit=1) if frag.strip()]
        fragment_norms = [normalize_title(fragment) for fragment in candidate_fragments]
        matched = False
        for index, point in enumerate(leafs):
            if index in used_leaf_indexes:
                continue
            label_norm = normalize_title(str(point.get("label", "")))
            if not label_norm:
                continue
            if label_norm in candidate_norm or candidate_norm in label_norm or any(label_norm in frag or frag in label_norm for frag in fragment_norms if frag):
                used_leaf_indexes.add(index)
                matched = True
                matched_chapters += 1
                break
        if not matched:
            unmatched_chapters.append(candidate.text)

    unclassified = [str(point.get("label", "")) for index, point in enumerate(leafs) if index not in used_leaf_indexes]
    return matched_chapters, unmatched_chapters, unclassified


def diagnose_toc(zf: zipfile.ZipFile, ncx_path: str | None, manifest_by_href: dict[str, dict[str, str]]) -> TocDiagnostics:
    diagnostics = TocDiagnostics()
    if ncx_path and ncx_path in zip_names(zf):
        points = ncx_points(zf, ncx_path)
        leaf_points = [point for point in points if point.get("src") and point.get("is_leaf")]
        diagnostics.ncx_leaf_items = [
            {"label": str(point.get("label", "")), "src": str(point.get("src", ""))}
            for point in leaf_points
        ]
        diagnostics.ncx_leaf_count = len(leaf_points)
        diagnostics.ncx_max_depth = max((int(point.get("depth", 0)) for point in points), default=0)
        diagnostics.ncx_is_flat = diagnostics.ncx_leaf_count > 1 and diagnostics.ncx_max_depth <= 1
    else:
        points = []

    toc_path, candidates = extract_book_toc_candidates(zf, manifest_by_href)
    diagnostics.book_toc_path = toc_path
    diagnostics.book_toc_candidates = candidates
    matched, unmatched, unclassified = match_toc_candidates_to_ncx(candidates, points)
    diagnostics.matched_chapters = matched
    diagnostics.unmatched_chapters = unmatched
    diagnostics.unclassified_leafs = unclassified
    return diagnostics


def context_for(text: str, start: int, end: int, radius: int = 25) -> str:
    return text[max(0, start - radius): min(len(text), end + radius)].replace("\n", " ").strip()


def ascii_paren_matches(text: str) -> list[re.Match[str]]:
    matches = []
    for match in ASCII_PAREN_CANDIDATE_RE.finditer(text):
        inner = match.group(1)
        before = text[match.start() - 1] if match.start() > 0 else ""
        after = text[match.end()] if match.end() < len(text) else ""
        if CHINESE_RE.search(inner) or CHINESE_RE.search(before) or CHINESE_RE.search(after):
            matches.append(match)
    return matches


def diagnose_punctuation_in_text(path: str, text: str, diagnostics: PunctuationDiagnostics) -> None:
    question_matches = list(ASCII_QUESTION_BETWEEN_CHINESE_RE.finditer(text))
    diagnostics.ascii_question_between_chinese += len(question_matches)
    for match in question_matches[:8]:
        if len(diagnostics.ascii_question_examples) < 20:
            diagnostics.ascii_question_examples.append(PunctuationExample(path, context_for(text, match.start(), match.end())))

    paren_matches = ascii_paren_matches(text)
    diagnostics.ascii_paren_candidates += len(paren_matches)
    for match in paren_matches[:8]:
        if len(diagnostics.ascii_paren_examples) < 20:
            diagnostics.ascii_paren_examples.append(PunctuationExample(path, context_for(text, match.start(), match.end())))

    diagnostics.cn_comma_after_chinese += len(re.findall(r"[\u4e00-\u9fff],", text))
    diagnostics.cn_period_after_chinese += len(re.findall(r"[\u4e00-\u9fff]\.", text))
    diagnostics.cn_colon_after_chinese += len(re.findall(r"[\u4e00-\u9fff]:", text))
    diagnostics.cn_semicolon_after_chinese += len(re.findall(r"[\u4e00-\u9fff];", text))


def is_html_entry(name: str, manifest_by_href: dict[str, dict[str, str]]) -> bool:
    suffix = Path(name).suffix.lower()
    if suffix in HTML_EXTENSIONS:
        return True
    item = manifest_by_href.get(name)
    return bool(item and item.get("media_type") in XHTML_MEDIA_TYPES)


def text_for_mojibake(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace")


def diagnose_epub(epub_path: Path) -> Diagnosis:
    ensure_epub(epub_path)
    diagnosis = Diagnosis(input_path=str(epub_path), checked_at=utc_timestamp())

    try:
        with zipfile.ZipFile(epub_path, "r") as zf:
            bad_member = zf.testzip()
            if bad_member:
                diagnosis.error = f"ZIP CRC check failed at {bad_member}"
                return diagnosis
            diagnosis.zip_ok = True
            names = zip_names(zf)

            opf_path = find_opf_path(zf)
            diagnosis.opf_path = opf_path
            diagnosis.opf_found = bool(opf_path and opf_path in names)
            if not diagnosis.opf_found or not opf_path:
                diagnosis.error = "OPF package file not found"
                return diagnosis

            manifest, spine_idrefs, ncx_path, nav_path = parse_opf(zf, opf_path)
            manifest_by_href = {item["href"]: item for item in manifest.values()}
            diagnosis.manifest_items = len(manifest)
            diagnosis.spine_items = len(spine_idrefs)
            diagnosis.ncx_path = ncx_path
            diagnosis.nav_path = nav_path
            diagnosis.toc_diagnostics = diagnose_toc(zf, ncx_path, manifest_by_href)

            for item in manifest.values():
                href = item["href"]
                if href not in names:
                    diagnosis.manifest_missing.append(href)

            for idref in spine_idrefs:
                item = manifest.get(idref)
                if not item:
                    diagnosis.spine_missing_idrefs.append(idref)
                elif item["href"] not in names:
                    diagnosis.spine_missing_files.append(item["href"])

            if ncx_path and ncx_path in names:
                sources = ncx_sources(zf, ncx_path)
                diagnosis.toc_entries = len(sources)
                diagnosis.toc_missing = [src for src in sources if src not in names]

            if nav_path and nav_path in names:
                sources = nav_sources(zf, nav_path)
                diagnosis.nav_entries = len(sources)
                diagnosis.nav_missing = [src for src in sources if src not in names]

            for info in zf.infolist():
                name = info.filename
                if info.is_dir() or not is_html_entry(name, manifest_by_href):
                    continue
                data = read_entry_bytes(zf, name)
                double_matches = DOUBLE_ESCAPED_NUMERIC_RE.findall(data)
                decoded = text_for_mojibake(data)
                mojibake_count = len(MOJIBAKE_RE.findall(decoded))
                diagnose_punctuation_in_text(name, visible_text(decoded), diagnosis.punctuation_diagnostics)
                diagnosis.html_files += 1
                if double_matches or mojibake_count:
                    examples = []
                    for match in double_matches[:5]:
                        examples.append(match.decode("ascii", errors="replace"))
                    diagnosis.html_issues.append(
                        HtmlIssue(
                            path=name,
                            double_escaped_numeric_entities=len(double_matches),
                            mojibake_markers=mojibake_count,
                            examples=examples,
                        )
                    )
    except zipfile.BadZipFile as exc:
        diagnosis.error = f"Bad ZIP/EPUB file: {exc}"
    except Exception as exc:  # keep caller-facing failures reportable
        diagnosis.error = f"{type(exc).__name__}: {exc}"

    return diagnosis


def diagnosis_to_dict(diagnosis: Diagnosis) -> dict:
    return {
        "input_path": diagnosis.input_path,
        "checked_at": diagnosis.checked_at,
        "zip_ok": diagnosis.zip_ok,
        "error": diagnosis.error,
        "container_path": diagnosis.container_path,
        "opf_path": diagnosis.opf_path,
        "opf_found": diagnosis.opf_found,
        "ncx_path": diagnosis.ncx_path,
        "nav_path": diagnosis.nav_path,
        "manifest_items": diagnosis.manifest_items,
        "manifest_missing": diagnosis.manifest_missing,
        "spine_items": diagnosis.spine_items,
        "spine_missing_idrefs": diagnosis.spine_missing_idrefs,
        "spine_missing_files": diagnosis.spine_missing_files,
        "toc_entries": diagnosis.toc_entries,
        "toc_missing": diagnosis.toc_missing,
        "nav_entries": diagnosis.nav_entries,
        "nav_missing": diagnosis.nav_missing,
        "html_files": diagnosis.html_files,
        "double_escaped_file_count": diagnosis.double_escaped_file_count,
        "double_escaped_total": diagnosis.double_escaped_total,
        "mojibake_file_count": diagnosis.mojibake_file_count,
        "toc_diagnostics": {
            "ncx_max_depth": diagnosis.toc_diagnostics.ncx_max_depth,
            "ncx_is_flat": diagnosis.toc_diagnostics.ncx_is_flat,
            "ncx_leaf_count": diagnosis.toc_diagnostics.ncx_leaf_count,
            "ncx_leaf_items": diagnosis.toc_diagnostics.ncx_leaf_items,
            "book_toc_path": diagnosis.toc_diagnostics.book_toc_path,
            "book_toc_candidate_count": len(diagnosis.toc_diagnostics.book_toc_candidates),
            "book_toc_candidates": [
                {"kind": candidate.kind, "text": candidate.text, "source_path": candidate.source_path}
                for candidate in diagnosis.toc_diagnostics.book_toc_candidates
            ],
            "matched_chapters": diagnosis.toc_diagnostics.matched_chapters,
            "unmatched_chapters": diagnosis.toc_diagnostics.unmatched_chapters,
            "unclassified_leaf_count": len(diagnosis.toc_diagnostics.unclassified_leafs),
            "unclassified_leafs": diagnosis.toc_diagnostics.unclassified_leafs,
        },
        "punctuation_diagnostics": {
            "ascii_question_between_chinese": diagnosis.punctuation_diagnostics.ascii_question_between_chinese,
            "ascii_question_examples": [
                {"path": example.path, "context": example.context}
                for example in diagnosis.punctuation_diagnostics.ascii_question_examples
            ],
            "ascii_paren_candidates": diagnosis.punctuation_diagnostics.ascii_paren_candidates,
            "ascii_paren_examples": [
                {"path": example.path, "context": example.context}
                for example in diagnosis.punctuation_diagnostics.ascii_paren_examples
            ],
            "cn_comma_after_chinese": diagnosis.punctuation_diagnostics.cn_comma_after_chinese,
            "cn_period_after_chinese": diagnosis.punctuation_diagnostics.cn_period_after_chinese,
            "cn_colon_after_chinese": diagnosis.punctuation_diagnostics.cn_colon_after_chinese,
            "cn_semicolon_after_chinese": diagnosis.punctuation_diagnostics.cn_semicolon_after_chinese,
        },
        "html_issues": [
            {
                "path": issue.path,
                "double_escaped_numeric_entities": issue.double_escaped_numeric_entities,
                "mojibake_markers": issue.mojibake_markers,
                "examples": issue.examples,
            }
            for issue in diagnosis.html_issues
        ],
    }


def format_list(items: Iterable[str], empty: str = "None") -> str:
    values = list(items)
    if not values:
        return empty
    return "\n".join(f"- `{item}`" for item in values)


def repair_directions(diagnosis: Diagnosis) -> list[str]:
    directions = []
    if diagnosis.double_escaped_total:
        directions.append(f"Safe repair available: fix {diagnosis.double_escaped_total} double-escaped numeric HTML entities.")
    if diagnosis.punctuation_diagnostics.ascii_paren_candidates:
        directions.append(f"Safe repair available: normalize {diagnosis.punctuation_diagnostics.ascii_paren_candidates} ASCII parenthesis candidates in Chinese context.")
    if diagnosis.punctuation_diagnostics.ascii_question_between_chinese:
        directions.append(f"Manual review needed: {diagnosis.punctuation_diagnostics.ascii_question_between_chinese} '?' markers appear between Chinese characters and may indicate OCR/text loss.")
    if diagnosis.toc_diagnostics.book_toc_candidates:
        directions.append(f"Directory recognized: {len(diagnosis.toc_diagnostics.book_toc_candidates)} candidate TOC lines were extracted from `{diagnosis.toc_diagnostics.book_toc_path}`.")
    if diagnosis.toc_diagnostics.ncx_is_flat:
        if diagnosis.toc_diagnostics.book_toc_candidates and not (
            diagnosis.manifest_missing or diagnosis.spine_missing_idrefs or diagnosis.spine_missing_files or diagnosis.toc_missing or diagnosis.nav_missing
        ):
            directions.append("Safe directory repair available: rebuild flat NCX hierarchy from recognized directory evidence while preserving existing links.")
        else:
            directions.append("Directory issue detected: NCX is flat; directory repair requires explicit directory evidence and no missing references.")
    if diagnosis.manifest_missing or diagnosis.spine_missing_idrefs or diagnosis.spine_missing_files or diagnosis.toc_missing or diagnosis.nav_missing:
        directions.append("Structural issue detected: missing OPF/spine/TOC/nav references require manual review before repair.")
    if not directions:
        directions.append("No safe automatic repair direction detected by current rules.")
    return directions


def diagnosis_summary(diagnosis: Diagnosis) -> dict:
    toc = diagnosis.toc_diagnostics
    punctuation = diagnosis.punctuation_diagnostics
    structural_missing = (
        len(diagnosis.manifest_missing)
        + len(diagnosis.spine_missing_idrefs)
        + len(diagnosis.spine_missing_files)
        + len(diagnosis.toc_missing)
        + len(diagnosis.nav_missing)
    )
    return {
        "ok": diagnosis.error is None,
        "input_path": diagnosis.input_path,
        "error": diagnosis.error,
        "problem_summary": {
            "directory_text": {
                "book_toc_path": toc.book_toc_path,
                "recognized_directory_items": len(toc.book_toc_candidates),
                "recognized_from_book_toc_page": bool(toc.book_toc_candidates),
            },
            "directory_structure": {
                "ncx_path": diagnosis.ncx_path,
                "ncx_leaf_count": toc.ncx_leaf_count,
                "ncx_max_depth": toc.ncx_max_depth,
                "ncx_is_flat": toc.ncx_is_flat,
                "toc_missing_links": len(diagnosis.toc_missing),
                "nav_missing_links": len(diagnosis.nav_missing),
            },
            "body_text": {
                "html_files_scanned": diagnosis.html_files,
                "double_escaped_numeric_entities": diagnosis.double_escaped_total,
                "files_with_double_escaped_numeric_entities": diagnosis.double_escaped_file_count,
                "mojibake_files": diagnosis.mojibake_file_count,
                "ascii_parenthesis_candidates": punctuation.ascii_paren_candidates,
                "question_markers_between_chinese": punctuation.ascii_question_between_chinese,
            },
            "structure": {
                "zip_readable": diagnosis.zip_ok,
                "opf_path": diagnosis.opf_path,
                "manifest_items": diagnosis.manifest_items,
                "spine_items": diagnosis.spine_items,
                "missing_reference_count": structural_missing,
            },
        },
        "repair_directions": repair_directions(diagnosis),
    }


def recognized_toc_lines(diagnosis: Diagnosis) -> list[str]:
    lines = []
    for candidate in diagnosis.toc_diagnostics.book_toc_candidates:
        if candidate.kind in {"intro", "part"}:
            lines.append(f"{candidate.text}")
        elif candidate.kind == "chapter":
            lines.append(f"  {candidate.text}")
    return lines


def format_recognized_directory(diagnosis: Diagnosis) -> str:
    lines = []
    for candidate in diagnosis.toc_diagnostics.book_toc_candidates:
        if candidate.kind in {"intro", "part"}:
            lines.append(f"- {candidate.text}")
        elif candidate.kind == "chapter":
            lines.append(f"  - {candidate.text}")
    if not lines:
        return "No directory candidates recognized from the book TOC page."
    return "\n".join(lines)


def repair_verification_lines(repair_log: dict) -> list[str]:
    before = repair_log.get("before") or {}
    after = repair_log.get("after") or {}
    if not after:
        return ["- Post-repair verification: `Not available; no fixed EPUB was generated.`"]

    introduced_missing = any(
        after.get(key)
        for key in (
            "manifest_missing",
            "spine_missing_idrefs",
            "spine_missing_files",
            "toc_missing",
            "nav_missing",
        )
    )
    before_punctuation = before.get("punctuation_diagnostics") or {}
    after_punctuation = after.get("punctuation_diagnostics") or {}

    return [
        f"- Post-repair verification embedded: `true`",
        f"- ZIP readable after repair: `{after.get('zip_ok')}`",
        f"- OPF path after repair: `{after.get('opf_path') or 'Not found'}`",
        f"- Missing references introduced: `{introduced_missing}`",
        f"- Double-escaped numeric entities: `{before.get('double_escaped_total', 'unknown')} -> {after.get('double_escaped_total', 'unknown')}`",
        f"- ASCII parenthesis candidates: `{before_punctuation.get('ascii_paren_candidates', 'unknown')} -> {after_punctuation.get('ascii_paren_candidates', 'unknown')}`",
        f"- Chinese-context question markers after repair: `{after_punctuation.get('ascii_question_between_chinese', 'unknown')}`",
        "- Extra verification Markdown generated: `false`",
    ]


def directory_repair_prompt(diagnosis: Diagnosis) -> str:
    recognized_directory = format_recognized_directory(diagnosis)
    existing_items = "\n".join(
        f"- title: {item.get('label', '')}; href: {item.get('src', '')}"
        for item in diagnosis.toc_diagnostics.ncx_leaf_items[:160]
    ) or "- None captured in this report"
    notes = [
        f"NCX path: {diagnosis.ncx_path or 'Not found'}",
        f"NCX max depth: {diagnosis.toc_diagnostics.ncx_max_depth}",
        f"NCX appears flat: {diagnosis.toc_diagnostics.ncx_is_flat}",
        f"Book TOC path: {diagnosis.toc_diagnostics.book_toc_path or 'Not found'}",
        f"Book TOC candidates: {len(diagnosis.toc_diagnostics.book_toc_candidates)}",
        f"Unmatched chapter/intro candidates: {len(diagnosis.toc_diagnostics.unmatched_chapters)}",
    ]
    diagnosis_notes = "\n".join(f"- {note}" for note in notes)
    return f"""```text
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
{recognized_directory}

【现有 NCX/nav 目录项，含原始顺序和链接】
{existing_items}

【诊断备注】
{diagnosis_notes}

请输出 JSON，格式如下：
{{
  "directory_source_priority": "book_toc_page | existing_ncx_nav",
  "global_notes": ["你做了哪些保守修复"],
  "items": [
    {{
      "level": 1,
      "title": "修复后的目录标题",
      "original_title": "原始标题",
      "href": "原始链接，必须保留",
      "href_source": "existing_ncx_nav | book_toc_page | toc_snippet_search | heading_search | body_search | spine_order_inference",
      "children": [
        {{
          "level": 2,
          "title": "修复后的章节标题",
          "original_title": "原始章节标题",
          "href": "原始链接，必须保留",
          "href_source": "existing_ncx_nav | book_toc_page | toc_snippet_search | heading_search | body_search | spine_order_inference"
        }}
      ]
    }}
  ],
  "uncertain": [
    {{
      "original_title": "无法确定的原始标题",
      "href": "原始链接",
      "reason": "为什么不能安全归类或修复"
    }}
  ]
}}
```"""


def markdown_report(diagnosis: Diagnosis, repair_log: dict | None = None) -> str:
    data = diagnosis_to_dict(diagnosis)
    lines = [
        f"# EPUB Diagnosis: {Path(diagnosis.input_path).name}",
        "",
        "## Summary",
        "",
        f"- Checked at: `{diagnosis.checked_at}`",
        f"- ZIP readable: `{diagnosis.zip_ok}`",
        f"- Error: `{diagnosis.error or 'None'}`",
        f"- OPF path: `{diagnosis.opf_path or 'Not found'}`",
        f"- NCX path: `{diagnosis.ncx_path or 'Not found'}`",
        f"- Nav path: `{diagnosis.nav_path or 'Not found'}`",
        f"- Manifest items: `{diagnosis.manifest_items}`",
        f"- Spine items: `{diagnosis.spine_items}`",
        f"- TOC entries: `{diagnosis.toc_entries}`",
        f"- Nav entries: `{diagnosis.nav_entries}`",
        f"- HTML/XHTML files scanned: `{diagnosis.html_files}`",
        f"- Files with double-escaped numeric entities: `{diagnosis.double_escaped_file_count}`",
        f"- Total double-escaped numeric entities: `{diagnosis.double_escaped_total}`",
        f"- Files with mojibake markers: `{diagnosis.mojibake_file_count}`",
        f"- NCX max depth: `{diagnosis.toc_diagnostics.ncx_max_depth}`",
        f"- NCX appears flat: `{diagnosis.toc_diagnostics.ncx_is_flat}`",
        f"- Book TOC candidates: `{len(diagnosis.toc_diagnostics.book_toc_candidates)}`",
        f"- Matched TOC candidates: `{diagnosis.toc_diagnostics.matched_chapters}`",
        f"- Unclassified NCX leafs: `{len(diagnosis.toc_diagnostics.unclassified_leafs)}`",
        f"- ASCII question marks between Chinese characters: `{diagnosis.punctuation_diagnostics.ascii_question_between_chinese}`",
        f"- ASCII parenthesis candidates: `{diagnosis.punctuation_diagnostics.ascii_paren_candidates}`",
        "",
        "## Repair Directions",
        "",
        format_list(repair_directions(diagnosis)),
        "",
        "## Missing References",
        "",
        "### Manifest files missing from ZIP",
        "",
        format_list(diagnosis.manifest_missing),
        "",
        "### Spine idrefs missing from manifest",
        "",
        format_list(diagnosis.spine_missing_idrefs),
        "",
        "### Spine files missing from ZIP",
        "",
        format_list(diagnosis.spine_missing_files),
        "",
        "### TOC links missing from ZIP",
        "",
        format_list(diagnosis.toc_missing),
        "",
        "### Nav links missing from ZIP",
        "",
        format_list(diagnosis.nav_missing),
        "",
        "## TOC Diagnostics",
        "",
        f"- NCX max depth: `{diagnosis.toc_diagnostics.ncx_max_depth}`",
        f"- NCX leaf count: `{diagnosis.toc_diagnostics.ncx_leaf_count}`",
        f"- NCX appears flat: `{diagnosis.toc_diagnostics.ncx_is_flat}`",
        f"- Book TOC path: `{diagnosis.toc_diagnostics.book_toc_path or 'Not found'}`",
        f"- Book TOC candidates: `{len(diagnosis.toc_diagnostics.book_toc_candidates)}`",
        f"- Matched chapter/intro candidates: `{diagnosis.toc_diagnostics.matched_chapters}`",
        f"- Unmatched chapter/intro candidates: `{len(diagnosis.toc_diagnostics.unmatched_chapters)}`",
        f"- Unclassified NCX leafs: `{len(diagnosis.toc_diagnostics.unclassified_leafs)}`",
        "",
        "## Recognized Directory",
        "",
        format_recognized_directory(diagnosis),
        "",
        "## Directory Repair Prompt",
        "",
        directory_repair_prompt(diagnosis),
        "",
        "### Book TOC Candidates",
        "",
        format_list([f"{candidate.kind}: {candidate.text}" for candidate in diagnosis.toc_diagnostics.book_toc_candidates[:80]]),
        "",
        "### Unmatched Chapter/Intro Candidates",
        "",
        format_list(diagnosis.toc_diagnostics.unmatched_chapters[:80]),
        "",
        "### Unclassified NCX Leafs",
        "",
        format_list(diagnosis.toc_diagnostics.unclassified_leafs[:80]),
        "",
        "## Punctuation Diagnostics",
        "",
        f"- ASCII question marks between Chinese characters: `{diagnosis.punctuation_diagnostics.ascii_question_between_chinese}`",
        f"- ASCII parenthesis candidates: `{diagnosis.punctuation_diagnostics.ascii_paren_candidates}`",
        f"- Chinese followed by ASCII comma: `{diagnosis.punctuation_diagnostics.cn_comma_after_chinese}`",
        f"- Chinese followed by ASCII period: `{diagnosis.punctuation_diagnostics.cn_period_after_chinese}`",
        f"- Chinese followed by ASCII colon: `{diagnosis.punctuation_diagnostics.cn_colon_after_chinese}`",
        f"- Chinese followed by ASCII semicolon: `{diagnosis.punctuation_diagnostics.cn_semicolon_after_chinese}`",
        "",
        "### ASCII Question Examples",
        "",
        format_list(
            [
                f"{example.path}: {example.context}"
                for example in diagnosis.punctuation_diagnostics.ascii_question_examples
            ]
        ),
        "",
        "### ASCII Parenthesis Examples",
        "",
        format_list(
            [
                f"{example.path}: {example.context}"
                for example in diagnosis.punctuation_diagnostics.ascii_paren_examples
            ]
        ),
        "",
        "## Text Issues",
        "",
    ]

    if diagnosis.html_issues:
        for issue in diagnosis.html_issues[:50]:
            lines.extend(
                [
                    f"### `{issue.path}`",
                    "",
                    f"- Double-escaped numeric entities: `{issue.double_escaped_numeric_entities}`",
                    f"- Mojibake markers: `{issue.mojibake_markers}`",
                    f"- Examples: {', '.join(f'`{example}`' for example in issue.examples) if issue.examples else '`None`'}",
                    "",
                ]
            )
        if len(diagnosis.html_issues) > 50:
            lines.extend([f"_Only first 50 issue files shown out of {len(diagnosis.html_issues)}._", ""])
    else:
        lines.extend(["No HTML/XHTML text issues detected by current rules.", ""])

    if repair_log:
        lines.extend(
            [
                "## Repair",
                "",
                f"- Repair mode: `{repair_log.get('repair_mode')}`",
                f"- Fixed EPUB: `{repair_log.get('fixed_epub') or 'Not generated'}`",
                f"- Files changed: `{repair_log.get('files_changed', 0)}`",
                f"- Total replacements: `{repair_log.get('total_replacements', 0)}`",
                "",
                "## Post-Repair Verification",
                "",
                *repair_verification_lines(repair_log),
                "",
            ]
        )

    lines.extend(["## Raw Counts", "", "```json", json.dumps(data, ensure_ascii=False, indent=2), "```", ""])
    return "\n".join(lines)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("epub", type=Path, help="Path to a single .epub file")
    parser.add_argument("--output-dir", type=Path, default=None, help="Directory for generated reports and fixed EPUB")


def output_paths(epub_path: Path, output_dir: Path | None) -> tuple[Path, Path, Path]:
    out_dir = output_dir or default_output_dir(epub_path)
    base = local_name(epub_path)
    return (
        out_dir / f"{base}.diagnosis.md",
        out_dir / f"{base}.repair-log.json",
        out_dir / f"{base}.fixed.epub",
    )


def print_result(result: dict) -> None:
    json.dump(result, sys.stdout, ensure_ascii=True, indent=2)
    sys.stdout.write("\n")
