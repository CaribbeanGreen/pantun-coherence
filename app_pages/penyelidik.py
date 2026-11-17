"""Researcher and expert view (business case Section 6.4, Exhibit 5): English, precise, every number shown.

The expert rating form saves to results/expert_ratings.csv — the data for the M3 "meaning-score gate"
(deliverable D2: 300 pantun rated by 3 experts).
"""

import json
from datetime import datetime

import altair as alt
import numpy as np
import pandas as pd
import streamlit as st
from scipy.stats import gaussian_kde

from src.app_core import (DECISIONS_CSV, EXAMPLES, FLAGS_CSV, GOLD, LEAN_ENGLISH, MODEL_BY_SHORT, MODEL_LABEL,
                          RATINGS_CSV, RESULTS, TEAL, analyse, baselines, check_lines, help_button, load_calibration,
                          load_corpus, load_result_table, read_log, reference, ready_models, save_rating,
                          section_label, split_text, tour)
from src.share import current_user, inquiries_for, require_view

require_view("penyelidik")     # researchers / experts (and the owner) only
ME = current_user()

LINK_TYPES = ["Word echo", "Sound echo", "Kiasan", "Same topic", "None"]
st.session_state.setdefault("r_text", "\n".join(EXAMPLES["Pisang emas"]))


def use_example(name):
    st.session_state["r_text"] = "\n".join(EXAMPLES[name])
    st.session_state.pop("r_result", None)


@st.cache_data(show_spinner=False)
def density(model_short):
    """Smoothed score distributions for real pantun and random pairings (one model)."""
    ref = reference()
    real, fake = ref["real_scores"][model_short], ref["fake_scores"][model_short]
    lo, hi = np.percentile(np.r_[real, fake], [0.5, 99.5])
    grid = np.linspace(lo, hi, 200)
    rng = np.random.default_rng(0)
    pick = lambda a: a[rng.choice(len(a), min(4000, len(a)), replace=False)]
    return pd.concat([
        pd.DataFrame({"score": grid, "density": gaussian_kde(pick(real))(grid), "group": "real pantun"}),
        pd.DataFrame({"score": grid, "density": gaussian_kde(pick(fake))(grid), "group": "random pairings"}),
    ])


def expert_form(lines, res, key):
    """Exhibit 5, label 6: rate the link 1-5, choose the link type, agree with the system."""
    with st.container(border=True):
        section_label("Expert review")
        with st.form(f"rate_{key}", border=False):
            rating = st.segmented_control("How strongly does the pembayang prepare the maksud?",
                                          [1, 2, 3, 4, 5], key=f"rate_{key}_n")
            types = st.pills("Type of link", LINK_TYPES, selection_mode="multi", key=f"rate_{key}_t")
            agree = st.segmented_control("Agree with system?", ["Agree", "Disagree", "Unsure"], key=f"rate_{key}_a")
            comment = st.text_area("Comment (optional)", key=f"rate_{key}_c")
            if st.form_submit_button("Save rating", type="primary"):
                if rating is None or agree is None:
                    st.warning("Choose a rating and whether you agree.", icon=":material/rule:")
                else:
                    save_rating(lines, res, rating, types, agree, comment, ME["username"])
                    st.success("Rating saved.", icon=":material/check:")


def form_and_sound(res):
    with st.container(border=True):
        section_label("Form and sound")
        (a1, b1, e1, f1, s1), (a2, b2, e2, f2, s2) = res["rhyme"]
        mark = lambda s: "✔" if s == 1 else ("〰" if s == 0.5 else "✖")
        crit = {c["name"].split(" ")[0]: c for c in res["criteria"]}
        syl = crit["8–12"]["detail"].replace("syllables: ", "").replace(", ", " · ")
        st.markdown(
            f"Rhyme 1–3: **-{e1} / -{f1}** {mark(s1)} · 2–4: **-{e2} / -{f2}** {mark(s2)} → sound `{res['sound']:g}/10`  \n"
            f"Syllables: `{syl}` {'✔' if crit['8–12']['passed'] else '✖'} · middle rhyme "
            f"{'★' if res['bonus'] else '☆'} · nature imagery {'✔' if crit['Pembayang']['passed'] else '✖'}  \n"
            f"Shared words: {', '.join(f'*{w}*' for w in res['shared']) if res['shared'] else 'none'}")


