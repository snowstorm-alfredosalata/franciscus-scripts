#!/usr/bin/env python3
"""Extract raw text from a PDF file.

Concatenates text from every page (or a selected range).
Output goes to stdout or a file.

Usage:
    python extract_pdf/pdf_to_text.py source.pdf
    python extract_pdf/pdf_to_text.py source.pdf --pages 2-78 -o raw.txt

Dependencies: pip install pymupdf
"""

import argparse
import sys
from pathlib import Path

import fitz


def parse_page_range(spec: str, total: int) -> range:
    """Parse '5-20' or '3' into a 0-based range."""
    if "-" in spec:
        a, b = spec.split("-", 1)
        start = max(int(a) - 1, 0)
        end = min(int(b), total)
    else:
        start = int(spec) - 1
        end = int(spec)
    return range(start, end)


def extract(pdf_path: str, pages: str | None = None) -> str:
    doc = fitz.open(pdf_path)
    if pages:
        rng = parse_page_range(pages, len(doc))
    else:
        rng = range(len(doc))

    parts: list[str] = []
    for i in rng:
        parts.append(doc[i].get_text())
    return "\n".join(parts)


def main():
    parser = argparse.ArgumentParser(description="Extract raw text from a PDF")
    parser.add_argument("pdf", help="Path to the PDF file")
    parser.add_argument("--pages", help="Page range, e.g. '2-78' (1-based, inclusive)")
    parser.add_argument("-o", "--output", help="Output text file (default: stdout)")
    args = parser.parse_args()

    text = extract(args.pdf, args.pages)

    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
