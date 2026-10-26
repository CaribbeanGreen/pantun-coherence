import sys
import nbformat as nbf

nb = nbf.v4.new_notebook()
cells = []
md = lambda s: cells.append(nbf.v4.new_markdown_cell(s.strip()))
code = lambda s: cells.append(nbf.v4.new_code_cell(s.strip()))

md("""
# Phase 3 — Evaluation: do real pembayang–maksud pairs score higher than random pairs?

The coherence score (Phase 2) is the cosine similarity between the embedding of the
pembayang (lines 1–2) and the maksud (lines 3–4). A score on its own means little, so
we compare it with **shuffled baselines**: the same pembayang paired with the maksud
of a *different* pantun.

* **random** — partner drawn from the whole corpus
* **within_collection** — partner drawn from the *same book* (same author, style and
  topics), a harder and fairer comparison

Each baseline is repeated with 10 fixed seeds, so results are reproducible.
Helper code is in `src/evaluate.py`.
""")

code("""
import os, sys
from pathlib import Path
# Run from the project root so "src" can be imported and paths match.
if Path.cwd().name == "notebooks":
    os.chdir("..")
sys.path.insert(0, str(Path.cwd()))

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy import stats
from src.evaluate import (MODELS, load_scores, load_embeddings, shuffled_scores,
                          compare, word_overlap, N_SHUFFLES)

pd.set_option("display.max_colwidth", 120)
pd.set_option("display.float_format", "{:.3f}".format)
RESULTS = Path("results")

# Chart style: thin marks, light recessive grid. Colours = validated categorical slots 1-3.
COLORS = {"real": "#2a78d6", "random": "#eb6834", "within_collection": "#1baf7a"}
plt.rcParams.update({"axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.color": "#e5e5e5", "grid.linewidth": 0.6,
                     "axes.edgecolor": "#999999", "font.size": 10, "figure.dpi": 110})
MODEL_NAMES = [m["short"] for m in MODELS]
""")

md("## 1. The real scores")
code("""
df = load_scores()
print(f"{len(df)} pantun, labels: {df['label'].value_counts().to_dict()}")
df[MODEL_NAMES].describe()
""")

md("""
## 2. Real vs shuffled
For every model and baseline: mean difference, Cohen's *d* (0.2 small, 0.5 medium,
0.8 large), AUC (chance a real pair beats a shuffled pair; 0.5 = no difference),
a Mann–Whitney U test, and a **paired** Wilcoxon test (each pantun's real score vs the
mean of its own shuffled scores). With ~11,000 pantun almost any difference is
"significant", so read the effect sizes first.
""")
code("""
real_only = df[df["label"] == "real"].reset_index(drop=True)
shuffled = {}   # (model, baseline) -> array (N_SHUFFLES, n)
rows = []
for m in MODEL_NAMES:
    emb_p, emb_m = load_embeddings(m, df["id"])
    keep = (df["label"] == "real").to_numpy()
    emb_p, emb_m = emb_p[keep], emb_m[keep]
    real = real_only[m].to_numpy()
    for baseline, groups in [("random", None), ("within_collection", real_only["collection"])]:
        sh = shuffled_scores(emb_p, emb_m, real_only["maksud"], groups)
        shuffled[(m, baseline)] = sh
        rows.append({"model": m, "baseline": baseline, **compare(real, sh)})

summary = pd.DataFrame(rows)
summary.to_csv(RESULTS / "baseline_summary.csv", index=False)
summary.style.format({"mannwhitney_p": "{:.1e}", "wilcoxon_paired_p": "{:.1e}"}, precision=3)
""")

