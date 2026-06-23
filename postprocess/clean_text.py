#!/usr/bin/env python3
"""Clean up raw PDF-extracted text.

Applies, in order:
  1. Rejoin hyphenated words (cross-line and inline typesetting artifacts)
  2. Collapse runs of whitespace to single spaces (preserving newlines)

Usage:
    python postprocess/clean_text.py raw.txt -o cleaned.txt
    cat raw.txt | python postprocess/clean_text.py -
"""

import argparse
import re
import sys
from pathlib import Path


def rejoin_hyphens(text: str) -> str:
    text = re.sub(r"-\s*\n\s*([a-z])", r"\1", text)
    text = re.sub(r"(\w)-([a-z])", r"\1\2", text)
    return text


def collapse_whitespace(text: str) -> str:
    return re.sub(r"[^\S\n]+", " ", text)


def clean(text: str) -> str:
    text = rejoin_hyphens(text)
    text = collapse_whitespace(text)
    return text


def main():
    parser = argparse.ArgumentParser(description="Clean PDF-extracted text")
    parser.add_argument("input", help="Input text file, or '-' for stdin")
    parser.add_argument("-o", "--output", help="Output file (default: stdout)")
    args = parser.parse_args()

    if args.input == "-":
        text = sys.stdin.read()
    else:
        text = Path(args.input).read_text(encoding="utf-8")

    result = clean(text)

    if args.output:
        Path(args.output).write_text(result, encoding="utf-8")
    else:
        sys.stdout.write(result)


if __name__ == "__main__":
    main()
