"""Phase 3 - Evaluation helpers (used by notebooks/evaluation.ipynb).

Main question: do real pembayang-maksud pairs score higher than random pairs?
If the models capture anything about pantun coherence, the real score should
be clearly higher than the score of a pembayang paired with someone else's
maksud. If not, the score is mostly noise.

Two shuffled baselines:
  - random:            pembayang i + maksud of a random other pantun
  - within_collection: pembayang i + maksud of a random other pantun from the
                       SAME book. Pantun in one book share an author, style and
                       topics, so this is a harder, fairer comparison.
"""

import re

import numpy as np
import pandas as pd
from scipy import stats

from src.data_loader import PROJECT_ROOT
from src.score import CACHE_DIR, MODELS, SCORES_CSV

N_SHUFFLES = 10          # how many different shuffles per baseline
SEEDS = list(range(N_SHUFFLES))   # fixed seeds -> results are reproducible


def load_scores():
    """results/scores.csv as a DataFrame."""
    return pd.read_csv(SCORES_CSV, keep_default_na=False)


def load_embeddings(short, expected_ids):
    """Cached (pembayang, maksud) vectors for one model, checked against scores.csv order."""
    data = np.load(CACHE_DIR / f"{short}.npz", allow_pickle=False)
    if list(data["ids"]) != list(expected_ids):
        raise ValueError(f"Embedding cache for {short} does not match scores.csv - rerun src.score")
    return data["pembayang"], data["maksud"]


def shuffled_partner(maksud_texts, seed, groups=None):
    """For each pantun i, pick the index of another pantun whose maksud it will be paired with.

    Rules: never itself, and never a pantun with the identical maksud text
    (e.g. variants of the same pantun), otherwise the "random" pair would
    really be a real pair. If groups is given, partners come from the same group.
    """
    rng = np.random.default_rng(seed)
    n = len(maksud_texts)
    maksud_texts = np.asarray(maksud_texts)
    groups = np.zeros(n, dtype=int) if groups is None else pd.factorize(np.asarray(groups))[0]

    partner = np.empty(n, dtype=int)
    for g in np.unique(groups):
        members = np.flatnonzero(groups == g)
        perm = rng.permutation(members)
        partner[members] = perm
        # Fix "bad" pairs (itself / same maksud) by re-drawing, a few rounds.
        for _ in range(50):
            bad = members[maksud_texts[partner[members]] == maksud_texts[members]]
            if len(bad) == 0:
                break
            partner[bad] = rng.choice(members, size=len(bad))
    return partner


def rhyme_matched_partner(lines, maksud_texts, seed=0):
    """Harder fakes: pair each pembayang with another pantun's maksud that has the SAME end
    sounds (line 1 ~ line 3, line 2 ~ line 4), so rhyme cannot reveal the fake.

    lines: list of 4-line lists. Returns (idx, partner) arrays; pantun with no possible
    partner are left out.
    """
    from collections import defaultdict
    from src.rhyme import last_word, rime

    maksud_texts = np.asarray(maksud_texts)
    by_ending = defaultdict(list)       # (end sound line 3, end sound line 4) -> pantun indices
    for j, l in enumerate(lines):
        by_ending[(rime(last_word(l[2])), rime(last_word(l[3])))].append(j)
    rng = np.random.default_rng(seed)
    idx, partner = [], []
    for i, l in enumerate(lines):
        pool = [j for j in by_ending[(rime(last_word(l[0])), rime(last_word(l[1])))]
                if maksud_texts[j] != maksud_texts[i]]
        if pool:
            idx.append(i)
            partner.append(rng.choice(pool))
    return np.array(idx), np.array(partner)


def shuffled_scores(emb_p, emb_m, maksud_texts, groups=None):
    """Scores for N_SHUFFLES shuffles. Returns array shape (N_SHUFFLES, n)."""
    out = []
    for seed in SEEDS:
        partner = shuffled_partner(maksud_texts, seed, groups)
        out.append(np.sum(emb_p * emb_m[partner], axis=1))   # cosine (unit vectors)
    return np.vstack(out)


def compare(real, shuffled):
    """Statistics for real scores (n,) vs shuffled scores (N_SHUFFLES, n).

    - mean difference
    - Cohen's d: difference in means measured in standard deviations
      (rough guide: 0.2 small, 0.5 medium, 0.8 large)
    - AUC: chance that a random real pair scores higher than a random
      shuffled pair (0.5 = no difference, 1.0 = always higher)
    - Mann-Whitney U test p-value (real vs all shuffled scores)
    - Wilcoxon signed-rank p-value, PAIRED: each pantun's real score vs the
      mean of its own shuffled scores. Pairing is better here because the same
      pembayang appears on both sides.
    With ~11,000 pantun, even tiny differences are "significant", so the
    effect sizes (d, AUC) matter more than the p-values.
    """
    flat = shuffled.ravel()
    diff = real.mean() - flat.mean()
    pooled_sd = np.sqrt((real.var(ddof=1) + flat.var(ddof=1)) / 2)
    u, p_mw = stats.mannwhitneyu(real, flat, alternative="greater")
    _, p_w = stats.wilcoxon(real - shuffled.mean(axis=0), alternative="greater")
    return {
        "real_mean": real.mean(),
        "shuffled_mean": flat.mean(),
        "mean_diff": diff,
        "cohens_d": diff / pooled_sd,
        "auc": u / (len(real) * len(flat)),
        "mannwhitney_p": p_mw,
        "wilcoxon_paired_p": p_w,
        "pct_real_above_own_shuffled_mean": 100 * np.mean(real > shuffled.mean(axis=0)),
    }


