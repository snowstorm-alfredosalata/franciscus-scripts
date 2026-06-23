"""Shared scripture-reference utilities.

Canonical Latin→anglophone book-abbreviation map and compiled regex
builders used by both the per-PDF extractors and the postprocess
pipeline.

Import from anywhere in franciscus-scripts:
    from lib.scripture import BOOK_MAP, build_patterns, roman_to_int
"""

import re

# ── Latin → anglophone scripture-book abbreviations ──────────────────────
# Keys  : abbreviations found in Quaracchi / Analecta Franciscana editions
# Values: standard anglophone biblical notation (used in FORMAT.md refs)
BOOK_MAP: dict[str, str] = {
    # Old Testament
    "Gen":   "Gen",
    "Ex":    "Exod",
    "Lev":   "Lev",
    "Num":   "Num",
    "Deut":  "Deut",
    "Ios":   "Josh",
    "Iods":  "Josh",
    # "Iud" is ambiguous (Iudicum=Judges vs. Iudae=Jude) — mapped to Jude
    # below because it's more common as a NT abbreviation.  Judges uses the
    # unambiguous "Iudc" form in Quaracchi editions.
    "Iudc":  "Judg",
    "Rut":   "Ruth",
    "1Re":   "1 Kgs",
    "2Re":   "2 Kgs",
    "3Re":   "3 Kgs",
    "4Re":   "4 Kgs",
    "1Par":  "1 Chr",
    "2Par":  "2 Chr",
    "2Esd":  "2 Esd",
    "Tob":   "Tob",
    "Iudt":  "Jdt",
    "Est":   "Esth",
    "Iob":   "Job",
    "Ps":    "Ps",
    "Prov":  "Prov",
    "Qo":    "Eccl",
    "Cant":  "Song",
    "Sap":   "Wis",
    "Sir":   "Sir",
    "Is":    "Isa",
    "Ier":   "Jer",
    "Lam":   "Lam",
    "Bar":   "Bar",
    "Ez":    "Ezek",
    "Dan":   "Dan",
    "Os":    "Hos",
    "Ioel":  "Joel",
    "Mic":   "Mic",
    "Zac":   "Zech",
    "1Mac":  "1 Macc",
    "2Mac":  "2 Macc",
    # New Testament
    "Mat":   "Matt",
    "Mar":   "Mark",
    "Luc":   "Luke",
    "Ioa":   "John",
    "Act":   "Acts",
    "Rom":   "Rom",
    "1Cor":  "1 Cor",
    "2Cor":  "2 Cor",
    "Gal":   "Gal",
    "Eph":   "Eph",
    "Phip":  "Phil",
    "Col":   "Col",
    "1The":  "1 Thess",
    "2The":  "2 Thess",
    "1Tim":  "1 Tim",
    "2Tim":  "2 Tim",
    "Tit":   "Titus",
    "Heb":   "Heb",
    "Iac":   "Jas",
    "1Pet":  "1 Pet",
    "2Pet":  "2 Pet",
    "1Ioa":  "1 John",
    "1Joa":  "1 John",
    "Iud":   "Jude",
    "Apoc":  "Rev",
}


def build_patterns(book_map: dict[str, str] | None = None):
    """Compile regexes from a book map (defaults to BOOK_MAP).

    Returns (re_cfr, re_single):
      re_cfr    — matches full parenthetical citations: (cfr. Book ch,v)
                   and bare (Book ch,v).  Also handles bare continuations
                   where the book name is omitted after ";":
                   (cfr. Apoc 6,12; 7,2)
      re_single — matches one "Book ch,v" inside a multi-ref string
      re_cont   — matches a bare "ch,v" continuation (no book name)
    """
    bmap = book_map or BOOK_MAP
    book_pat = "|".join(
        re.escape(k) for k in sorted(bmap, key=len, reverse=True)
    )
    re_cfr = re.compile(
        r"\((?:[Cc]fr\.?\s+)?"
        r"((?:" + book_pat + r"),?\s*\d+[,:\.\s\d\-]*"
        r"(?:;\s*(?:(?:" + book_pat + r"),?\s*)?\d+[,:\.\s\d\-]*)*"
        r")\)",
    )
    re_single = re.compile(
        r"(" + book_pat + r"),?\s*(\d+(?:\s*,\s*\d+(?:\s*-\s*\d+)?)?)"
    )
    re_cont = re.compile(
        r"(\d+(?:\s*,\s*\d+(?:\s*-\s*\d+)?)?)"
    )
    return re_cfr, re_single, re_cont


def roman_to_int(roman: str) -> int:
    """Convert a Roman numeral string to an integer."""
    vals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    roman = roman.strip().upper()
    for i, ch in enumerate(roman):
        v = vals.get(ch, 0)
        if i + 1 < len(roman) and v < vals.get(roman[i + 1], 0):
            total -= v
        else:
            total += v
    return total
