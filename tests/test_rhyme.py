"""Checks for src/rhyme.py. Run from the project root: python tests/test_rhyme.py"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.rhyme import pair_score, rime, sound_score  # noqa: E402


def test_rime():
    assert rime("belayar") == "ar"
    assert rime("peti") == "i"
    assert rime("pantai") == "ai"
    assert rime("tanjung") == "ung"


def test_pairs():
    assert pair_score("Pisang emas dibawa belayar,", "Hutang emas boleh dibayar,") == 1.0
    assert pair_score("Masak sebiji di atas peti;", "Hutang budi dibawa mati.") == 1.0
    assert pair_score("Bunga tanjung", "Buah pinang") == 0.5              # -ung / -ang
    assert pair_score("Pisau lipat tajam", "Hati yang malang") == 0.0     # -am / -ang
    assert pair_score("Pergi ke pekan", "Duduk di rumah") == 0.0
    assert pair_score("Anak kenang-kenang", "Hati tenang") == 1.0         # last part of a hyphenated word


def test_sound_score():
    pisang = ["Pisang emas dibawa belayar", "Masak sebiji di atas peti",
              "Hutang emas boleh dibayar", "Hutang budi dibawa mati"]
    assert sound_score(pisang) == 10
    # Halves swapped round: line 1 now faces "mati", line 2 faces "dibayar".
    assert sound_score(pisang[:2] + pisang[3:] + pisang[2:3]) == 0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"PASS {name}")
    print("All tests passed.")
