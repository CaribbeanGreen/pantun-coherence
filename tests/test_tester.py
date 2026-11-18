"""Tester form and lecturer dashboard helpers. Uses a throwaway database.
Run from the project root: python tests/test_tester.py"""

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

os.environ["PANTUN_SHARE_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from src import dashboard as dz  # noqa: E402
from src import share, tester  # noqa: E402

USER = {"kind": "member", "username": "rakan", "name": "Rakan", "role": "pensyarah"}
RES = {"lines": ["a", "b", "c", "d"], "sound": 10, "p_avg": 0.57, "rules": 4, "lean": "cannot_tell"}


def refused(fn, word=""):
    try:
        fn()
    except ValueError as e:
        return word in str(e)
    return False


def report(ip, name="Rakan", tasks=None):
    tester.save_report(USER, ip, name, "Pelajar", "Telefon", "Chrome",
                       tasks if tasks is not None else {"p_check": (tester.RESULTS[0], "")},
                       {"easy": 5, "look": None}, 8, "suka", "", "")


def test_report_needs_a_name_and_one_real_test():
    assert refused(lambda: report("9.0.0.1", name="  "), "nama")
    assert refused(lambda: report("9.0.0.1", tasks={"p_check": (tester.RESULTS[3], "")}), "satu ujian")


def test_report_is_saved_and_summarised_worst_first():
    report("9.0.0.2", tasks={"p_check": (tester.RESULTS[0], ""), "p_error": (tester.RESULTS[2], "tiada mesej")})
    rep = tester.reports()
    summary = tester.task_summary(rep[rep["tasks"].str.contains("p_error")])
    assert summary.iloc[0][tester.RESULTS[2]] == 1 and "tiada mesej" in summary.iloc[0]["Catatan"]
    assert tester.rating_means(rep)["Mudah digunakan"] == 5


def test_unknown_task_is_ignored_and_reports_are_limited_per_ip():
    report("9.0.0.3", tasks={"p_check": (tester.RESULTS[0], ""), "hack": (tester.RESULTS[0], "x")})
    assert "hack" not in tester.reports().iloc[0]["tasks"]
    for _ in range(tester.REPORTS_PER_HOUR - 1):
        report("9.0.0.3")
    assert refused(lambda: report("9.0.0.3"), "Terlalu banyak")


def test_rating_needs_an_opinion_and_is_saved():
    assert refused(lambda: tester.save_rating(USER, "9.0.0.4", "Rakan", RES, None, "Tepat", "Tepat", ""))
    tester.save_rating(USER, "9.0.0.4", "Rakan", RES, tester.HUMAN[0], "Tepat", "Tepat", "ok")
    assert abs(tester.ratings().iloc[0]["meaning"] - 0.57) < 1e-9


def test_tuning_finds_the_cut_off_that_matches_people():
    df = pd.DataFrame({"human": [tester.HUMAN[0]] * 3 + [tester.HUMAN[2]] * 3 + [tester.HUMAN[1]],
                       "meaning": [.45, .46, .6, .35, .4, .42, .5]})
    t = tester.tuning(df)
    assert t["n"] == 7 and t["n_sure"] == 6
    assert t["best_acc"] == 1 and 0.42 < t["best"] <= 0.45
    assert abs(t["current"] - 4 / 6) < 1e-9


def test_tester_form_is_hidden_until_the_owner_opens_it():
    assert share.state()["tester_open"] is False
    share.set_tester_open(True)
    assert share.state()["tester_open"] is True
    share.set_tester_open(False)


def test_dashboard_escapes_names_and_counts_days():
    assert "<script" not in dz.avatar("<script>x") and "<script" not in dz.hero("<script>", 0, 0)
    now = datetime(2026, 11, 18, 10, tzinfo=dz.MYT)
    counts = dz.daily_counts([now.timestamp(), now.timestamp() - 86400], days=3, now=now.timestamp())
    assert [n for _, n in counts] == [0, 1, 1]
    assert dz.greeting(now) == "Selamat pagi" and dz.malay_date(now) == "Rabu, 18 November 2026"
    assert dz.greeting(now.replace(hour=13)) == "Selamat tengah hari"
    assert dz.greeting(now.replace(hour=2)) == "Selamat malam"


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
