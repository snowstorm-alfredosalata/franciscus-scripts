#!/usr/bin/env python3
"""Extract the *Opuscula Omnia Sancti Francisci* into one FORMAT.md book.

Input is the franciscanos.org page
(https://www.franciscanos.org/esfa/omfra.html), optionally as a Chrome
"view-source" save (a <table> of line-number/line-content cells); both are
detected and handled.

The page collects ~38 short works (admonitions, letters, prayers, rules,
the Canticle of the Sun, the Testament…). Each is emitted as one level-2
chapter of a single book, keyed by the page's own in-document anchors
(<A NAME="adm"/> → ## … <a id="adm"></a>). Titles and chapter order come
from the page's index.

Mapping to FORMAT.md:
  * <SUP>N</SUP> verse markers      → [N] verse markers inside <p>
  * numbered paragraphs            → <p id="<slug>-<k>"> (k restarts per work)
  * rubrics / editorial headings   → <aside> (any non-numbered text)
  * <I>…</I>, <B>…</B>, alignment  → dropped (text kept)
  * named entities (&iacute; …)    → unescaped to Unicode

Scripture citations are left as the source's parenthetical Latin form
(e.g. "(cfr. Joa 6,64)"); run them through postprocess/convert_refs.py and
postprocess/fix_ref_verse.py afterwards to obtain <ref> tags, exactly as for
the other books.

Usage:
    python extract_opomnia.py opuscola_omnia_sancti_francisci.html \
        -o ../franciscus-data/books/Opuscula.md
"""

import argparse
import html
import re
import sys
from html.parser import HTMLParser
from pathlib import Path


