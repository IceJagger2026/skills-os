#!/usr/bin/env python3
from __future__ import annotations

import argparse

from epub_repair_common import (
    add_common_args,
    diagnose_epub,
    diagnosis_summary,
    diagnosis_to_dict,
    markdown_report,
    output_paths,
    print_result,
    write_text,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose one EPUB without modifying it.")
    add_common_args(parser)
    parser.add_argument("--summary-only", action="store_true", help="Print diagnosis summary JSON only; do not write files")
    parser.add_argument("--write-report", action="store_true", help="Write a Markdown diagnosis report")
    args = parser.parse_args()

    diagnosis = diagnose_epub(args.epub)
    if args.write_report and not args.summary_only:
        diagnosis_md, _, _ = output_paths(args.epub, args.output_dir)
        write_text(diagnosis_md, markdown_report(diagnosis))
        print_result(
            {
                "ok": diagnosis.error is None,
                "diagnosis_md": str(diagnosis_md),
                "summary": diagnosis_to_dict(diagnosis),
            }
        )
        return 0 if diagnosis.error is None else 2

    print_result(diagnosis_summary(diagnosis))
    return 0 if diagnosis.error is None else 2


if __name__ == "__main__":
    raise SystemExit(main())
