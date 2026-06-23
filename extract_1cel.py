#!/usr/bin/env python3
"""
extract_1cel.py — Extract 1Celano (Vita Prima) from the Quaracchi PDF
into a FORMAT.md-compliant Markdown file.

This is the document-specific driver.  It delegates to the shared pipeline
modules for PDF extraction, text cleanup, scripture-ref conversion, and
validation.  Only the structural parsing (chapters, paragraphs, asides)
is 1Cel-specific.

Usage:
    python extract_1cel.py path/to/1Celano-Quaracchi.pdf [-o output.md]

Dependencies:
    pip install pymupdf
"""

import argparse
import re
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

from extract_pdf.pdf_to_text import extract as pdf_extract           # noqa: E402
from extract_pdf.strip_boilerplate import strip as strip_boilerplate  # noqa: E402
from lib.scripture import BOOK_MAP, roman_to_int                     # noqa: E402
from postprocess.clean_text import clean as clean_text                # noqa: E402
from postprocess.convert_refs import process as convert_refs          # noqa: E402
from postprocess.fix_ref_verse import fix as fix_ref_verse            # noqa: E402

# ── 1Cel-specific constants ──────────────────────────────────────────────

LICENCE_SENTINEL = "Quest'opera di propriet"

ASIDE_MARKERS = [
    "IN NOMINE DOMINI",
    "INCIPIT",
    "EXPLICIT",
    "AD LAUDEM ET GLORIAM",
]

RE_PARA = re.compile(r"^(\d+)\.\s*$", re.MULTILINE)


# ── Helpers ──────────────────────────────────────────────────────────────

def is_aside_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    for marker in ASIDE_MARKERS:
        if stripped.startswith(marker):
            return True
    if stripped.isupper() and len(stripped) > 3 and not RE_PARA.match(stripped):
        return True
    return False


# ── Structural parser (1Cel-specific) ────────────────────────────────────

