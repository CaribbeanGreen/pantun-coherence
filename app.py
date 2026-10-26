"""Phase 4 - Streamlit demo with two views.

Simple view   - for everyone (even children): three steps, colour-coded parts,
                two ratings: sound link (rhyme, 0-10) and meaning link (%). No statistics words.
Advanced view - for researchers / examiners: per-model scores, baselines,
                corpus distribution, Phase 3 statistics, method, flagged pantun.

Start it by double-clicking "Start Demo.bat", or from a terminal:
    streamlit run app.py

The score is a similarity between two sentence embeddings. It is NOT an
objective judgement of literary quality, and the app says so in both views.
"""

import csv
import json
import re
from datetime import datetime

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st
from scipy import stats

from src.data_loader import PROJECT_ROOT, find_merged_line, join_couplet, normalise_line
from src.evaluate import lean, predict_p_real, word_overlap
from src.criteria import checklist
from src.rhyme import explain as explain_rhyme
from src.rhyme import sound_score
from src.score import MODELS, SCORES_CSV, load_encoder

RESULTS = PROJECT_ROOT / "results"
FLAGS_CSV = RESULTS / "expert_review_flags.csv"
FLAG_COLUMNS = ["timestamp", "view", "line1", "line2", "line3", "line4", "comment"] + [m["short"] for m in MODELS]

# Friendly names for the models (full names are shown in the advanced view).
FRIENDLY = {"minilm": "Model A (MiniLM)", "labse": "Model B (LaBSE)", "e5": "Model C (E5)",
            "e5_large_instruct": "Model D (E5-large-instruct)", "mesolitica": "Model E (Mesolitica, Malay)"}
MODEL_BY_SHORT = {m["short"]: m for m in MODELS}
ALL_MODELS = [m["short"] for m in MODELS]

# Example pantun taken from the corpus (real, published pantun).
EXAMPLES = {
    "Pisang emas": ("Pisang emas dibawa belayar,\nMasak sebiji di atas peti;\n"
                    "Hutang emas boleh dibayar,\nHutang budi dibawa mati."),
    "Pandai menyimpai": ("Kalau tuan pandai menyimpai,\nCubalah simpai taruk berturang;\n"
                         "Kalau tuan pandai mengungkai,\nCubalah ungkai di tangan orang."),
    "Francis Light": ("Francis Light membuka negeri,\nPulau dibangunkan jadi pelabuhan;\n"
                      "Bukan sedikit termakan budi,\nBudi setahun segunung intan."),
    # Test case: picture part of "Francis Light" + message part of "Pandai menyimpai".
    # Both halves are real; they just do not belong together.
    "Mixed-up test": ("Francis Light membuka negeri,\nPulau dibangunkan jadi pelabuhan;\n"
                      "Kalau tuan pandai mengungkai,\nCubalah ungkai di tangan orang."),
}

st.set_page_config(page_title="Pantun connection checker", page_icon=":material/menu_book:")


# ---------- data and models (cached) ----------

@st.cache_resource(show_spinner=False)
def load_model(model_short):
    return load_encoder(MODEL_BY_SHORT[model_short])


@st.cache_data(max_entries=500, show_spinner=False)
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
    """Phase 3 section 8: bins for p_real per model + the held-out test results."""
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


# ---------- logic ----------

def check_structure(text):
    """Return (lines, problems). A pantun empat kerat has exactly 4 non-empty lines."""
    raw = [line for line in text.splitlines() if line.strip()]
    problems = []
    if len(raw) != 4:
        problems.append(f"We found {len(raw)} line(s), but a pantun needs 4 lines. "
                        "Press Enter after each line.")
    lines = [normalise_line(line) for line in raw]
    if any(not line for line in lines):
        problems.append("One of the lines has no words.")
    if len(lines) == 4 and not problems and find_merged_line(lines):
        problems.append("One line seems to repeat another line. Please check the line breaks.")
    return lines, problems


