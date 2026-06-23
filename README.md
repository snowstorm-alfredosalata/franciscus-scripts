# franciscus-scripts

Python scripts for extracting and manipulating source texts into structured Markdown files compliant with the [FORMAT.md](../franciscus-data/FORMAT.md) specification.

Processing a typical PDF file goes through six stages: text extraction, boilerplate stripping, whitespace cleanup, structural parsing, scripture-reference conversion, and format validation.

## Requirements

- Python 3.12+
- [PyMuPDF](https://pymupdf.readthedocs.io/): `pip install pymupdf`

## Quick start

```bash
# Inspect a new PDF to plan extraction
python analyze_pdf/report.py "path/to/Source.pdf" -o report.json

# Run the full pipeline (1Celano example)
python extract_1cel.py "path/to/1Celano-Quaracchi.pdf" -o "../franciscus-data/books/1Cel.md"

# Validate the output
python validate/validate_format.py "../franciscus-data/books/1Cel.md"
```

## Pipeline

```
PDF ─→ pdf_to_text ─→ strip_boilerplate ─→ clean_text
       ─→ structural parser (per-document) ─→ convert_refs
       ─→ fix_ref_verse ─→ validate_format
```

Each document gets its own driver script (e.g. `extract_1cel.py`) that handles the structural parsing stage. Everything else is shared.

## Project layout

```
franciscus-scripts/
├── lib/
│   └── scripture.py           Latin→anglophone book-abbreviation map, regex builders
├── analyze_pdf/
│   └── report.py             JSON structural report of a PDF
├── extract_pdf/
│   ├── pdf_to_text.py         PyMuPDF page-by-page text extraction
│   └── strip_boilerplate.py   Remove licence / header / footer by sentinel
├── postprocess/
│   ├── clean_text.py          Rejoin hyphenated words, collapse whitespace
│   ├── convert_refs.py        Latin citations → <ref to="…"> tags
│   └── fix_ref_verse.py       Prevent <ref> tags from straddling verse markers
├── validate/
│   └── validate_format.py     Check all FORMAT.md requirements
├── extract_1cel.py            Document-specific driver for 1Celano (Vita Prima)
└── extract_legmai.py          Document-specific driver for Legenda Maior (Bonaventure)
```

## Standalone usage

Every module under `extract_pdf/`, `postprocess/`, and `validate/` works as a standalone CLI tool, reading from a file or stdin (`-`) and writing to stdout or a file (`-o`).

```bash
python extract_pdf/pdf_to_text.py source.pdf --pages 2-78 > raw.txt
python extract_pdf/strip_boilerplate.py raw.txt --start-after "LEGENDA MAIOR" > trimmed.txt
python postprocess/clean_text.py trimmed.txt > clean.txt
python postprocess/convert_refs.py draft.md -o refs.md
python postprocess/fix_ref_verse.py refs.md -o final.md
python validate/validate_format.py final.md
```

## Adding a new document

1. Run `analyze_pdf/report.py` on the PDF to understand its structure
2. Copy `extract_1cel.py` as a template — adapt frontmatter, title sentinel, and structural parser
3. Add any new book abbreviations to `lib/scripture.py` (or pass `--book-map` for one-offs)
4. Run the driver, validate, then review manually

See [GUIDE.md](GUIDE.md) for the full walkthrough.

## License

[AGPL-3.0](LICENSE) — Copyright 2026 Alfredo Salata