md("### Distributions")
code("""
fig, axes = plt.subplots(1, len(MODEL_NAMES), figsize=(3.3 * len(MODEL_NAMES), 3.4))
for ax, m in zip(axes, MODEL_NAMES):
    series = [("real", real_only[m].to_numpy()),
              ("random", shuffled[(m, "random")].ravel()),
              ("within_collection", shuffled[(m, "within_collection")].ravel())]
    # Each model gets its own x-range: e5 scores sit in a narrow band near 0.85,
    # so raw scores are only comparable WITHIN a model, not between models.
    lo, hi = np.percentile(np.concatenate([v for _, v in series]), [0.2, 99.8])
    bins = np.linspace(lo, hi, 60)
    for name, values in series:
        ax.hist(values, bins=bins, density=True, histtype="step", linewidth=2,
                color=COLORS[name], label=name.replace("_", " "))
    ax.set_title(m, loc="left")
    ax.set_xlabel("cosine similarity")
axes[0].set_ylabel("density")
axes[0].legend(frameon=False, loc="upper right")
fig.suptitle("Real pembayang–maksud pairs vs shuffled pairs (x-axis differs per model)", x=0.01, ha="left")
fig.tight_layout()
fig.savefig(RESULTS / "fig_real_vs_shuffled_hist.png", bbox_inches="tight")
plt.show()
""")
code("""
fig, axes = plt.subplots(1, len(MODEL_NAMES), figsize=(3.0 * len(MODEL_NAMES), 3.4))
for ax, m in zip(axes, MODEL_NAMES):
    names = ["real", "random", "within_collection"]
    data = [real_only[m].to_numpy() if n == "real" else shuffled[(m, n)].ravel() for n in names]
    bp = ax.boxplot(data, widths=0.6, patch_artist=True, showfliers=False,
                    medianprops={"color": "white", "linewidth": 2})
    for patch, n in zip(bp["boxes"], names):
        patch.set_facecolor(COLORS[n]); patch.set_edgecolor(COLORS[n])
    ax.set_xticks([1, 2, 3], ["real", "random", "same book"])
    ax.set_title(m, loc="left")
axes[0].set_ylabel("cosine similarity")
fig.suptitle("Score distributions, outliers hidden (y-axis differs per model)", x=0.01, ha="left")
fig.tight_layout()
fig.savefig(RESULTS / "fig_real_vs_shuffled_box.png", bbox_inches="tight")
plt.show()
""")

md("""
## 3. Deliberately mismatched pantun (`label == mismatch`)
""")
code("""
mm = df[df["label"] == "mismatch"]
if mm.empty:
    print("No 'mismatch' rows in the corpus - this check was not run.")
else:
    for m in MODEL_NAMES:
        u, p = stats.mannwhitneyu(real_only[m], mm[m], alternative="greater")
        print(f"{m}: real mean {real_only[m].mean():.3f} vs mismatch mean {mm[m].mean():.3f}, "
              f"Mann-Whitney p = {p:.1e}")
""")

md("""
## 4. Do the models agree?
Spearman rank correlation between the models' scores for the same pantun.
Low agreement means "coherence" depends heavily on which model you ask.
""")
code("""
real_only[MODEL_NAMES].corr(method="spearman")
""")

md("""
## 5. Is it just repeated words?
Pantun often repeat words across the two halves (*Pisang **emas** … Hutang **emas** …*).
If the score mostly tracks shared words, it measures repetition rather than meaning.
We (a) correlate the score with word overlap, and (b) redo the real-vs-random comparison
using **only pantun with no shared words at all**.
""")
code("""
real_only["overlap"] = [word_overlap(p, q) for p, q in zip(real_only["pembayang"], real_only["maksud"])]
no_overlap = (real_only["overlap"] == 0).to_numpy()
print(f"Pantun with at least one shared word: {100 * (~no_overlap).mean():.1f}%")

rows = []
for m in MODEL_NAMES:
    rho, _ = stats.spearmanr(real_only["overlap"], real_only[m])
    c = compare(real_only[m].to_numpy()[no_overlap], shuffled[(m, "random")][:, no_overlap])
    rows.append({"model": m, "spearman_score_vs_overlap": rho,
                 "no_overlap_n": int(no_overlap.sum()),
                 "no_overlap_cohens_d": c["cohens_d"], "no_overlap_auc": c["auc"]})
overlap_summary = pd.DataFrame(rows)
overlap_summary.to_csv(RESULTS / "overlap_summary.csv", index=False)
overlap_summary
""")

