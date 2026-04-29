#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import re
import zipfile
from xml.etree import ElementTree as ET

from epub_repair_common import (
    ASCII_PAREN_CANDIDATE_RE,
    DOUBLE_ESCAPED_NUMERIC_RE,
    add_common_args,
    diagnose_epub,
    diagnosis_summary,
    diagnosis_to_dict,
    is_html_entry,
    local_tag,
    markdown_report,
    normalize_title,
    output_paths,
    parse_xml,
    parse_opf,
    print_result,
    read_entry_bytes,
    read_entry_text,
    visible_text,
    write_json,
    write_text,
    zip_names,
)


def copy_info(info: zipfile.ZipInfo) -> zipfile.ZipInfo:
    copied = zipfile.ZipInfo(info.filename, info.date_time)
    copied.comment = info.comment
    copied.extra = info.extra
    copied.internal_attr = info.internal_attr
    copied.external_attr = info.external_attr
    copied.create_system = info.create_system
    copied.compress_type = info.compress_type
    return copied


def repair_double_escaped_numeric_entities(data: bytes) -> tuple[bytes, int]:
    count = len(DOUBLE_ESCAPED_NUMERIC_RE.findall(data))
    if not count:
        return data, 0
    return data.replace(b"&amp;#", b"&#"), count


def should_convert_ascii_parens(text: str, match: re.Match[str]) -> bool:
    inner = match.group(1)
    before = text[match.start() - 1] if match.start() > 0 else ""
    after = text[match.end()] if match.end() < len(text) else ""
    return bool(re.search(r"[\u4e00-\u9fff]", inner + before + after))


def repair_ascii_parentheses(data: bytes) -> tuple[bytes, int]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data, 0

    count = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal count
        if not should_convert_ascii_parens(text, match):
            return match.group(0)
        count += 1
        return f"（{match.group(1)}）"

    repaired = ASCII_PAREN_CANDIDATE_RE.sub(replace, text)
    if not count:
        return data, 0
    return repaired.encode("utf-8"), count


def ncx_namespace(root: ET.Element) -> str:
    if root.tag.startswith("{") and "}" in root.tag:
        return root.tag[1:].split("}", 1)[0]
    return ""


def ncx_tag(namespace: str, tag: str) -> str:
    return f"{{{namespace}}}{tag}" if namespace else tag


def first_child_text(elem: ET.Element, tag: str) -> str:
    for child in elem.iter():
        if local_tag(child.tag) == tag and child.text:
            return html.unescape(child.text.strip())
    return ""


def first_content_src(elem: ET.Element) -> str:
    for child in elem.iter():
        if local_tag(child.tag) == "content":
            return child.attrib.get("src", "")
    return ""


def matches_toc_title(label: str, candidate_text: str) -> bool:
    label_norm = normalize_title(label)
    candidate_norm = normalize_title(candidate_text)
    if not label_norm or not candidate_norm:
        return False
    fragments = [normalize_title(part) for part in re.split(r"[：:]", candidate_text, maxsplit=1)]
    return label_norm in candidate_norm or candidate_norm in label_norm or any(
        fragment and (label_norm in fragment or fragment in label_norm)
        for fragment in fragments
    )


def find_candidate_leaf_indexes(candidates, labels: list[str]) -> dict[int, int]:
    matches: dict[int, int] = {}
    used: set[int] = set()
    for candidate_index, candidate in enumerate(candidates):
        if candidate.kind not in {"intro", "chapter"}:
            continue
        for leaf_index, label in enumerate(labels):
            if leaf_index in used:
                continue
            if matches_toc_title(label, candidate.text):
                matches[candidate_index] = leaf_index
                used.add(leaf_index)
                break
    return matches


def build_part_groups(candidates, labels: list[str]) -> list[tuple[str, int, int]]:
    candidate_leaf_indexes = find_candidate_leaf_indexes(candidates, labels)
    groups: list[tuple[str, int, int]] = []
    part_positions = [index for index, candidate in enumerate(candidates) if candidate.kind == "part"]
    for part_number, part_candidate_index in enumerate(part_positions):
        next_part_index = part_positions[part_number + 1] if part_number + 1 < len(part_positions) else len(candidates)
        child_indexes = [
            leaf_index
            for candidate_index, leaf_index in candidate_leaf_indexes.items()
            if part_candidate_index < candidate_index < next_part_index
        ]
        if child_indexes:
            groups.append((html.unescape(candidates[part_candidate_index].text), min(child_indexes), max(child_indexes)))

    groups.sort(key=lambda item: item[1])
    bounded: list[tuple[str, int, int]] = []
    for index, (title, start, end) in enumerate(groups):
        next_start = groups[index + 1][1] if index + 1 < len(groups) else len(labels)
        bounded.append((title, start, max(end, next_start - 1)))
    return bounded


