"""Tester programme: what friends fill in on the Borang Penguji page, and what the owner reads on Tetapan.

Answers are saved in Malay (RESULTS, HUMAN, ...) whatever language the tester reads; English readers see them
through `shown()`.

Two kinds of answer, both kept in results/share.db (never committed):
  tester_reports  one per finished form: which tasks worked, 1-5 ratings and comments
  tester_ratings  one per pantun: the system's scores next to the tester's own judgement (used for tuning)

The tuning summary only suggests. It never changes how the app scores a pantun.
"""

import json
import threading
import time
from contextlib import closing

import numpy as np
import pandas as pd
import streamlit as st

from src import illus, share
from src.evaluate import LEAN
from src.lang import role, tr

RESULTS = ["Berjaya", "Ada masalah", "Gagal", "Langkau"]
RESULT_PIC = dict(zip(RESULTS, ["ok_mark", "warning", "ng_mark", "arrow_right"]))
GROUP_PIC = {"pelajar": "backpack", "pensyarah": "job_senesi", "penyelidik": "microscope", "akaun": "key"}
HUMAN = ["Sepadan", "Tidak pasti", "Tidak sepadan"]
SCORE_VERDICT = ["Terlalu rendah", "Tepat", "Terlalu tinggi"]
BACKGROUND = ["Pelajar", "Guru / pensyarah", "Peminat pantun", "Tidak biasa dengan pantun"]
DEVICES = ["Komputer", "Telefon", "Tablet"]
# English for the saved Malay answers above (what an English reader sees; the database keeps the Malay word).
ENGLISH = {"Berjaya": "Worked", "Ada masalah": "Had a problem", "Gagal": "Failed", "Langkau": "Skipped",
           "Sepadan": "Match", "Tidak pasti": "Not sure", "Tidak sepadan": "Do not match",
           "Terlalu rendah": "Too low", "Tepat": "About right", "Terlalu tinggi": "Too high",
           "Pelajar": "Pupil / student", "Guru / pensyarah": "Teacher / lecturer", "Peminat pantun": "Pantun fan",
           "Tidak biasa dengan pantun": "New to pantun", "Komputer": "Computer", "Telefon": "Phone", "Tablet": "Tablet"}


def shown(value):
    """A saved answer in the reader's language."""
    return tr(value, ENGLISH.get(value, value))
RATING_TARGET = 5                # pantun each tester is asked to judge
MIN_FOR_TUNING = 20              # judged pantun needed before a cut-off suggestion means anything
REPORTS_PER_HOUR, RATINGS_PER_HOUR = 5, 60       # per IP: keeps a public link from filling the database
LIMITS = {"text": 1000, "short": 80, "line": 120}