md("""
## 6. By collection
Effect size (real vs within-collection shuffle) per book. `collection_type` describes the
book, not each pantun, so treat this as exploratory.
""")
code("""
rows = []
for coll, idx in real_only.groupby("collection").groups.items():
    idx = np.asarray(idx)
    row = {"collection": coll, "type": real_only.loc[idx[0], "collection_type"], "n": len(idx)}
    for m in MODEL_NAMES:
        row[f"{m}_auc"] = compare(real_only[m].to_numpy()[idx],
                                  shuffled[(m, "within_collection")][:, idx])["auc"]
    rows.append(row)
by_collection = pd.DataFrame(rows).sort_values("n", ascending=False)
by_collection.to_csv(RESULTS / "by_collection.csv", index=False)
by_collection
""")

md("""
## 7. Highest- and lowest-scoring real pantun
Ranked by the **average rank across all models**, so one model's quirks matter less.
For qualitative discussion: does a high score look like a pantun whose halves really
connect, or only one that repeats words?
""")
code("""
real_only["mean_rank"] = real_only[MODEL_NAMES].rank(pct=True).mean(axis=1)
cols = ["id", "collection", "pembayang", "maksud"] + MODEL_NAMES + ["overlap"]
top = real_only.sort_values("mean_rank", ascending=False).head(15)[cols]
bottom = real_only.sort_values("mean_rank").head(15)[cols]
top.to_csv(RESULTS / "top_pantun.csv", index=False)
bottom.to_csv(RESULTS / "bottom_pantun.csv", index=False)
print("HIGHEST"); display(top)
""")
code("""
print("LOWEST"); display(bottom)
""")

md("""
## 8. Can the score judge ONE pantun?
Sections 2–7 compare *groups*. A user of the demo has *one* pantun, so the fair question is:
*is a score like this more common among real pantun or among random pairings?*

For each model we cut the score range into 20 bins and count how often real and random scores
fall in each bin. `p_real` = how much more common the bin is among real pantun (0.5 = equally
common → **can't tell**). The three models' `p_real` are averaged. Nothing is trained; we only count.

**Honest test:** pantun are split in half at random. Bins are counted on half A and tested on
half B (each real pantun + one random pairing, so 50% is pure guessing). The score only
"leans" when `p_real` is at least 0.10 away from 0.5. The calibration used by the demo is then
counted on **all** pantun and saved to `results/calibration.json`.
""")
code("""
import json
from src.evaluate import fit_calibration, evaluate_single_pantun, LEAN

real_by_model = {m: real_only[m].to_numpy() for m in MODEL_NAMES}
random_by_model = {m: shuffled[(m, "random")] for m in MODEL_NAMES}
single = evaluate_single_pantun(real_by_model, random_by_model)

calibration = {m: fit_calibration(real_by_model[m], random_by_model[m].ravel()) for m in MODEL_NAMES}
with open(RESULTS / "calibration.json", "w") as f:
    json.dump({"lean_margin": LEAN, "models": calibration, "held_out_test": single}, f, indent=1)

pd.Series(single).to_frame("held-out result")
""")
code("""
# How p_real changes with the score, per model (fitted on all pantun).
fig, axes = plt.subplots(1, len(MODEL_NAMES), figsize=(3.3 * len(MODEL_NAMES), 3.0), sharey=True)
for ax, m in zip(axes, MODEL_NAMES):
    cal = calibration[m]
    edges = np.r_[real_by_model[m].min(), cal["edges"], real_by_model[m].max()]
    centers = (edges[:-1] + edges[1:]) / 2
    ax.axhspan(0.5 - LEAN, 0.5 + LEAN, color="#e5e5e5", zorder=0)
    ax.plot(centers, cal["p_real"], color=COLORS["real"], linewidth=2, marker="o", markersize=4)
    ax.set_title(m, loc="left")
    ax.set_xlabel("score")
    ax.set_ylim(0, 1)
axes[0].set_ylabel("p_real")
axes[0].text(0.02, 0.52, "grey band = can't tell", transform=axes[0].transAxes, fontsize=9, color="#666")
fig.suptitle("Is a score like this more common among real pantun? (0.5 = no information)", x=0.01, ha="left")
fig.tight_layout()
fig.savefig(RESULTS / "fig_calibration.png", bbox_inches="tight")
plt.show()
""")

