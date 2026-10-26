"""Checks for src/data_loader.py.

Uses small made-up CSV files with BROKEN rows to test the checks.
The text in these files is test input only, never part of the corpus.

Run from the project root:
    python tests/test_data_loader.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.data_loader import load_pantun, normalise_line  # noqa: E402

HEADER = "id,line1,line2,line3,line4,source,label\n"
GOOD = '"Pisang emas dibawa belayar,","Masak sebiji di atas peti;","Hutang emas boleh dibayar,","Hutang budi dibawa mati.","Traditional",real\n'


def load_from_text(text):
    """Write text to a temporary CSV file and load it."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "test.csv"
        path.write_text(text, encoding="utf-8")
        return load_pantun(path)


def test_normalise_line():
    assert normalise_line("  Pisang   emas dibawa belayar , ") == "Pisang emas dibawa belayar"
    assert normalise_line("Masak sebiji di atas peti ;") == "Masak sebiji di atas peti"
    assert normalise_line("“Kata” orang…") == '"Kata" orang'


def test_good_row():
    accepted, rejected = load_from_text(HEADER + "P1," + GOOD)
    assert rejected == []
    p = accepted[0]
    assert p.pembayang == "Pisang emas dibawa belayar, Masak sebiji di atas peti."
    assert p.maksud == "Hutang emas boleh dibayar, Hutang budi dibawa mati."


def test_bad_rows_are_rejected_with_reasons():
    text = HEADER + (
        "P1," + GOOD +
        'P2,"a","b","","d","Src",real\n'          # empty line3
        'P3,"a","b","c","d","",real\n'            # no source
        'P4,"a","b","c","d","Src",fake\n'         # unknown label
        'P5,"a","b","c"\n'                        # too few columns
        'P6,"a","b","c","d","Src",real,extra\n'   # too many columns
        "P1," + GOOD.replace("Pisang", "Buah") +  # duplicate id
        "P7," + GOOD +                            # duplicate text
        'P8,"a","b",";","d","Src",real\n'         # line with only punctuation
    )
    accepted, rejected = load_from_text(text)
    assert [p.id for p in accepted] == ["P1"]
    reasons = {r.id: " ".join(r.reasons) for r in rejected}
    assert "line3 is empty" in reasons["P2"]
    assert "source is empty" in reasons["P3"]
    assert "label" in reasons["P4"]
    assert "line4 is empty" in reasons["P5"]
    assert "more columns" in reasons["P6"]
    assert "duplicate id" in reasons["P1"]
    assert "duplicate pantun" in reasons["P7"]
    assert "line3 has no words" in reasons["P8"]


def test_source_file_problems():
    # OCR look-alike letters and leftover list numbers are fixed.
    assert normalise_line("Segala pujı bağı Allah,") == "Segala puji bagi Allah"
    assert normalise_line("Аpa dіbuat") == "Apa dibuat"   # Cyrillic A and i
    assert normalise_line("5. Pasir Mayang buat tajuk") == "Pasir Mayang buat tajuk"
    text = HEADER + (
        'X1,"#VALUE!","b","c","d","Src",real\n'                          # Excel error
        'X2,"aa bb. cc dd ee","cc dd ee","ff gg","hh ii","Src",real\n'   # merged cells
        'X3,"Bagaimana tidak dikenang","Pucuk pauh","Bagaimana tidak dikenang-kenang","Dagang jauh","Src",real\n'
    )
    accepted, rejected = load_from_text(text)
    reasons = {r.id: " ".join(r.reasons) for r in rejected}
    assert "Excel error" in reasons["X1"]
    assert "merged" in reasons["X2"]
    assert [p.id for p in accepted] == ["X3"]   # normal repetition is kept


def test_excel_bom_and_blank_lines():
    accepted, rejected = load_from_text("﻿" + HEADER + "P1," + GOOD + "\n\n")
    assert len(accepted) == 1 and rejected == []


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"PASS {name}")
    print("All tests passed.")