def run_check(text, chosen):
    """Check structure, score with the chosen models, store the result in session state.

    Returns a list of problems (empty list = success).
    """
    lines, problems = check_structure(text)
    st.session_state.pop("result", None)
    if problems:
        return problems
    if not chosen:
        return ["Pick at least one model."]
    pembayang, maksud = join_couplet(lines[0], lines[1]), join_couplet(lines[2], lines[3])
    corpus = load_corpus()
    with st.spinner("Reading your pantun… the first check takes about a minute."):
        scores = {s: score_pair(s, pembayang, maksud) for s in chosen}
    pcts = {s: stats.percentileofscore(corpus[s], v) for s, v in scores.items()}
    cal = load_calibration()["models"]
    p_real = {s: float(predict_p_real(cal[s], v)) for s, v in scores.items()}
    p_avg = float(np.mean(list(p_real.values())))
    match = corpus[(corpus["pembayang"].str.lower() == pembayang.lower())
                   & (corpus["maksud"].str.lower() == maksud.lower())]
    st.session_state["result"] = {
        "lines": lines, "pembayang": pembayang, "maksud": maksud,
        "scores": scores, "pcts": pcts, "avg": float(np.mean(list(pcts.values()))),
        "p_real": p_real, "p_avg": p_avg, "lean": lean(p_avg),
        "sound": sound_score(lines), "rhyme": explain_rhyme(lines), "criteria": checklist(lines),
        "match": None if match.empty else f"{match.iloc[0]['collection']} ({match.iloc[0]['id']})",
    }
    return []


# The three honest outcomes (from the averaged p_real, see src/evaluate.py: lean()).
OUTCOMES = {
    "belong": {"emoji": "🙂", "simple": "Some signs these parts belong together",
               "advanced": "Leans towards: real pantun"},
    "cannot_tell": {"emoji": "🤔", "simple": "The computer can't tell",
                    "advanced": "Can't tell"},
    "not_belong": {"emoji": "🙁", "simple": "Some signs these parts don't belong together",
                   "advanced": "Leans towards: random pairing"},
}


def out_of_ten(share):
    return f"{max(1, round(10 * share))} out of 10"