def renumber_play_order(navpoints: list[ET.Element]) -> None:
    order = 1

    def walk(point: ET.Element) -> None:
        nonlocal order
        point.set("playOrder", str(order))
        order += 1
        for child in list(point):
            if local_tag(child.tag) == "navPoint":
                walk(child)

    for navpoint in navpoints:
        walk(navpoint)


def make_part_navpoint(namespace: str, title: str, src: str, index: int) -> ET.Element:
    point = ET.Element(ncx_tag(namespace, "navPoint"), {"class": "part", "id": f"safe_part_{index}"})
    label = ET.SubElement(point, ncx_tag(namespace, "navLabel"))
    text = ET.SubElement(label, ncx_tag(namespace, "text"))
    text.text = title
    ET.SubElement(point, ncx_tag(namespace, "content"), {"src": src})
    return point


def make_toc_navpoint(namespace: str, nav_class: str, point_id: str, title: str, src: str) -> ET.Element:
    point = ET.Element(ncx_tag(namespace, "navPoint"), {"class": nav_class, "id": point_id})
    label = ET.SubElement(point, ncx_tag(namespace, "navLabel"))
    text = ET.SubElement(label, ncx_tag(namespace, "text"))
    text.text = html.unescape(title)
    ET.SubElement(point, ncx_tag(namespace, "content"), {"src": src})
    return point


def search_terms(title: str) -> list[str]:
    title = html.unescape(title)
    values = [title]
    for separator in ("：", ":"):
        if separator in title:
            values.append(title.split(separator, 1)[1])
    match = re.search(r"第[一二三四五六七八九十百千万0-9]+章\s*(.+)", title)
    if match:
        values.append(match.group(1))
    return [term for value in values if (term := normalize_title(value)) and len(term) >= 4]


def toc_following_snippets(zf: zipfile.ZipFile, diagnosis) -> dict[int, str]:
    toc_path = diagnosis.toc_diagnostics.book_toc_path
    candidates = diagnosis.toc_diagnostics.book_toc_candidates
    if not toc_path or toc_path not in zf.namelist():
        return {}
    try:
        text = read_entry_text(zf, toc_path)
    except Exception:
        return {}
    lines = [
        re.sub(r"\s+", " ", visible_text(match).strip())
        for match in re.findall(r"<p\b[^>]*>(.*?)</p>", text, flags=re.IGNORECASE | re.DOTALL)
    ]
    candidate_norms = [normalize_title(candidate.text) for candidate in candidates]
    snippets: dict[int, str] = {}
    cursor = 0
    for candidate_index, candidate_norm in enumerate(candidate_norms):
        if not candidate_norm:
            continue
        found = None
        for line_index in range(cursor, len(lines)):
            if normalize_title(lines[line_index]) == candidate_norm:
                found = line_index
                break
        if found is None:
            continue
        cursor = found + 1
        for line in lines[cursor:]:
            line_norm = normalize_title(line)
            if line_norm in candidate_norms:
                break
            if len(line_norm) >= 10:
                snippets[candidate_index] = line_norm[:12]
                break
    return snippets


