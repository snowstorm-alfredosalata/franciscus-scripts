#!/usr/bin/env python3
"""Strip boilerplate (licence pages, headers, footers) from extracted text.

Trims everything before the first occurrence of --start-after and
everything from the last occurrence of --end-before onward.

Usage:
    python extract_pdf/strip_boilerplate.py raw.txt \
        --start-after "VITA PRIMA" \
        --end-before "Quest'opera di propriet"
    cat raw.txt | python extract_pdf/strip_boilerplate.py - \
        --start-after "LEGENDA MAIOR"
"""

import argparse
import sys
from pathlib import Path


def strip(text: str, start_after: str | None, end_before: str | None) -> str:
    if start_after:
        idx = text.find(start_after)
        if idx >= 0:
            text = text[idx:]
        else:
            print(f"WARNING: start sentinel not found: {start_after!r}", file=sys.stderr)

    if end_before:
        idx = text.rfind(end_before)
        if idx >= 0:
            text = text[:idx]
        else:
            print(f"WARNING: end sentinel not found: {end_before!r}", file=sys.stderr)

    return text.strip()


def main():
    parser = argparse.ArgumentParser(description="Strip boilerplate from extracted text")
    parser.add_argument("input", help="Input text file, or '-' for stdin")
    parser.add_argument("--start-after", help="Keep text from this sentinel onward")
    parser.add_argument("--end-before", help="Drop text from the last occurrence of this sentinel")
    parser.add_argument("-o", "--output", help="Output file (default: stdout)")
    args = parser.parse_args()

    if args.input == "-":
        text = sys.stdin.read()
    else:
        text = Path(args.input).read_text(encoding="utf-8")

    result = strip(text, args.start_after, args.end_before)

    if args.output:
        Path(args.output).write_text(result, encoding="utf-8")
    else:
        sys.stdout.write(result)


if __name__ == "__main__":
    main()