# (key, what to do in Malay, in English). The view decides who sees the group: testers only get tasks they can open.
_TASKS = {
    "pelajar": [
        ("p_check", "Tulis pantun 4 baris dan tekan Semak Pantun Saya. Hasil keluar dengan betul?",
         "Write a 4-line pantun and press Check My Pantun. Does the result come out right?"),
        ("p_error", "Cuba hantar 3 baris sahaja. Mesej yang keluar jelas?",
         "Try sending only 3 lines. Is the message that comes up clear?"),
        ("p_disagree", "Tekan Saya tidak setuju dan hantar kepada cikgu.",
         "Press I disagree and send it to the teacher."),
        ("p_learn", "Buka Belajar Pantun. Penerangan mudah difahami?", "Open Learn Pantun. Is it easy to understand?"),
        ("p_history", "Buka Sejarah Saya. Pantun yang tadi ada di situ?",
         "Open My History. Is the pantun you just checked there?"),
        ("p_phone", "Buka laman di telefon. Semua boleh dibaca dan ditekan?",
         "Open the site on a phone. Can you read and press everything?"),
    ],
    "pensyarah": [
        ("l_dash", "Buka Papan pemuka. Maklumat dan butang jalan pintas masuk akal?",
         "Open the Dashboard. Do the information and shortcut buttons make sense?"),
        ("l_code", "Cipta satu kelas di Kod kelas & murid. Kod kelas keluar?",
         "Create a class under Class codes & pupils. Does a class code come out?"),
        ("l_class", "Di Kelas saya, tekan Guna kelas contoh. Senarai kerja keluar?",
         "In My class, press Use the sample class. Does the work list appear?"),
        ("l_decide", "Pilih satu pantun, kemudian Setuju, Ubah atau Hantar kepada pakar.",
         "Pick a pantun, then Agree, Change or Send to an expert."),
        ("l_reply", "Di Semakan, pilih pertanyaan (jika ada) dan jawab.",
         "In Reviews, pick a question (if there is one) and answer it."),
        ("l_report", "Di Laporan, lihat carta dan muat turun CSV atau PDF.",
         "In Report, look at the chart and download the CSV or PDF."),
    ],
    "penyelidik": [
        ("r_analyse", "Pilih contoh dan tekan Analyse. Semua nombor keluar?",
         "Pick an example and press Analyse. Do all the numbers come out?"),
        ("r_rate", "Isi borang Expert review dan simpan penilaian.", "Fill in the Expert review form and save the rating."),
        ("r_tabs", "Buka tab Findings, Expert queue dan Method.", "Open the Findings, Expert queue and Method tabs."),
    ],
    "akaun": [
        ("a_video", "Tekan Cara guna. Video dimainkan dan sepadan dengan skrin?",
         "Press How to use. Does the video play and match the screen?"),
        ("a_tour", "Tekan Mulakan lawatan berpandu. Langkahnya betul?", "Press Start the guided tour. Are the steps right?"),
        ("a_password", "Jika ada akaun: tukar kata laluan, log keluar, log masuk semula.",
         "If you have an account: change the password, log out, log in again."),
    ],
}


def tasks():
    """{view: (group name, [(key, what to do), ...])} in the reader's language."""
    names = {"pelajar": role("pelajar"), "pensyarah": role("pensyarah"), "penyelidik": role("penyelidik"),
             "akaun": tr("Bantuan & akaun", "Help & account")}
    return {v: (names[v], [(k, tr(ms, en)) for k, ms, en in items]) for v, items in _TASKS.items()}


TASK_KEYS = {k for items in _TASKS.values() for k, _, _ in items}
_RATING_QUESTIONS = [("easy", "Mudah digunakan", "Easy to use"), ("look", "Rupa laman menarik", "Looks good"),
                     ("speed", "Kelajuan laman", "Speed"), ("trust", "Skor boleh dipercayai", "Scores can be trusted"),
                     ("help", "Video dan panduan membantu", "Video and guide help")]


def rating_questions():
    return [(k, tr(ms, en)) for k, ms, en in _RATING_QUESTIONS]

SCHEMA = """
CREATE TABLE IF NOT EXISTS tester_reports (
    id INTEGER PRIMARY KEY, time REAL NOT NULL, account TEXT DEFAULT '', name TEXT NOT NULL,
    background TEXT DEFAULT '', device TEXT DEFAULT '', browser TEXT DEFAULT '',
    tasks TEXT NOT NULL,                     -- JSON {task key: {"result": ..., "note": ...}}
    ratings TEXT NOT NULL,                   -- JSON {question key: 1-5}
    recommend INTEGER, liked TEXT DEFAULT '', confusing TEXT DEFAULT '', ideas TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS tester_ratings (
    id INTEGER PRIMARY KEY, time REAL NOT NULL, account TEXT DEFAULT '', name TEXT DEFAULT '',
    line1 TEXT, line2 TEXT, line3 TEXT, line4 TEXT,
    sound REAL, meaning REAL, rules INTEGER, lean TEXT,      -- what the system said
    human TEXT NOT NULL, meaning_verdict TEXT, sound_verdict TEXT, comment TEXT DEFAULT ''
);
"""

_recent: list = []                # (time, ip, kind), in memory
_recent_lock = threading.Lock()


