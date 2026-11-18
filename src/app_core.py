"""Shared logic and design pieces for the three app pages (students, instructors, researchers).

The scoring is the same as in the prototype:
  - sound link   = end rhyme a-b-a-b (src/rhyme.py), 0-10
  - meaning link = calibrated p(real) averaged over the embedding models (Phase 3), as a %
  - rules        = traditional criteria (src/criteria.py), out of 4 (+ middle-rhyme bonus)

Design follows the business case (Section 6, Exhibits 1-5): Cenderawasih teal and gold, cream
background, songket diamond border, pantun text in Lora with the pembayang in teal and the maksud
in brown. Colours and the main fonts are set in .streamlit/config.toml; the few pieces Streamlit has
no element for (songket border, round score dials, pantun card) are small HTML snippets below.
"""

import csv
import html
import urllib.parse
import json
import re
from datetime import datetime

import numpy as np
import pandas as pd
import streamlit as st
from scipy import stats

from src import illus, kids_theme
from src.criteria import checklist
from src.data_loader import PROJECT_ROOT, find_merged_line, join_couplet, normalise_line
from src.evaluate import lean, predict_p_real
from src.rhyme import explain as explain_rhyme
from src.rhyme import sound_score
from src.score import MODELS, SCORES_CSV, load_encoder

RESULTS = PROJECT_ROOT / "results"
FLAGS_CSV = RESULTS / "expert_review_flags.csv"          # "I disagree" requests from students
DECISIONS_CSV = RESULTS / "instructor_decisions.csv"      # every instructor decision (logged)
RATINGS_CSV = RESULTS / "expert_ratings.csv"              # expert ratings (data for the M3 gate)

MODEL_BY_SHORT = {m["short"]: m for m in MODELS}
ALL_MODELS = [m["short"] for m in MODELS]
MODEL_LABEL = {"minilm": "MiniLM", "labse": "LaBSE", "e5": "multilingual-e5-base",
               "e5_large_instruct": "e5-large-instruct", "mesolitica": "Mesolitica (Malay)"}

# Cenderawasih design system (Exhibit 1)
TEAL, GOLD, CREAM = "#0C525C", "#DEB251", "#FBF7EE"
PEMBAYANG, MAKSUD = "#1B6E78", "#8A4B1C"
PASS, CANT_TELL, CHECK, FAIL = "#2F7D4F", "#52606D", "#A15C00", "#B4443C"

# Example pantun from the corpus (real, published). "Mixed-up" joins two real halves.
EXAMPLES = {
    "Pisang emas": ["Pisang emas dibawa belayar,", "Masak sebiji di atas peti;",
                    "Hutang emas boleh dibayar,", "Hutang budi dibawa mati."],
    "Francis Light": ["Francis Light membuka negeri,", "Pulau dibangunkan jadi pelabuhan;",
                      "Bukan sedikit termakan budi,", "Budi setahun segunung intan."],
    "Pandai menyimpai": ["Kalau tuan pandai menyimpai,", "Cubalah simpai taruk berturang;",
                         "Kalau tuan pandai mengungkai,", "Cubalah ungkai di tangan orang."],
    "Bercampur (ujian)": ["Francis Light membuka negeri,", "Pulau dibangunkan jadi pelabuhan;",
                          "Kalau tuan pandai mengungkai,", "Cubalah ungkai di tangan orang."],
}


# ---------------------------------------------------------------------------
# Data and models (cached once per server)
# ---------------------------------------------------------------------------

@st.cache_resource(show_spinner=False)
def load_model(model_short):
    return load_encoder(MODEL_BY_SHORT[model_short])


@st.cache_data(max_entries=2000, show_spinner=False)
def score_pair(model_short, pembayang, maksud):
    """Cosine similarity between pembayang and maksud for one model."""
    m = MODEL_BY_SHORT[model_short]
    a, b = load_model(model_short).encode([m["prefix"] + pembayang, m["prefix"] + maksud],
                                          normalize_embeddings=True)
    return float(np.dot(a, b))


@st.cache_data
def load_corpus():
    df = pd.read_csv(SCORES_CSV, keep_default_na=False)
    return df[df["label"] == "real"].reset_index(drop=True)


@st.cache_data
def load_result_table(name):
    path = RESULTS / name
    return pd.read_csv(path, keep_default_na=False) if path.exists() else None


@st.cache_data
def load_calibration():
    """Phase 3 section 8: bins for p(real) per model + the held-out test results."""
    path = RESULTS / "calibration.json"
    if not path.exists():
        st.error("results/calibration.json is missing - run notebooks/evaluation.ipynb first.")
        st.stop()
    with open(path) as f:
        return json.load(f)


def baselines():
    """{model: row} for the random-shuffle baseline from Phase 3."""
    b = load_result_table("baseline_summary.csv")
    if b is None:
        return {}
    return {r["model"]: r for r in b[b["baseline"] == "random"].to_dict("records")}


def ready_models():
    """Models with scores (Phase 2) AND calibration + baselines (Phase 3)."""
    cal, b, corpus = load_calibration()["models"], baselines(), load_corpus()
    return [s for s in ALL_MODELS if s in corpus.columns and s in cal and s in b]