md("""
## 9. The sound link: rhyme
Pantun halves are tied together by **sound** as well as meaning: lines 1 and 3, and lines 2 and 4,
normally rhyme (a-b-a-b). Embedding models cannot see this, so `src/rhyme.py` measures it with a
simple spelling rule: same end sound = 1, same final consonant with a different vowel = 0.5,
else 0, for each of the two cross-half pairs. **Sound score** = 5 × (pair 1–3 + pair 2–4), from 0 to 10.

This measures *form*. A nonsensical pantun that rhymes gets 10/10, so it must be reported
next to the meaning link, never merged into one "coherence" number.
""")
code("""
from src.rhyme import sound_score
from src.evaluate import shuffled_partner

from src.data_loader import load_pantun
lines_by_id = {p.id: p.lines for p in load_pantun()[0]}   # the 4 cleaned lines of each pantun
lines = [lines_by_id[i] for i in real_only["id"]]
sound_real = np.array([sound_score(l) for l in lines])
sound_shuf = np.array([[sound_score(lines[i][:2] + lines[j][2:]) for i, j in
                        enumerate(shuffled_partner(real_only["maksud"], seed))] for seed in range(N_SHUFFLES)])
real_only["sound"] = sound_real

dist = pd.DataFrame({
    "real pantun (%)": pd.Series(sound_real).value_counts(normalize=True).mul(100),
    "random pairing (%)": pd.Series(sound_shuf.ravel()).value_counts(normalize=True).mul(100),
}).fillna(0).sort_index()
dist.index.name = "sound score"
sound_cmp = compare(sound_real.astype(float), sound_shuf.astype(float))
print(f"AUC real vs random: {sound_cmp['auc']:.3f}   Cohen's d: {sound_cmp['cohens_d']:.2f}")
dist
""")
code("""
# All methods side by side: how well does each separate real pantun from random pairings?
rows = [{"method": f"meaning: {m}", "AUC (random)": summary.query("model == @m and baseline == 'random'")["auc"].item(),
         "AUC (same book)": summary.query("model == @m and baseline == 'within_collection'")["auc"].item()}
        for m in MODEL_NAMES]
sound_same = compare(sound_real.astype(float), np.array([[sound_score(lines[i][:2] + lines[j][2:]) for i, j in
                     enumerate(shuffled_partner(real_only["maksud"], seed, real_only["collection"]))]
                     for seed in range(N_SHUFFLES)]).astype(float))
rows.append({"method": "sound: rhyme rule", "AUC (random)": sound_cmp["auc"], "AUC (same book)": sound_same["auc"]})
rows.append({"method": "meaning: all models, calibrated (held-out)", "AUC (random)": single["auc"], "AUC (same book)": np.nan})
methods = pd.DataFrame(rows)
methods.to_csv(RESULTS / "methods_comparison.csv", index=False)
methods
""")
code("""
# Do sound and meaning measure the same thing? (Spearman correlation across real pantun)
real_only[["sound"] + MODEL_NAMES].corr(method="spearman").loc["sound", MODEL_NAMES].to_frame("Spearman with sound score")
""")