def save_flag(view, lines, scores, comment):
    new_file = not FLAGS_CSV.exists()
    with open(FLAGS_CSV, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(FLAG_COLUMNS)
        writer.writerow([datetime.now().isoformat(timespec="seconds"), view, *lines, comment]
                        + [f"{scores[s]:.4f}" if s in scores else "" for s in ALL_MODELS])


def flag_box(view, lines, scores, label, prompt):
    """Expander with a small form to send the pantun for expert review."""
    with st.expander(label, icon=":material/flag:"):
        with st.form(f"flag_form_{view}", border=False):
            comment = st.text_area(prompt, key=f"flag_comment_{view}")
            if st.form_submit_button("Send"):
                save_flag(view, lines, scores, comment)
                st.success("Thank you! An expert will look at it.")


def example_buttons(view, button_type):
    for label, pantun in EXAMPLES.items():
        if st.button(label, key=f"{view}_{label}", type=button_type):
            st.session_state["text"] = pantun
            st.session_state.pop("result", None)


# ---------- page ----------

# Only use models whose scores (Phase 2) AND calibration + baselines (Phase 3) exist,
# so the app still works while a newly added model is being processed.
READY_MODELS = [s for s in ALL_MODELS
                if s in load_corpus().columns and s in load_calibration()["models"] and s in baselines()]
if len(READY_MODELS) < len(ALL_MODELS):
    st.caption(f"Note: {len(ALL_MODELS) - len(READY_MODELS)} model(s) are still being prepared and "
               "are not used yet.")

if "text" not in st.session_state:
    st.session_state["text"] = EXAMPLES["Pisang emas"]

mode = st.segmented_control(
    "View", ["Simple", "Advanced"], default="Simple", key="mode", required=True,
    format_func=lambda m: {"Simple": ":material/child_care: Simple",
                           "Advanced": ":material/science: Advanced"}[m],
    help="Simple: easy for everyone. Advanced: per-model scores and full statistics.",
    label_visibility="collapsed",
)


# =====================================================================
# SIMPLE VIEW - short words, three steps, one picture-like result.
# =====================================================================
if mode == "Simple":
    st.title("Do the two parts of a pantun go together?", anchor=False)
    st.markdown(
        "A pantun has **4 lines** in **2 parts**:\n\n"
        "- :blue[**Picture part**] (lines 1 and 2) paints a picture, like fruit or the sea.\n"
        "- :orange[**Message part**] (lines 3 and 4) tells you the real message.\n\n"
        "Let's see if the **computer** thinks the two parts go together!"
    )

    st.subheader("1. Pick a pantun, or write your own", anchor=False)
    with st.container(horizontal=True):
        example_buttons("simple", "secondary")
    st.text_area("Write 4 lines (press Enter after each line)", key="text", height=130)

    st.subheader("2. Press the button", anchor=False)
    if st.button("Check my pantun", type="primary", icon=":material/search:", width="stretch"):
        for problem in run_check(st.session_state["text"], READY_MODELS):
            st.warning(problem, icon=":material/edit:")

    res = st.session_state.get("result")
    if res:
        st.subheader("3. See what the computer thinks", anchor=False)
        lines = res["lines"]
        with st.container(border=True):
            st.markdown(f":blue[**Picture part**]  \n:blue[{lines[0]}]  \n:blue[{lines[1]}]")
            st.markdown(f":orange[**Message part**]  \n:orange[{lines[2]}]  \n:orange[{lines[3]}]")
        test = load_calibration()["held_out_test"]
        sound_card, meaning_card = st.columns(2)

        # Rating 1: sound link (rhyme) - reliable, but only about sound.
        with sound_card.container(border=True, height="stretch"):
            st.markdown("🎵 **Sound link**", text_alignment="center")
            st.markdown(f"# {res['sound']:g} / 10", text_alignment="center")
            st.progress(res["sound"] / 10)
            for a, b, ea, eb, s in res["rhyme"]:
                mark = "✅" if s == 1 else ("〰️" if s == 0.5 else "❌")
                st.markdown(f"{mark} Line {a} ends in **-{ea}**, line {b} in **-{eb}**")
            st.caption("Do the ends of the lines rhyme? (a-b-a-b)")

        # Rating 2: meaning link - the calibrated p_real, shown as a %.
        with meaning_card.container(border=True, height="stretch"):
            st.markdown("💭 **Meaning link**", text_alignment="center")
            st.markdown(f"# {100 * res['p_avg']:.0f}%", text_alignment="center")
            st.progress(res["p_avg"])
            st.markdown(f"{OUTCOMES[res['lean']]['emoji']} **{OUTCOMES[res['lean']]['simple']}**",
                        text_alignment="center")
            st.caption("The computer's guess that the two parts were written together. "
                       "**50% = just guessing.**")

        if res["lean"] == "cannot_tell":
            st.markdown(
                f"💭 For about **{out_of_ten(test['share_cannot_tell'])}** pantun, the computer can't tell "
                "if the meanings belong together — for real pantun **and** for mixed-up ones. "
                "Try the **Mixed-up test** example to see for yourself!")
            with st.expander("Why can't the computer tell?", icon=":material/help:"):
                st.markdown(
                    "In a good pantun, the picture part always gives a **hint** about the message.\n\n"
                    ":blue[*Pisang **emas** dibawa belayar…*] — a golden banana on a ship  \n"
                    ":orange[*Hutang **emas** boleh dibayar, hutang budi dibawa mati*] — debts of gold "
                    "and of kindness\n\n"
                    "The hint here is the word **emas** (gold) in both parts. Many hints are harder: a "
                    "picture that stands for an idea (*kiasan*), or words that sound alike.\n\n"
                    "The computer mostly checks *\"are these about the same topic?\"* On the surface, the "
                    "picture part and the message part are **usually about different topics** — in real "
                    "pantun **and** in mixed-up ones. The computer can spot a hint only when the same word "
                    "appears (that happens in about 1 in 6 pantun). Understanding a picture-hint needs a "
                    "person who knows pantun.")
        else:
            st.markdown(
                f"💭 The computer only gives an answer like this for about "
                f"**{out_of_ten(1 - test['share_cannot_tell'])}** pantun, and then it is right about "
                f"**{out_of_ten(test['accuracy_when_it_leans'])}** times."
                + (" It often happens when both parts share the same words." if res["lean"] == "belong" else ""))
        # Traditional rules of pantun form (src/criteria.py).
        with st.container(border=True):
            st.markdown("📋 **Pantun rules** — does it follow the traditional rules?")
            core = [c for c in res["criteria"] if not c["name"].startswith("Middle")]
            bonus = [c for c in res["criteria"] if c["name"].startswith("Middle")]
            st.markdown("✅ It has **4 lines**: a picture part and a message part")
            for c in core:
                st.markdown(f"{'✅' if c['passed'] else '❌'} {c['simple']}  \n:gray[{c['detail']}]")
            for c in bonus:
                st.markdown(f"{'⭐' if c['passed'] else '☆'} **Bonus:** {c['simple']}  \n:gray[{c['detail']}]")
            n_ok = 1 + sum(c["passed"] for c in core)
            st.markdown(f"**Follows {n_ok} of {1 + len(core)} rules**"
                        + (" + the bonus ⭐" if bonus and bonus[0]["passed"] else ""))
            st.caption("Rules from Malay literature on pantun. They check the **form**, not how clever "
                       "or beautiful the pantun is.")

        st.info("🎵 The **sound** check is good at spotting rhyme, but a pantun can rhyme and still make no "
                "sense. 💭 The **meaning** check is often unsure, and it can't feel beauty or hidden "
                "meanings. A low score does **not** mean a bad pantun. People who know pantun know best!",
                title="Remember", icon=":material/lightbulb:")
        flag_box("simple", lines, res["scores"], "I don't agree with the computer",
                 "Tell us why (you can leave this empty)")

    st.caption("Want the numbers and charts? Choose **Advanced** at the top.")
    st.stop()


# =====================================================================
# ADVANCED VIEW
# =====================================================================
st.title("Pantun connection checker", anchor=False)
st.markdown(
    "A pantun has two halves: the **pembayang** (lines 1–2, the image) and the **maksud** "
    "(lines 3–4, the message). How closely do sentence-embedding models think the halves are "
    f"connected? Compared against **{len(load_corpus()):,} published pantun** from 13 books."
)

tab_try, tab_found, tab_about = st.tabs(
    [":material/edit_note: Try a pantun", ":material/insights: What we found", ":material/info: About"])


# ---------- tab 1: try a pantun ----------

with tab_try:
    with st.container(horizontal=True, vertical_alignment="center"):
        st.caption("Examples:")
        example_buttons("advanced", "tertiary")

    st.text_area("Your pantun (4 lines, one per row)", key="text", height=130)
    chosen = st.pills("Models", READY_MODELS, default=READY_MODELS, selection_mode="multi",
                      format_func=lambda s: FRIENDLY[s], key="models") or []

    if st.button("Check connection", type="primary", icon=":material/search:", width="stretch"):
        for problem in run_check(st.session_state["text"], chosen):
            st.warning(problem, icon=":material/rule:")

    res = st.session_state.get("result")
    if res:
        lines, scores, pcts, avg = res["lines"], res["scores"], res["pcts"], res["avg"]
        test = load_calibration()["held_out_test"]

        with st.container(border=True):
            st.caption("Result (calibrated against random pairings)")
            st.subheader(f"{OUTCOMES[res['lean']]['emoji']} {OUTCOMES[res['lean']]['advanced']}", anchor=False)
            with st.container(horizontal=True):
                st.metric("p_real (avg. of selected models)", f"{res['p_avg']:.2f}", border=True,
                          help="How much more common a score like this is among real pantun than among "
                               "random pairings. 0.5 = equally common = no information. "
                               "Leans only outside 0.40–0.60.")
                st.metric("Held-out accuracy", f"{100 * test['accuracy_at_0.5']:.0f}%", border=True,
                          help="Real pantun vs random pairing on pantun not used for the bins (50% = guessing).")
                st.metric("Pantun where it can't tell", f"{100 * test['share_cannot_tell']:.0f}%", border=True)
                st.metric("Accuracy when it leans", f"{100 * test['accuracy_when_it_leans']:.0f}%", border=True)
            st.caption("A low score is not evidence of a mismatch: in the held-out test the models leaned "
                       f"'random pairing' for only {100 * test['random_said_not_belong']:.1f}% of random "
                       "pairings. Accuracy figures are for all three models together.")

        with st.container(border=True):
            left, right = st.columns(2)
            left.caption("Pembayang")
            left.markdown(f"{lines[0]}  \n{lines[1]}")
            right.caption("Maksud")
            right.markdown(f"{lines[2]}  \n{lines[3]}")
        if res["match"]:
            st.caption(f"This pantun is in the corpus: {res['match']}.")

        b = baselines()
        st.subheader("Per-model results", anchor=False)
        rows = [{
            "model": FRIENDLY[s],
            "score": scores[s],
            "p_real": res["p_real"][s],
            "percentile": pcts[s],
            "corpus mean (real)": b.get(s, {}).get("real_mean"),
            "random pairing mean": b.get(s, {}).get("shuffled_mean"),
            "AUC real vs random": b.get(s, {}).get("auc"),
        } for s in scores]
        st.dataframe(pd.DataFrame(rows), hide_index=True, alt="Per-model scores for this pantun",
                     column_config={
                         "score": st.column_config.NumberColumn(format="%.3f", help="Cosine similarity"),
                         "p_real": st.column_config.NumberColumn(
                             format="%.2f", help="0.5 = no information (see calibration in Phase 3, section 8)"),
                         "percentile": st.column_config.ProgressColumn(
                             "percentile among real pantun", min_value=0, max_value=100, format="%.0f",
                             help="Position among real pantun only. NOT evidence of coherence: random "
                                  "pairings land in the same range."),
                         "corpus mean (real)": st.column_config.NumberColumn(format="%.3f"),
                         "random pairing mean": st.column_config.NumberColumn(format="%.3f"),
                         "AUC real vs random": st.column_config.NumberColumn(
                             format="%.3f", help="Phase 3: chance a real pair beats a random pair"),
                     })
        st.caption("Headline = average p_real across the selected models. Raw scores are not "
                   "comparable between models (Model C's scores always sit near 0.85).")

        # Where this pantun sits in the corpus, for one model.
        show = st.segmented_control("Corpus distribution for", list(scores), default=list(scores)[0],
                                    format_func=lambda s: FRIENDLY[s], key="dist_model", required=True)
        counts, edges = np.histogram(load_corpus()[show].to_numpy(), bins=50)
        hist = pd.DataFrame({"start": edges[:-1], "end": edges[1:], "count": counts})
        bars = alt.Chart(hist).mark_bar(color="#86b6ef").encode(
            x=alt.X("start:Q", title=f"{FRIENDLY[show]} score (cosine similarity)"),
            x2="end:Q", y=alt.Y("count:Q", title="number of pantun"),
            tooltip=[alt.Tooltip("start:Q", format=".3f", title="from"),
                     alt.Tooltip("end:Q", format=".3f", title="to"), "count:Q"])
        rule = alt.Chart(pd.DataFrame({"x": [scores[show]], "t": ["this pantun"]})).mark_rule(
            color="#2a78d6", strokeWidth=2).encode(x="x:Q", tooltip=["t:N", alt.Tooltip("x:Q", format=".3f")])
        label = rule.mark_text(align="left", dx=5, dy=-6, color="#2a78d6").encode(y=alt.value(0), text="t:N")
        st.altair_chart((bars + rule + label).properties(height=220),
                        alt=f"Histogram of {FRIENDLY[show]} scores across the corpus, "
                            f"with this pantun at {scores[show]:.3f}")

        st.subheader("Sound link (rhyme)", anchor=False)
        st.dataframe(pd.DataFrame([{"lines": f"{a} & {b}", "ending A": f"-{ea}", "ending B": f"-{eb}",
                                    "match": {1.0: "full rhyme", 0.5: "near rhyme (same final consonant)",
                                              0.0: "none"}[s]} for a, b, ea, eb, s in res["rhyme"]]),
                     hide_index=True, alt="Rhyme between the pembayang and maksud lines")
        methods = load_result_table("methods_comparison.csv")
        rhyme_auc = (methods.loc[methods["method"].str.startswith("sound"), "AUC (random)"].item()
                     if methods is not None else None)
        st.markdown(f"**Sound score: {res['sound']:g} / 10** = 5 × (pair 1–3 + pair 2–4). "
                    + (f"Separates real pantun from random pairings with AUC {rhyme_auc:.2f}, but it "
                       "measures form: a nonsensical pantun that rhymes scores 10." if rhyme_auc else ""))

        st.subheader("Traditional criteria", anchor=False)
        crit = load_result_table("criteria_summary.csv")
        rates = crit.set_index(crit.columns[0])["real pantun (%)"].to_dict() if crit is not None else {}
        st.dataframe(pd.DataFrame([{
            "criterion": c["name"], "this pantun": "yes" if c["passed"] else "no", "detail": c["detail"],
            "real pantun meeting it (%)": rates.get(c["name"]), "source": c["source"],
        } for c in res["criteria"]]), hide_index=True, alt="Traditional pantun criteria for this pantun",
            column_config={"real pantun meeting it (%)": st.column_config.NumberColumn(format="%.0f")})
        st.caption("Rule-based checks of convention and form (src/criteria.py). Middle rhyme is met by only "
                   "about half of real pantun, so it is shown as a bonus in the simple view. The symbolic "
                   "link (perlambangan, kiasan) cannot be checked by rule.")

        words = lambda t: set(re.findall(r"[a-z]+(?:-[a-z]+)*", t.lower()))
        shared = sorted(words(res["pembayang"]) & words(res["maksud"]))
        st.markdown(f"**Shared words between halves:** {', '.join(shared) if shared else 'none'} "
                    f"(Jaccard overlap {word_overlap(res['pembayang'], res['maksud']):.2f}). "
                    "Phase 3 found scores rise with shared words, so a high score may reflect "
                    "repetition rather than meaning.")
        with st.expander("Text sent to the models"):
            st.code(f"pembayang: {res['pembayang']}\nmaksud:    {res['maksud']}", language=None)
            st.caption("Lines are cleaned (spacing, punctuation, OCR look-alike letters) and each half "
                       "is joined as 'line1, line2.' Model C also receives the prefix 'query: '.")

        st.info("Embeddings capture shared words and broad meaning, not rhyme, rhythm, symbolism or "
                "cultural meaning. This is not a judgement of literary quality.",
                title="A rough signal, not a grade", icon=":material/lightbulb:")
        flag_box("advanced", lines, scores, "Disagree? Send this pantun to an expert",
                 "What did the models get wrong? (optional)")


# ---------- tab 2: what we found ----------

with tab_found:
    b = baselines()
    st.subheader("Can the models see the link between pembayang and maksud?", anchor=False)
    st.markdown("**A little, but not reliably.** Each pembayang was also paired with the maksud of a "
                "random other pantun. A model that understood the link would score the real pantun "
                "higher almost every time.")
    if b:
        chart_df = pd.DataFrame({"model": [FRIENDLY[s] for s in READY_MODELS],
                                 "pct": [100 * b[s]["auc"] for s in READY_MODELS]})
        bars = alt.Chart(chart_df).mark_bar(cornerRadiusEnd=4, color="#2a78d6", size=30).encode(
            x=alt.X("pct:Q", title="How often the real pantun scored higher (%)",
                    scale=alt.Scale(domain=[0, 100])),
            y=alt.Y("model:N", title=None, sort=None),
            tooltip=["model:N", alt.Tooltip("pct:Q", format=".0f", title="% of the time")])
        labels = bars.mark_text(align="left", dx=6).encode(text=alt.Text("pct:Q", format=".0f"))
        chance = alt.Chart(pd.DataFrame({"x": [50], "t": ["50% = guessing"]}))
        st.altair_chart(
            (bars + labels + chance.mark_rule(strokeDash=[4, 4], color="gray").encode(x="x:Q")
             + chance.mark_text(align="left", dx=4, dy=-6, color="gray").encode(
                 x="x:Q", y=alt.value(0), text="t:N")).properties(height=160),
            alt="Bar chart: how often each model scores the real pantun above a random pairing")
    test = load_calibration()["held_out_test"]
    st.markdown(
        f"- **For one pantun, the models usually can't tell.** On {test['test_pantun']:,} held-out pantun "
        f"(real vs random pairing) they were right {100 * test['accuracy_at_0.5']:.0f}% of the time; "
        f"for {100 * test['share_cannot_tell']:.0f}% the score gave no clear lean.\n"
        "- Effect sizes are small (Cohen's d 0.14–0.40); significance is guaranteed by n ≈ 11,000.\n"
        "- The best Malay model in the SEA-BED benchmark (e5-large-instruct) ties LaBSE; the "
        "Malaysian Mesolitica model does worse. Language coverage is not the bottleneck.\n"
        "- Scores rise with **shared words and sounds** (e.g. *para-paranya / gara-garanya*); "
        "without shared words the effect shrinks further.\n"
        "- The models **disagree** (Spearman 0.17–0.57).\n"
        "- **Sound is a strong, separate link:** the rhyme rule separates real pantun from random "
        "pairings with AUC 0.99, and it is uncorrelated with every meaning score.\n"
        "- Separation was clearest in the **traditional anthology** (Zainal Abidin Bakar)."
    )

    st.divider()
    st.subheader("Full statistics (Phase 3)", anchor=False)
    tables = [
        ("baseline_summary.csv", "Real vs shuffled: effect sizes and tests",
         "random = partner from the whole corpus; within_collection = partner from the same book. "
         "p-values shown as 0 are below floating-point precision."),
        ("overlap_summary.csv", "Effect of shared words",
         "Spearman correlation of score with word overlap, and the effect using only pantun "
         "with no shared words."),
        ("by_collection.csv", "AUC per book (real vs same-book shuffle)",
         "collection_type describes the book, not each pantun. Exploratory."),
    ]
    for name, heading, note in tables:
        t = load_result_table(name)
        if t is not None:
            st.markdown(f"**{heading}**")
            st.dataframe(t.round(4), hide_index=True, alt=heading)
            st.caption(note)
    st.markdown("**Agreement between models (Spearman)**")
    st.dataframe(load_corpus()[READY_MODELS].corr(method="spearman").round(3),
                 alt="Spearman correlation between model scores")
    for img, cap in [("fig_real_vs_shuffled_hist.png", "Distributions: real vs shuffled"),
                     ("fig_real_vs_shuffled_box.png", "Box plots: real vs shuffled"),
                     ("fig_calibration.png", "Calibration: p_real by score (grey band = can't tell)")]:
        if (RESULTS / img).exists():
            st.image(str(RESULTS / img), caption=cap)
    for name, heading in [("top_pantun.csv", "Highest-scoring pantun (average rank across models)"),
                          ("bottom_pantun.csv", "Lowest-scoring pantun")]:
        t = load_result_table(name)
        if t is not None:
            st.markdown(f"**{heading}**")
            st.dataframe(t, hide_index=True, alt=heading)
    st.caption("Full analysis: notebooks/evaluation.ipynb")


# ---------- tab 3: about ----------

with tab_about:
    st.markdown(
        "**What is this?** A student research project (CSC575) that *measures* how sentence-embedding "
        "models see pantun. It does not write pantun, and it does not judge them.\n\n"
        f"**Data.** {len(load_corpus()):,} pantun empat kerat from 13 published books, e.g. "
        "*Kumpulan Pantun Melayu* (Zainal Abidin Bakar), the *Pantun Pak Nazel* series and "
        "*1010 Pantun Baharu* (Khadijah Hashim). Every pantun keeps its source. No pantun were invented."
    )
    st.subheader("Method", anchor=False)
    st.dataframe(pd.DataFrame([{"model": FRIENDLY[m["short"]], "Hugging Face id": m["name"],
                                "input prefix": m["prefix"] or "(none)"} for m in MODELS]),
                 hide_index=True, alt="Models used")
    st.markdown(
        "- **Score:** cosine similarity of L2-normalised embeddings of pembayang (lines 1–2) and "
        "maksud (lines 3–4).\n"
        "- **Percentile:** position of the score among all real pantun in the corpus, per model.\n"
        "- **Baselines:** each pembayang paired with a random other maksud (whole corpus, and same "
        "book), 10 fixed seeds; never with itself or an identical maksud.\n"
        "- **Statistics:** Cohen's d, AUC, Mann–Whitney U, paired Wilcoxon signed-rank.\n"
        "- **Limits:** models not trained on pantun; no rhyme, rhythm or symbolism.\n"
        "- **Reproduce:** `python -m src.build_corpus` → `python -m src.score` → "
        "`notebooks/evaluation.ipynb`."
    )
    st.subheader("Pantun flagged for expert review", anchor=False)
    flags = pd.read_csv(FLAGS_CSV, keep_default_na=False) if FLAGS_CSV.exists() else None
    if flags is None or flags.empty:
        st.caption("No pantun flagged yet.")
    else:
        st.dataframe(flags, hide_index=True, alt="Pantun flagged for expert review")
        st.download_button("Download flags (CSV)", flags.to_csv(index=False),
                           file_name="expert_review_flags.csv", icon=":material/download:")