def _init():
    with share._lock, closing(share._db()) as con, con:
        con.executescript(SCHEMA)
        # Tester accounts used to be made as teachers (note "penguji"); they have their own role now.
        con.execute("UPDATE members SET role='penguji' WHERE role='pensyarah' AND note='penguji'")


_init()


def _clip(v, kind="text"):
    return str(v or "").strip()[:LIMITS[kind]]


def _allow(ip, kind, limit):
    now = time.time()
    with _recent_lock:
        _recent[:] = [r for r in _recent if now - r[0] < 3600]
        if sum(1 for _, a, k in _recent if a == ip and k == kind) >= limit:
            return False
        _recent.append((now, ip, kind))
    return True


def save_report(user, ip, name, background, device, browser, tasks, ratings, recommend, liked, confusing, ideas):
    """Store a finished form. `tasks`: {key: (result, note)}. Raises ValueError with a message for the tester."""
    name = _clip(name, "short")
    done = {k: {"result": r, "note": _clip(n)} for k, (r, n) in tasks.items() if k in TASK_KEYS and r in RESULTS}
    if not name:
        raise ValueError(tr("Isi nama anda di bahagian 1.", "Fill in your name in part 1."))
    if not any(v["result"] != RESULTS[3] for v in done.values()):
        raise ValueError(tr("Cuba sekurang-kurangnya satu ujian di bahagian 2.", "Try at least one test in part 2."))
    if not _allow(ip, "report", REPORTS_PER_HOUR):
        raise ValueError(tr("Terlalu banyak borang dari rangkaian ini. Cuba lagi dalam sejam.",
                            "Too many forms from this network. Try again in an hour."))
    stars = {k: int(v) for k, v in ratings.items() if v in (1, 2, 3, 4, 5)}
    with share._lock, closing(share._db()) as con, con:
        con.execute("INSERT INTO tester_reports(time, account, name, background, device, browser, tasks, ratings, "
                    "recommend, liked, confusing, ideas) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (time.time(), user["username"] or user["kind"], name, _clip(background, "short"),
                     _clip(device, "short"), _clip(browser, "short"), json.dumps(done, ensure_ascii=False),
                     json.dumps(stars), recommend, _clip(liked), _clip(confusing), _clip(ideas)))
    share._log("penguji: borang dihantar", user["username"] or name)


def save_rating(user, ip, name, res, human, meaning_verdict, sound_verdict, comment):
    if human not in HUMAN:
        raise ValueError(tr("Pilih pendapat anda tentang pantun ini.", "Choose your opinion of this pantun."))
    if not _allow(ip, "rating", RATINGS_PER_HOUR):
        raise ValueError(tr("Terlalu banyak penilaian dari rangkaian ini. Cuba lagi dalam sejam.",
                            "Too many ratings from this network. Try again in an hour."))
    lines = [_clip(l, "line") for l in res["lines"]]
    with share._lock, closing(share._db()) as con, con:
        con.execute("INSERT INTO tester_ratings(time, account, name, line1, line2, line3, line4, sound, meaning, rules,"
                    " lean, human, meaning_verdict, sound_verdict, comment) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (time.time(), user["username"] or user["kind"], _clip(name, "short"), *lines, float(res["sound"]),
                     float(res["p_avg"]), int(res["rules"]), res["lean"], human, meaning_verdict or "",
                     sound_verdict or "", _clip(comment)))


def reports():
    with closing(share._db()) as con:
        return pd.read_sql("SELECT * FROM tester_reports ORDER BY time DESC", con)


def ratings():
    with closing(share._db()) as con:
        return pd.read_sql("SELECT * FROM tester_ratings ORDER BY time DESC", con)


# ---- Summaries ------------------------------------------------------------------------------------