@st.cache_resource(show_spinner="Menyediakan data perbandingan (kali pertama sahaja)...")
def reference():
    """Corpus numbers used to put each result in context.

    For every model: scores of real pantun and of random pairings (seed 0). Also the averaged
    p(real) of real pantun and random pairings, and the share of real pantun at each sound /
    rules score.
    """
    from src.data_loader import load_pantun
    from src.evaluate import shuffled_partner

    pantun, _ = load_pantun()
    lines = [p.lines for p in pantun]
    sound = np.array([sound_score(l) for l in lines])
    rules, bonus = [], []
    for l in lines:
        c = checklist(l)
        rules.append(1 + sum(x["passed"] for x in c if not x["name"].startswith("Middle")))
        bonus.append(any(x["passed"] for x in c if x["name"].startswith("Middle")))
    cal = load_calibration()["models"]
    partner = shuffled_partner(np.array([p.maksud for p in pantun]), 0)
    real, fake, p_real, p_fake = {}, {}, [], []
    for s in ready_models():
        e = np.load(RESULTS / "embeddings" / f"{s}.npz")
        P, M = e["pembayang"], e["maksud"]
        real[s], fake[s] = (P * M).sum(1), (P * M[partner]).sum(1)
        p_real.append(predict_p_real(cal[s], real[s]))
        p_fake.append(predict_p_real(cal[s], fake[s]))
    return {"sound": sound, "rules": np.array(rules), "bonus": np.array(bonus),
            "real_scores": real, "fake_scores": fake,
            "p_real": np.mean(p_real, axis=0), "p_fake": np.mean(p_fake, axis=0)}


# ---------------------------------------------------------------------------
# Checking and scoring one pantun
# ---------------------------------------------------------------------------

def split_text(text):
    """Text box -> list of non-empty lines."""
    return [line for line in text.splitlines() if line.strip()]


def check_lines(raw_lines, malay=True):
    """Return (clean lines, problems). A pantun empat kerat has exactly 4 non-empty lines."""
    raw = [l for l in raw_lines if l and l.strip()]
    problems = []
    if len(raw) != 4:
        problems.append(f"Kami jumpa {len(raw)} baris, tetapi pantun empat kerat perlu 4 baris."
                        if malay else f"Found {len(raw)} line(s); a pantun empat kerat has 4 lines.")
    lines = [normalise_line(l) for l in raw]
    if any(not l for l in lines):
        problems.append("Satu baris tidak mempunyai perkataan." if malay else "A line has no words.")
    if len(lines) == 4 and not problems and find_merged_line(lines):
        problems.append("Satu baris seolah-olah mengulang baris lain. Sila semak pemisah baris."
                        if malay else "One line seems to contain another line - check the line breaks.")
    return lines, problems


def shared_words(pembayang, maksud):
    words = lambda t: set(re.findall(r"[a-z]+(?:-[a-z]+)*", t.lower()))
    stop = {"di", "ke", "dan", "yang", "dari", "pada", "itu", "ini", "tak", "tidak", "ada"}
    return sorted((words(pembayang) & words(maksud)) - stop)


def analyse(lines, models=None):
    """Score a clean 4-line pantun. Returns one dict with every number the pages show."""
    models = models or ready_models()
    pembayang, maksud = join_couplet(lines[0], lines[1]), join_couplet(lines[2], lines[3])
    corpus, cal = load_corpus(), load_calibration()["models"]
    scores = {s: score_pair(s, pembayang, maksud) for s in models}
    pcts = {s: float(stats.percentileofscore(corpus[s], v)) for s, v in scores.items()}
    p_real = {s: float(predict_p_real(cal[s], v)) for s, v in scores.items()}
    p_avg = float(np.mean(list(p_real.values())))
    crit = checklist(lines)
    core = [c for c in crit if not c["name"].startswith("Middle")]
    bonus = [c for c in crit if c["name"].startswith("Middle")]
    match = corpus[(corpus["pembayang"].str.lower() == pembayang.lower())
                   & (corpus["maksud"].str.lower() == maksud.lower())]
    return {
        "lines": lines, "pembayang": pembayang, "maksud": maksud,
        "scores": scores, "pcts": pcts, "p_real": p_real, "p_avg": p_avg, "lean": lean(p_avg),
        "sound": sound_score(lines), "rhyme": explain_rhyme(lines),
        "criteria": crit, "rules": 1 + sum(c["passed"] for c in core),
        "bonus": bool(bonus) and bonus[0]["passed"],
        "shared": shared_words(pembayang, maksud),
        "match": None if match.empty else f"{match.iloc[0]['collection']} ({match.iloc[0]['id']})",
    }


@st.cache_resource(show_spinner=False)
def start_warmup():
    """Load every model once in the background when the app first opens (SRNF02: result within 7 s).

    Without this the first check waits about a minute while the models load. Runs once per server.
    """
    import threading
    import time

    from streamlit.runtime.scriptrunner import add_script_run_ctx

    state = {"done": False, "seconds": None}

    def run():
        start = time.perf_counter()
        analyse(EXAMPLES["Pisang emas"])        # loads the data, calibration and all models
        state.update(done=True, seconds=round(time.perf_counter() - start, 1))

    thread = threading.Thread(target=run, name="pantun-warmup", daemon=True)
    add_script_run_ctx(thread)
    thread.start()
    return state