def analysis(res):
    test, b = load_calibration()["held_out_test"], baselines()
    left, right = st.columns([3, 2], gap="medium")
    with left:
        with st.container(border=True):
            section_label("Pantun")
            from src.app_core import pantun_card
            pantun_card(res["lines"], compact=True)
            st.markdown(f"**Overall:** {LEAN_ENGLISH[res['lean']]} · mean p(real) = `{res['p_avg']:.2f}` · "
                        f":gray[{100 * test['share_cannot_tell']:.1f}% of held-out pantun fall in \"can't tell\"]"
                        + (f"  \n:gray[In the corpus: {res['match']}]" if res["match"] else ""))
        with st.container(border=True):
            section_label("Per-model results")
            st.dataframe(pd.DataFrame([{
                "Model": MODEL_LABEL[s], "Cosine": res["scores"][s], "Percentile": res["pcts"][s],
                "p(real)": res["p_real"][s], "Corpus AUC": b.get(s, {}).get("auc")} for s in res["scores"]]),
                hide_index=True, alt="Per-model scores for this pantun",
                column_config={"Cosine": st.column_config.NumberColumn(format="%.2f"),
                               "Percentile": st.column_config.NumberColumn(format="%.0f"),
                               "p(real)": st.column_config.NumberColumn(format="%.2f",
                                                                        help="0.5 = no information"),
                               "Corpus AUC": st.column_config.NumberColumn(format="%.3f",
                                                                           help="Real vs random pairing, Phase 3")})
        with st.container(border=True):
            show = st.segmented_control("Where this pantun sits", list(res["scores"]), default="labse"
                                        if "labse" in res["scores"] else list(res["scores"])[0],
                                        format_func=lambda s: MODEL_LABEL[s], key="r_dist", required=True)
            d = density(show)
            lines_chart = alt.Chart(d).mark_line(strokeWidth=2.5).encode(
                x=alt.X("score:Q", title=f"{MODEL_LABEL[show]} cosine similarity"),
                y=alt.Y("density:Q", title=None, axis=None),
                color=alt.Color("group:N", scale=alt.Scale(domain=["real pantun", "random pairings"],
                                                           range=[TEAL, "#B9BDB8"]),
                                legend=alt.Legend(orient="top", title=None)))
            rule = alt.Chart(pd.DataFrame({"x": [res["scores"][show]], "t": ["this pantun"]})).mark_rule(
                color=GOLD, strokeWidth=3).encode(x="x:Q")
            label = rule.mark_text(align="left", dx=6, dy=-4, color="#8a6a1c").encode(y=alt.value(8), text="t:N")
            st.altair_chart((lines_chart + rule + label).properties(height=200),
                            alt=f"Score distributions of real pantun and random pairings for {MODEL_LABEL[show]}, "
                                f"with this pantun at {res['scores'][show]:.2f}")
    with right:
        form_and_sound(res)
        expert_form(res["lines"], res, "analyse")


# ---- Page ---------------------------------------------------------------------------------------
n_models = len(ready_models())
with st.container(horizontal=True, vertical_alignment="bottom"):
    st.title("Research & Expert Review", anchor=False)
    st.caption(f"Corpus: {len(load_corpus()):,} published pantun · 13 books · {n_models} embedding models")
    help_button("penyelidik", lang="en")

decisions = read_log(DECISIONS_CSV)
queue = []
# Experts (and teachers in expert mode) see the cases lecturers sent on ("Hantar kepada pakar"). Raw student
# inquiries, which carry student names, stay with their teacher; only the owner sees those here too.
if ME["kind"] == "owner":
    inq = inquiries_for(ME)
    queue += [{"from": f"{r.kind} ({r.who or 'anonymous'})",
               "time": datetime.fromtimestamp(r.time).isoformat(timespec="seconds"),
               "lines": [r.line1, r.line2, r.line3, r.line4], "note": r.comment} for r in inq.itertuples()]
if not decisions.empty:
    queue += [{"from": f"instructor · {r._2} · {r.student}", "time": r.timestamp,
               "lines": [r.line1, r.line2, r.line3, r.line4], "note": r.note}
              for r in decisions.itertuples() if r.action == "pakar"]
rated = read_log(RATINGS_CSV)
rated_keys = set() if rated.empty else {tuple(x) for x in rated[["line1", "line2", "line3", "line4"]].values}
open_items = [q for q in queue if tuple(q["lines"]) not in rated_keys]

tab_a, tab_f, tab_q, tab_m = st.tabs(["Analyse a pantun", "Findings", f"Expert queue ({len(open_items)})", "Method"])

with tab_a:
    with st.container(horizontal=True, vertical_alignment="center"):
        st.caption("Examples:")
        for name in EXAMPLES:
            st.button(name, key=f"r_ex_{name}", type="tertiary", on_click=use_example, args=(name,))
    with st.container(key="r_input"):
        st.text_area("Pantun (4 lines, one per row)", key="r_text", height=120)
    if st.button("Analyse", key="r_go", type="primary", icon=":material/search:"):
        lines, problems = check_lines(split_text(st.session_state["r_text"]), malay=False)
        st.session_state.pop("r_result", None)
        for p in problems:
            st.warning(p, icon=":material/rule:")
        if not problems:
            with st.spinner("Scoring with all models (about a minute the first time)…"):
                st.session_state["r_result"] = analyse(lines)
    if st.session_state.get("r_result"):
        analysis(st.session_state["r_result"])

