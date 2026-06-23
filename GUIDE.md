# franciscus-scripts — Extraction Pipeline Guide

Scripts for converting Franciscan source-text PDFs into
[FORMAT.md](../franciscus-data/FORMAT.md)-compliant Markdown files.

## Prerequisites

```
pip install pymupdf
```

Python 3.12+.

## Directory layout

```
franciscus-scripts/
├── lib/                    Shared libraries
│   └── scripture.py        Book-abbreviation map, regex builders, roman_to_int
│
├── analyze_pdf/            Pre-pipeline inspection
│   └── report.py          JSON structural report of a new PDF
│
├── extract_pdf/            PDF → raw text
│   ├── pdf_to_text.py      PyMuPDF page-by-page extraction
│   └── strip_boilerplate.py  Remove licence / header / footer by sentinel
│
├── postprocess/            Text → FORMAT.md compliance
│   ├── clean_text.py       Rejoin hyphenated words, collapse whitespace
│   ├── convert_refs.py     Latin (cfr. …) citations → <ref to="…"> tags
│   └── fix_ref_verse.py    Ensure <ref> tags don't straddle verse markers
│
├── validate/               Quality gate
│   └── validate_format.py  Check all FORMAT.md requirements
│
└── extract_1cel.py         Document-specific driver for 1Celano
```

## How the pipeline works

Every extraction follows the same six-stage pattern.  Only **stage 4**
(structural parsing) varies per document; the rest are shared modules.

```
┌─────────┐    ┌──────────────┐    ┌────────────┐
│  PDF     │───▶│ pdf_to_text  │───▶│ strip_     │
│  file    │    │              │    │ boilerplate│
└─────────┘    └──────────────┘    └─────┬──────┘
                                         │ raw text
                                   ┌─────▼──────┐
                                   │ clean_text  │
                                   └─────┬──────┘
                                         │ cleaned text
                                   ┌─────▼──────────────┐
                                   │ structural parser   │  ← document-specific
                                   │ (extract_XXXX.py)   │
                                   └─────┬──────────────┘
                                         │ markdown with raw citations
                                   ┌─────▼──────────┐
                                   │ convert_refs    │
                                   └─────┬──────────┘
                                         │ markdown with <ref> tags
                                   ┌─────▼──────────┐
                                   │ fix_ref_verse   │
                                   └─────┬──────────┘
                                         │ final markdown
                                   ┌─────▼──────────────┐
                                   │ validate_format     │
                                   └────────────────────┘
```

## Starting a new extraction

### 1. Inspect the PDF

```bash
python analyze_pdf/report.py "path/to/Source.pdf" -o report.json
```

The JSON report tells you:
- **paragraph_markers** — numbering style (continuous vs. per-section), range
- **chapter_headings** — Caput / Capitulum patterns found
- **scripture_refs.book_abbreviations** — Latin abbreviations present
  (check these against `lib/scripture.py` and add any missing ones)
- **structural_markers** — INCIPIT / EXPLICIT / OPUSCULUM markers
- **allcaps_lines_sample** — potential aside / rubric text

### 2. Write a document-specific driver

Copy `extract_1cel.py` as a template.  You only need to change:
- The **frontmatter** values (id, title, author, date, etc.)
- The **title sentinel** passed to `strip_boilerplate()`
- The **structural parser** — adapt chapter heading patterns, section
  grouping, and paragraph-ID logic to match the edition's conventions

The driver imports all shared stages — no need to rewrite ref conversion,
text cleanup, or validation.

### 3. Run the pipeline

```bash
python extract_XXXX.py "path/to/Source.pdf" -o "../franciscus-data/books/XXXX.md"
```

### 4. Validate

```bash
python validate/validate_format.py "../franciscus-data/books/XXXX.md"
```

### 5. Manual review

The pipeline output is a strong first draft, **not a finished product**.
Items that always need human review:

- **`<ref>` clause boundaries** — the wrapping heuristic looks backward to
  the nearest comma / semicolon / period.  It is wrong when the allusion
  spans a longer or shorter clause than the heuristic expects.
- **Aside vs. paragraph boundaries** — EXPLICIT / INCIPIT markers that
  appear inline within a paragraph's last verse get absorbed into the
  paragraph text.  Move them into a separate `<aside>` block.
- **Rubric headings inside paragraphs** — some editions embed section
  subtitles within paragraph text (e.g. "VI. — De mutis…").  These should
  become `<aside>` blocks or part of a `##` heading.
- **Typos in the source** — the PDF itself may contain errors (e.g.
  "dsicipulus" for "discipulus").

## Using the scripts standalone

Every script under `extract_pdf/`, `postprocess/`, and `validate/` also
works as a standalone CLI tool.  Each reads from a file or stdin (`-`) and
writes to stdout or a file (`-o`).

```bash
# Extract raw text from pages 2–78
python extract_pdf/pdf_to_text.py source.pdf --pages 2-78 > raw.txt

# Strip boilerplate
python extract_pdf/strip_boilerplate.py raw.txt \
    --start-after "LEGENDA MAIOR" \
    --end-before "Quest'opera" > trimmed.txt

# Clean hyphenation + whitespace
python postprocess/clean_text.py trimmed.txt > clean.txt

# Convert scripture refs (with optional custom book map)
python postprocess/convert_refs.py draft.md -o refs.md
python postprocess/convert_refs.py draft.md --book-map custom.json

# Fix ref/verse overlap
python postprocess/fix_ref_verse.py refs.md -o final.md

# Validate
python validate/validate_format.py final.md
```

## Shared library: `lib/scripture.py`

Contains:
- **`BOOK_MAP`** — Latin → anglophone abbreviation dict
  (Quaracchi / Analecta Franciscana conventions)
- **`build_patterns(book_map)`** — compiles `re_cfr` and `re_single`
  regexes from any book map
- **`roman_to_int(s)`** — Roman numeral → int conversion

If a new PDF uses abbreviations not in `BOOK_MAP`, add them there so all
future extractors benefit.  `convert_refs.py` also accepts `--book-map`
for one-off overrides without touching the shared code.

## FORMAT.md rules enforced by the validator

| Check                                         | Level    |
|-----------------------------------------------|----------|
| YAML frontmatter with all six required fields  | REQUIRED |
| Exactly one `#` heading                        | REQUIRED |
| `##` headings have `<a id="…"></a>` anchors    | REQUIRED |
| No headings below level 2                      | REQUIRED |
| All body text inside `<p id="…">` or `<aside>` | REQUIRED |
| No duplicate paragraph IDs                     | REQUIRED |
| `<ref>` tags have non-empty `to` attributes    | REQUIRED |
| `<ref>` does not open immediately before `[N]` | REQUIRED |
| `</ref>` does not close immediately after `[N]`| REQUIRED |
