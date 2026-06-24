#!/usr/bin/env python3
"""Validate a Markdown file against the Franciscus FORMAT.md specification.

Checks:
  1. YAML frontmatter with all six required fields
  2. Exactly one level-1 heading (title)
  3. All level-2 headings have <a id="…"> anchors
  4. No heading levels below 2
  5. All body text inside <p id="…"> or <aside>
  6. No duplicate paragraph IDs
  7. <ref> tags have non-empty 'to' attribute
  8. No <ref>-opens immediately before verse markers
  9. No </ref>-closes immediately after verse markers

Exit code 0 = pass, 1 = failures found.

Usage:
    python validate/validate_format.py books/1Cel.md
"""

import argparse
import re
import sys
from pathlib import Path


def validate(text: str) -> list[str]:
    errors: list[str] = []
    lines = text.split("\n")

    # ── 1. Frontmatter ──────────────────────────────────────────────────
    if not text.startswith("---\n"):
        errors.append("Missing YAML frontmatter (file must start with '---')")
    else:
        end = text.find("\n---\n", 4)
        if end < 0:
            errors.append("Unterminated YAML frontmatter (no closing '---')")
        else:
            fm = text[4:end]
            required = ["id", "title", "author", "date", "reference_edition", "license"]
            for field in required:
                if not re.search(rf"^{field}\s*:", fm, re.MULTILINE):
                    errors.append(f"Frontmatter missing required field: {field}")

    # ── 2. Exactly one level-1 heading ──────────────────────────────────
    h1s = [i for i, l in enumerate(lines, 1) if re.match(r"^# ", l)]
    if len(h1s) == 0:
        errors.append("No level-1 heading (# title) found")
    elif len(h1s) > 1:
        errors.append(f"Multiple level-1 headings at lines: {h1s}")

    # ── 3. Level-2 headings need <a id="…"> ─────────────────────────────
    for i, l in enumerate(lines, 1):
        if re.match(r"^## ", l):
            if not re.search(r'<a id="[^"]+"></a>', l):
                errors.append(f"Line {i}: ## heading missing <a id=\"…\"></a> anchor")

    # ── 4. No headings below level 2 ────────────────────────────────────
    for i, l in enumerate(lines, 1):
        if re.match(r"^###+ ", l):
            errors.append(f"Line {i}: heading level 3+ not permitted")

    # ── 5. Body text outside <p> or <aside> ─────────────────────────────
    in_frontmatter = False
    in_p = False
    in_aside = False
    past_frontmatter = False
    for i, l in enumerate(lines, 1):
        stripped = l.strip()
        if stripped == "---":
            if not past_frontmatter:
                in_frontmatter = not in_frontmatter
                if not in_frontmatter:
                    past_frontmatter = True
            continue
        if in_frontmatter:
            continue
        if not stripped:
            continue
        if re.match(r"^#+ ", stripped):
            continue
        if stripped.startswith("<p "):
            in_p = True
            continue
        if stripped == "</p>":
            in_p = False
            continue
        if stripped == "<aside>":
            in_aside = True
            continue
        if stripped == "</aside>":
            in_aside = False
            continue
        if not in_p and not in_aside:
            errors.append(f"Line {i}: text outside <p> or <aside>: {stripped[:60]}")

    # ── 6. Duplicate paragraph IDs ──────────────────────────────────────
    pids = re.findall(r'<p id="([^"]+)">', text)
    seen: set[str] = set()
    for pid in pids:
        if pid in seen:
            errors.append(f"Duplicate paragraph id: {pid}")
        seen.add(pid)

    # ── 7. <ref> tags with empty 'to' ──────────────────────────────────
    for m in re.finditer(r'<ref to="([^"]*)">', text):
        if not m.group(1).strip():
            pos = text[:m.start()].count("\n") + 1
            errors.append(f"Line ~{pos}: <ref> with empty 'to' attribute")

    # ── 8–9. <ref>/verse overlap ────────────────────────────────────────
    for m in re.finditer(r'<ref to="[^"]+">[ \t]*\[\d+\]', text):
        pos = text[:m.start()].count("\n") + 1
        errors.append(f"Line ~{pos}: <ref> opens immediately before verse marker")

    for m in re.finditer(r'\[\d+\][ \t]*</ref>', text):
        pos = text[:m.start()].count("\n") + 1
        errors.append(f"Line ~{pos}: </ref> closes immediately after verse marker")

    return errors


def main():
    parser = argparse.ArgumentParser(description="Validate FORMAT.md conformance")
    parser.add_argument("file", help="Markdown file to validate")
    args = parser.parse_args()

    text = Path(args.file).read_text(encoding="utf-8")
    errors = validate(text)

    if errors:
        print(f"FAIL — {len(errors)} issue(s):", file=sys.stderr)
        for e in errors:
            print(f"  • {e}", file=sys.stderr)
        sys.exit(1)
    else:
        print("PASS — all checks passed", file=sys.stderr)


if __name__ == "__main__":
    main()