md("""
## 10. Traditional criteria of a good pantun
Malay literary sources describe conventions of a well-formed pantun (see `docs/related_work.md`,
section 5): **8–12 syllables per line**, **end rhyme a-b-a-b** (rima akhir), **middle rhyme a-b-a-b**
(rima tengah, described as what makes a pantun *lebih baik*), and a **pembayang drawn from nature and
daily life** (alam). `src/criteria.py` checks these by rule. The link through symbol and metaphor
(perlambangan, kiasan) cannot be checked by rule and is not included.

How often does each criterion hold for real pantun, for random pairings, and by collection type?
For the nature check we also compare pembayang with maksud: if the word list captures the convention,
it should match pembayang far more often than maksud.
""")
code("""
from src.criteria import checklist, has_nature_imagery

crit_names = [c["name"] for c in checklist(lines[0])]
crit_real = np.array([[c["passed"] for c in checklist(l)] for l in lines])
partner = shuffled_partner(real_only["maksud"], 0)
crit_shuf = np.array([[c["passed"] for c in checklist(lines[i][:2] + lines[j][2:])] for i, j in enumerate(partner)])
ctype = real_only["collection_type"].to_numpy()

criteria_summary = pd.DataFrame({
    "real pantun (%)": crit_real.mean(0) * 100,
    "random pairing (%)": crit_shuf.mean(0) * 100,
    "traditional anthology (%)": crit_real[ctype == "traditional_anthology"].mean(0) * 100,
    "author collections (%)": crit_real[ctype == "author_collection"].mean(0) * 100,
}, index=crit_names)
criteria_summary.to_csv(RESULTS / "criteria_summary.csv")

nature_pembayang = np.mean([bool(has_nature_imagery(" ".join(l[:2]))) for l in lines]) * 100
nature_maksud = np.mean([bool(has_nature_imagery(" ".join(l[2:]))) for l in lines]) * 100
print(f"Nature / daily-life words found in pembayang: {nature_pembayang:.1f}%   in maksud: {nature_maksud:.1f}%")
print(f"All four criteria met: real {crit_real.all(1).mean() * 100:.1f}%   random pairing {crit_shuf.all(1).mean() * 100:.1f}%")
criteria_summary.round(1)
""")

md("""
## 11. Can a model learn kiasan from peribahasa? (pre-registered experiment)
LaBSE was fine-tuned on 8,321 Malay peribahasa ↔ meaning pairs (`mesolitica/peribahasa-instructions`,
no pantun used in training) and compared with plain LaBSE. The settings, tests, leakage control and
decision rule were written down **before** training: `docs/kiasan_experiment_plan.md`. Code:
`src/kiasan_experiment.py` (run `train`, then `evaluate`). Pantun whose maksud contains a training
peribahasa are excluded from the pantun tests.
""")
code("""
kiasan_path = RESULTS / "kiasan_experiment.json"
if kiasan_path.exists():
    kx = json.load(open(kiasan_path))
    rows = {name: {"peribahasa held-out top-1": kx[name]["peribahasa_top1"],
                   "AUC real vs random": kx[name]["auc_random"],
                   "AUC real vs rhyme-matched": kx[name]["auc_rhyme_matched"],
                   "AUC no shared words": kx[name]["auc_no_shared_words"]}
            for name in ["labse", "labse_peribahasa"]}
    print(f"Pantun excluded by the leakage control: {kx['excluded_pantun']}; "
          f"pantun tested: {kx['labse']['n_pantun']}")
    print(f"Pre-registered decision rule - fine-tuning helps: {kx['helps']}")
    display(pd.DataFrame(rows).T.round(3))
else:
    print("Run `python -m src.kiasan_experiment train` and `... evaluate` first.")
""")

