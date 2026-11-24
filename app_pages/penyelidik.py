"""Researcher and expert view, "Penyelidik & Pakar / Researcher & Expert" (business case Section 6.4, Exhibit 5):
precise, every number shown. Text follows the visitor's language (src/lang.py); expert ratings are saved with the
English words (Agree, Word echo, ...) whatever language the expert reads, so the CSV stays comparable.

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

from src import illus
from src.app_core import (DECISIONS_CSV, EXAMPLES, FLAGS_CSV, GOLD, LEAN_ENGLISH, MODEL_BY_SHORT, MODEL_LABEL,
                          RATINGS_CSV, RESULTS, TEAL, analyse, baselines, check_lines, help_button, load_calibration,
                          load_corpus, load_result_table, read_log, reference, ready_models, save_rating,
                          section_label, split_text, tour, example_name)
from src.lang import role, tr
from src.share import current_user, inquiries_for, require_view

require_view("penyelidik")     # researchers / experts (and the owner) only
ME = current_user()

LINK_TYPES = ["Word echo", "Sound echo", "Kiasan", "Same topic", "None"]
AGREE = ["Agree", "Disagree", "Unsure"]
# Malay for the saved English words above (what a Malay reader sees).
MALAY = {"Word echo": "Gema perkataan", "Sound echo": "Gema bunyi", "Kiasan": "Kiasan", "Same topic": "Topik sama",
         "None": "Tiada", "Agree": "Setuju", "Disagree": "Tidak setuju", "Unsure": "Tidak pasti"}
LEAN_MS = {"belong": "condong sebenar", "cannot_tell": "tidak pasti", "not_belong": "condong tidak sepadan"}


def shown(word):
    return tr(MALAY.get(word, word), word)
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
        pd.DataFrame({"score": grid, "density": gaussian_kde(pick(real))(grid), "group": "real"}),
        pd.DataFrame({"score": grid, "density": gaussian_kde(pick(fake))(grid), "group": "random"}),
    ])


def expert_form(lines, res, key):
    """Exhibit 5, label 6: rate the link 1-5, choose the link type, agree with the system."""
    with st.container(border=True):
        section_label(tr("Penilaian pakar", "Expert review"))
        with st.form(f"rate_{key}", border=False):
            rating = st.segmented_control(tr("Sejauh mana pembayang menyediakan maksud?",
                                             "How strongly does the pembayang prepare the maksud?"),
                                          [1, 2, 3, 4, 5], key=f"rate_{key}_n")
            types = st.pills(tr("Jenis kaitan", "Type of link"), LINK_TYPES, selection_mode="multi", key=f"rate_{key}_t",
                             format_func=shown)
            agree = st.segmented_control(tr("Setuju dengan sistem?", "Agree with system?"), AGREE, key=f"rate_{key}_a",
                                         format_func=shown)
            comment = st.text_area(tr("Komen (pilihan)", "Comment (optional)"), key=f"rate_{key}_c")
            if st.form_submit_button(tr("Simpan penilaian", "Save rating"), type="primary"):
                if rating is None or agree is None:
                    st.warning(tr("Pilih penilaian dan sama ada anda setuju.", "Choose a rating and whether you agree."),
                               icon=":material/rule:")
                else:
                    save_rating(lines, res, rating, types, agree, comment, ME["username"])
                    st.success(tr("Penilaian disimpan.", "Rating saved."), icon=":material/check:")


def form_and_sound(res):
    with st.container(border=True):
        section_label(tr("Bentuk dan bunyi", "Form and sound"))
        (a1, b1, e1, f1, s1), (a2, b2, e2, f2, s2) = res["rhyme"]
        mark = lambda s: "✔" if s == 1 else ("〰" if s == 0.5 else "✖")
        crit = {c["name"].split(" ")[0]: c for c in res["criteria"]}
        syl = crit["8–12"]["detail"].replace("syllables: ", "").replace(", ", " · ")
        words = ", ".join(f"*{w}*" for w in res["shared"]) if res["shared"] else tr("tiada", "none")
        syl_ok, nature_ok = "✔" if crit["8–12"]["passed"] else "✖", "✔" if crit["Pembayang"]["passed"] else "✖"
        st.markdown(
            tr("Rima", "Rhyme") + f" 1–3: **-{e1} / -{f1}** {mark(s1)} · 2–4: **-{e2} / -{f2}** {mark(s2)} → "
            + tr("bunyi", "sound") + f" `{res['sound']:g}/10`  \n"
            + tr("Suku kata", "Syllables") + f": `{syl}` {syl_ok} · " + tr("rima tengah", "middle rhyme")
            + f" {'★' if res['bonus'] else '☆'} · " + tr("unsur alam", "nature imagery") + f" {nature_ok}  \n"
            + tr("Perkataan dikongsi", "Shared words") + f": {words}")


def analysis(res):
    test, b = load_calibration()["held_out_test"], baselines()
    left, right = st.columns([3, 2], gap="medium")
    with left:
        with st.container(border=True):
            section_label("Pantun")
            from src.app_core import pantun_card
            pantun_card(res["lines"], compact=True)
            unsure = 100 * test["share_cannot_tell"]
            st.markdown(tr(f"**Keseluruhan:** {LEAN_MS[res['lean']]} · purata p(real) = `{res['p_avg']:.2f}` · "
                           f":gray[{unsure:.1f}% pantun ujian luar sampel jatuh dalam \"tidak pasti\"]",
                           f"**Overall:** {LEAN_ENGLISH[res['lean']]} · mean p(real) = `{res['p_avg']:.2f}` · "
                           f":gray[{unsure:.1f}% of held-out pantun fall in \"can't tell\"]")
                        + (f"  \n:gray[{tr('Dalam korpus', 'In the corpus')}: {res['match']}]" if res["match"] else ""))
        with st.container(border=True):
            section_label(tr("Keputusan setiap model", "Per-model results"))
            st.dataframe(pd.DataFrame([{
                "Model": MODEL_LABEL[s], "Cosine": res["scores"][s], "Percentile": res["pcts"][s],
                "p(real)": res["p_real"][s], "Corpus AUC": b.get(s, {}).get("auc")} for s in res["scores"]]),
                hide_index=True, alt=tr("Skor setiap model untuk pantun ini", "Per-model scores for this pantun"),
                column_config={"Cosine": st.column_config.NumberColumn(format="%.2f"),
                               "Percentile": st.column_config.NumberColumn(format="%.0f"),
                               "p(real)": st.column_config.NumberColumn(format="%.2f",
                                                                        help=tr("0.5 = tiada maklumat",
                                                                                "0.5 = no information")),
                               "Corpus AUC": st.column_config.NumberColumn(format="%.3f",
                                                                           help=tr("Sebenar lawan pasangan rawak, Fasa 3",
                                                                                   "Real vs random pairing, Phase 3"))})
        with st.container(border=True):
            show = st.segmented_control(tr("Kedudukan pantun ini", "Where this pantun sits"), list(res["scores"]), default="labse"
                                        if "labse" in res["scores"] else list(res["scores"])[0],
                                        format_func=lambda s: MODEL_LABEL[s], key="r_dist", required=True)
            groups = {"real": tr("pantun sebenar", "real pantun"), "random": tr("pasangan rawak", "random pairings")}
            d = density(show).assign(group=lambda f: f["group"].map(groups))
            lines_chart = alt.Chart(d).mark_line(strokeWidth=2.5).encode(
                x=alt.X("score:Q", title=tr(f"Keserupaan kosinus {MODEL_LABEL[show]}",
                                            f"{MODEL_LABEL[show]} cosine similarity")),
                y=alt.Y("density:Q", title=None, axis=None),
                color=alt.Color("group:N", scale=alt.Scale(domain=list(groups.values()),
                                                           range=[TEAL, "#B9BDB8"]),
                                legend=alt.Legend(orient="top", title=None)))
            rule = alt.Chart(pd.DataFrame({"x": [res["scores"][show]],
                                           "t": [tr("pantun ini", "this pantun")]})).mark_rule(
                color=GOLD, strokeWidth=3).encode(x="x:Q")
            label = rule.mark_text(align="left", dx=6, dy=-4, color="#8a6a1c").encode(y=alt.value(8), text="t:N")
            st.altair_chart((lines_chart + rule + label).properties(height=200),
                            alt=tr(f"Taburan skor pantun sebenar dan pasangan rawak untuk {MODEL_LABEL[show]}, "
                                   f"dengan pantun ini pada {res['scores'][show]:.2f}",
                                   f"Score distributions of real pantun and random pairings for {MODEL_LABEL[show]}, "
                                   f"with this pantun at {res['scores'][show]:.2f}"))
    with right:
        form_and_sound(res)
        expert_form(res["lines"], res, "analyse")


# ---- Page ---------------------------------------------------------------------------------------
n_models = len(ready_models())
with st.container(horizontal=True, vertical_alignment="bottom"):
    st.title(tr("Penyelidikan & Penilaian Pakar", "Research & Expert Review"), anchor=False)
    st.caption(tr(f"Korpus: {len(load_corpus()):,} pantun terbitan · 13 buku · {n_models} model pembenaman",
                  f"Corpus: {len(load_corpus()):,} published pantun · 13 books · {n_models} embedding models"))
    help_button("penyelidik")

decisions = read_log(DECISIONS_CSV)
queue = []
# Experts (and teachers in expert mode) see the cases teachers sent on ("Hantar kepada pakar"). Raw pupil
# inquiries, which carry pupil names, stay with their teacher; only the owner sees those here too.
if ME["kind"] == "owner":
    inq = inquiries_for(ME)
    queue += [{"from": f"{r.kind} ({r.who or tr('tanpa nama', 'anonymous')})",
               "time": datetime.fromtimestamp(r.time).isoformat(timespec="seconds"),
               "lines": [r.line1, r.line2, r.line3, r.line4], "note": r.comment} for r in inq.itertuples()]
if not decisions.empty:
    queue += [{"from": f"{role('pensyarah').lower()} · {r._2} · {r.student}", "time": r.timestamp,
               "lines": [r.line1, r.line2, r.line3, r.line4], "note": r.note}
              for r in decisions.itertuples() if r.action == "pakar"]
rated = read_log(RATINGS_CSV)
rated_keys = set() if rated.empty else {tuple(x) for x in rated[["line1", "line2", "line3", "line4"]].values}
open_items = [q for q in queue if tuple(q["lines"]) not in rated_keys]

tab_a, tab_f, tab_q, tab_m = st.tabs([tr("Analisis pantun", "Analyse a pantun"), tr("Dapatan", "Findings"),
                                      tr(f"Barisan pakar ({len(open_items)})", f"Expert queue ({len(open_items)})"),
                                      tr("Kaedah", "Method")])

with tab_a:
    illus.stage("analyse", tr("Analisis Pantun", "Analyse a Pantun"),
                tr("Setiap model, setiap nombor, secara terbuka.", "Every model, every number, in the open."),
                tr("Makmal penyelidikan", "Research lab"))
    with st.container(horizontal=True, vertical_alignment="center"):
        st.caption(tr("Contoh:", "Examples:"))
        for name in EXAMPLES:
            st.button(example_name(name), key=f"r_ex_{name}", type="tertiary", on_click=use_example, args=(name,))
    with st.container(key="r_input"):
        st.text_area(tr("Pantun (4 baris, satu setiap baris)", "Pantun (4 lines, one per row)"), key="r_text", height=120)
    if st.button(tr("Analisis", "Analyse"), key="r_go", type="primary", icon=":material/search:"):
        lines, problems = check_lines(split_text(st.session_state["r_text"]))
        st.session_state.pop("r_result", None)
        for p in problems:
            st.warning(p, icon=":material/rule:")
        if not problems:
            with st.spinner(tr("Menilai dengan semua model (kira-kira seminit pada kali pertama)…",
                               "Scoring with all models (about a minute the first time)…")):
                st.session_state["r_result"] = analyse(lines)
    if st.session_state.get("r_result"):
        analysis(st.session_state["r_result"])

with tab_f:
    illus.stage("findings", tr("Dapatan", "Findings"),
                tr("Penilaian penuh di sebalik skor.", "The full evaluation behind the scores."),
                tr("Apa yang kami pelajari", "What we learned"))
    test = load_calibration()["held_out_test"]
    with st.container(horizontal=True):
        st.metric(tr("AUC peraturan rima", "Rhyme rule AUC"), "0.99", border=True,
                  help=tr("Sebenar lawan pasangan rawak, kesemua 10,907 pantun", "Real vs random pairings, all 10,907 pantun"))
        st.metric(tr("AUC pembenaman terbaik", "Best embedding AUC"), "0.60", border=True,
                  help=tr("LaBSE dan e5-large-instruct", "LaBSE and e5-large-instruct"))
        st.metric(tr("Ketepatan luar sampel (semua model)", "Held-out accuracy (all models)"),
                  f"{100 * test['accuracy_at_0.5']:.0f}%", border=True)
        st.metric(tr("\"Tidak pasti\"", "\"Can't tell\""), f"{100 * test['share_cannot_tell']:.1f}%", border=True)
        st.metric(tr("Betul apabila condong", "Right when it leans"), f"{100 * test['accuracy_when_it_leans']:.0f}%",
                  border=True)
    if tr("ms", "en") == "ms":
        st.caption("Jadual di bawah dalam Bahasa Inggeris, seperti dalam fail hasil penyelidikan.")
    for name, heading in [("methods_comparison.csv", tr("Perbandingan kaedah (AUC, sebenar lawan palsu)",
                                                        "Methods compared (AUC, real vs fake)")),
                          ("baseline_summary.csv", tr("Sebenar lawan dikocok: saiz kesan dan ujian",
                                                      "Real vs shuffled: effect sizes and tests")),
                          ("criteria_summary.csv", tr("Kriteria tradisional: peratus pantun yang memenuhi setiap satu",
                                                      "Traditional criteria: share of pantun meeting each")),
                          ("overlap_summary.csv", tr("Kesan perkataan dikongsi", "Effect of shared words")),
                          ("by_collection.csv", tr("AUC setiap buku (sebenar lawan dikocok dalam buku yang sama)",
                                                   "AUC per book (real vs same-book shuffle)"))]:
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
        st.markdown(tr("**Hakim AI lawan pantun palsu yang berima sempurna**", "**AI judges vs perfectly rhyming fakes**"))
        st.dataframe(pd.DataFrame(judges).round(3), hide_index=True, alt=tr("Keputusan hakim AI", "AI judge results"))
    for img, cap in [("fig_real_vs_shuffled_hist.png", tr("Taburan: sebenar lawan dikocok", "Distributions: real vs shuffled")),
                     ("fig_calibration.png", tr("Kalibrasi: p(real) mengikut skor (jalur kelabu = tidak pasti)",
                                                "Calibration: p(real) by score (grey band = can't tell)"))]:
        if (RESULTS / img).exists():
            st.image(str(RESULTS / img), caption=cap)
    st.caption(tr("Analisis penuh: notebooks/evaluation.ipynb", "Full analysis: notebooks/evaluation.ipynb"))

with tab_q:
    illus.stage("queue", tr("Barisan Pakar", "Expert Queue"),
                tr("Pantun sukar yang dihantar oleh cikgu untuk disemak.", "Difficult pantun that teachers sent for review."),
                tr("Untuk pakar", "For experts"))
    if not open_items:
        st.info(tr("Tiada pantun menunggu pakar. Cikgu menghantar kes sukar ke sini.",
                   "No pantun waiting for an expert. Teachers send difficult cases here."),
                icon=":material/inbox:")
    else:
        qdf = pd.DataFrame([{tr("Daripada", "From"): q["from"], tr("Masa", "Time"): q["time"],
                             tr("Baris 1", "Line 1"): q["lines"][0], tr("Baris 3", "Line 3"): q["lines"][2],
                             tr("Catatan", "Note"): q["note"]} for q in open_items])
        ev = st.dataframe(qdf, hide_index=True, on_select="rerun", selection_mode="single-row", key="r_queue",
                          alt=tr("Pantun menunggu penilaian pakar", "Pantun waiting for expert review"))
        sel = ev.selection.rows if ev and ev.selection else []
        if sel:
            item = open_items[sel[0]]
            lines, problems = check_lines(item["lines"])
            if problems:
                st.warning("; ".join(problems))
            else:
                with st.spinner(tr("Menilai…", "Scoring…")):
                    analysis(analyse(lines))
    if not rated.empty:
        st.markdown(tr(f"**Penilaian disimpan: {len(rated)}** (sasaran get M3: 300 pantun × 3 pakar)",
                       f"**Ratings saved: {len(rated)}** (target for the M3 gate: 300 pantun × 3 experts)"))
        st.download_button(tr("Muat turun penilaian (CSV)", "Download ratings (CSV)"), rated.to_csv(index=False).encode("utf-8-sig"),
                           file_name="expert_ratings.csv", icon=":material/download:")

with tab_m:
    illus.stage("method", tr("Kaedah", "Method"), tr("Model dan peraturan, langkah demi langkah.",
                                                     "The models and rules, step by step."),
                tr("Cara ia berfungsi", "How it works"))
    st.dataframe(pd.DataFrame([{"Model": MODEL_LABEL[m["short"]], "Hugging Face id": m["name"],
                                tr("Awalan input", "Input prefix"): m["prefix"].replace("\n", " ") or tr("(tiada)", "(none)")}
                               for m in MODEL_BY_SHORT.values()]),
                 hide_index=True, alt=tr("Model yang digunakan", "Models used"))
    st.markdown(tr(
        "- **Bunyi:** rima akhir a-b-a-b, baris 1–3 dan 2–4: rima penuh 1, konsonan akhir sama 0.5 → ×5 = 0–10.\n"
        "- **Makna:** keserupaan kosinus pembenaman ternormal-L2 bagi pembayang dan maksud untuk setiap model; "
        "dikalibrasi kepada p(real) dengan 20 bin skor (sebenar lawan pasangan rawak); dipuratakan merentas model. "
        "Hanya condong di luar 0.40–0.60.\n"
        "- **Peraturan:** 4 baris, 8–12 suku kata, rima akhir, unsur alam (+ bonus rima tengah), daripada kesusasteraan "
        "Melayu (docs/related_work.md).\n"
        "- **Kejujuran:** skor bukan penilaian mutu sastera; kaitan kiasan tidak diukur oleh mana-mana kaedah yang "
        "kami uji.\n"
        "- **Ulang semula:** `python -m src.build_corpus` → `python -m src.score` → `notebooks/evaluation.ipynb`.",
        "- **Sound:** end rhyme a-b-a-b, lines 1–3 and 2–4: full rhyme 1, same final consonant 0.5 → ×5 = 0–10.\n"
        "- **Meaning:** cosine similarity of L2-normalised embeddings of pembayang and maksud per model; "
        "calibrated to p(real) with 20 score bins (real vs random pairings); averaged across models. "
        "Leans only outside 0.40–0.60.\n"
        "- **Rules:** 4 lines, 8–12 syllables, end rhyme, nature imagery (+ middle-rhyme bonus), from Malay "
        "literature (docs/related_work.md).\n"
        "- **Honesty:** the scores are not a judgement of literary quality; the analogical link (kiasan) is not "
        "measured by any method we tested.\n"
        "- **Reproduce:** `python -m src.build_corpus` → `python -m src.score` → `notebooks/evaluation.ipynb`."))

pic = lambda name: f" <img class=cz-i alt src=/app/static/i/{name}.png>"
ANALYSE_TAB = ("[data-testid='stMain'] [role='tab']", 0)   # steps on the first tab: the tour opens it
tour("penyelidik", [
    (".st-key-r_input", tr("Analisis pantun", "Analyse a pantun") + pic("microscope"),
     tr("Tampal 4 baris atau pilih contoh, kemudian tekan <b>Analisis</b>.",
        "Paste 4 lines or pick an example, then press <b>Analyse</b>."), ANALYSE_TAB),
    (".st-key-r_go", tr("Setiap nombor ditunjuk", "Every number shown") + pic("chart"),
     tr("Keputusan keseluruhan, <b>skor setiap model</b>, kedudukan pantun dalam korpus, dan semakan bentuk dan bunyi.",
        "Overall result, <b>per-model scores</b>, where the pantun sits in the corpus, and the form and sound checks."),
     ANALYSE_TAB),
    ("[role='tablist']", tr("Dapatan, barisan dan kaedah", "Findings, queue and method") + pic("folder"),
     tr("<b>Dapatan</b>: penilaian penuh. <b>Barisan pakar</b>: pantun yang dihantar cikgu untuk disemak. "
        "<b>Kaedah</b>: model dan peraturan.",
        "<b>Findings</b>: the full evaluation. <b>Expert queue</b>: pantun teachers sent on for review. "
        "<b>Method</b>: models and rules.")),
    (".st-key-help_penyelidik", tr("Video tutorial", "Tutorial video") + pic("play"),
     tr("Tekan <b>Cara guna</b> bila-bila masa untuk menonton video.", "Press <b>How to use</b> any time to watch the video.")),
])
