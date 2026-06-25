#!/usr/bin/env python3
"""
extract_3soc.py — Extract the Legenda Trium Sociorum (Legend of the Three
Companions) from an HTML source into a FORMAT.md-compliant Markdown file.

Unlike the other drivers, the source for 3Soc is **HTML**, not a PDF, so this
driver replaces the `pdf_to_text` stage with an HTML stage but reuses the rest
of the shared pipeline (scripture-ref conversion, ref/verse-overlap fixing).

The provided source (`raw-sources/3Soc.html`) is a Wayback-Machine
"view-source" capture of

    http://www.paxetbonum.net/biographies/3companions_lat.html

i.e. the real page markup is HTML-escaped inside a table of
`<td class="line-content">` cells.  We therefore proceed in two HTML steps:

  1. unwrap_view_source()  — rebuild the original page HTML from the
     view-source table (reusable for any Wayback view-source capture).
  2. parse_and_emit()      — 3Soc-specific structural parse of that page.

Structure of the underlying paxetbonum page:
  - Chapters are introduced by named anchors: `<a name="epistola">` and
    `<a name="1">` … `<a name="18">`, each followed by a bold heading
    ("Epistola" / "Caput I - …").
  - Paragraphs use **continuous** numbering 1–73, each marked by a bold
    bare number `<b> N </b>` (FORMAT.md §6.1 → bare-integer paragraph ids).
  - Within a paragraph, verses are `<br>K text` (FORMAT.md §9 → `[K]`).
  - Scripture citations are already in Quaracchi `(cfr. Book ch,v)` form.

Usage:
    python extract_3soc.py raw-sources/3Soc.html -o ../franciscus-data/books/3Soc.md
"""

import argparse
import html
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPT_DIR))

from lib.scripture import BOOK_MAP, roman_to_int            # noqa: E402
from postprocess.convert_refs import process as convert_refs  # noqa: E402
from postprocess.fix_ref_verse import fix as fix_ref_verse    # noqa: E402

# ── Stage 1: Wayback "view-source" → original page HTML ───────────────────


class _ViewSourceParser(HTMLParser):
    """Collect the text of every `<td class="line-content">` cell, in order.

    The view-source page shows the original markup HTML-escaped, so the cell
    *text* (with character references resolved) is the original source line.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._in_line = False
        self._buf: list[str] = []
        self.lines: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "td" and ("class", "line-content") in attrs:
            self._in_line = True
            self._buf = []

    def handle_endtag(self, tag):
        if tag == "td" and self._in_line:
            self._in_line = False
            self.lines.append("".join(self._buf))

    def handle_data(self, data):
        if self._in_line:
            self._buf.append(data)

    def handle_entityref(self, name):
        if self._in_line:
            self._buf.append(html.unescape(f"&{name};"))

    def handle_charref(self, name):
        if self._in_line:
            self._buf.append(html.unescape(f"&#{name};"))


def unwrap_view_source(raw_html: str) -> str:
    """Rebuild the original page HTML from a Wayback view-source capture."""
    parser = _ViewSourceParser()
    parser.feed(raw_html)
    return "\n".join(parser.lines)


# ── Stage 2 helpers: HTML fragment → plain text ───────────────────────────

_TAG_RE = re.compile(r"<[^>]+>")


def _detag(fragment: str) -> str:
    """Strip tags and resolve the *second* layer of entities (e.g. &nbsp;)."""
    text = _TAG_RE.sub("", fragment)
    text = html.unescape(text)
    return text.replace("\xa0", " ")


def _clean_heading(fragment: str) -> str:
    """Heading text → single spaced line (collapse newlines too)."""
    return re.sub(r"\s+", " ", _detag(fragment)).strip()


def _collapse(text: str) -> str:
    """Collapse runs of intra-line whitespace, keep newlines."""
    return re.sub(r"[^\S\n]+", " ", text).strip()


# ── Stage 2: 3Soc-specific structural parser ──────────────────────────────

# Named anchors that introduce a section: the letter (epistola) or a chapter.
_ANCHOR_RE = re.compile(r'<a name="(epistola|\d+)"></a>')
# A paragraph marker: a bold tag wrapping nothing but a number (some carry a
# stray trailing period, e.g. `<b> 39. </b>`).
_PARA_RE = re.compile(r"<b>\s*(\d+)\.?\s*</b>")
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_VERSE_RE = re.compile(r"^(\d+)\s+(.*)$", re.DOTALL)

# Sentinels used while flattening paragraph markers out of the HTML.
_PARA_OPEN = "\x01"
_PARA_CLOSE = "\x02"


def _emit_chapter_body(body_html: str, output: list[str]) -> None:
    """Flatten one chapter's HTML body into <p> blocks with [N] verses."""
    # Mark paragraph numbers so they survive tag stripping, then linebreaks.
    marked = _PARA_RE.sub(lambda m: f"\n{_PARA_OPEN}{m.group(1)}{_PARA_CLOSE}\n", body_html)
    marked = _BR_RE.sub("\n", marked)
    text = _detag(marked)

    para_num: str | None = None
    verses: list[str] = []

    def flush() -> None:
        nonlocal para_num, verses
        if para_num is not None and verses:
            output.append(f'<p id="{para_num}">')
            output.append("\n".join(verses))
            output.append("</p>")
            output.append("")
        para_num, verses = None, []

    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        pm = re.match(rf"^{_PARA_OPEN}(\d+){_PARA_CLOSE}$", line)
        if pm:
            flush()
            para_num = pm.group(1)
            continue
        if para_num is None:
            continue  # stray text before the first paragraph marker
        vm = _VERSE_RE.match(line)
        if vm:
            verses.append(f"[{vm.group(1)}] {_collapse(vm.group(2))}")
        elif verses:
            verses[-1] += " " + _collapse(line)
        else:
            verses.append(_collapse(line))
    flush()