def task_summary(df):
    """One row per task: how many testers got each result, plus their notes."""
    label = {k: (group, text) for group, items in tasks().values() for k, text in items}
    tally = {}
    for r in df.itertuples():
        for k, v in json.loads(r.tasks).items():
            if k in label:
                t = tally.setdefault(k, {x: 0 for x in RESULTS} | {"notes": []})
                # answers saved before the icons changed may still have an emoji in front of the word
                result = next((x for x in RESULTS if x in v["result"]), None)
                if result:
                    t[result] += 1
                if v.get("note"):
                    t["notes"].append(f"{r.name}: {v['note']}")
    rows = [{tr("Bahagian", "Part"): label[k][0], tr("Ujian", "Test"): label[k][1],
             **{shown(x): t[x] for x in RESULTS}, tr("Catatan", "Notes"): " | ".join(t["notes"])}
            for k, t in tally.items()]
    rows.sort(key=lambda x: -(x[shown(RESULTS[2])] * 2 + x[shown(RESULTS[1])]))       # the worst tasks first
    return pd.DataFrame(rows)


def rating_means(df):
    out = {}
    for key, label in rating_questions():
        vals = [json.loads(s).get(key) for s in df["ratings"]]
        vals = [v for v in vals if v]
        out[label] = round(float(np.mean(vals)), 1) if vals else None
    return out


def tuning(df):
    """How the meaning score compares with people's judgement.

    Uses only pantun the tester was sure about. `best` is the single cut-off on the meaning score (30-70%) that agrees
    with them most often; `current` is the same measure at the 50% mid-point the app leans around."""
    sure = df[df["human"].isin([HUMAN[0], HUMAN[2]])]
    y = (sure["human"] == HUMAN[0]).to_numpy()
    p = sure["meaning"].to_numpy(dtype=float)
    out = {"n": len(df), "n_sure": len(sure), "current": None, "best": None, "best_acc": None}
    if len(sure):
        cuts = np.round(np.arange(0.30, 0.701, 0.01), 2)
        acc = np.array([np.mean((p >= c) == y) for c in cuts])
        top = acc.max()
        tied = cuts[acc >= top - 1e-9]
        out.update(current=float(np.mean((p >= 0.5) == y)), best=float(tied[np.argmin(abs(tied - 0.5))]), best_acc=float(top))
    return out


# ---- Owner: Tetapan -> Penguji ---------------------------------------------------------------------

def _toggled():
    share.set_tester_open(st.session_state["owner_tester_on"])


def _invite(username="", key=""):
    """The invitation message, in the owner's language (a ?lang=en link opens the form in English)."""
    if tr("ms", "en") == "en":
        login = (f"Username: {username}\nPassword: {key}\n" if key else
                 "Account: I will give you a username and password, or a guest code.\n")
        return ("Hi! Could you help me test my Semak Pantun site? About 20 minutes.\n\n"
                f"1. Open {share.PUBLIC_URL}/penguji?lang=en\n2. Log in:\n{login}"
                "3. Follow the Tester Form: try each task, rate a few pantun, then press Send.\n\n"
                "If anything looks odd or broken, just write it in the form. Thank you!")
    login = (f"Nama pengguna: {username}\nKata laluan: {key}\n" if key else
             "Akaun: saya akan beri nama pengguna dan kata laluan, atau kod tetamu.\n")
    return ("Hai! Boleh tolong uji laman Semak Pantun saya? Lebih kurang 20 minit.\n\n"
            f"1. Buka {share.PUBLIC_URL}/penguji\n2. Log masuk:\n{login}"
            "3. Ikut Borang Penguji: cuba setiap tugasan, nilai beberapa pantun, kemudian tekan Hantar.\n\n"
            "Jika ada yang pelik atau rosak, tulis sahaja dalam borang. Terima kasih!")


