#!/usr/bin/env python3
"""Analyze a PDF and report its structure as JSON.

Helps configure the extraction pipeline for a new source text.

Usage:
    python analyze_pdf/report.py path/to/source.pdf
    python analyze_pdf/report.py path/to/source.pdf -o report.json

Dependencies: pip install pymupdf
"""

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

import fitz


def inspect_pdf(pdf_path: str) -> dict:
    doc = fitz.open(pdf_path)
    full_text = ""
    for page in doc:
        full_text += page.get_text() + "\n"

    raw_bytes = Path(pdf_path).read_bytes()

    # ── Basic metadata ──────────────────────────────────────────────────
    info = {
        "file": str(pdf_path),
        "pages": len(doc),
        "file_size_bytes": len(raw_bytes),
        "has_fonts": b"/Font" in raw_bytes,
        "has_images": b"/Image" in raw_bytes,
    }

    # ── Paragraph numbering ─────────────────────────────────────────────
    para_nums = [int(m) for m in re.findall(r"(?m)^(\d+)\.\s*$", full_text)]
    info["paragraph_markers"] = {
        "count": len(para_nums),
        "first": para_nums[0] if para_nums else None,
        "last": para_nums[-1] if para_nums else None,
        "sample": para_nums[:30],
    }
    if para_nums:
        sorted_nums = sorted(set(para_nums))
        restarts = sum(1 for a, b in zip(sorted_nums, sorted_nums[1:]) if b <= a)
        info["paragraph_markers"]["numbering_style"] = (
            "per_section" if restarts > 0 else "continuous"
        )

    # ── Chapter / heading patterns ──────────────────────────────────────
    caput = re.findall(r"(?m)^(Caput\.?\s+[IVXLC]+\s*-\s*.+?)$", full_text)
    capitulum = re.findall(r"(?m)^(Capitulum\s+[IVXLC]+.*?)$", full_text)
    info["chapter_headings"] = {
        "caput": caput,
        "capitulum": capitulum,
        "total": len(caput) + len(capitulum),
    }

    # ── Scripture references ────────────────────────────────────────────
    cfr_refs = re.findall(r"\(cfr\.?\s+([^)]+)\)", full_text)
    bare_refs = re.findall(
        r"\((\d?[A-Z][a-z]{1,4}\s*,?\s*\d+[,:\d\s\-;]*)\)", full_text
    )
    books: Counter[str] = Counter()
    for r in cfr_refs + bare_refs:
        for part in re.split(r";\s*", r):
            m = re.match(r"(\d?\s*[A-Z][a-z]+)", part.strip())
            if m:
                books[m.group(1).strip()] += 1
    info["scripture_refs"] = {
        "cfr_count": len(cfr_refs),
        "bare_count": len(bare_refs),
        "book_abbreviations": dict(books.most_common()),
    }

    # ── Structural markers ──────────────────────────────────────────────
    markers = []
    for pat in [
        r"OPUSCUL\w+\s+\w+",
        r"EXPLICIT\s+[^\n]+",
        r"INCIPIT\s+[^\n]+",
        r"IN NOMINE DOMINI[^\n]*",
        r"PROLOGUS",
    ]:
        for m in re.finditer(pat, full_text):
            markers.append(m.group().strip()[:120])
    info["structural_markers"] = sorted(set(markers))

    # ── All-caps lines (potential asides / rubrics) ─────────────────────
    allcaps = []
    for line in full_text.split("\n"):
        s = line.strip()
        if s.isupper() and len(s) > 10 and not re.match(r"^\d+\.\s*$", s):
            allcaps.append(s[:120])
    info["allcaps_lines_sample"] = sorted(set(allcaps))[:30]

    return info


def main():
    parser = argparse.ArgumentParser(description="Inspect a PDF for extraction planning")
    parser.add_argument("pdf", help="Path to the PDF file")
    parser.add_argument("-o", "--output", help="Output JSON file (default: stdout)")
    args = parser.parse_args()

    report = inspect_pdf(args.pdf)
    text = json.dumps(report, indent=2, ensure_ascii=False)

    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"Written to {args.output}", file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