with tab_f:
    test = load_calibration()["held_out_test"]
    with st.container(horizontal=True):
        st.metric("Rhyme rule AUC", "0.99", border=True, help="Real vs random pairings, all 10,907 pantun")
        st.metric("Best embedding AUC", "0.60", border=True, help="LaBSE and e5-large-instruct")
        st.metric("Held-out accuracy (all models)", f"{100 * test['accuracy_at_0.5']:.0f}%", border=True)
        st.metric("\"Can't tell\"", f"{100 * test['share_cannot_tell']:.1f}%", border=True)
        st.metric("Right when it leans", f"{100 * test['accuracy_when_it_leans']:.0f}%", border=True)
    for name, heading in [("methods_comparison.csv", "Methods compared (AUC, real vs fake)"),
                          ("baseline_summary.csv", "Real vs shuffled: effect sizes and tests"),
                          ("criteria_summary.csv", "Traditional criteria: share of pantun meeting each"),
                          ("overlap_summary.csv", "Effect of shared words"),
                          ("by_collection.csv", "AUC per book (real vs same-book shuffle)")]:
        t = load_result_table(name)
        if t is not None:
            st.markdown(f"**{heading}**")
            st.dataframe(t.round(4) if hasattr(t, "round") else t, hide_index=True, alt=heading)
    judges = []
    for label, file in [("Gemma 4 12B (local)", "gemma_judge.json"), ("Gemini 3.8 Flash (interim)", "gemini_judge.json")]:
        p = RESULTS / file
        if p.exists():
            j = json.load(open(p, encoding="utf-8"))
            judges.append({"AI judge": label, "items": j["items_scored"], "AUC": j["auc"]["gemini_score"],
                           "95% low": j["auc_ci95"]["gemini_score"][0], "95% high": j["auc_ci95"]["gemini_score"][1]})
    if judges:
        st.markdown("**AI judges vs perfectly rhyming fakes**")
        st.dataframe(pd.DataFrame(judges).round(3), hide_index=True, alt="AI judge results")
    for img, cap in [("fig_real_vs_shuffled_hist.png", "Distributions: real vs shuffled"),
                     ("fig_calibration.png", "Calibration: p(real) by score (grey band = can't tell)")]:
        if (RESULTS / img).exists():
            st.image(str(RESULTS / img), caption=cap)
    st.caption("Full analysis: notebooks/evaluation.ipynb")

with tab_q:
    if not open_items:
        st.info("No pantun waiting for an expert. Students and instructors can send pantun here.",
                icon=":material/inbox:")
    else:
        qdf = pd.DataFrame([{"From": q["from"], "Time": q["time"], "Line 1": q["lines"][0],
                             "Line 3": q["lines"][2], "Note": q["note"]} for q in open_items])
        ev = st.dataframe(qdf, hide_index=True, on_select="rerun", selection_mode="single-row", key="r_queue",
                          alt="Pantun waiting for expert review")
        sel = ev.selection.rows if ev and ev.selection else []
        if sel:
            item = open_items[sel[0]]
            lines, problems = check_lines(item["lines"], malay=False)
            if problems:
                st.warning("; ".join(problems))
            else:
                with st.spinner("Scoring…"):
                    analysis(analyse(lines))
    if not rated.empty:
        st.markdown(f"**Ratings saved: {len(rated)}** (target for the M3 gate: 300 pantun × 3 experts)")
        st.download_button("Download ratings (CSV)", rated.to_csv(index=False).encode("utf-8-sig"),
                           file_name="expert_ratings.csv", icon=":material/download:")

with tab_m:
    st.dataframe(pd.DataFrame([{"Model": MODEL_LABEL[m["short"]], "Hugging Face id": m["name"],
                                "Input prefix": m["prefix"].replace("\n", " ") or "(none)"} for m in MODEL_BY_SHORT.values()]),
                 hide_index=True, alt="Models used")
    st.markdown(
        "- **Sound:** end rhyme a-b-a-b, lines 1–3 and 2–4: full rhyme 1, same final consonant 0.5 → ×5 = 0–10.\n"
        "- **Meaning:** cosine similarity of L2-normalised embeddings of pembayang and maksud per model; "
        "calibrated to p(real) with 20 score bins (real vs random pairings); averaged across models. "
        "Leans only outside 0.40–0.60.\n"
        "- **Rules:** 4 lines, 8–12 syllables, end rhyme, nature imagery (+ middle-rhyme bonus), from Malay "
        "literature (docs/related_work.md).\n"
        "- **Honesty:** the scores are not a judgement of literary quality; the analogical link (kiasan) is not "
        "measured by any method we tested.\n"
        "- **Reproduce:** `python -m src.build_corpus` → `python -m src.score` → `notebooks/evaluation.ipynb`.")

tour("penyelidik", [
    (".st-key-r_input", "Analyse a pantun 🔬", "Paste 4 lines or pick an example, then press <b>Analyse</b>."),
    (".st-key-r_go", "Every number shown 📊",
     "Overall result, <b>per-model scores</b>, where the pantun sits in the corpus, and the form and sound checks."),
    ("[role='tablist']", "Findings, queue and method 🗂️",
     "<b>Findings</b>: the full evaluation. <b>Expert queue</b>: pantun sent by students and instructors. "
     "<b>Method</b>: models and rules."),
    (".st-key-help_penyelidik", "Tutorial video ▶️", "Press <b>How to use</b> any time to watch the video."),
], lang="en")