def owner_panel():
    s = share.state()
    st.session_state.setdefault("owner_tester_on", s["tester_open"])
    st.toggle(tr("Buka Borang Penguji kepada pelawat", "Open the Tester Form to visitors"), key="owner_tester_on",
              on_change=_toggled, help=tr("Apabila mati, hanya anda nampak borang ini.",
                                          "When off, only you can see the form."))
    if not s["tester_open"]:
        st.caption(tr("Borang tersembunyi daripada pelawat. Hidupkan semasa rakan anda menguji.",
                      "The form is hidden from visitors. Switch it on while your friends are testing."))

    with st.expander("![](/app/static/i/mail.png) " + tr("Jemput penguji", "Invite testers"), expanded=not len(reports())):
        tester_name = role("penguji")
        st.caption(tr(f"Akaun **{tester_name}** boleh membuka ketiga-tiga paparan, jadi semua ujian boleh dicuba. Ia "
                      "tidak nampak pertanyaan murid, tetamu atau kelas cikgu lain.",
                      f"A **{tester_name}** account can open all three views, so every test can be tried. It does "
                      "not see pupils' or guests' questions, or other teachers' classes."))
        with st.form("tester_invite", clear_on_submit=True):
            c1, c2, c3 = st.columns([2, 2, 1])
            name = c1.text_input(tr("Nama rakan", "Friend's name"), placeholder=tr("cth. Hakim", "e.g. Hakim"))
            user = c2.text_input(tr("Nama pengguna", "Username"), placeholder=tr("cth. penguji.hakim", "e.g. penguji.hakim"),
                                 max_chars=24)
            days = c3.selectbox(tr("Tempoh", "For"), [3, 7, 14], index=1,
                                format_func=lambda d: f"{d} " + tr("hari", "days"))
            if st.form_submit_button(tr("Cipta akaun penguji", "Create tester account"), type="primary",
                                     icon=":material/person_add:"):
                try:
                    key = share.add_member(user, name, days, "penguji", "penguji")
                    st.session_state["owner_tester_new"] = (user.strip().lower(), key)
                except ValueError as e:
                    st.error(str(e), icon=":material/error:")
        new = st.session_state.get("owner_tester_new")
        if new:
            st.success(tr("Salin mesej ini sekarang. Kata laluan hanya dipaparkan **sekali**.",
                          "Copy this message now. The password is shown only **once**."), icon=":material/key:")
            st.code(_invite(*new), language=None)
            if st.button(tr("Sudah disalin", "Copied"), key="tester_copied", icon=":material/check:"):
                st.session_state.pop("owner_tester_new")
                st.rerun()
        else:
            st.code(_invite(), language=None)

    rep, rat = reports(), ratings()
    with st.container(horizontal=True):
        st.metric(tr("borang diterima", "forms received"), len(rep), border=True)
        st.metric(tr("penguji", "testers"), rep["name"].str.lower().nunique() if len(rep) else 0, border=True)
        st.metric(tr("pantun dinilai", "pantun rated"), len(rat), border=True)
        st.metric(tr("cadangan kepada rakan", "would recommend"), f"{rep['recommend'].mean():.1f}/10" if len(rep) else "—",
                  border=True)
    if rep.empty and rat.empty:
        st.info(tr("Belum ada jawapan. Jawapan penguji akan muncul di sini.",
                   "No answers yet. Testers' answers will appear here."), icon=":material/inbox:")
        return

    if len(rep):
        st.markdown(tr("**Hasil ujian** (yang paling bermasalah di atas)", "**Test results** (most problems first)"))
        st.dataframe(task_summary(rep), hide_index=True, alt=tr("Keputusan setiap ujian", "Result of each test"))
        st.markdown(tr("**Penilaian purata** (1 hingga 5)", "**Average ratings** (1 to 5)"))
        means = rating_means(rep)
        with st.container(horizontal=True):
            for label, v in means.items():
                st.metric(label, v if v is not None else "—", border=True)
        st.markdown(tr("**Komen penguji**", "**Testers' comments**"))
        st.dataframe(rep.assign(when=rep["time"].map(share._when), background=rep["background"].map(shown),
                                device=rep["device"].map(shown))[
            ["when", "name", "background", "device", "browser", "liked", "confusing", "ideas"]].rename(columns=tr(
                {"when": "Masa", "name": "Nama", "background": "Latar", "device": "Peranti", "browser": "Pelayar",
                 "liked": "Disukai", "confusing": "Mengelirukan", "ideas": "Cadangan"},
                {"when": "Time", "name": "Name", "background": "Background", "device": "Device", "browser": "Browser",
                 "liked": "Liked", "confusing": "Confusing", "ideas": "Ideas"})),
            hide_index=True, alt=tr("Komen penguji", "Testers' comments"))
    if len(rat):
        tuning_panel(rat)
    with st.container(horizontal=True):
        st.download_button(tr("Muat turun borang (CSV)", "Download forms (CSV)"), rep.to_csv(index=False).encode("utf-8-sig"),
                           file_name="penguji_borang.csv", icon=":material/download:", disabled=rep.empty)
        st.download_button(tr("Muat turun penilaian pantun (CSV)", "Download pantun ratings (CSV)"), rat.to_csv(index=False).encode("utf-8-sig"),
                           file_name="penguji_penilaian.csv", icon=":material/download:", disabled=rat.empty)


