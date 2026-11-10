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
    """Append one row. A file from an older app version (different header) is kept as *_old_format.csv."""
    if path.exists():
        with open(path, encoding="utf-8", newline="") as f:
            header = next(csv.reader(f), [])
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


def save_flag(view, lines, res, comment, who=""):
    append_row(FLAGS_CSV, ["timestamp", "view", "who", "line1", "line2", "line3", "line4", "comment",
                           "sound", "meaning_pct", "rules"],
               [now(), view, who, *lines, comment, res["sound"], round(100 * res["p_avg"]), res["rules"]])


def save_decision(class_name, student, action, note, lines, res):
    append_row(DECISIONS_CSV, ["timestamp", "class", "student", "action", "note",
                               "line1", "line2", "line3", "line4", "sound", "meaning_pct", "rules"],
               [now(), class_name, student, action, note, *lines,
                res["sound"] if res else "", round(100 * res["p_avg"]) if res else "",
                res["rules"] if res else ""])


def save_rating(lines, res, rating, link_types, agree, comment):
    append_row(RATINGS_CSV, ["timestamp", "line1", "line2", "line3", "line4", "rating", "link_types",
                             "agree_with_system", "comment", "system_lean", "meaning_pct", "sound"],
               [now(), *lines, rating, ";".join(link_types), agree, comment, res["lean"],
                round(100 * res["p_avg"]), res["sound"]])


LOG_COLUMNS = {
    FLAGS_CSV: ["timestamp", "view", "who", "line1", "line2", "line3", "line4", "comment", "sound", "meaning_pct",
                "rules"],
    DECISIONS_CSV: ["timestamp", "class", "student", "action", "note", "line1", "line2", "line3", "line4", "sound",
                    "meaning_pct", "rules"],
    RATINGS_CSV: ["timestamp", "line1", "line2", "line3", "line4", "rating", "link_types", "agree_with_system",
                  "comment", "system_lean", "meaning_pct", "sound"],
}


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

# The SVG is fully percent-encoded so it has no quotes or "<" that would end the style="..." attribute early.
_SONGKET_SVG = ("<svg xmlns='http://www.w3.org/2000/svg' width='22' height='12'>"
                "<rect width='22' height='12' fill='#DEB251'/>"
                "<polygon points='11,2 16,6 11,10 6,6' fill='white'/></svg>")
SONGKET = (f"background-image:url(data:image/svg+xml,{urllib.parse.quote(_SONGKET_SVG, safe='')});"
           "background-repeat:repeat-x;height:12px;")


def fonts():
    """Load Lora (pantun text) and Nunito (student view). Inter and JetBrains Mono come from config."""
    st.html(FONTS_CSS)


def songket_border():
    st.html(f"<div style=\"{SONGKET}border-radius:2px\"></div>")


def banner(kicker, title, subtitle="", font="Nunito"):
    """Teal header with the gold logo dot and a songket border (Exhibits 2-4)."""
    st.html(f"""
<div style="background:{TEAL};border-radius:18px 18px 0 0;padding:18px 22px 16px;font-family:'{font}',sans-serif">
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


def dial(value_text, fraction, colour, label, caption, icon, font="Nunito"):
    """Round score dial (Exhibit 2, label 5): a ring that fills to `fraction`.

    Drawn with a CSS conic gradient, because st.html removes inline <svg>.
    """
    deg = 360 * max(0.0, min(1.0, fraction))
    return f"""
<div style="text-align:center;font-family:'{font}',sans-serif;flex:1 1 0;min-width:84px">
  <div role="img" aria-label="{html.escape(label)} {html.escape(value_text)}"
       style="width:88px;height:88px;margin:0 auto;border-radius:50%;
              background:conic-gradient({colour} {deg:.1f}deg, #E6E1D6 0);display:flex;align-items:center;justify-content:center">
    <div style="width:68px;height:68px;border-radius:50%;background:#FBF7EE;display:flex;align-items:center;
                justify-content:center;font-size:1.2rem;font-weight:800;color:#1F2A2E">{html.escape(value_text)}</div>
  </div>
  <div style="font-weight:800;color:#1F2A2E;margin-top:6px">{icon} {html.escape(label)}</div>
  <div style="color:#5b6670;font-size:0.9rem">{html.escape(caption)}</div>
</div>"""


def dials(items):
    st.html('<div style="display:flex;justify-content:space-around;gap:4px">'
            + "".join(items) + "</div>")


def card_html(title, body_html, background="#ffffff", border="#E3DCCB", font="Nunito", title_colour="#1F2A2E"):
    """Rounded card (student view). `title` and `body_html` must already be safe HTML."""
    head = (f'<div style="font-weight:800;font-size:1.1rem;color:{title_colour};margin-bottom:6px">{title}</div>'
            if title else "")
    return f"""
<div style="flex:1 1 240px;background:{background};border:2px solid {border};border-radius:18px;padding:14px 18px;font-family:'{font}',sans-serif">
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