# ── 1. view-source decode ────────────────────────────────────────────────
class _ViewSourceDecoder(HTMLParser):
    """Reconstruct original line text from Chrome's view-source table."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_cell = False
        self.cur: list[str] = []
        self.lines: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "td" and dict(attrs).get("class") == "line-content":
            self.in_cell, self.cur = True, []

    def handle_endtag(self, tag):
        if tag == "td" and self.in_cell:
            self.in_cell = False
            self.lines.append("".join(self.cur))

    def handle_data(self, data):
        if self.in_cell:
            self.cur.append(data)


def to_original_html(raw: str) -> str:
    if "line-content" not in raw:
        return raw  # already the plain page
    dec = _ViewSourceDecoder()
    dec.feed(raw)
    return "\n".join(dec.lines)


# ── 2. index (slug → title, canonical order) ─────────────────────────────
def parse_index(doc: str) -> list[tuple[str, str]]:
    out, seen = [], set()
    for slug, title in re.findall(r'<A HREF="#([^"]+)">(.*?)\[\w+\]', doc):
        if slug in seen:
            continue
        seen.add(slug)
        clean = html.unescape(re.sub(r"<[^>]+>", "", title)).strip()
        clean = re.sub(r"\s+", " ", clean)
        clean = clean.replace("Canticum fratis Solis", "Canticum Fratris Solis")
        out.append((slug, clean))
    return out


# ── 3. body parse (streaming, tolerant of malformed nesting) ─────────────
class _Para:
    __slots__ = ("parts", "verses", "bold", "center")

    def __init__(self):
        self.parts: list[str] = []
        self.verses = 0
        self.bold = False
        self.center = False

    def text(self) -> str:
        raw = html.unescape("".join(self.parts))
        lines = []
        for ln in raw.split("\n"):
            ln = re.sub(r"[ \t]+", " ", ln).strip()
            if ln:
                lines.append(ln)
        return "\n".join(lines)


class BodyParser(HTMLParser):
    def __init__(self, slugs: set[str]):
        super().__init__(convert_charrefs=True)
        self.slugs = slugs
        self.chapters: dict[str, list[_Para]] = {}
        self.cur: list[_Para] | None = None
        self.para: _Para | None = None
        self.open = False
        self.in_sup = False
        self.sup_buf = ""

    # ---- helpers ----
    def _append(self, s: str):
        if self.para is not None:
            self.para.parts.append(s)

    # ---- tag handlers ----
    def handle_starttag(self, tag, attrs):
        if tag == "a":
            name = dict(attrs).get("name")
            if name and name in self.slugs:
                self.cur = self.chapters.setdefault(name, [])
                self.para, self.open = None, False
            return
        if self.cur is None:
            return
        if tag == "p":
            self.para = _Para()
            self.para.center = dict(attrs).get("align", "").lower() == "center"
            self.cur.append(self.para)
            self.open = True
        elif tag == "sup":
            self.in_sup, self.sup_buf = True, ""
        elif tag == "br":
            self._append("\n")
        elif tag == "b":
            if self.para is not None:
                self.para.bold = True

    def handle_startendtag(self, tag, attrs):
        # <br/>, <A NAME=".."/>, <P .../>, <hr/> …
        if tag == "br":
            if self.cur is not None:
                self._append("\n")
        else:
            self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == "p":
            self.open = False
        elif tag == "sup":
            self.in_sup = False
            num = self.sup_buf.strip()
            if num and self.para is not None:
                self.para.verses += 1
                self._append(f"[{num}] ")

    def handle_data(self, data):
        if self.cur is None:
            return
        if self.in_sup:
            self.sup_buf += data
            return
        if self.para is None:
            return
        # Orphan text after a stray </p> (e.g. Canticle): treat as a
        # continuation of the last open paragraph rather than dropping it.
        self._append(data)


# ── 4. emit ──────────────────────────────────────────────────────────────
FRONTMATTER = """\
---
title: "Opuscula Omnia Sancti Francisci Assisiensis"
author: "Franciscus Assisiensis"
date: "1205-1226"
reference_edition: "Kajetan Esser, Opuscula sancti patris Francisci Assisiensis (Grottaferrata, 1978); text from franciscanos.org (Directorio Franciscano)"
description:
notes:
---
"""


def emit(index: list[tuple[str, str]], chapters: dict[str, list[_Para]]) -> str:
    out = [FRONTMATTER, "", "# OPUSCULA OMNIA SANCTI FRANCISCI ASSISIENSIS", ""]
    for slug, title in index:
        paras = chapters.get(slug, [])
        out.append(f"## {title} <a id=\"{slug}\"></a>")
        out.append("")

        aside: list[str] = []
        body: list[str] = []  # consecutive numbered paragraphs → one <p>
        last = 0  # highest verse number seen in the open body group
        k = 0

        def flush_aside():
            if aside:
                out.append("<aside>")
                out.extend(aside)
                out.append("</aside>")
                out.append("")
                aside.clear()

        def flush_body():
            nonlocal k, last
            if body:
                k += 1
                out.append(f'<p id="{slug}-{k}">')
                out.append("\n".join(body))
                out.append("</p>")
                out.append("")
                body.clear()
            last = 0

        for p in paras:
            txt = p.text()
            if not txt:
                continue
            if p.bold:  # the work's own title line — supplied by the index
                continue
            is_rubric = not p.verses and (p.center or txt.lstrip().startswith("["))
            if is_rubric:
                # Editorial heading (centered or bracketed) → aside; closes the
                # current division.
                flush_body()
                aside.append(txt)
                continue
            # Numbered text, or verse-less body prose, continues the current
            # division. Group a division (chapter/psalm/letter) into one <p> so
            # its verse numbers run 1..n — but a *restart* of the numbering (next
            # number ≤ the last seen, e.g. an antiphon after a psalm) opens a new
            # paragraph rather than duplicating verse ids.
            flush_aside()
            vnums = [int(n) for n in re.findall(r"\[(\d+)\]", txt)]
            if body and vnums and vnums[0] <= last:
                flush_body()
            body.append(txt)
            if vnums:
                last = max(vnums)
        flush_body()
        flush_aside()
    return "\n".join(out).rstrip() + "\n"


def main():
    ap = argparse.ArgumentParser(description="Extract Opuscula Omnia → FORMAT.md")
    ap.add_argument("input", help="saved HTML page (view-source or plain), or -")
    ap.add_argument("-o", "--output", default="-", help="output .md (default stdout)")
    args = ap.parse_args()

    raw = (sys.stdin.read() if args.input == "-"
           else Path(args.input).read_text("utf-8", "replace"))
    doc = to_original_html(raw)

    index = parse_index(doc)
    if not index:
        sys.exit("error: no index found — is this the omfra.html page?")
    slugs = {s for s, _ in index}

    bp = BodyParser(slugs)
    bp.feed(doc[doc.find('<A NAME='):])  # skip the index region
    md = emit(index, bp.chapters)

    if args.output == "-":
        sys.stdout.write(md)
    else:
        Path(args.output).write_text(md, "utf-8")
    missing = [s for s in slugs if not bp.chapters.get(s)]
    print(f"{len(index)} works; "
          f"{sum(1 for s,_ in index if bp.chapters.get(s))} with content"
          + (f"; EMPTY: {missing}" if missing else ""), file=sys.stderr)


if __name__ == "__main__":
    main()