md("""
## 12. Can a model learn the link from pantun themselves? (pre-registered + post-hoc checks)
Two models were trained on real pantun from 10 books, with rhyme-matched fakes as negatives, and
tested on 3 **unseen books**: a LaBSE bi-encoder and an XLM-RoBERTa cross-encoder (reads both halves
together). Plan: `docs/pantun_training_plan.md`. Code: `src/pantun_training.py` (`all`, then `diagnose`).

The pre-registered tests 1, 3 and 4 use random fakes, which do not rhyme, so they cannot rule out a
**rhyme shortcut**. Two diagnostics were added **after** seeing the results: removing the last word of
every line, and fakes that match the whole final syllable within the same book.
""")
code("""
pt_path, dg_path = RESULTS / "pantun_training.json", RESULTS / "pantun_training_diagnostics.json"
if pt_path.exists() and dg_path.exists():
    pt, dg = json.load(open(pt_path, encoding="utf-8")), json.load(open(dg_path, encoding="utf-8"))
    names = {"labse_plain": "plain LaBSE", "labse_pantun": "LaBSE trained on pantun", "xlmr_cross": "cross-encoder"}
    table = pd.DataFrame({names[m]: {
        "1. random fakes (pre-reg.)": pt[m]["auc_random"],
        "2. rhyme-matched fakes (pre-reg.)": pt[m]["auc_rhyme_matched"],
        "3. same-book fakes (pre-reg.)": pt[m]["auc_same_book"],
        "4. no shared words (pre-reg.)": pt[m]["auc_no_shared_words"],
        "D1. line-end words removed (post-hoc)": dg[m]["auc_random_line_ends_removed"],
        "D2. whole final syllable matched, same book (post-hoc)": dg[m]["auc_strict_rhyme_same_book"],
    } for m in names})
    print(f"train {pt['n_train']} pantun, test {pt['n_test']} (unseen books; {pt['n_duplicates_removed']} near-duplicates removed); "
          f"D2 pairs: {dg['n_strict_pairs']}")
    print("Pre-registered decision rule:", pt["learned_beyond_shortcuts"])
    display(table.round(3))
else:
    print("Run `python -m src.pantun_training all` and `... diagnose` first.")
""")