def resolve_candidate_hrefs(zf: zipfile.ZipFile, diagnosis, manifest: dict[str, dict[str, str]], spine_idrefs: list[str], labels: list[str], srcs: list[str]) -> dict[int, str]:
    candidates = diagnosis.toc_diagnostics.book_toc_candidates
    hrefs: dict[int, str] = {}
    used_src_indexes: set[int] = set()

    for candidate_index, candidate in enumerate(candidates):
        if candidate.kind == "part":
            continue
        for src_index, label in enumerate(labels):
            if src_index in used_src_indexes:
                continue
            if matches_toc_title(label, candidate.text):
                hrefs[candidate_index] = srcs[src_index]
                used_src_indexes.add(src_index)
                break

    spine_hrefs = [
        manifest[idref]["href"]
        for idref in spine_idrefs
        if idref in manifest
        and manifest[idref]["href"] != diagnosis.toc_diagnostics.book_toc_path
        and is_html_entry(manifest[idref]["href"], {item["href"]: item for item in manifest.values()})
    ]
    text_by_href = {}
    for href in spine_hrefs:
        if href not in zf.namelist():
            continue
        try:
            text_by_href[href] = normalize_title(visible_text(read_entry_text(zf, href)))
        except Exception:
            text_by_href[href] = ""

    snippets = toc_following_snippets(zf, diagnosis)
    last_spine_index = -1
    for candidate_index, candidate in enumerate(candidates):
        if candidate.kind == "part":
            continue
        if candidate_index in hrefs and hrefs[candidate_index] in spine_hrefs:
            last_spine_index = max(last_spine_index, spine_hrefs.index(hrefs[candidate_index]))
            continue
        terms = search_terms(candidate.text)
        terms.extend([snippet for snippet in [snippets.get(candidate_index)] if snippet])
        matches = [
            href
            for href in spine_hrefs
            if spine_hrefs.index(href) > last_spine_index and any(term and term in text_by_href.get(href, "") for term in terms)
        ]
        if len(matches) >= 1:
            hrefs[candidate_index] = matches[0]
            last_spine_index = spine_hrefs.index(matches[0])

    for candidate_index, candidate in enumerate(candidates):
        if candidate.kind != "part":
            continue
        for child_index in range(candidate_index + 1, len(candidates)):
            if candidates[child_index].kind == "part":
                break
            if child_index in hrefs:
                hrefs[candidate_index] = hrefs[child_index]
                break

    toc_index = srcs.index(diagnosis.toc_diagnostics.book_toc_path) if diagnosis.toc_diagnostics.book_toc_path in srcs else -1
    ordered_content_srcs = [
        src
        for index, src in enumerate(srcs)
        if src and index > toc_index and src != diagnosis.toc_diagnostics.book_toc_path
    ]
    used_ordered = {href for href in hrefs.values() if href in ordered_content_srcs}
    for candidate_index, candidate in enumerate(candidates):
        if candidate.kind == "part" or candidate_index in hrefs:
            continue
        if candidate.kind == "intro":
            hrefs[candidate_index] = diagnosis.toc_diagnostics.book_toc_path or ordered_content_srcs[0]
            continue
        for src in ordered_content_srcs:
            if src not in used_ordered:
                hrefs[candidate_index] = src
                used_ordered.add(src)
                break

    for candidate_index, candidate in enumerate(candidates):
        if candidate.kind != "part" or candidate_index in hrefs:
            continue
        for child_index in range(candidate_index + 1, len(candidates)):
            if candidates[child_index].kind == "part":
                break
            if child_index in hrefs:
                hrefs[candidate_index] = hrefs[child_index]
                break

    return hrefs


def rebuild_ncx_from_book_toc(root: ET.Element, namespace: str, diagnosis, hrefs: dict[int, str]) -> tuple[list[ET.Element], int]:
    candidates = diagnosis.toc_diagnostics.book_toc_candidates
    has_parts = any(candidate.kind == "part" for candidate in candidates)
    rebuilt: list[ET.Element] = []
    current_part: ET.Element | None = None
    created = 0

    for index, candidate in enumerate(candidates):
        href = hrefs.get(index)
        if not href:
            continue
        if candidate.kind == "part":
            current_part = make_toc_navpoint(namespace, "part", f"book_toc_{index + 1}", candidate.text, href)
            rebuilt.append(current_part)
            created += 1
        elif candidate.kind == "chapter" and has_parts and current_part is not None:
            current_part.append(make_toc_navpoint(namespace, "chapter", f"book_toc_{index + 1}", candidate.text, href))
            created += 1
        else:
            rebuilt.append(make_toc_navpoint(namespace, candidate.kind or "chapter", f"book_toc_{index + 1}", candidate.text, href))
            created += 1

    return rebuilt, created


