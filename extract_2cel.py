#!/usr/bin/env python3
"""
extract_2cel.py — Extract 2Celano (Vita Secunda) from the Quaracchi PDF
into a FORMAT.md-compliant Markdown file.

Document-specific driver.  Delegates to the shared pipeline modules for PDF
extraction, text cleanup, scripture-ref conversion, and validation.  Only the
structural parsing (chapters, paragraphs, asides) is 2Cel-specific.

Usage:
    python extract_2cel.py "path/to/2Celano - Quaracchi.pdf" [-o output.md]

Dependencies:
    pip install pymupdf

Manual review checklist (after running):
  - Bare "cfr." without opening paren in the source PDF.  These are
    OCR/typesetting errors that the regex cannot match.
    Search for: cfr\\.\\s+\\w+\\s+\\d+ outside <ref>.
  - <ref> clause boundaries: the backward-looking heuristic wraps to the
    nearest comma/semicolon/period, which is wrong when the allusion spans
    a longer or shorter clause.  Spot-check each <ref>…</ref>.
  - Section headings ("De paupertate.", etc.) before chapter headings:
    these are detected by a peek-ahead and emitted as <aside>.  Verify
    they were not accidentally appended to the preceding paragraph.
  - Quaracchi ligature "ę" occasionally extracted as "e".
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

# ── 2Cel-specific constants ──────────────────────────────────────────

ASIDE_MARKERS = [
    "IN NOMINE DOMINI",
    "INCIPIT",
    "EXPLICIT",
    "AD LAUDEM ET GLORIAM",
    "ORATIO SOCIORUM",
]

PAGE_HEADERS = {"Thomae a Celano", "Vita Secunda"}

RE_PARA_NUM = re.compile(r"^(\d+)\s*$")
RE_VERSE_LINE = re.compile(r"^(\d+)\s+(.*)")
RE_CAPUT = re.compile(r"^Caput\.?\s+([IVXLC]+)(.*)", re.IGNORECASE)
RE_BARE_CHAP = re.compile(r"^([IVXLC]+)\s*[–—-]\s*(.*)")
RE_STANDALONE_ROMAN = re.compile(r"^([IVXLC]+)\.?\s*$")


# ── Helpers ──────────────────────────────────────────────────────────────

def strip_page_headers(text: str) -> str:
    return "\n".join(
        l for l in text.split("\n") if l.strip() not in PAGE_HEADERS
    )


def is_aside_line(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    upper = stripped.upper()
    for marker in ASIDE_MARKERS:
        if upper.startswith(marker):
            return True
    return False


def clean_caput_rest(rest: str) -> str:
    rest = rest.strip()
    rest = re.sub(r"^[\s\-–—.]+", "", rest)
    return rest.rstrip(".").strip()


# ── Structural parser (2Cel-specific) ─────────────────────────────────

def parse_and_emit(text: str) -> str:
    """Parse cleaned text into FORMAT.md Markdown."""
    lines = text.split("\n")
    output: list[str] = []

    # ── Frontmatter ──────────────────────────────────────────────────
    output.append("---")
    output.append("id: 2Cel")
    output.append('title: "Vita Secunda S. Francisci"')
    output.append('author: "Tommaso da Celano"')
    output.append('date: "1246-1247"')
    output.append('reference_edition: "Analecta Franciscana X (Quaracchi, 1926-1941)"')
    output.append("license: CC0-1.0")
    output.append("---")
    output.append("")

    # ── Title ────────────────────────────────────────────────────────
    output.append("# VITA SECUNDA S. FRANCISCI")
    output.append("")

    # ── State ────────────────────────────────────────────────────────
    current_opus = 0
    in_para = False
    para_num = 0
    verse_buf: list[str] = []
    pending_aside: list[str] = []
    emitted_prolog_heading = False

    def flush_para():
        nonlocal in_para, verse_buf
        if not in_para or not verse_buf:
            in_para = False
            return
        body = "\n".join(verse_buf).strip()
        if body:
            output.append(f'<p id="{para_num}">')
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

    def emit_chapter(roman: str, description: str):
        cap_num = roman_to_int(roman)
        cid = f"op{current_opus}-{cap_num}" if current_opus > 0 else f"cap{cap_num}"
        if description:
            output.append(f'## Caput {roman} - {description} <a id="{cid}"></a>')
        else:
            output.append(f'## Caput {roman} <a id="{cid}"></a>')
        output.append("")

    def absorb_continuation(idx: int, desc: str) -> tuple[str, int]:
        while idx + 1 < len(lines):
            nxt = lines[idx + 1].strip()
            if not nxt:
                break
            if RE_PARA_NUM.match(nxt):
                break
            if is_aside_line(nxt):
                break
            if RE_CAPUT.match(nxt):
                break
            if RE_BARE_CHAP.match(nxt):
                break
            desc += " " + nxt
            idx += 1
        return desc, idx

    def peek_is_chapter(idx: int) -> bool:
        j = idx + 1
        while j < len(lines):
            s = lines[j].strip()
            if not s:
                j += 1
                continue
            return bool(
                RE_CAPUT.match(s)
                or RE_BARE_CHAP.match(s)
                or RE_STANDALONE_ROMAN.match(s)
            )
        return False

    def peek_is_para_num(idx: int) -> bool:
        j = idx + 1
        while j < len(lines):
            s = lines[j].strip()
            if not s:
                j += 1
                continue
            return bool(RE_PARA_NUM.match(s))
        return False

    i = 0
    while i < len(lines):
        stripped = lines[i].strip()

        if not stripped:
            i += 1
            continue

        # ── PROLOGUS ─────────────────────────────────────────────────
        if stripped.upper().startswith("PROLOGUS") and not emitted_prolog_heading:
            flush_para()
            flush_aside()
            emitted_prolog_heading = True
            output.append('## PROLOGUS <a id="prolog"></a>')
            output.append("")
            i += 1
            continue

        # ── OPUS markers ─────────────────────────────────────────────
        if re.match(r"^(PRIMUM|SECUNDUM)\s+OPUS", stripped, re.IGNORECASE):
            flush_para()
            flush_aside()
            if "PRIMUM" in stripped.upper():
                current_opus = 1
            elif "SECUNDUM" in stripped.upper():
                current_opus = 2
            pending_aside.append(stripped)
            i += 1
            continue

        # ── Explicit markers ─────────────────────────────────────────
        if re.match(r"(?i)^Explic(?:it|iunt)\b", stripped):
            flush_para()
            pending_aside.append(stripped)
            flush_aside()
            i += 1
            continue

        # ── CAPUT headings ───────────────────────────────────────────
        caput_match = RE_CAPUT.match(stripped)
        if caput_match:
            flush_para()
            roman = caput_match.group(1)
            description = clean_caput_rest(caput_match.group(2))
            if not description and pending_aside:
                description = " ".join(pending_aside).strip().rstrip(".")
                pending_aside = []
            else:
                flush_aside()
            description, i = absorb_continuation(i, description)
            description = description.rstrip(".")
            emit_chapter(roman, description)
            i += 1
            continue

        # ── Bare Roman numeral chapter headings (XXXIII – …) ─────────
        bare_match = RE_BARE_CHAP.match(stripped)
        if bare_match and current_opus > 0:
            flush_para()
            flush_aside()
            roman = bare_match.group(1)
            description = bare_match.group(2).strip()
            description, i = absorb_continuation(i, description)
            description = description.rstrip(".")
            emit_chapter(roman, description)
            i += 1
            continue

        # ── Standalone Roman numeral (e.g. CLXVII) ──────────────────
        roman_match = RE_STANDALONE_ROMAN.match(stripped)
        if roman_match and current_opus > 0 and peek_is_para_num(i):
            flush_para()
            description = ""
            if pending_aside:
                description = " ".join(pending_aside).strip().rstrip(".")
                pending_aside = []
            else:
                flush_aside()
            emit_chapter(roman_match.group(1), description)
            i += 1
            continue

        # ── Paragraph starts ─────────────────────────────────────────
        para_match = RE_PARA_NUM.match(stripped)
        if para_match:
            flush_para()
            flush_aside()
            para_num = int(para_match.group(1))
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

        # ── Section heading before a chapter (flush paragraph) ───────
        # All 2Cel section headings start with "De " — use this to avoid
        # misidentifying verse continuations as section headings.
        if in_para and stripped.startswith("De ") and peek_is_chapter(i):
            flush_para()
            pending_aside.append(stripped)
            i += 1
            continue

        # ── Aside-worthy lines ───────────────────────────────────────
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
        description="Extract 2Celano from Quaracchi PDF to FORMAT.md Markdown"
    )
    parser.add_argument("pdf", help="Path to '2Celano - Quaracchi.pdf'")
    parser.add_argument("-o", "--output", help="Output .md file (default: stdout)")
    args = parser.parse_args()

    # 1. PDF → raw text
    print("1/6  Extracting text from PDF…", file=sys.stderr)
    raw = pdf_extract(args.pdf)

    # 2. Strip boilerplate
    print("2/6  Stripping boilerplate…", file=sys.stderr)
    text = strip_boilerplate(raw, start_after="PROLOGUS", end_before=None)

    # 3. Clean up extraction artefacts
    print("3/6  Cleaning text…", file=sys.stderr)
    text = clean_text(text)
    text = strip_page_headers(text)

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
