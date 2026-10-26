"""Phase 1 - Data loader for the pantun corpus.

Loads data/pantun.csv, checks every row, cleans the text and splits each
pantun empat kerat into:
    pembayang = lines 1-2  (the "shadow" / imagery couplet)
    maksud    = lines 3-4  (the "meaning" couplet)

Rows that fail a check are not used. They are returned (and printed) together
with the reason, so nothing is dropped silently.

Run from the project root to see a report:
    python -m src.data_loader
"""

import csv
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = PROJECT_ROOT / "data" / "pantun.csv"

REQUIRED_COLUMNS = ["id", "line1", "line2", "line3", "line4", "source", "label"]
LINE_COLUMNS = ["line1", "line2", "line3", "line4"]
ALLOWED_LABELS = {"real", "mismatch"}

# Look-alike characters (often pasted from Word or websites) mapped to plain ASCII.
CHAR_REPLACEMENTS = {
    "‘": "'", "’": "'",   # curly single quotes
    "“": '"', "”": '"',   # curly double quotes
    "–": "-", "—": "-",   # en dash, em dash
    "…": "...",                # ellipsis character
    " ": " ",                  # non-breaking space
    "​": "",                   # zero-width space
    # OCR errors found in the source spreadsheets: letters from other alphabets
    # that look identical to Latin letters (e.g. "pujı bağı" for "puji bagi").
    # A model sees them as different characters, so map them back.
    "ı": "i",                  # Turkish dotless i
    "ğ": "g",                  # Turkish g with breve
    "í": "i", "ü": "u",   # i with accent, u with umlaut
    "А": "A", "В": "B", "М": "M", "Р": "P",  # Cyrillic capitals
    "а": "a", "с": "c", "р": "p", "і": "i",  # Cyrillic small letters
}

# Columns we read but do not need to validate; they are kept for analysis.
OPTIONAL_COLUMNS = ["collection", "collection_type", "theme"]

# Punctuation found at the end of a line (",", ";", ".", etc.).
TRAILING_PUNCT = ".,;:!?-"


@dataclass
class Pantun:
    """One accepted pantun after cleaning."""
    id: str
    lines: list        # the 4 cleaned lines
    pembayang: str     # lines 1-2 joined into one string
    maksud: str        # lines 3-4 joined into one string
    source: str
    label: str         # "real" or "mismatch"
    info: dict         # optional columns (collection, collection_type, theme)


@dataclass
class RejectedRow:
    """A row that was not used, with the reasons why."""
    row_number: int    # line number in the CSV file (header = line 1)
    id: str
    reasons: list


def normalise_line(text):
    """Clean one line of a pantun.

    - Unicode NFC, so the same letter is always stored the same way.
    - Replace curly quotes/dashes/odd spaces with plain versions.
    - Collapse runs of whitespace into one space and trim the ends.
    - Remove spaces before punctuation ("peti ;" -> "peti;").
    - Remove the punctuation at the END of the line. Sources are not
      consistent here (some end line 1 with ",", others with ";" or nothing),
      so we strip it and add our own consistent punctuation in join_couplet().
    The words themselves are never changed.
    """
    text = unicodedata.normalize("NFC", text)
    for old, new in CHAR_REPLACEMENTS.items():
        text = text.replace(old, new)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^\d+\.\s+", "", text)          # leftover list number, e.g. "5. Pasir Mayang"
    text = re.sub(r"\s+([,;:.!?])", r"\1", text)
    text = text.rstrip(TRAILING_PUNCT + " ")
    return text


def join_couplet(first, second):
    """Join two cleaned lines into one sentence-like string: 'first, second.'"""
    return f"{first}, {second}."


def validate_row(row):
    """Return a list of problems with one CSV row (empty list = row is fine)."""
    problems = []
    if not row.get("id"):
        problems.append("missing id")
    for col in LINE_COLUMNS:
        if not row.get(col):
            problems.append(f"{col} is empty")
        elif row[col].startswith("#") and row[col].rstrip("!").isupper():
            # Excel error values such as "#VALUE!" or "#REF!" are not text.
            problems.append(f"{col} is an Excel error value ({row[col]})")
        elif not normalise_line(row[col]):
            # e.g. a line that is only "..." or "," becomes empty after cleaning
            problems.append(f"{col} has no words")
        elif "\n" in row[col].strip():
            problems.append(f"{col} contains a line break (two lines in one cell?)")
    if not row.get("source"):
        problems.append("source is empty")
    label = (row.get("label") or "").lower()
    if label not in ALLOWED_LABELS:
        problems.append(f"label '{row.get('label')}' is not one of {sorted(ALLOWED_LABELS)}")
    return problems