def parse_and_emit(text: str) -> str:
    """Parse cleaned text into FORMAT.md Markdown.

    Emits raw (cfr. …) citations as-is — ref conversion is a later step.
    """
    lines = text.split("\n")
    output: list[str] = []

    # ── Frontmatter ──────────────────────────────────────────────────
    output.append("---")
    output.append("id: 1Cel")
    output.append('title: "Vita Prima S. Francisci"')
    output.append('author: "Tommaso da Celano"')
    output.append('date: "1228-1229"')
    output.append('reference_edition: "Analecta Franciscana X (Quaracchi, 1926-1941)"')
    output.append("license: CC0-1.0")
    output.append("---")
    output.append("")

    # ── Title ────────────────────────────────────────────────────────
    output.append("# VITA PRIMA S. FRANCISCI")
    output.append("")

    # ── State ────────────────────────────────────────────────────────
    current_opusculum = 0
    in_prolog = False
    in_para = False
    para_num = 0
    verse_buf: list[str] = []
    pending_aside: list[str] = []
    emitted_prolog_heading = False
    skipped_title_line = False

    def flush_para():
        nonlocal in_para, verse_buf
        if not in_para or not verse_buf:
            in_para = False
            return
        body = "\n".join(verse_buf).strip()
        if body:
            pid = f"prolog-{para_num}" if in_prolog else str(para_num)
            output.append(f'<p id="{pid}">')
            output.append(body)
            output.append("</p>")
            output.append("")
        verse_buf = []
        in_para = False

    def flush_aside():
        nonlocal pending_aside
        if not pending_aside:
            return
        content = "\n".join(pending_aside).strip()
        if content:
            output.append("<aside>")
            output.append(content)
            output.append("</aside>")
            output.append("")
        pending_aside = []

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # Skip the raw title line extracted from PDF
        if not skipped_title_line and "VITA PRIMA" in stripped:
            skipped_title_line = True
            i += 1
            continue

        # ── PROLOGUS ─────────────────────────────────────────────────
        if stripped == "PROLOGUS" and not emitted_prolog_heading:
            flush_para()
            flush_aside()
            emitted_prolog_heading = True
            in_prolog = True
            output.append('## PROLOGUS <a id="prolog"></a>')
            output.append("")
            i += 1
            continue

        # ── Opusculum markers ────────────────────────────────────────
        if stripped.startswith("OPUSCUL"):
            flush_para()
            flush_aside()
            in_prolog = False
            if "PRIMUM" in stripped.upper():
                current_opusculum = 1
            elif "SECUNDUM" in stripped.upper():
                current_opusculum = 2
            elif "TERTIUM" in stripped.upper():
                current_opusculum = 3
            pending_aside.append(stripped)
            i += 1
            continue

        # ── Caput headings ───────────────────────────────────────────
        caput_match = re.match(
            r"Caput\.?\s+([IVXLC]+)\s*-\s*(.*)", stripped
        )
        if caput_match:
            flush_para()
            flush_aside()
            roman = caput_match.group(1)
            description = caput_match.group(2).strip()
            cap_num = roman_to_int(roman)

            while i + 1 < len(lines) and lines[i + 1].strip():
                next_stripped = lines[i + 1].strip()
                if is_aside_line(next_stripped) and not description:
                    break
                if re.match(r"^\d+\.\s*$", next_stripped):
                    break
                if re.match(r"^\d+\s+[A-Z]", next_stripped):
                    break
                description += " " + next_stripped
                i += 1

            chapter_id = f"op{current_opusculum}-{cap_num}" if current_opusculum > 0 else f"cap{cap_num}"
            output.append(f'## Caput {roman} - {description} <a id="{chapter_id}"></a>')
            output.append("")
            i += 1
            continue

        # ── Paragraph starts: "N." on its own line ───────────────────
        para_match = re.match(r"^(\d+)\.\s*$", stripped)
        if para_match:
            flush_para()
            flush_aside()
            para_num = int(para_match.group(1))
            in_para = True
            verse_buf = []
            i += 1
            continue

        # ── Verse-numbered lines inside a paragraph ──────────────────
        verse_match = re.match(r"^(\d+)\s+(.*)", stripped)
        if in_para and verse_match:
            verse_buf.append(f"[{verse_match.group(1)}] {verse_match.group(2)}")
            i += 1
            continue

        # ── Aside-worthy lines ───────────────────────────────────────
        if not in_para and is_aside_line(stripped):
            pending_aside.append(stripped)
            i += 1
            continue

        # ── Continuation ─────────────────────────────────────────────
        if in_para:
            if verse_buf:
                verse_buf[-1] += " " + stripped
            else:
                verse_buf.append(stripped)
        elif pending_aside:
            pending_aside.append(stripped)
        else:
            pending_aside.append(stripped)

        i += 1

    flush_para()
    flush_aside()

    return "\n".join(output) + "\n"


# ── Entry point ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Extract 1Celano from Quaracchi PDF to FORMAT.md Markdown"
    )
    parser.add_argument("pdf", help="Path to '1Celano - Quaracchi.pdf'")
    parser.add_argument("-o", "--output", help="Output .md file (default: stdout)")
    args = parser.parse_args()

    # 1. PDF → raw text
    print("1/6  Extracting text from PDF…", file=sys.stderr)
    raw = pdf_extract(args.pdf)

    # 2. Strip licence boilerplate
    print("2/6  Stripping boilerplate…", file=sys.stderr)
    text = strip_boilerplate(raw, start_after="VITA PRIMA", end_before=LICENCE_SENTINEL)

    # 3. Clean up extraction artefacts
    print("3/6  Cleaning text…", file=sys.stderr)
    text = clean_text(text)

    # 4. Document-specific structural parsing
    print("4/6  Parsing structure…", file=sys.stderr)
    md = parse_and_emit(text)

    # 5. Convert scripture references
    print("5/6  Converting scripture refs…", file=sys.stderr)
    md = convert_refs(md, BOOK_MAP)

    # 6. Fix <ref>/verse-marker overlap
    print("6/6  Fixing ref/verse overlap…", file=sys.stderr)
    md = fix_ref_verse(md)

    if args.output:
        Path(args.output).write_text(md, encoding="utf-8")
        print(f"Done → {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(md)


if __name__ == "__main__":
    main()
