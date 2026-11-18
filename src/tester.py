"""Tester programme: what friends fill in on the Borang Penguji page, and what the owner reads on Kongsi.

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

RESULTS = ["Berjaya", "Ada masalah", "Gagal", "Langkau"]
RESULT_PIC = dict(zip(RESULTS, ["ok_mark", "warning", "ng_mark", "arrow_right"]))
GROUP_PIC = {"pelajar": "backpack", "pensyarah": "job_senesi", "penyelidik": "microscope", "akaun": "key"}
HUMAN = ["Sepadan", "Tidak pasti", "Tidak sepadan"]
SCORE_VERDICT = ["Terlalu rendah", "Tepat", "Terlalu tinggi"]
BACKGROUND = ["Pelajar", "Guru / pensyarah", "Peminat pantun", "Tidak biasa dengan pantun"]
DEVICES = ["Komputer", "Telefon", "Tablet"]
RATING_TARGET = 5                # pantun each tester is asked to judge
MIN_FOR_TUNING = 20              # judged pantun needed before a cut-off suggestion means anything
REPORTS_PER_HOUR, RATINGS_PER_HOUR = 5, 60       # per IP: keeps a public link from filling the database
LIMITS = {"text": 1000, "short": 80, "line": 120}

# (key, what to do). The view decides who sees the group: testers only get tasks they can open.
TASKS = {
    "pelajar": ("Pelajar", [
        ("p_check", "Tulis pantun 4 baris dan tekan Semak Pantun Saya. Hasil keluar dengan betul?"),
        ("p_error", "Cuba hantar 3 baris sahaja. Mesej yang keluar jelas?"),
        ("p_disagree", "Tekan Saya tidak setuju dan hantar kepada guru."),
        ("p_learn", "Buka Belajar Pantun. Penerangan mudah difahami?"),
        ("p_history", "Buka Sejarah Saya. Pantun yang tadi ada di situ?"),
        ("p_phone", "Buka laman di telefon. Semua boleh dibaca dan ditekan?"),
    ]),
    "pensyarah": ("Pensyarah", [
        ("l_dash", "Buka Papan pemuka. Maklumat dan butang jalan pintas masuk akal?"),
        ("l_code", "Cipta satu kelas di Kod kelas & pelajar. Kod kelas keluar?"),
        ("l_class", "Di Kelas saya, tekan Guna kelas contoh. Senarai kerja keluar?"),
        ("l_decide", "Pilih satu pantun, kemudian Setuju, Ubah atau Hantar kepada pakar."),
        ("l_reply", "Di Semakan, pilih pertanyaan (jika ada) dan jawab."),
        ("l_report", "Di Laporan, lihat carta dan muat turun CSV atau PDF."),
    ]),
    "penyelidik": ("Penyelidik", [
        ("r_analyse", "Pilih contoh dan tekan Analyse. Semua nombor keluar?"),
        ("r_rate", "Isi borang Expert review dan simpan penilaian."),
        ("r_tabs", "Buka tab Findings, Expert queue dan Method."),
    ]),
    "akaun": ("Bantuan & akaun", [
        ("a_video", "Tekan Cara guna. Video dimainkan dan sepadan dengan skrin?"),
        ("a_tour", "Tekan Mulakan lawatan berpandu. Langkahnya betul?"),
        ("a_password", "Jika ada akaun: tukar kata laluan, log keluar, log masuk semula."),
    ]),
}
RATING_QUESTIONS = [("easy", "Mudah digunakan"), ("look", "Rupa laman menarik"), ("speed", "Kelajuan laman"),
                    ("trust", "Skor boleh dipercayai"), ("help", "Video dan panduan membantu")]

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
    known = {k for _, group in TASKS.values() for k, _ in group}
    done = {k: {"result": r, "note": _clip(n)} for k, (r, n) in tasks.items() if k in known and r in RESULTS}
    if not name:
        raise ValueError("Isi nama anda di bahagian 1.")
    if not any(v["result"] != RESULTS[3] for v in done.values()):
        raise ValueError("Cuba sekurang-kurangnya satu ujian di bahagian 2.")
    if not _allow(ip, "report", REPORTS_PER_HOUR):
        raise ValueError("Terlalu banyak borang dari rangkaian ini. Cuba lagi dalam sejam.")
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
        raise ValueError("Pilih pendapat anda tentang pantun ini.")
    if not _allow(ip, "rating", RATINGS_PER_HOUR):
        raise ValueError("Terlalu banyak penilaian dari rangkaian ini. Cuba lagi dalam sejam.")
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
    label = {k: (group, text) for group, items in TASKS.values() for k, text in items}
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
    rows = [{"Bahagian": label[k][0], "Ujian": label[k][1], **{x: t[x] for x in RESULTS}, "Catatan": " | ".join(t["notes"])}
            for k, t in tally.items()]
    rows.sort(key=lambda x: -(x[RESULTS[2]] * 2 + x[RESULTS[1]]))       # the worst tasks first
    return pd.DataFrame(rows)


def rating_means(df):
    out = {}
    for key, label in RATING_QUESTIONS:
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


# ---- Owner: Kongsi -> Penguji ----------------------------------------------------------------------

def _toggled():
    share.set_tester_open(st.session_state["owner_tester_on"])


def _invite(username="", key=""):
    login = (f"Nama pengguna: {username}\nKata laluan: {key}\n" if key else
             "Akaun: saya akan beri nama pengguna dan kata laluan, atau kod tetamu.\n")
    return ("Hai! Boleh tolong uji laman Semak Pantun saya? Lebih kurang 20 minit.\n\n"
            f"1. Buka {share.PUBLIC_URL}/penguji\n2. Log masuk:\n{login}"
            "3. Ikut Borang Penguji: cuba setiap tugasan, nilai beberapa pantun, kemudian tekan Hantar.\n\n"
            "Jika ada yang pelik atau rosak, tulis sahaja dalam borang. Terima kasih!")


def owner_panel():
    s = share.state()
    st.session_state.setdefault("owner_tester_on", s["tester_open"])
    st.toggle("Buka Borang Penguji kepada pelawat", key="owner_tester_on", on_change=_toggled,
              help="Apabila mati, hanya anda nampak borang ini.")
    if not s["tester_open"]:
        st.caption("Borang tersembunyi daripada pelawat. Hidupkan semasa rakan anda menguji.")
    st.caption("Rakan hanya boleh masuk semasa **Start Sharing.bat** berjalan di komputer ini.")

    with st.expander("![](/app/static/i/mail.png) Jemput penguji", expanded=not len(reports())):
        st.caption("Akaun **Pensyarah** boleh membuka ketiga-tiga paparan, jadi semua ujian boleh dicuba. Ia juga boleh "
                   "melihat pertanyaan tetamu semasa, tetapi bukan kelas pensyarah lain.")
        with st.form("tester_invite", clear_on_submit=True):
            c1, c2, c3 = st.columns([2, 2, 1])
            name = c1.text_input("Nama rakan", placeholder="cth. Hakim")
            user = c2.text_input("Nama pengguna", placeholder="cth. penguji.hakim", max_chars=24)
            days = c3.selectbox("Tempoh", [3, 7, 14], index=1, format_func=lambda d: f"{d} hari")
            if st.form_submit_button("Cipta akaun penguji", type="primary", icon=":material/person_add:"):
                try:
                    key = share.add_member(user, name, days, "penguji", "pensyarah")
                    st.session_state["owner_tester_new"] = (user.strip().lower(), key)
                except ValueError as e:
                    st.error(str(e), icon=":material/error:")
        new = st.session_state.get("owner_tester_new")
        if new:
            st.success("Salin mesej ini sekarang. Kata laluan hanya dipaparkan **sekali**.", icon=":material/key:")
            st.code(_invite(*new), language=None)
            if st.button("Sudah disalin", key="tester_copied", icon=":material/check:"):
                st.session_state.pop("owner_tester_new")
                st.rerun()
        else:
            st.code(_invite(), language=None)

    rep, rat = reports(), ratings()
    with st.container(horizontal=True):
        st.metric("borang diterima", len(rep), border=True)
        st.metric("penguji", rep["name"].str.lower().nunique() if len(rep) else 0, border=True)
        st.metric("pantun dinilai", len(rat), border=True)
        st.metric("cadangan kepada rakan", f"{rep['recommend'].mean():.1f}/10" if len(rep) else "—", border=True)
    if rep.empty and rat.empty:
        st.info("Belum ada jawapan. Jawapan penguji akan muncul di sini.", icon=":material/inbox:")
        return

    if len(rep):
        st.markdown("**Hasil ujian** (yang paling bermasalah di atas)")
        st.dataframe(task_summary(rep), hide_index=True, alt="Keputusan setiap ujian")
        st.markdown("**Penilaian purata** (1 hingga 5)")
        means = rating_means(rep)
        with st.container(horizontal=True):
            for label, v in means.items():
                st.metric(label, v if v is not None else "—", border=True)
        st.markdown("**Komen penguji**")
        st.dataframe(rep.assign(Masa=rep["time"].map(share._when))[
            ["Masa", "name", "background", "device", "browser", "liked", "confusing", "ideas"]].rename(columns={
                "name": "Nama", "background": "Latar", "device": "Peranti", "browser": "Pelayar", "liked": "Disukai",
                "confusing": "Mengelirukan", "ideas": "Cadangan"}), hide_index=True, alt="Komen penguji")
    if len(rat):
        tuning_panel(rat)
    with st.container(horizontal=True):
        st.download_button("Muat turun borang (CSV)", rep.to_csv(index=False).encode("utf-8-sig"),
                           file_name="penguji_borang.csv", icon=":material/download:", disabled=rep.empty)
        st.download_button("Muat turun penilaian pantun (CSV)", rat.to_csv(index=False).encode("utf-8-sig"),
                           file_name="penguji_penilaian.csv", icon=":material/download:", disabled=rat.empty)


def tuning_panel(rat):
    st.subheader("![](/app/static/i/compass.png) Penalaan skor", anchor=False)
    st.caption("Membandingkan skor Makna sistem dengan pendapat penguji. Tiada apa-apa diubah secara automatik.")
    t = tuning(rat)
    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("**Purata skor Makna ikut pendapat penguji**")
        g = rat.groupby("human")["meaning"].agg(["count", "mean"]).reindex(HUMAN).dropna()
        st.dataframe(pd.DataFrame({"Pendapat penguji": g.index, "Pantun": g["count"].astype(int),
                                   "Purata Makna": (100 * g["mean"]).round().astype(int).astype(str) + "%"}),
                     hide_index=True, alt="Purata skor Makna ikut pendapat penguji")
    with right:
        st.markdown("**Adakah skor tepat?**")
        rows = [{"Skor": n, **{v: int((rat[c] == v).sum()) for v in SCORE_VERDICT}}
                for n, c in (("Makna", "meaning_verdict"), ("Bunyi", "sound_verdict"))]
        st.dataframe(pd.DataFrame(rows), hide_index=True, alt="Pendapat penguji tentang ketepatan skor")
    low, high = round(100 * (0.5 - LEAN)), round(100 * (0.5 + LEAN))
    if t["n_sure"] < MIN_FOR_TUNING:
        st.info(f"Ada **{t['n_sure']}** penilaian yang pasti. Perlu sekurang-kurangnya **{MIN_FOR_TUNING}** sebelum "
                f"sebarang cadangan bermakna. Julat Tidak pasti sekarang: {low}% hingga {high}%.", icon=":material/tune:")
    else:
        st.success(f"Daripada {t['n_sure']} pantun, garis 50% sepadan dengan penguji **{100 * t['current']:.0f}%** "
                   f"daripada masa. Garis terbaik dalam sampel ini: **{100 * t['best']:.0f}%** "
                   f"(**{100 * t['best_acc']:.0f}%** sepadan). Sahkan dengan sampel lain sebelum mengubah tetapan.",
                   icon=":material/tune:")