def parse_and_emit(page_html: str) -> str:
    """Parse the paxetbonum page HTML into FORMAT.md Markdown.

    Emits raw (cfr. …) citations as-is — ref conversion is a later step.
    """
    # Body runs from the first named anchor (Epistola) to the closing
    # </blockquote>; everything before/after is nav, index and footer.
    start = page_html.index('<a name="epistola">')
    end = page_html.index("</blockquote>", start)
    body = page_html[start:end]

    output: list[str] = []
    output.append("---")
    output.append("id: 3Soc")
    output.append('title: "Legenda Trium Sociorum"')
    output.append('author: "Fratres Leo, Rufinus et Angelus (attr.)"')
    output.append('date: "1246"')
    output.append('reference_edition: "Fontes Franciscani (Editiones Collegii S. Bonaventurae, 1995)"')
    output.append("license: CC0-1.0")
    output.append("---")
    output.append("")
    output.append("# LEGENDA TRIUM SOCIORUM")
    output.append("")

    anchors = list(_ANCHOR_RE.finditer(body))
    for idx, m in enumerate(anchors):
        name = m.group(1)
        chunk_start = m.end()
        chunk_end = anchors[idx + 1].start() if idx + 1 < len(anchors) else len(body)
        chunk = body[chunk_start:chunk_end]

        # Heading text is everything up to the first </b> after the anchor.
        hb = chunk.find("</b>")
        heading = _clean_heading(chunk[:hb]) if hb != -1 else ""
        chapter_body = chunk[hb + 4:] if hb != -1 else chunk

        if name == "epistola":
            chapter_id = "epistola"
            output.append(f'## {heading or "Epistola"} <a id="{chapter_id}"></a>')
        else:
            roman = ""
            cm = re.match(r"Caput\s+([IVXLC]+)", heading)
            if cm:
                roman = cm.group(1)
            cap_num = roman_to_int(roman) if roman else name
            chapter_id = f"cap{cap_num}"
            output.append(f"## {heading} <a id=\"{chapter_id}\"></a>")
        output.append("")

        _emit_chapter_body(chapter_body, output)

    return "\n".join(output) + "\n"


# ── Entry point ───────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract Legenda Trium Sociorum from HTML to FORMAT.md Markdown"
    )
    parser.add_argument("html", help="Path to '3Soc.html' (Wayback view-source capture)")
    parser.add_argument("-o", "--output", help="Output .md file (default: stdout)")
    args = parser.parse_args()

    # 1. Read raw capture (the page is windows-1252).
    print("1/5  Reading HTML source…", file=sys.stderr)
    raw = Path(args.html).read_text(encoding="windows-1252")

    # 2. Unwrap the Wayback view-source table → original page HTML.
    print("2/5  Unwrapping view-source capture…", file=sys.stderr)
    page = unwrap_view_source(raw)

    # 3. Document-specific structural parsing.
    print("3/5  Parsing structure…", file=sys.stderr)
    md = parse_and_emit(page)

    # 4. Convert scripture references.
    print("4/5  Converting scripture refs…", file=sys.stderr)
    md = convert_refs(md, BOOK_MAP)

    # 5. Fix <ref>/verse-marker overlap.
    print("5/5  Fixing ref/verse overlap…", file=sys.stderr)
    md = fix_ref_verse(md)

    if args.output:
        Path(args.output).write_text(md, encoding="utf-8")
        print(f"Done → {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(md)


if __name__ == "__main__":
    main()