def tuning_panel(rat):
    st.subheader("![](/app/static/i/compass.png) " + tr("Penalaan skor", "Score tuning"), anchor=False)
    st.caption(tr("Membandingkan skor Makna sistem dengan pendapat penguji. Tiada apa-apa diubah secara automatik.",
                  "Compares the system's Meaning score with the testers' opinion. Nothing changes automatically."))
    t = tuning(rat)
    left, right = st.columns(2, gap="large")
    with left:
        st.markdown(tr("**Purata skor Makna ikut pendapat penguji**", "**Average Meaning score by testers' opinion**"))
        g = rat.groupby("human")["meaning"].agg(["count", "mean"]).reindex(HUMAN).dropna()
        st.dataframe(pd.DataFrame({tr("Pendapat penguji", "Testers' opinion"): [shown(v) for v in g.index],
                                   "Pantun": g["count"].astype(int).to_numpy(),
                                   tr("Purata Makna", "Average Meaning"):
                                       ((100 * g["mean"]).round().astype(int).astype(str) + "%").to_numpy()}),
                     hide_index=True, alt=tr("Purata skor Makna ikut pendapat penguji", "Average Meaning score by opinion"))
    with right:
        st.markdown(tr("**Adakah skor tepat?**", "**Are the scores right?**"))
        rows = [{tr("Skor", "Score"): n, **{shown(v): int((rat[c] == v).sum()) for v in SCORE_VERDICT}}
                for n, c in ((tr("Makna", "Meaning"), "meaning_verdict"), (tr("Bunyi", "Sound"), "sound_verdict"))]
        st.dataframe(pd.DataFrame(rows), hide_index=True,
                     alt=tr("Pendapat penguji tentang ketepatan skor", "Testers' view of how right the scores are"))
    low, high = round(100 * (0.5 - LEAN)), round(100 * (0.5 + LEAN))
    if t["n_sure"] < MIN_FOR_TUNING:
        st.info(tr(f"Ada **{t['n_sure']}** penilaian yang pasti. Perlu sekurang-kurangnya **{MIN_FOR_TUNING}** sebelum "
                   f"sebarang cadangan bermakna. Julat Tidak pasti sekarang: {low}% hingga {high}%.",
                   f"There are **{t['n_sure']}** sure ratings. At least **{MIN_FOR_TUNING}** are needed before any "
                   f"suggestion means something. The Not sure range now: {low}% to {high}%."), icon=":material/tune:")
    else:
        st.success(tr(f"Daripada {t['n_sure']} pantun, garis 50% sepadan dengan penguji **{100 * t['current']:.0f}%** "
                      f"daripada masa. Garis terbaik dalam sampel ini: **{100 * t['best']:.0f}%** "
                      f"(**{100 * t['best_acc']:.0f}%** sepadan). Sahkan dengan sampel lain sebelum mengubah tetapan.",
                      f"Out of {t['n_sure']} pantun, the 50% line agrees with the testers **{100 * t['current']:.0f}%** "
                      f"of the time. The best line in this sample: **{100 * t['best']:.0f}%** "
                      f"(**{100 * t['best_acc']:.0f}%** agree). Check with another sample before changing anything."),
                   icon=":material/tune:")
