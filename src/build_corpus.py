"""Build data/pantun.csv from the book spreadsheets in data/raw/.

Nothing is typed in by hand: every row comes straight from a spreadsheet
cell, and every row records which book it came from.

Two spreadsheet layouts exist:
  1. Most books have a sheet "Pantun 4 Kerat" with columns Baris 1..Baris 4,
     plus a sheet "Maklumat Buku" with title / author / publisher / year.
  2. "Kumpulan Pantun Melayu" (Zainal Abidin Bakar) has the whole pantun in
     ONE cell, e.g. "line1, line2; line3, line4." and mixes 2-, 4- and 6-line
     pantun. We only keep cells that split cleanly into 2 + 2 lines.

Text is copied as-is here; cleaning happens in data_loader.py.
Anything not used is written to data/skipped_from_raw.csv with a reason.

Run from the project root:
    python -m src.build_corpus
then check the result with:
    python -m src.data_loader
"""

import csv
import re
import sys
from pathlib import Path

import openpyxl

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
OUT_CSV = PROJECT_ROOT / "data" / "pantun.csv"
SKIPPED_CSV = PROJECT_ROOT / "data" / "skipped_from_raw.csv"

# One entry per book: (short code used in ids, file name, collection type).
# collection_type describes the BOOK, not each pantun:
#   traditional_anthology  - compiled from older published/oral sources
#   author_collection      - pantun written by the named author
#   editorial_compilation  - compiled by a publisher's editors (origin not stated)
BOOKS = [
    ("ZAB",  "Kumpulan Pantun Melayu oleh Zainal Abidin Bakar.xlsx", "traditional_anthology"),
    ("KH1010", "1010 Pantun Baharu.xlsx", "author_collection"),
    ("KHPB", "Pantun Peribahasa.xlsx", "author_collection"),
    ("AS",   "Pantun Berkait Mengejar Pelangi.xlsx", "author_collection"),
    ("ASM",  "Pantun Kasih Setia Budi.xlsx", "author_collection"),
    ("PN1",  "Pantun Pak Nazel.xlsx", "author_collection"),
    ("PN2",  "Pantun Pak Nazel 2.xlsx", "author_collection"),
    ("PN3",  "Pantun Pak Nazel 3.xlsx", "author_collection"),
    ("PN4",  "Pantun Pak Nazel 4.xlsx", "author_collection"),
    ("PNIP", "Pantun Pak Nazel Indahnya Pantun Melayu.xlsx", "author_collection"),
    ("PNSS", "Pantun Pak Nazel Santun Seni Bicara.xlsx", "author_collection"),
    ("HR",   "Setaman Pantun Bertatah Bahasa.xlsx", "author_collection"),
    ("DBP",  "Sekalung Budi, Seuntai Bahasa.xlsx", "editorial_compilation"),
]

# Files in data/raw that are deliberately NOT used, and why.
EXCLUDED = {
    "Gurindam Hidup.xlsx": "gurindam (2-line verse), not pantun",
    "Kurik Kundi Merah Saga - Dewan Bahasa Dan Pustaka.pdf": "PDF, not yet extracted",
}

OUT_COLUMNS = ["id", "line1", "line2", "line3", "line4", "source", "label",
               "collection", "collection_type", "theme"]


def cell_text(value):
    """Spreadsheet cell -> clean string ('' for empty cells)."""
    return "" if value is None else str(value).strip()


def read_book_info(workbook):
    """Read the 'Maklumat Buku' sheet into a dict like {'Tajuk Buku': '...'}."""
    if "Maklumat Buku" not in workbook.sheetnames:
        return {}
    info = {}
    for row in workbook["Maklumat Buku"].iter_rows(values_only=True):
        if row and row[0] and len(row) > 1 and row[1] is not None:
            info[cell_text(row[0])] = cell_text(row[1])
    return info


def make_source(info, fallback_title):
    """Build e.g. 'Pantun Pak Nazel 3, Nazel Hashim Mohamad (Dewan Bahasa dan Pustaka, 2015)'."""
    title = info.get("Tajuk Buku", fallback_title)
    # The author field has a different name in different files.
    author = next((v for k, v in info.items() if k.startswith(("Pengarang", "Nama Penulis"))), "")
    publisher = info.get("Penerbit", "")
    year = info.get("Tahun Terbitan", "").removesuffix(".0")
    details = ", ".join(x for x in [publisher, year] if x and x != "Tiada Nyataan")
    source = f"{title}, {author}" if author else title
    return f"{source} ({details})" if details else source


