#!/usr/bin/env python3
"""
extract_LMj.py — Extract Legenda Maior (Bonaventure) from the Quaracchi PDF
into a spec-compliant Markdown file.

Document-specific driver.  Delegates to the shared pipeline modules for PDF
extraction, text cleanup, scripture-ref conversion, and validation.  Only the
structural parsing (chapters, paragraphs, asides) is LMj-specific.

Usage:
    python extract_LMj.py "path/to/Legenda Maior - Quaracchi.pdf" [-o output.md]

Dependencies:
    pip install pymupdf

Manual review checklist (after running):
  - ~11 bare "cfr." without opening paren in the source PDF.  These are
    OCR/typesetting errors (e.g. "cfr. Is 66,2; Iob 36,22)") that the
    regex cannot match.  Search for: cfr\\.\\s+\\w+\\s+\\d+ outside <ref>.
  - 1 abbreviated "(c Mar 1,3; Luc 3,4)" — uses "(c " instead of
    "(cfr. ".  Needs manual wrapping.
  - 1 OCR typo "9cfr." (missing space/paren) in cap9-6.
  - <ref> clause boundaries: the backward-looking heuristic wraps to the
    nearest comma/semicolon/period, which is wrong when the allusion spans
    a longer or shorter clause.  Spot-check each <ref>…</ref>.
  - Quaracchi ligature "ę" occasionally extracted as "e" — invisible in
    the output but present in the source.
  - (Sir 35,10; ioa 9,24): lowercase "ioa" — OCR error, not matched.
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

# ── LMj-specific constants ──────────────────────────────────────────

ASIDE_MARKERS = [
    "IN NOMINE DOMINI",
    "INCIPIT",
    "INCIPIUNT",
    "EXPLICIT",
    "EXPLICIUNT",
    "AD LAUDEM ET GLORIAM",
]

# Hardcoded to 75-page PDF; adjust if re-running on a different scan.
RE_PAGE_NUM = re.compile(r"^\d+/75$")
RE_PARA_NUM = re.compile(r"^(\d+)\s*$")
RE_PARA_NUM_A = re.compile(r"^(\d+[a-z])\s*$")
RE_ADDITIO = re.compile(r"^(\d+[a-z])\s+Additio\s+posterior\.", re.IGNORECASE)
RE_VERSE_LINE = re.compile(r"^(\d+)\s+(.*)")
RE_CAPUT = re.compile(
    r"CAPUT\s+([IVXLC]+)\s*[-–—]\s*(.*)", re.IGNORECASE
)
RE_MIRACLE_CHAP = re.compile(
    r"^([IVXLC]+)\s*[-–—]\s*(.*)"
)


# ── Helpers ──────────────────────────────────────────────────────────────

def is_aside_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    for marker in ASIDE_MARKERS:
        if stripped.upper().startswith(marker):
            return True
    if stripped == "Prologus.":
        return True
    return False


def strip_page_numbers(text: str) -> str:
    lines = text.split("\n")
    return "\n".join(l for l in lines if not RE_PAGE_NUM.match(l.strip()))


# ── Structural parser (LMj-specific) ─────────────────────────────────

def parse_and_emit(text: str) -> str:
    """Parse cleaned text into spec-compliant Markdown."""
    lines = text.split("\n")
    output: list[str] = []

    # ── Frontmatter ──────────────────────────────────────────────────
    output.append("---")
    output.append('title: "Legenda Maior Sancti Francisci"')
    output.append('author: "Bonaventura da Bagnoregio"')
    output.append('date: "1260-1263"')
    output.append('reference_edition: "Analecta Franciscana X (Quaracchi, 1926-1941)"')
    output.append("description:")
    output.append("notes:")
    output.append("---")
    output.append("")

    # ── Title ────────────────────────────────────────────────────────
    output.append("# LEGENDA MAIOR SANCTI FRANCISCI")
    output.append("")

    # ── State ────────────────────────────────────────────────────────
    in_prolog = False
    in_miracles = False
    in_para = False
    current_chapter_id = ""
    para_num = ""
    verse_buf: list[str] = []
    pending_aside: list[str] = []
    emitted_prolog_heading = False
    skipped_title = False
    miracle_chap_num = 0

    def flush_para():
        nonlocal in_para, verse_buf
        if not in_para or not verse_buf:
            in_para = False
            return
        body = "\n".join(verse_buf).strip()
        if body:
            pid = f"{current_chapter_id}-{para_num}"
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

    def peek_is_caput(idx: int) -> bool:
        """Check if a standalone number is followed by a CAPUT heading."""
        j = idx + 1
        while j < len(lines):
            s = lines[j].strip()
            if not s:
                j += 1
                continue
            return bool(RE_CAPUT.match(s))
        return False

    def peek_is_miracle_heading(idx: int) -> bool:
        """Check if a standalone number is followed by a miracle chapter heading."""
        j = idx + 1
        while j < len(lines):
            s = lines[j].strip()
            if not s:
                j += 1
                continue
            return bool(RE_MIRACLE_CHAP.match(s))
        return False

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # Skip the raw title / header lines from PDF
        if not skipped_title and (
            "Legenda Maior" in stripped
            or "Legenda Major" in stripped
            or "1221-1274" in stripped
        ):
            skipped_title = True
            i += 1
            continue

        # ── PROLOGUS ─────────────────────────────────────────────────
        if stripped.upper() == "PROLOGUS" or stripped == "Prologus.":
            if not emitted_prolog_heading:
                flush_para()
                flush_aside()
                emitted_prolog_heading = True
                in_prolog = True
                current_chapter_id = "prolog"
                output.append('## PROLOGUS <a id="prolog"></a>')
                output.append("")
                i += 1
                continue

        # ── Explicit prologus ────────────────────────────────────────
        if stripped.lower().startswith("explicit prologus"):
            flush_para()
            pending_aside.append(stripped)
            flush_aside()
            in_prolog = False
            i += 1
            continue

        # ── OPUSCULUM markers ────────────────────────────────────────
        if stripped.upper().startswith("OPUSCUL"):
            flush_para()
            flush_aside()
            in_prolog = False
            if "TERTIUM" in stripped.upper():
                in_miracles = True
            pending_aside.append(stripped)
            i += 1
            continue

        # ── CAPUT headings ───────────────────────────────────────────
        caput_match = RE_CAPUT.match(stripped)
        if caput_match:
            flush_para()
            flush_aside()
            in_prolog = False
            roman = caput_match.group(1)
            description = caput_match.group(2).strip()
            cap_num = roman_to_int(roman)

            # Absorb continuation lines of the heading
            while i + 1 < len(lines) and lines[i + 1].strip():
                next_stripped = lines[i + 1].strip()
                if RE_PARA_NUM.match(next_stripped):
                    break
                if is_aside_line(next_stripped):
                    break
                description += " " + next_stripped
                i += 1

            # Remove trailing period
            description = description.rstrip(".")

            chapter_id = f"cap{cap_num}"
            current_chapter_id = chapter_id
            output.append(f'## Caput {roman} - {description} <a id="{chapter_id}"></a>')
            output.append("")
            i += 1
            continue

        # ── Miracle chapter headings ─────────────────────────────────
        if in_miracles:
            mir_match = RE_MIRACLE_CHAP.match(stripped)
            if mir_match and not stripped.startswith("CAPUT"):
                flush_para()
                flush_aside()
                roman = mir_match.group(1)
                description = mir_match.group(2).strip()
                miracle_chap_num = roman_to_int(roman)

                # Absorb continuation lines
                while i + 1 < len(lines) and lines[i + 1].strip():
                    next_stripped = lines[i + 1].strip()
                    if RE_PARA_NUM.match(next_stripped):
                        break
                    if is_aside_line(next_stripped):
                        break
                    description += " " + next_stripped
                    i += 1

                description = description.rstrip(".")

                chapter_id = f"mir{miracle_chap_num}"
                current_chapter_id = chapter_id
                output.append(f'## {roman} - {description} <a id="{chapter_id}"></a>')
                output.append("")
                i += 1
                continue

        # ── Explicit / Expliciunt markers (force-flush paragraph) ────
        if re.match(r"(?i)^Explic(?:it|iunt)\b", stripped):
            flush_para()
            pending_aside.append(stripped)
            flush_aside()
            i += 1
            continue

        # ── "Na Additio posterior." combined on one line ─────────────
        additio_match = RE_ADDITIO.match(stripped)
        if additio_match:
            flush_para()
            flush_aside()
            para_num = additio_match.group(1)
            in_para = True
            verse_buf = []
            pending_aside.append("Additio posterior.")
            flush_aside()
            i += 1
            continue

        # ── Standalone numbers: chapter markers vs paragraphs ────────
        para_match = RE_PARA_NUM.match(stripped)
        para_match_a = RE_PARA_NUM_A.match(stripped) if not para_match else None

        if para_match:
            if peek_is_caput(i) or peek_is_miracle_heading(i):
                i += 1
                continue
            flush_para()
            flush_aside()
            para_num = para_match.group(1)
            in_para = True
            verse_buf = []
            i += 1
            continue

        # Handle "5a" style addendum paragraph markers
        if para_match_a:
            flush_para()
            flush_aside()
            para_num = para_match_a.group(1)
            in_para = True
            verse_buf = []
            i += 1
            continue

        # ── "Additio posterior." on its own line after a para marker ─
        if re.match(r"(?i)^Additio\s+posterior", stripped):
            flush_para()
            pending_aside.append(stripped)
            flush_aside()
            in_para = True
            verse_buf = []
            i += 1
            continue

        # ── Verse-numbered lines inside a paragraph ──────────────────
        verse_match = RE_VERSE_LINE.match(stripped)
        if in_para and verse_match:
            verse_buf.append(f"[{verse_match.group(1)}] {verse_match.group(2)}")
            i += 1
            continue

        # OCR fix: lowercase "l" misread as digit "1" (mir10-5a verse 1)
        if in_para and re.match(r"^l\s+[A-Z]", stripped):
            verse_buf.append(f"[1] {stripped[2:]}")
            i += 1
            continue

        # ── Aside-worthy lines (even inside a paragraph) ─────────────
        if is_aside_line(stripped):
            flush_para()
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
        description="Extract Legenda Maior from the Quaracchi PDF to Markdown"
    )
    parser.add_argument("pdf", help="Path to 'Legenda Maior - Quaracchi.pdf'")
    parser.add_argument("-o", "--output", help="Output .md file (default: stdout)")
    args = parser.parse_args()

    # 1. PDF → raw text
    print("1/6  Extracting text from PDF…", file=sys.stderr)
    raw = pdf_extract(args.pdf)

    # 2. Strip boilerplate
    print("2/6  Stripping boilerplate…", file=sys.stderr)
    text = strip_boilerplate(
        raw,
        start_after="OPUSCULUM PRIMUM",
        end_before=None,
    )

    # 3. Clean up extraction artefacts
    print("3/6  Cleaning text…", file=sys.stderr)
    text = clean_text(text)
    text = strip_page_numbers(text)

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