def repair_ncx_directory(data: bytes, diagnosis, zf: zipfile.ZipFile, manifest: dict[str, dict[str, str]], spine_idrefs: list[str]) -> tuple[bytes, int]:
    toc = diagnosis.toc_diagnostics
    if not diagnosis.ncx_path or not toc.book_toc_candidates:
        return data, 0
    if diagnosis.manifest_missing or diagnosis.spine_missing_idrefs or diagnosis.spine_missing_files or diagnosis.toc_missing or diagnosis.nav_missing:
        return data, 0

    text = data.decode("utf-8")
    root = parse_xml(text)
    namespace = ncx_namespace(root)
    if namespace:
        ET.register_namespace("", namespace)

    nav_map = next((elem for elem in root.iter() if local_tag(elem.tag) == "navMap"), None)
    if nav_map is None:
        return data, 0

    original_points = [child for child in list(nav_map) if local_tag(child.tag) == "navPoint"]
    if len(original_points) < 2:
        return data, 0

    labels = [first_child_text(point, "text") for point in original_points]
    srcs = [first_content_src(point) for point in original_points]
    hrefs = resolve_candidate_hrefs(zf, diagnosis, manifest, spine_idrefs, labels, srcs)
    rebuilt, created = rebuild_ncx_from_book_toc(root, namespace, diagnosis, hrefs)
    if not rebuilt or created < max(3, len(toc.book_toc_candidates) // 2):
        return data, 0

    nav_map.clear()
    for point in rebuilt:
        nav_map.append(point)
    renumber_play_order(rebuilt)

    for meta in root.iter():
        if local_tag(meta.tag) == "meta" and meta.attrib.get("name") == "dtb:depth":
            meta.set("content", "2")

    repaired = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return repaired, created


def safe_repair_epub(epub_path, fixed_epub, repair_entities=True, repair_punctuation=False, repair_directory=False):
    before = diagnose_epub(epub_path)
    if before.error:
        return before, {
            "repair_mode": "safe",
            "input_epub": str(epub_path),
            "fixed_epub": None,
            "error": before.error,
            "files_changed": 0,
            "total_replacements": 0,
            "changes": [],
        }

    fixed_epub.parent.mkdir(parents=True, exist_ok=True)
    tmp_epub = fixed_epub.with_suffix(fixed_epub.suffix + ".tmp")
    if tmp_epub.exists():
        tmp_epub.unlink()

    changes = []
    total_replacements = 0
    directory_replacements = 0

    with zipfile.ZipFile(epub_path, "r") as src:
        names = zip_names(src)
        manifest = {}
        spine_idrefs = []
        manifest_by_href = {}
        if before.opf_path and before.opf_path in names:
            try:
                manifest, spine_idrefs, _, _ = parse_opf(src, before.opf_path)
                manifest_by_href = {item["href"]: item for item in manifest.values()}
            except Exception:
                manifest = {}
                spine_idrefs = []
                manifest_by_href = {}

        with zipfile.ZipFile(tmp_epub, "w") as dst:
            for info in src.infolist():
                data = read_entry_bytes(src, info.filename)
                entity_replacements = 0
                punctuation_replacements = 0
                if not info.is_dir() and is_html_entry(info.filename, manifest_by_href):
                    if repair_entities:
                        data, entity_replacements = repair_double_escaped_numeric_entities(data)
                    if repair_punctuation:
                        data, punctuation_replacements = repair_ascii_parentheses(data)
                    if entity_replacements or punctuation_replacements:
                        changes.append(
                            {
                                "path": info.filename,
                                "double_escaped_numeric_entities_fixed": entity_replacements,
                                "ascii_parentheses_fixed": punctuation_replacements,
                            }
                        )
                        total_replacements += entity_replacements + punctuation_replacements
                elif repair_directory and before.ncx_path and info.filename == before.ncx_path:
                    data, directory_replacements = repair_ncx_directory(data, before, src, manifest, spine_idrefs)
                    if directory_replacements:
                        changes.append(
                            {
                                "path": info.filename,
                                "directory_part_groups_created": directory_replacements,
                            }
                        )
                        total_replacements += directory_replacements
                dst.writestr(copy_info(info), data)

    if total_replacements:
        if fixed_epub.exists():
            fixed_epub.unlink()
        tmp_epub.replace(fixed_epub)
    else:
        tmp_epub.unlink(missing_ok=True)
        fixed_epub = None

    repair_log = {
        "repair_mode": "safe",
        "input_epub": str(epub_path),
        "fixed_epub": str(fixed_epub) if fixed_epub else None,
        "error": None,
        "files_changed": len(changes),
        "total_replacements": total_replacements,
        "changes": changes,
        "before": diagnosis_to_dict(before),
    }

    if fixed_epub:
        after = diagnose_epub(fixed_epub)
        repair_log["after"] = diagnosis_to_dict(after)

    return before, repair_log


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely repair one EPUB without overwriting the original.")
    add_common_args(parser)
    parser.add_argument("--diagnose-only", action="store_true", help="Only write diagnosis outputs; do not create a fixed EPUB")
    parser.add_argument("--repair-safe", action="store_true", help="Apply safe entity repairs")
    parser.add_argument("--repair-punctuation-safe", action="store_true", help="Normalize conservative Chinese punctuation candidates")
    parser.add_argument("--repair-directory-safe", action="store_true", help="Rebuild safe NCX hierarchy from recognized directory evidence while preserving links")
    parser.add_argument("--epub-only", action="store_true", help="Create only the fixed EPUB and print verification summary; do not write Markdown or JSON reports")
    args = parser.parse_args()

    diagnosis_md, repair_json, fixed_epub = output_paths(args.epub, args.output_dir)

    requested_repair = args.repair_safe or args.repair_punctuation_safe or args.repair_directory_safe
    if args.diagnose_only or not requested_repair:
        diagnosis = diagnose_epub(args.epub)
        write_text(diagnosis_md, markdown_report(diagnosis))
        repair_log = {
            "repair_mode": "diagnose-only",
            "input_epub": str(args.epub),
            "fixed_epub": None,
            "error": diagnosis.error,
            "files_changed": 0,
            "total_replacements": 0,
            "changes": [],
            "before": diagnosis_to_dict(diagnosis),
        }
        write_json(repair_json, repair_log)
        print_result({"ok": diagnosis.error is None, "diagnosis_md": str(diagnosis_md), "repair_log_json": str(repair_json), "fixed_epub": None})
        return 0 if diagnosis.error is None else 2

    before, repair_log = safe_repair_epub(
        args.epub,
        fixed_epub,
        repair_entities=args.repair_safe,
        repair_punctuation=args.repair_punctuation_safe,
        repair_directory=args.repair_directory_safe,
    )
    if args.epub_only:
        after = repair_log.get("after")
        after_punctuation = (after or {}).get("punctuation_diagnostics") or {}
        print_result(
            {
                "ok": repair_log.get("error") is None,
                "fixed_epub": repair_log.get("fixed_epub"),
                "files_changed": repair_log.get("files_changed", 0),
                "total_replacements": repair_log.get("total_replacements", 0),
                "before": diagnosis_summary(before),
                "after": {
                    "zip_readable": (after or {}).get("zip_ok"),
                    "opf_path": (after or {}).get("opf_path"),
                    "missing_reference_count": sum(
                        len((after or {}).get(key) or [])
                        for key in ("manifest_missing", "spine_missing_idrefs", "spine_missing_files", "toc_missing", "nav_missing")
                    ),
                    "double_escaped_numeric_entities": (after or {}).get("double_escaped_total"),
                    "ascii_parenthesis_candidates": after_punctuation.get("ascii_paren_candidates"),
                    "question_markers_between_chinese": after_punctuation.get("ascii_question_between_chinese"),
                    "ncx_max_depth": ((after or {}).get("toc_diagnostics") or {}).get("ncx_max_depth"),
                    "ncx_is_flat": ((after or {}).get("toc_diagnostics") or {}).get("ncx_is_flat"),
                },
                "reports_written": False,
            }
        )
        return 0 if repair_log.get("error") is None else 2

    write_json(repair_json, repair_log)
    report_diagnosis = diagnose_epub(fixed_epub) if repair_log.get("fixed_epub") else before
    write_text(diagnosis_md, markdown_report(report_diagnosis, repair_log=repair_log))
    ok = repair_log.get("error") is None
    print_result(
        {
            "ok": ok,
            "diagnosis_md": str(diagnosis_md),
            "repair_log_json": str(repair_json),
            "fixed_epub": repair_log.get("fixed_epub"),
            "files_changed": repair_log.get("files_changed", 0),
            "total_replacements": repair_log.get("total_replacements", 0),
        }
    )
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