def find_merged_line(lines):
    """Return a problem message if one line seems to contain another line, else ''."""
    low = [line.lower() for line in lines]
    for i in range(4):
        for j in range(4):
            if i != j and low[j] in low[i] and len(low[i].split()) >= len(low[j].split()) + 2:
                return f"line{i + 1} also contains line{j + 1} (merged cells?)"
    return ""


def load_pantun(csv_path=DEFAULT_CSV):
    """Load and validate the corpus.

    Returns (accepted, rejected):
        accepted - list of Pantun
        rejected - list of RejectedRow
    """
    csv_path = Path(csv_path)
    accepted, rejected = [], []
    seen_ids = {}     # id -> row number where it first appeared
    seen_texts = {}   # cleaned 4 lines (lower-case) -> id of first copy

    # "utf-8-sig" also handles the invisible BOM that Excel adds when saving CSV.
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        missing_cols = [c for c in REQUIRED_COLUMNS if c not in (reader.fieldnames or [])]
        if missing_cols:
            raise ValueError(f"{csv_path} is missing column(s): {missing_cols}")

        for row in reader:
            row_number = reader.line_num  # physical line in the file
            # A row with too many commas gets extra values under the key None.
            extra_values = row.pop(None, None)
            # Strip outer spaces; a missing value (short row) becomes "".
            row = {k: (v or "").strip() for k, v in row.items()}
            row_id = row.get("id", "")

            # Skip completely blank lines quietly (e.g. trailing empty lines).
            if not any(row.values()) and not extra_values:
                continue

            problems = validate_row(row)
            if extra_values and any(v.strip() for v in extra_values):
                problems.append("row has more columns than the header (unquoted comma?)")

            if row_id in seen_ids:
                problems.append(f"duplicate id (first used on line {seen_ids[row_id]})")

            if problems:
                rejected.append(RejectedRow(row_number, row_id, problems))
                continue

            lines = [normalise_line(row[c]) for c in LINE_COLUMNS]

            # Merged cells: one cell holding several lines, e.g. line1 =
            # "Di pokok beluntas murai bersarang. Biar senget jangan runtuh; ..."
            # Spotted when a line contains another whole line of the same pantun
            # and is at least 2 words longer (so "dikenang" vs "dikenang-kenang",
            # a normal repetition, is not flagged).
            merged = find_merged_line(lines)
            if merged:
                rejected.append(RejectedRow(row_number, row_id, [merged]))
                continue

            # The same pantun twice would count double in the statistics.
            text_key = tuple(line.lower() for line in lines)
            if text_key in seen_texts:
                rejected.append(RejectedRow(
                    row_number, row_id,
                    [f"same text as {seen_texts[text_key]} (duplicate pantun)"]))
                continue

            seen_ids[row_id] = row_number
            seen_texts[text_key] = row_id
            accepted.append(Pantun(
                id=row_id,
                lines=lines,
                pembayang=join_couplet(lines[0], lines[1]),
                maksud=join_couplet(lines[2], lines[3]),
                source=row["source"],
                label=row["label"].lower(),
                info={c: row.get(c, "") for c in OPTIONAL_COLUMNS},
            ))

    return accepted, rejected


def print_report(accepted, rejected):
    """Print a short human-readable summary of the load."""
    n_real = sum(p.label == "real" for p in accepted)
    n_mismatch = sum(p.label == "mismatch" for p in accepted)
    print(f"Accepted: {len(accepted)}  (real: {n_real}, mismatch: {n_mismatch})")
    print(f"Rejected: {len(rejected)}")
    for r in rejected:
        print(f"  line {r.row_number} (id '{r.id}'): " + "; ".join(r.reasons))

    # Accepted pantun per collection (only if that column exists).
    counts = {}
    for p in accepted:
        name = p.info.get("collection") or "(no collection column)"
        counts[name] = counts.get(name, 0) + 1
    print("\nAccepted per collection:")
    for name, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {n:5}  {name}")
    if accepted:
        p = accepted[0]
        print("\nExample after cleaning:")
        print(f"  id:        {p.id}")
        print(f"  pembayang: {p.pembayang}")
        print(f"  maksud:    {p.maksud}")


if __name__ == "__main__":
    # Malay text can contain characters the Windows console cannot print.
    sys.stdout.reconfigure(encoding="utf-8")
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CSV
    accepted, rejected = load_pantun(path)
    print_report(accepted, rejected)
