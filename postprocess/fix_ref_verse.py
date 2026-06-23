#!/usr/bin/env python3
"""Fix <ref> / verse-marker overlap in FORMAT.md files.

Rules:
  - A <ref> opening tag must NOT appear immediately before a verse marker [N].
    → move the opening tag to after the verse marker.
  - A </ref> closing tag must NOT appear immediately after a verse marker [N].
    → move the closing tag to before the verse marker.

In other words, a verse marker may be inside a <ref> only when the ref
genuinely spans multiple verses.

Usage:
    python postprocess/fix_ref_verse.py draft.md -o fixed.md
    cat draft.md | python postprocess/fix_ref_verse.py -
"""

import argparse
import re
import sys
from pathlib import Path


def fix(text: str) -> str:
    # <ref to="..."> immediately followed by optional whitespace then [N]
    # → swap: put verse marker first, then the <ref> tag
    text = re.sub(
        r'(<ref to="[^"]+">)\s*(\[\d+\])',
        r"\2 \1",
        text,
    )

    # [N] immediately followed by optional whitespace then </ref>
    # → swap: put </ref> before the verse marker
    text = re.sub(
        r'(\[\d+\])\s*(</ref>)',
        r"\2\1",
        text,
    )

    return text


def main():
    parser = argparse.ArgumentParser(
        description="Fix <ref>/verse-marker overlap in FORMAT.md files"
    )
    parser.add_argument("input", help="Input .md file, or '-' for stdin")
    parser.add_argument("-o", "--output", help="Output file (default: stdout)")
    args = parser.parse_args()

    if args.input == "-":
        text = sys.stdin.read()
    else:
        text = Path(args.input).read_text(encoding="utf-8")

    result = fix(text)

    if args.output:
        Path(args.output).write_text(result, encoding="utf-8")
    else:
        sys.stdout.write(result)


if __name__ == "__main__":
    main()