def word_overlap(pembayang, maksud):
    """Share of words the two halves have in common (Jaccard, 0-1).

    Pantun often repeat a word or sound across halves ("Pisang EMAS ... Hutang EMAS").
    If models mainly react to shared words, the score measures word repetition,
    not meaning. We check this in the notebook.
    """
    a = set(re.findall(r"[a-z]+(?:-[a-z]+)*", pembayang.lower()))
    b = set(re.findall(r"[a-z]+(?:-[a-z]+)*", maksud.lower()))
    return len(a & b) / len(a | b) if a | b else 0.0


# ---------------------------------------------------------------------------
# Can the score judge ONE pantun?  ("calibration")
#
# For a single score we ask: is a score like this more common among real
# pantun or among random pairings? We cut the score range into N_BINS bins
# (equal numbers of scores per bin) and count both groups in each bin:
#     p_real(bin) = share of real scores in bin / (share real + share random)
# 0.5 = the score is equally common in both groups -> "can't tell".
# This only counts; no model is trained. Each of the 3 models gives a p_real,
# and we average them.
# ---------------------------------------------------------------------------

N_BINS = 20
LEAN = 0.10   # p_real must be at least 0.5 +/- LEAN before we say the score leans one way


def fit_calibration(real, shuffled_flat, n_bins=N_BINS):
    """Return {'edges': inner bin edges, 'p_real': value per bin} for one model."""
    edges = np.quantile(np.concatenate([real, shuffled_flat]), np.linspace(0, 1, n_bins + 1))[1:-1]
    bins_real = np.bincount(np.searchsorted(edges, real, side="right"), minlength=n_bins) + 1
    bins_shuf = np.bincount(np.searchsorted(edges, shuffled_flat, side="right"), minlength=n_bins) + 1
    share_real, share_shuf = bins_real / bins_real.sum(), bins_shuf / bins_shuf.sum()
    return {"edges": edges.tolist(), "p_real": (share_real / (share_real + share_shuf)).tolist()}


def predict_p_real(calibration, scores):
    """p_real for one or many scores of one model."""
    idx = np.searchsorted(np.asarray(calibration["edges"]), scores, side="right")
    return np.asarray(calibration["p_real"])[idx]


def lean(p):
    """'belong', 'not_belong' or 'cannot_tell' for an averaged p_real."""
    if p >= 0.5 + LEAN:
        return "belong"
    if p <= 0.5 - LEAN:
        return "not_belong"
    return "cannot_tell"


def evaluate_single_pantun(real_scores, shuffled, seed=42):
    """Honest test of the calibration on pantun it has not seen.

    real_scores: {model: (n,)}; shuffled: {model: (N_SHUFFLES, n)} random-baseline scores.
    Pantun are split in half at random: bins are fitted on half A, then tested on
    half B with a balanced set (each real pantun + one random pairing).
    """
    models = list(real_scores)
    n = len(next(iter(real_scores.values())))
    in_a = np.random.default_rng(seed).random(n) < 0.5
    cal = {m: fit_calibration(real_scores[m][in_a], shuffled[m][:, in_a].ravel()) for m in models}
    p_real = np.mean([predict_p_real(cal[m], real_scores[m][~in_a]) for m in models], axis=0)
    p_shuf = np.mean([predict_p_real(cal[m], shuffled[m][0, ~in_a]) for m in models], axis=0)

    y = np.r_[np.ones(len(p_real)), np.zeros(len(p_shuf))]
    p = np.r_[p_real, p_shuf]
    leans = np.array([lean(x) for x in p])
    decided = leans != "cannot_tell"
    u, _ = stats.mannwhitneyu(p_real, p_shuf)
    return {
        "test_pantun": int((~in_a).sum()),
        "auc": float(u / (len(p_real) * len(p_shuf))),
        "accuracy_at_0.5": float(((p >= 0.5) == y).mean()),
        "share_cannot_tell": float(1 - decided.mean()),
        "accuracy_when_it_leans": float(((leans[decided] == "belong") == (y[decided] == 1)).mean())
        if decided.any() else float("nan"),
        "real_said_belong": float(np.mean([lean(x) == "belong" for x in p_real])),
        "random_said_belong": float(np.mean([lean(x) == "belong" for x in p_shuf])),
        "real_said_not_belong": float(np.mean([lean(x) == "not_belong" for x in p_real])),
        "random_said_not_belong": float(np.mean([lean(x) == "not_belong" for x in p_shuf])),
    }


__all__ =["MODELS", "PROJECT_ROOT", "load_scores", "load_embeddings", "shuffled_scores",
           "compare", "word_overlap", "N_SHUFFLES", "fit_calibration", "predict_p_real", "lean",
           "evaluate_single_pantun", "LEAN"]