def read_four_line_sheet(path, code, collection_type, skipped):
    """Layout 1: read the 'Pantun 4 Kerat' sheet."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    info = read_book_info(wb)
    title = info.get("Tajuk Buku", path.stem)
    source = make_source(info, path.stem)
    rows = list(wb["Pantun 4 Kerat"].iter_rows(values_only=True))

    # Find columns by header name (headers sometimes have trailing spaces).
    header = [cell_text(h).lower() for h in rows[0]]
    line_cols = [header.index(f"baris {i}") for i in range(1, 5)]
    theme_col = header.index("tema") if "tema" in header else None
    origin_col = header.index("asal") if "asal" in header else None  # only in "Pantun Pak Nazel"

    out = []
    for n, row in enumerate(rows[1:], start=2):
        row = list(row) + [None] * (len(header) - len(row))  # pad short rows
        lines = [cell_text(row[c]) for c in line_cols]
        if not any(lines):
            continue  # blank spreadsheet row
        row_source = source
        if origin_col is not None:
            origin = cell_text(row[origin_col])
            if origin and origin != title:  # e.g. "WG, JANUARI 2006" = first published in a magazine
                row_source = f"{source}; asal: {origin}"
        out.append({
            "id": f"{code}-{len(out) + 1:04d}",
            "line1": lines[0], "line2": lines[1], "line3": lines[2], "line4": lines[3],
            "source": row_source, "label": "real",
            "collection": title, "collection_type": collection_type,
            "theme": cell_text(row[theme_col]) if theme_col is not None else "",
        })
    return out


def split_zainal_cell(text):
    """Split 'line1, line2; line3, line4.' into 4 lines, or return None.

    Rule: exactly one ';' separates pembayang from maksud, and each half has
    exactly one ', ' between its two lines. Anything else (2-line or 6-line
    pantun, extra commas inside a line, missing ';') is left out rather than
    guessed, because a wrong split would give a wrong pembayang/maksud.
    """
    halves = text.strip().rstrip(".!?").split(";")
    if len(halves) != 2:
        return None
    lines = []
    for half in halves:
        parts = re.split(r",\s+", half.strip().rstrip(","))
        if len(parts) != 2:
            return None
        lines.extend(p.strip() for p in parts)
    return lines if all(lines) else None


def read_zainal(path, code, collection_type, skipped):
    """Layout 2: one pantun per cell, with the original source per row."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    rows = list(wb.worksheets[0].iter_rows(values_only=True))
    header = [cell_text(h).upper() for h in rows[0]]
    c_text, c_theme, c_orig = header.index("PANTUN"), header.index("TEMA"), header.index("SUMBER")
    book = "Kumpulan Pantun Melayu, Zainal Abidin Bakar"

    out = []
    for n, row in enumerate(rows[1:], start=2):
        text = cell_text(row[c_text])
        if not text:
            continue
        lines = split_zainal_cell(text)
        if lines is None:
            skipped.append({"file": path.name, "sheet_row": n,
                            "reason": "not a clean 'a, b; c, d' 4-line pantun", "text": text})
            continue
        original = cell_text(row[c_orig])
        out.append({
            "id": f"{code}-{len(out) + 1:04d}",
            "line1": lines[0], "line2": lines[1], "line3": lines[2], "line4": lines[3],
            "source": f"{book}; asal: {original}" if original else book,
            "label": "real",
            "collection": "Kumpulan Pantun Melayu", "collection_type": collection_type,
            "theme": re.sub(r"\s+", " ", cell_text(row[c_theme])),
        })
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    all_rows, skipped = [], []

    for code, filename, collection_type in BOOKS:
        path = RAW_DIR / filename
        if not path.exists():
            print(f"MISSING  {filename}")
            continue
        reader = read_zainal if code == "ZAB" else read_four_line_sheet
        before = len(skipped)
        rows = reader(path, code, collection_type, skipped)
        all_rows.extend(rows)
        print(f"{len(rows):6} rows  {filename}"
              + (f"  ({len(skipped) - before} skipped)" if len(skipped) > before else ""))

    for filename, reason in EXCLUDED.items():
        print(f"     -       {filename}  (excluded: {reason})")
    other = {p.name for p in RAW_DIR.iterdir()} - {b[1] for b in BOOKS} - set(EXCLUDED)
    for name in sorted(other):
        print(f"     ?       {name}  (not listed in BOOKS or EXCLUDED - ignored)")

    with open(OUT_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUT_COLUMNS)
        writer.writeheader()
        writer.writerows(all_rows)
    with open(SKIPPED_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["file", "sheet_row", "reason", "text"])
        writer.writeheader()
        writer.writerows(skipped)

    print(f"\nWrote {len(all_rows)} rows to {OUT_CSV.relative_to(PROJECT_ROOT)}")
    print(f"Wrote {len(skipped)} skipped rows to {SKIPPED_CSV.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
