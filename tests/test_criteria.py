"""Checks for src/criteria.py. Run from the project root: python tests/test_criteria.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.criteria import (checklist, has_nature_imagery, middle_word,  # noqa: E402
                          syllables_in_line, syllables_in_word)

PISANG = ["Pisang emas dibawa belayar", "Masak sebiji di atas peti",
          "Hutang emas boleh dibayar", "Hutang budi dibawa mati"]


def test_syllables():
    assert syllables_in_word("pisang") == 2
    assert syllables_in_word("pantai") == 2      # pan-tai (final diphthong)
    assert syllables_in_word("baik") == 2        # ba-ik
    assert syllables_in_word("kerbau") == 2      # ker-bau
    assert syllables_in_line("Pisang emas dibawa belayar") == 10


def test_middle_word():
    assert middle_word("Pisang emas dibawa belayar") == "emas"
    assert middle_word("Masak sebiji di atas peti") == "sebiji"   # pause after 5 of 10 syllables
    assert middle_word("Hutang budi dibawa mati") == "budi"


def test_nature():
    assert has_nature_imagery("Pisang emas dibawa belayar") == ["pisang"]
    assert has_nature_imagery("Teori logik mengubah skema") == []


def test_checklist_pisang_emas():
    result = {c["name"]: c["passed"] for c in checklist(PISANG)}
    assert all(result.values()), result


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"PASS {name}")
    print("All tests passed.")