LEAN_MALAY = {"belong": ("▲", "Condong sepadan", "Ada tanda sepadan"),
              "cannot_tell": ("●", "Tidak pasti", "Tidak pasti"),
              "not_belong": ("▼", "Condong tidak sepadan", "Ada tanda tidak sepadan")}
LEAN_ENGLISH = {"belong": "leans real", "cannot_tell": "can't tell", "not_belong": "leans mismatch"}


def rhyme_text(res):
    """'-yar/-ti' style summary of the line-end sounds."""
    (a1, b1, e1, f1, _), (a2, b2, e2, f2, _) = res["rhyme"]
    return f"-{e1}/-{e2}" if (e1 == f1 and e2 == f2) else f"-{e1}/-{f1}, -{e2}/-{f2}"


# ---------------------------------------------------------------------------
# Logs (CSV files in results/, kept on this computer)
# ---------------------------------------------------------------------------

def append_row(path, columns, row):
    """Append one row. If the file has an older header that is the start of `columns`, the new columns are added
    (empty) to the old rows. A file with a different header is kept as *_old_format.csv."""
    if path.exists():
        with open(path, encoding="utf-8", newline="") as f:
            rows = list(csv.reader(f))
        header = rows[0] if rows else []
        if header != columns and header == columns[:len(header)] and header:
            with open(path, "w", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow(columns)
                w.writerows(r + [""] * (len(columns) - len(r)) for r in rows[1:])
            header = columns
        if header != columns:
            old = path.with_name(f"{path.stem}_old_format.csv")
            if not old.exists():
                path.rename(old)
    new = not path.exists()
    with open(path, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(columns)
        w.writerow(row)


def now():
    return datetime.now().isoformat(timespec="seconds")


LOG_COLUMNS = {
    # student_user / lecturer: which member sent it and which lecturer may see it ("" = owner only)
    FLAGS_CSV: ["timestamp", "view", "who", "line1", "line2", "line3", "line4", "comment", "sound", "meaning_pct",
                "rules", "student_user", "lecturer"],
    # instructor: the lecturer member who decided ("" = the owner on this computer)
    DECISIONS_CSV: ["timestamp", "class", "student", "action", "note", "line1", "line2", "line3", "line4", "sound",
                    "meaning_pct", "rules", "instructor"],
    RATINGS_CSV: ["timestamp", "line1", "line2", "line3", "line4", "rating", "link_types", "agree_with_system",
                  "comment", "system_lean", "meaning_pct", "sound", "rater"],
}


def save_flag(view, lines, res, comment, who="", student_user="", lecturer=""):
    append_row(FLAGS_CSV, LOG_COLUMNS[FLAGS_CSV],
               [now(), view, who, *lines, comment, res["sound"], round(100 * res["p_avg"]), res["rules"],
                student_user, lecturer])


def save_decision(class_name, student, action, note, lines, res, instructor=""):
    append_row(DECISIONS_CSV, LOG_COLUMNS[DECISIONS_CSV],
               [now(), class_name, student, action, note, *lines,
                res["sound"] if res else "", round(100 * res["p_avg"]) if res else "",
                res["rules"] if res else "", instructor])


def save_rating(lines, res, rating, link_types, agree, comment, rater=""):
    append_row(RATINGS_CSV, LOG_COLUMNS[RATINGS_CSV],
               [now(), *lines, rating, ";".join(link_types), agree, comment, res["lean"],
                round(100 * res["p_avg"]), res["sound"], rater])


def read_log(path):
    """Read a log; columns missing from older files are added as empty text."""
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, keep_default_na=False, dtype=str)
    for c in LOG_COLUMNS.get(path, []):
        if c not in df.columns:
            df[c] = ""
    return df


# ---------------------------------------------------------------------------
# Design pieces (HTML only where Streamlit has no element for them)
# ---------------------------------------------------------------------------

FONTS_CSS = """<style>
@import url('https://fonts.googleapis.com/css2?family=Lora:ital,wght@0,400;0,500;1,400&family=Nunito:wght@400;600;700;800&display=swap');
</style>"""

# Motion and polish for all three views. Everything is switched off for people who ask for less motion.
UX_CSS = """<style>
@property --p { syntax: '\\3c number>'; inherits: false; initial-value: 0; }  /* \\3c is the less-than sign, escaped: the sanitiser drops tag-like text */
@keyframes cz-rise { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: none; } }
@keyframes cz-pop { 0% { opacity: 0; transform: scale(.86); } 70% { opacity: 1; transform: scale(1.04); } 100% { transform: scale(1); } }
@keyframes cz-fill { from { --p: 0; } to { --p: var(--target); } }
@keyframes cz-shine { from { background-position: -200% 0; } to { background-position: 200% 0; } }
@keyframes cz-fall { 0% { opacity: 1; transform: translate(0, 0) rotate(0); }
                     100% { opacity: 0; transform: translate(var(--dx), 340px) rotate(var(--rot)); } }

.cz-rise { animation: cz-rise .55s cubic-bezier(.22,.8,.3,1) both; }
.cz-pop { animation: cz-pop .5s cubic-bezier(.22,.8,.3,1) both; }
.cz-ring { --p: var(--target); background: conic-gradient(var(--c) calc(var(--p) * 1deg), #E6E1D6 0);
           animation: cz-fill 1.3s cubic-bezier(.22,.8,.3,1) both; animation-delay: var(--delay, 0s); }
.cz-card { transition: transform .2s ease, box-shadow .2s ease; }
.cz-card:hover { transform: translateY(-2px); box-shadow: 0 10px 24px rgba(31, 42, 46, .08); }
.cz-confetti { position: fixed; left: 50%; top: 28%; width: 0; height: 0; z-index: 9999; pointer-events: none; }
.cz-confetti i { position: absolute; width: 9px; height: 14px; border-radius: 2px; opacity: 0;
                 animation: cz-fall 1.8s cubic-bezier(.2,.7,.4,1) forwards; }

/* Buttons: lift on hover, press on click */
.stButton button, .stDownloadButton button, .stFormSubmitButton button, .stPopover button {
  transition: transform .15s ease, box-shadow .15s ease, filter .15s ease; }
.stButton button:hover, .stDownloadButton button:hover, .stFormSubmitButton button:hover, .stPopover button:hover {
  transform: translateY(-1px); box-shadow: 0 6px 16px rgba(12, 82, 92, .14); }
.stButton button:active, .stDownloadButton button:active { transform: translateY(1px); box-shadow: none; }
.stButton button[kind="primary"] { box-shadow: 0 4px 0 #083b42; }
.stButton button[kind="primary"]:hover { box-shadow: 0 6px 0 #083b42, 0 8px 18px rgba(12, 82, 92, .18); }
.stButton button[kind="primary"]:active { box-shadow: 0 1px 0 #083b42; }

/* Inputs: soft focus glow */
.stTextInput input:focus, .stTextArea textarea:focus { box-shadow: 0 0 0 3px rgba(12, 82, 92, .15) !important; }

/* Tabs: gold underline */
.stTabs [data-baseweb="tab-highlight"], .stTabs [role="tablist"] > div:last-child[aria-hidden] { background: #DEB251 !important; height: 3px !important; }
.stTabs [role="tab"] { transition: color .2s ease; }

/* Metric cards, bordered boxes and tables appear with a gentle rise */
[data-testid="stMetric"] { animation: cz-rise .5s cubic-bezier(.22,.8,.3,1) both; background: #fff; }
[data-testid="stMetricValue"] { color: #0C525C; font-weight: 800; }
[data-testid="stDataFrame"], [data-testid="stVerticalBlockBorderWrapper"] { animation: cz-rise .45s ease both; }
[data-testid="stExpander"] details { border-radius: 14px; }
[data-testid="stAlert"] { border-radius: 12px; }

/* Loading text shimmer */
[data-testid="stSpinner"] p { background: linear-gradient(90deg, #0C525C 30%, #DEB251 50%, #0C525C 70%);
  background-size: 200% 100%; -webkit-background-clip: text; background-clip: text; color: transparent;
  animation: cz-shine 2.2s linear infinite; font-weight: 700; }

/* Animated illustrations (Irasutoya pictures, src/illus.py): pop in, bounce, wiggle, float */
@keyframes cz-popin { 0% { opacity: 0; transform: scale(.3); } 70% { opacity: 1; transform: scale(1.08); }
                      100% { transform: scale(1); } }
@keyframes cz-bounce { 0%, 100% { transform: translateY(0); } 40% { transform: translateY(-16px); }
                       60% { transform: translateY(-16px) rotate(-3deg); } }
@keyframes cz-wiggle { 0%, 100% { transform: rotate(0); } 20% { transform: rotate(-8deg); } 40% { transform: rotate(7deg); }
                       60% { transform: rotate(-4deg); } 80% { transform: rotate(2deg); } }
@keyframes cz-float { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-9px); } }
.cz-anim-pop { animation: cz-popin .6s cubic-bezier(.2, 1.4, .4, 1) both; }
.cz-anim-cheer { animation: cz-popin .6s cubic-bezier(.2, 1.4, .4, 1) both, cz-bounce 1s ease-in-out .6s 3; }
.cz-anim-wiggle { animation: cz-wiggle 2.6s ease-in-out infinite; transform-origin: 50% 85%; }
.cz-anim-float { animation: cz-float 3.2s ease-in-out infinite; }
.cz-illus { display: block; margin: 0 auto; filter: drop-shadow(0 6px 10px rgba(31, 42, 46, .12)); }

/* Sign-up celebration: character with a party hat, confetti, then it fades away by itself */
@keyframes cz-cel-out { to { opacity: 0; visibility: hidden; } }
.cz-celebrate { position: fixed; inset: 0; z-index: 100002; display: flex; align-items: center; justify-content: center;
  background: rgba(12, 82, 92, .38); pointer-events: none; animation: cz-cel-out .6s ease 5.5s forwards; }
.cz-celebrate .cz-confetti { top: 4%; }     /* falling confetti starts near the top, not over the character's face */
.cz-cel-card { background: #FFFBF1; border-radius: 26px; padding: 22px 30px 22px; text-align: center; max-width: 380px;
  border-top: 8px solid #DEB251; box-shadow: 0 24px 60px rgba(0, 0, 0, .28); font-family: 'Nunito', sans-serif;
  animation: cz-popin .65s cubic-bezier(.2, 1.4, .4, 1) both; }
.cz-cel-card h2 { margin: 6px 0 4px; padding: 0; font-size: 1.9rem; font-weight: 900; color: #0C525C; }
.cz-cel-card p { margin: 0; color: #45525a; font-size: 1.02rem; line-height: 1.5; }
.cz-cel-char { position: relative; width: 150px; margin: 34px auto 8px;
  animation: cz-popin .6s cubic-bezier(.2, 1.4, .4, 1) .15s both, cz-bounce 1s ease-in-out .8s 4; }
/* Party poppers on both sides: they jolt, then blast confetti and streamers out of their mouths */
@keyframes cz-popper-l { 0% { transform: rotate(30deg); } 35% { transform: rotate(16deg) scale(1.22); }
                         100% { transform: rotate(30deg) scale(1); } }
@keyframes cz-popper-r { 0% { transform: scaleX(-1) rotate(30deg); } 35% { transform: scaleX(-1) rotate(16deg) scale(1.22); }
                         100% { transform: scaleX(-1) rotate(30deg) scale(1); } }
@keyframes cz-burst { 0% { opacity: 1; transform: translate(0, 0) rotate(0); } 75% { opacity: 1; }
                      100% { opacity: 0; transform: translate(var(--dx), var(--dy)) rotate(var(--rot)); } }
.cz-popper { position: absolute; bottom: 4px; width: 42px; height: 60px; }
.cz-popper.l { left: -64px; transform: rotate(30deg); animation: cz-popper-l .55s ease-out .7s both; }
.cz-popper.r { right: -64px; transform: scaleX(-1) rotate(30deg); animation: cz-popper-r .55s ease-out .7s both; }
.cz-popper .cone { position: absolute; inset: 0; clip-path: polygon(0 0, 100% 0, 50% 100%);
  background: repeating-linear-gradient(-45deg, #DEB251 0 8px, #B4443C 8px 16px); }
.cz-popper .rim { position: absolute; top: -5px; left: -3px; right: -3px; height: 10px; border-radius: 50%; background: #0C525C; }
.cz-popper .burst { position: absolute; left: 50%; top: 0; width: 0; height: 0; }
.cz-popper .burst i, .cz-popper .burst b { position: absolute; left: -3px; top: -6px; opacity: 0;
  animation: cz-burst 1.2s cubic-bezier(.12, .75, .3, 1) .75s forwards; }
.cz-popper .burst i { width: 7px; height: 11px; border-radius: 2px; }
.cz-popper .burst b { width: 3px; height: 28px; border-radius: 3px; }

@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation-duration: 1ms !important; animation-delay: 0s !important; transition: none !important; }
  .cz-confetti { display: none; }
}
</style>"""

# The SVG is fully percent-encoded so it has no quotes or "<" that would end the style="..." attribute early.
_SONGKET_SVG = ("<svg xmlns='http://www.w3.org/2000/svg' width='22' height='12'>"
                "<rect width='22' height='12' fill='#DEB251'/>"
                "<polygon points='11,2 16,6 11,10 6,6' fill='white'/></svg>")
SONGKET = (f"background-image:url(data:image/svg+xml,{urllib.parse.quote(_SONGKET_SVG, safe='')});"
           "background-repeat:repeat-x;height:12px;")


# Page background: cream paper with soft teal and gold light and a faint songket diamond lattice.
_LATTICE_SVG = ("<svg xmlns='http://www.w3.org/2000/svg' width='56' height='56'>"
                "<path d='M28 4 L52 28 L28 52 L4 28 Z' fill='none' stroke='#0C525C' stroke-opacity='.035' stroke-width='1'/>"
                "<path d='M28 20 L36 28 L28 36 L20 28 Z' fill='#DEB251' fill-opacity='.07'/></svg>")
_LATTICE = urllib.parse.quote(_LATTICE_SVG, safe="")   # encoded: no "<" for the sanitiser to trip on
THEME_CSS = f"""<style>
.stApp {{
  background:
    radial-gradient(1100px 520px at 8% -8%, rgba(12, 82, 92, .10), transparent 62%),
    radial-gradient(900px 480px at 100% 0%, rgba(222, 178, 81, .16), transparent 60%),
    radial-gradient(900px 600px at 50% 110%, rgba(27, 110, 120, .07), transparent 65%),
    url("data:image/svg+xml,{_LATTICE}"),
    #FBF7EE;
  background-attachment: fixed;
}}
[data-testid="stHeader"] {{ background: rgba(251, 247, 238, .82); backdrop-filter: blur(10px);
  border-bottom: 1px solid rgba(222, 178, 81, .35); }}
[data-testid="stHeader"]::after {{ content: ""; position: absolute; left: 0; right: 0; bottom: -4px; height: 3px;
  background: linear-gradient(90deg, transparent, #DEB251 20%, #0C525C 50%, #DEB251 80%, transparent); opacity: .55; }}
[data-testid="stMainBlockContainer"] {{ padding-top: 3.2rem; }}
[data-testid="stMetric"], [data-testid="stVerticalBlockBorderWrapper"] {{ border-radius: 14px; }}
[data-testid="stVerticalBlockBorderWrapper"] {{ background: rgba(255, 255, 255, .72); backdrop-filter: blur(4px); }}
.stTextInput input, .stTextArea textarea {{ background: rgba(255, 255, 255, .9) !important; }}
[data-testid="stDialog"] [role="dialog"] {{ border-top: 6px solid #0C525C; border-radius: 18px; }}
::selection {{ background: rgba(222, 178, 81, .45); }}
</style>"""


def fonts():
    """Load Lora (pantun text) and Nunito (student view), plus the theme, motion and polish styles."""
    st.html(FONTS_CSS + UX_CSS + THEME_CSS + kids_theme.CSS)
    st.html(kids_theme.JS, unsafe_allow_javascript=True)


def confetti():
    """A short burst of confetti in the brand colours (shown once, for a perfect rhyme)."""
    colours = [GOLD, TEAL, PEMBAYANG, PASS, "#F3D58E", FAIL]
    pieces = []
    for i in range(48):
        dx = ((i * 53) % 520) - 260
        rot = 360 + (i * 47) % 540
        pieces.append(f'<i style="background:{colours[i % len(colours)]};--dx:{dx}px;--rot:{rot}deg;'
                      f'left:{((i * 29) % 80) - 40}px;animation-delay:{(i % 6) * 0.04:.2f}s"></i>')
    st.html(f'<div class="cz-confetti" aria-hidden="true">{"".join(pieces)}</div>')


def songket_border():
    st.html(f"<div style=\"{SONGKET}border-radius:2px\"></div>")


def result_banner(kicker, title, pic):
    """Bright pop-up heading with a hopping character (the student's result)."""
    st.html(f'<div class="ks-banner">{illus.img(pic, 66, "margin:0")}<div><small>{html.escape(kicker)}</small>'
            f"<div>{html.escape(title)}</div></div></div>")


def banner(kicker, title, subtitle="", font="Nunito"):
    """Teal header with the gold logo dot and a songket border (Exhibits 2-4)."""
    st.html(f"""
<div class="cz-rise" style="background:{TEAL};border-radius:18px 18px 0 0;padding:18px 22px 16px;font-family:'{font}',sans-serif">
  <div style="display:flex;align-items:center;gap:10px;color:#fff;font-weight:700;font-size:0.95rem">
    <span style="width:22px;height:22px;border-radius:50%;background:{GOLD};display:inline-block"></span>{html.escape(kicker)}
  </div>
  <div style="color:#fff;font-weight:800;font-size:1.7rem;margin-top:6px">{html.escape(title)}</div>
  {f'<div style="color:#e8f1f1;margin-top:4px">{html.escape(subtitle)}</div>' if subtitle else ''}
</div>
<div style="{SONGKET}"></div>""")


def pantun_card(lines, compact=False, size="1.15rem"):
    """Pantun in Lora, pembayang in teal and maksud in brown, on cream paper.

    compact=False: four lines (Exhibits 2-4). compact=True: one couplet per line with " / " (Exhibit 5).
    """
    e = [html.escape(l.rstrip(" ,;.")) for l in lines]   # the card adds its own , ; .
    join = " / " if compact else "<br>"
    st.html(f"""
<div style="background:#F7EFE3;border-radius:10px;padding:14px 18px;font-family:'Lora',serif;font-size:{size};line-height:1.6">
  <div style="color:{PEMBAYANG}">{e[0]},{join}{e[1]};</div>
  <div style="color:{MAKSUD}">{e[2]},{join}{e[3]}.</div>
</div>""")


def dial(value_text, fraction, colour, label, caption, icon, font="Nunito", delay=0.0):
    """Round score dial (Exhibit 2, label 5): a ring that fills up to `fraction` when it appears.

    Drawn with a CSS conic gradient (st.html removes inline <svg>); the fill is animated in UX_CSS.
    """
    deg = 360 * max(0.0, min(1.0, fraction))
    return f"""
<div class="cz-pop" style="text-align:center;font-family:'{font}',sans-serif;flex:1 1 0;min-width:84px;animation-delay:{delay:.2f}s">
  <div class="cz-ring" role="img" aria-label="{html.escape(label)} {html.escape(value_text)}"
       style="--c:{colour};--target:{deg:.1f};--delay:{delay + 0.15:.2f}s;width:88px;height:88px;margin:0 auto;border-radius:50%;
              display:flex;align-items:center;justify-content:center">
    <div style="width:68px;height:68px;border-radius:50%;background:#FBF7EE;display:flex;align-items:center;
                justify-content:center;font-size:1.2rem;font-weight:800;color:#1F2A2E">{html.escape(value_text)}</div>
  </div>
  <div style="font-weight:800;color:#1F2A2E;margin-top:6px">{icon} {html.escape(label)}</div>
  <div style="color:#5b6670;font-size:0.9rem">{html.escape(caption)}</div>
</div>"""


def dials(items):
    st.html('<div style="display:flex;justify-content:space-around;gap:4px">'
            + "".join(items) + "</div>")


def card_html(title, body_html, background="#ffffff", border="#BDE7FF", font="Nunito", title_colour="#1F2A2E",
              delay=0.0):
    """Rounded card (student view) that rises in after `delay` seconds. Inputs must already be safe HTML."""
    head = (f'<div style="font-weight:800;font-size:1.1rem;color:{title_colour};margin-bottom:6px">{title}</div>'
            if title else "")
    return f"""
<div class="cz-card cz-rise" style="animation-delay:{delay:.2f}s;flex:1 1 240px;background:{background};border:3px solid {border};border-radius:24px;box-shadow:0 5px 0 #CDEEFF;padding:14px 18px;font-family:'{font}',sans-serif">
  {head}<div style="color:#1F2A2E;line-height:1.6">{body_html}</div>
</div>"""


def card(title, body_html, **style):
    st.html(card_html(title, body_html, **style))


def cards_row(cards):
    """Cards side by side on a wide screen; they wrap under each other on a phone."""
    st.html('<div style="display:flex;flex-wrap:wrap;gap:12px">' + "".join(cards) + "</div>")


def section_label(text):
    """Small grey uppercase heading used in the researcher view (Exhibit 5)."""
    st.markdown(f":gray[**{text.upper()}**]")


# ---------------------------------------------------------------------------
# Help: tutorial video (assets/tutorial/<view>.mp4, made from tutorial/*.html) and a guided tour
# ---------------------------------------------------------------------------

TUTORIAL_DIR = PROJECT_ROOT / "assets" / "tutorial"

# Spotlight tour that runs in the page. Steps whose element is not on the page are skipped.
# Shown once per browser (remembered in localStorage, if the browser allows it), and again on request.
_TOUR_JS = r"""
<script>
(() => {
  const cfg = __CFG__;
  const doc = document, win = window;
  const storeKey = "cz_tour_done_" + cfg.view;
  let done = false;
  try { done = win.localStorage.getItem(storeKey) === "1"; } catch (e) {}
  win.__czTour = win.__czTour || {};
  if (win.__czTour[cfg.view] === cfg.nonce) return;          // this request was already shown
  if (cfg.nonce === 0 && done) return;                         // first-visit tour already seen
  win.__czTour[cfg.view] = cfg.nonce;

  const old = doc.getElementById("cz-tour"); if (old) old.remove();
  const css = doc.createElement("style");
  css.textContent = `
    #cz-tour { position: fixed; inset: 0; z-index: 1000001; pointer-events: none; font-family: 'Nunito', 'Inter', sans-serif; }
    /* While the tour is open, drop the top menu bar under the dark overlay (this style goes when the tour ends) */
    [data-testid="stHeader"], [data-testid="stToolbar"] { z-index: 1 !important; }
    #cz-tour .hole { position: fixed; border-radius: 16px; border: 3px solid #DEB251; pointer-events: none;
      box-shadow: 0 0 0 9999px rgba(20, 30, 32, .55), 0 0 26px rgba(222, 178, 81, .85);
      transition: all .45s cubic-bezier(.22,.8,.3,1); }
    #cz-tour .tip { position: fixed; width: 330px; background: #fff; border-radius: 18px; padding: 16px 18px 14px;
      box-shadow: 0 18px 50px rgba(0,0,0,.28); pointer-events: auto; border-top: 6px solid #0C525C;
      transition: left .45s cubic-bezier(.22,.8,.3,1), top .45s cubic-bezier(.22,.8,.3,1); animation: czTip .35s ease both; }
    @keyframes czTip { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
    #cz-tour .n { font-size: 12.5px; font-weight: 800; color: #A15C00; letter-spacing: .4px; }
    #cz-tour h4 { margin: 4px 0 6px; font-size: 19px; color: #0C525C; font-weight: 900; padding: 0; }
    #cz-tour p { margin: 0; font-size: 15px; line-height: 1.55; color: #1F2A2E; }
    #cz-tour .row { display: flex; align-items: center; justify-content: flex-end; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
    #cz-tour .dots { display: flex; gap: 5px; flex: 1 0 100%; margin-bottom: 4px; }
    #cz-tour .dots i { width: 7px; height: 7px; border-radius: 50%; background: #E3DCCB; }
    #cz-tour .dots i.on { background: #DEB251; width: 18px; border-radius: 4px; }
    #cz-tour button { font: 700 14px 'Nunito', sans-serif; border-radius: 999px; padding: 7px 14px; cursor: pointer;
      border: 1.5px solid #0C525C; background: #fff; color: #0C525C; white-space: nowrap; }
    #cz-tour button.go { background: #0C525C; color: #fff; }
    #cz-tour button.skip { border: none; color: #5b6670; padding: 7px 6px; margin-right: auto; }
    @media (prefers-reduced-motion: reduce) { #cz-tour .hole, #cz-tour .tip { transition: none; animation: none; } }`;
  const root = doc.createElement("div");
  root.id = "cz-tour";
  root.innerHTML = '<div class="hole"></div><div class="tip" role="dialog" aria-live="polite"></div>';
  root.appendChild(css);

  const start = () => {
    const steps = cfg.steps.filter((s) => doc.querySelector(s.sel));
    if (!steps.length) return;
    doc.body.appendChild(root);
    const hole = root.querySelector(".hole"), tip = root.querySelector(".tip");
    let i = 0;

    const place = () => {
      const el = doc.querySelector(steps[i].sel);
      if (!el) return;
      const r = el.getBoundingClientRect(), pad = 8;
      Object.assign(hole.style, { left: r.left - pad + "px", top: r.top - pad + "px",
                                  width: r.width + 2 * pad + "px", height: r.height + 2 * pad + "px" });
      const W = win.innerWidth, H = win.innerHeight, tw = Math.min(330, W - 24), th = tip.offsetHeight || 170;
      tip.style.width = tw + "px";
      let left = r.right + 18, top = r.top;
      if (left + tw > W - 12) { left = Math.max(12, Math.min(W - tw - 12, r.left)); top = r.bottom + 16; }
      if (top + th > H - 12) top = Math.max(12, r.top - th - 16);
      tip.style.left = left + "px"; tip.style.top = Math.max(12, top) + "px";
    };
    const keys = (e) => {
      if (e.key === "Escape") finish();
      else if (e.key === "ArrowRight" && i < steps.length - 1) { i++; show(); }
      else if (e.key === "ArrowLeft" && i > 0) { i--; show(); }
    };
    const finish = () => {
      try { win.localStorage.setItem(storeKey, "1"); } catch (e) {}
      root.remove(); win.removeEventListener("resize", place); doc.removeEventListener("scroll", place, true);
      doc.removeEventListener("keydown", keys, true);
    };
    const render = () => {
      const s = steps[i], last = i === steps.length - 1;
      tip.innerHTML = `<div class="n">${cfg.labels.step} ${i + 1} / ${steps.length}</div><h4>${s.title}</h4><p>${s.text}</p>
        <div class="row"><div class="dots">${steps.map((_, k) => `<i class="${k === i ? "on" : ""}"></i>`).join("")}</div>
        ${last ? "" : `<button class="skip">${cfg.labels.skip}</button>`}
        ${i ? `<button class="back">${cfg.labels.back}</button>` : ""}
        <button class="go">${last ? cfg.labels.done : cfg.labels.next}</button></div>`;
      tip.style.animation = "none"; void tip.offsetWidth; tip.style.animation = "";
      tip.querySelector(".go").onclick = () => (last ? finish() : (i++, show()));
      const b = tip.querySelector(".back"); if (b) b.onclick = () => { i--; show(); };
      const k = tip.querySelector(".skip"); if (k) k.onclick = finish;
      tip.querySelector(".go").focus({ preventScroll: true });
    };
    const show = () => {
      const el = doc.querySelector(steps[i].sel);
      if (el) el.scrollIntoView({ block: "center", behavior: "smooth" });
      render(); place(); setTimeout(place, 350); setTimeout(place, 700);
    };
    win.addEventListener("resize", place); doc.addEventListener("scroll", place, true);
    doc.addEventListener("keydown", keys, true);
    show();
  };
  setTimeout(start, cfg.nonce === 0 ? 1200 : 300);   // wait for the page to finish drawing
})();
</script>"""

TOUR_LABELS = {
    "ms": {"step": "LANGKAH", "next": "Seterusnya →", "back": "← Kembali", "skip": "Langkau", "done": "Selesai ✓"},
    "en": {"step": "STEP", "next": "Next →", "back": "← Back", "skip": "Skip", "done": "Done ✓"},
}


def tour(view, steps, lang="ms"):
    """Guided spotlight tour. steps = [(css selector, title, text), ...]. Text must be safe HTML."""
    nonce = st.session_state.get(f"tour_{view}", 0)
    cfg = {"view": view, "nonce": nonce, "labels": TOUR_LABELS[lang],
           "steps": [{"sel": s, "title": t, "text": x} for s, t, x in steps]}
    code = _TOUR_JS.replace("__CFG__", json.dumps(cfg, ensure_ascii=False))
    # The HTML sanitiser drops a <script> whose text contains "<tag"-like text, so write "<" as "\x3c" inside it.
    head, body = code.split("<script>", 1)
    body, tail = body.rsplit("</script>", 1)
    body = re.sub(r"<(?=[/!\w])", lambda m: "\\x3c", body)
    st.html(f"{head}<script>{body}</script>{tail}", unsafe_allow_javascript=True)


HELP_TEXT = {
    "ms": ("Cara guna", "Cara guna laman ini", "Mulakan lawatan berpandu",
           "Tonton video (1 hingga 1.5 minit), atau ikut lawatan berpandu langkah demi langkah.",
           "Video tutorial belum dibuat. Jalankan tutorial/render.py."),
    "en": ("How to use", "How to use this page", "Start the guided tour",
           "Watch the video (about 1 minute), or follow the step-by-step guided tour.",
           "The tutorial video has not been made yet. Run tutorial/render.py."),
}


def help_button(view, lang="ms"):
    """'Cara guna' button: opens the tutorial video, with a button to start the guided tour."""
    label, title, start_label, intro, missing = HELP_TEXT[lang]

    @st.dialog(title, width="large")
    def _show():
        st.caption(intro)
        video = TUTORIAL_DIR / f"{view}.mp4"
        if video.exists():
            st.video(str(video), autoplay=True)
        else:
            st.info(missing, icon=":material/movie:")
        if st.button(start_label, type="primary", icon=":material/tour:", width="stretch"):
            st.session_state[f"tour_{view}"] = st.session_state.get(f"tour_{view}", 0) + 1
            st.rerun()

    if st.button(label, key=f"help_{view}", icon=":material/play_circle:", type="secondary"):
        _show()
