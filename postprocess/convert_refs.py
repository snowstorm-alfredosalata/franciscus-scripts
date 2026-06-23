#!/usr/bin/env python3
"""Convert Latin scripture citations to FORMAT.md <ref> tags.

Handles:
  - (cfr. Book ch,v)  — standard Quaracchi form
  - (Book ch,v)        — bare citation without "cfr."
  - (cfr. Sir, 50,6)   — comma after book name (edge case)
  - Multi-references:   (cfr. Rom 5,10; 2Cor 5,19)

After converting the parenthetical to a <ref to="..."> marker, applies a
backward-looking heuristic to wrap the preceding clause in <ref>…</ref>.
The heuristic walks back to the nearest clause boundary (comma, semicolon,
colon, period, or newline).  Manual review is always needed.

The BOOK_MAP can be overridden with --book-map pointing to a JSON file
whose keys are Latin abbreviations and values are anglophone abbreviations.

Usage:
    python postprocess/convert_refs.py cleaned.txt -o refs.txt
    cat cleaned.txt | python postprocess/convert_refs.py -
    python postprocess/convert_refs.py cleaned.txt --book-map custom.json
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.scripture import BOOK_MAP, build_patterns  # noqa: E402


def convert_citations(text: str, book_map: dict[str, str]) -> str:
    """Replace parenthetical citations with <ref to="…"> markers."""
    re_cfr, re_single, re_cont = build_patterns(book_map)
    warnings: list[str] = []

    def _replace(m: re.Match) -> str:
        refs_raw = m.group(1)
        parts = [p.strip() for p in refs_raw.split(";")]
        ref_values = []
        last_book_lat = ""
        for part in parts:
            found = re_single.search(part)
            if found:
                last_book_lat = found.group(1)
                book_eng = book_map.get(last_book_lat, last_book_lat)
                loc_norm = found.group(2).replace(",", ":").replace(" ", "")
                ref_values.append(f"{book_eng} {loc_norm}")
            elif last_book_lat:
                # Bare continuation: "7,2" inherits the previous book
                cont = re_cont.match(part)
                if cont:
                    book_eng = book_map.get(last_book_lat, last_book_lat)
                    loc_norm = cont.group(1).replace(",", ":").replace(" ", "")
                    ref_values.append(f"{book_eng} {loc_norm}")
                else:
                    warnings.append(f"Could not parse continuation: {part!r} in {m.group(0)}")
            else:
                warnings.append(f"Could not parse ref: {part!r} in {m.group(0)}")

        if not ref_values:
            warnings.append(f"No refs extracted from: {m.group(0)}")
            return m.group(0)

        return '<ref to="' + "; ".join(ref_values) + '">'

    result = re_cfr.sub(_replace, text)
    for w in warnings:
        print(f"  REF WARNING: {w}", file=sys.stderr)
    return result


def wrap_ref_text(text: str) -> str:
    """Walk backwards from each <ref to="…"> marker to the nearest clause
    boundary and wrap that text in <ref>…</ref>."""
    parts = re.split(r'(<ref to="[^"]+">)', text)
    if len(parts) < 2:
        return text

    result: list[str] = []
    for part in parts:
        if part.startswith('<ref to="'):
            if result:
                prev = result[-1]
                boundary = -1
                for sep in [". ", "; ", ": ", ", ", "\n"]:
                    pos = prev.rfind(sep)
                    if pos > boundary:
                        boundary = pos

                if boundary >= 0:
                    sep_len = 2 if prev[boundary:boundary + 2] in [". ", "; ", ": ", ", "] else 1
                    before = prev[:boundary + sep_len]
                    clause = prev[boundary + sep_len:]
                else:
                    before = ""
                    clause = prev

                result[-1] = before
                result.append(f"{part}{clause}</ref>")
            else:
                result.append(f"{part}</ref>")
        else:
            result.append(part)
    return "".join(result)


def process(text: str, book_map: dict[str, str] | None = None) -> str:
    """Full pipeline: convert citations then wrap clause text."""
    bmap = book_map or BOOK_MAP
    text = convert_citations(text, bmap)
    text = wrap_ref_text(text)
    return text


def main():
    parser = argparse.ArgumentParser(
        description="Convert Latin scripture citations to <ref> tags"
    )
    parser.add_argument("input", help="Input text file, or '-' for stdin")
    parser.add_argument("-o", "--output", help="Output file (default: stdout)")
    parser.add_argument(
        "--book-map",
        help="JSON file with Latin→English book abbreviation overrides",
    )
    args = parser.parse_args()

    bmap = dict(BOOK_MAP)
    if args.book_map:
        custom = json.loads(Path(args.book_map).read_text(encoding="utf-8"))
        bmap.update(custom)

    if args.input == "-":
        text = sys.stdin.read()
    else:
        text = Path(args.input).read_text(encoding="utf-8")

    result = process(text, bmap)

    if args.output:
        Path(args.output).write_text(result, encoding="utf-8")
    else:
        sys.stdout.write(result)


if __name__ == "__main__":
    main()