md("""
## 13. Findings

_Numbers below are from the run on 10,907 pantun (13 books), five embedding models and the
rhyme rule. The shuffles use fixed seeds, so re-running gives the same values; if the corpus
changes, update this text. Models D and E were added after a literature check
(`docs/related_work.md`), chosen before their results were seen._

**1. Real pairs score higher than shuffled pairs for every model, but the effect is small.**

| model | Cohen's d (random) | AUC (random) | Cohen's d (same book) | AUC (same book) |
|---|---|---|---|---|
| MiniLM | 0.19 | 0.55 | 0.14 | 0.53 |
| LaBSE | 0.40 | 0.60 | 0.31 | 0.58 |
| e5-base | 0.29 | 0.58 | 0.23 | 0.56 |
| e5-large-instruct | 0.39 | 0.60 | 0.31 | 0.58 |
| Mesolitica (Malay) | 0.14 | 0.54 | 0.08 | 0.52 |

All differences are statistically significant (p far below 0.001), but with ~11,000 pantun that
is expected even for tiny effects. The effect sizes are the honest summary: the best models
(LaBSE, e5-large-instruct) rank a real pair above a random pair only about 60% of the time
(50% = chance).

**2. The best general Malay embedder did not do much better, and the Malay-specific one did worse.**
multilingual-e5-large-instruct, the top model for Malay in the SEA-BED benchmark, ties LaBSE
(AUC 0.602 vs 0.604). It is the best model once shared words are removed (AUC 0.573), so its
signal is slightly more about meaning. The Malaysian Mesolitica model is second-worst (AUC 0.54).
Being trained on Malaysian text does not help with the pembayang–maksud link: the difficulty
is the indirect, analogical relation, not the language.

**3. Part of the signal is shared words.** Only 16% of pantun share a word between halves, but
score correlates with word overlap (Spearman 0.13–0.35). Using only pantun with *no* shared
words, the effect shrinks for every model (e.g. LaBSE AUC 0.60 → 0.57; MiniLM 0.55 → 0.53).
The highest-scoring pantun (section 7) are mostly ones whose halves have **parallel wording
or sound** (e.g. *para-paranya / gara-garanya*) rather than a deeper link in meaning.

**4. The models disagree a lot.** Spearman correlation between models' scores is 0.17–0.57.
Which pantun counts as "coherent" depends heavily on the model chosen.

**5. e5 and Mesolitica scores are compressed** (mostly 0.7–0.95). Raw scores must not be compared
across models — only percentiles, p_real or comparisons with the same model's baseline.

**6. Traditional vs modern (exploratory).** The traditional anthology (Zainal Abidin Bakar) shows
the clearest separation (LaBSE AUC 0.68, e5-large-instruct 0.65), while single-author modern
collections are mostly 0.50–0.60. `collection_type` describes the book, not each pantun, and the
DBP set (n = 40) is too small to interpret.

**7. For a single pantun, the meaning score usually cannot tell (section 8).** Tested on 5,445
pantun the bins had not seen (real vs random pairing, 50% = guessing), all five models together
are right **58%** of the time (AUC 0.62). For **94%** of pantun the score is in the "can't tell"
band. When it leans, it is right about **78%** of the time, and it almost only leans towards
"belong together" (10% of real pantun vs 3% of random pairings). It practically never says
"do not belong", so **a low meaning score is not evidence of a mismatched pantun**.

**8. Sound is a strong, separate link (section 9).** The simple rhyme rule separates real pantun
from random pairings almost perfectly (AUC 0.99; 86% of real pantun score 10/10 vs 1% of random
pairings). Its correlation with every meaning score is about 0 (|Spearman| ≤ 0.04): **sound and
meaning are independent dimensions** of how a pantun's halves connect. Rhyme measures form,
not sense — a nonsensical pantun that rhymes scores 10/10 — so it is reported next to the
meaning score, never merged with it.

**9. Traditional criteria (section 10).** Checked by rule on real pantun: **8–12 syllables per line**
holds for 80% (median line = 10 syllables); **end rhyme a-b-a-b** for 95% (vs 1.5% of random
pairings); **middle rhyme a-b-a-b** for only 49% — and just 23% in the traditional anthology vs 54%
in modern author collections — so it is a mark of extra craft, not a rule; **nature / daily-life
images** appear in 74% of pembayang but only 27% of maksud, confirming the convention that the
pembayang draws on alam. One third of real pantun (33%) meet all four checks; no random pairing
does. These checks describe convention and form; the symbolic link (perlambangan, kiasan), which
the sources treat as the heart of a good pantun, still cannot be measured by rule or by embeddings.

**10. Learning peribahasa does not teach pantun kiasan (section 11, pre-registered).** Fine-tuning
LaBSE on 8,321 peribahasa ↔ meaning pairs worked for peribahasa (held-out top-1 matching 29.6% →
35.4%) but did not help with pantun: AUC fell slightly on every test (random 0.607 → 0.599;
rhyme-matched 0.588 → 0.581; no shared words 0.565 → 0.558; 9,582 pantun after excluding 1,325
that contain a training peribahasa). By the pre-registered rule, it does not help. A peribahasa maps
one figurative phrase to its meaning; a pantun links two separate couplets by analogy, which is a
different skill. A rule-based alternative, word-category overlap from Wordnet Bahasa, was also no
better than chance (AUC 0.52), because real pantun deliberately cross categories.

**11. Training on pantun teaches rhyme, not the analogical link (section 12).** Trained on 7,849 pantun
and tested on 3 unseen books, the LaBSE bi-encoder jumped from AUC 0.645 to 0.919 against random fakes
and the cross-encoder reached 0.704; both passed the pre-registered rule. But that rule was flawed:
random fakes do not rhyme. When rhyme is removed (post-hoc: line-end words deleted), the trained
models score 0.612 and 0.621 against plain LaBSE's 0.633 — no gain. Against fakes that match the whole
final syllable in the same book they are no better either (0.457 / 0.558 vs 0.561; only 258 pairs).
The models learned to hear end rhyme, which the simple rhyme rule already measures (AUC 0.99). With
about 8,000 pantun and no labels for *how* the halves connect, the easiest pattern to learn is sound,
not kiasan.

**Conclusion.** Off-the-shelf multilingual and Malay sentence embeddings — including the best
available model for Malay — detect only a weak, partly surface-level pembayang–maksud meaning
relationship, and cannot judge an individual pantun. The sound link (rhyme), which embeddings
cannot see, is strong and measurable. This fits the humanities view that the halves connect
through sound and analogy rather than literal similarity. None of these scores is a judgement
of literary quality.
""")


nb["cells"] = cells
nb["metadata"]["kernelspec"] = {"name": "python3", "display_name": "Python 3", "language": "python"}
nbf.write(nb, sys.argv[1])
print("written", sys.argv[1])
