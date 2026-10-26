"""Learning the pembayang-maksud link from real pantun (bi-encoder and cross-encoder).

The plan (book split, duplicate control, settings, tests, decision rule) was fixed BEFORE
running: see docs/pantun_training_plan.md. Nothing here is tuned on the test books.

Run from the project root:
    python -m src.pantun_training all        # train both models, then evaluate (~1-1.5 h on CPU)
    python -m src.pantun_training evaluate   # evaluate only (models already trained)

Everything stays on this computer: the pantun library is private.
"""

import json
import re
import sys
import time
from collections import defaultdict

import numpy as np
from scipy import stats

from src.data_loader import PROJECT_ROOT, join_couplet, load_pantun
from src.evaluate import rhyme_matched_partner, shuffled_partner, word_overlap
from src.rhyme import last_word, rime

TEST_BOOKS = {"Kumpulan Pantun Melayu", "Setaman Pantun Bertatah Bahasa", "Pantun Berkait Mengejar Pelangi"}
DUPLICATE_COSINE = 0.95
BI_DIR = PROJECT_ROOT / "models" / "labse-pantun"
CROSS_DIR = PROJECT_ROOT / "models" / "xlmr-pantun-cross"
OUT_JSON = PROJECT_ROOT / "results" / "pantun_training.json"
SEED = 42


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

def norm(text):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z\s]", " ", text.lower())).strip()


def build_split():
    """Return (pantun, lines, pembayang, maksud, books, train_idx, test_idx, n_duplicates)."""
    pantun, _ = load_pantun()
    lines = [p.lines for p in pantun]
    pembayang = np.array([join_couplet(l[0], l[1]) for l in lines])
    maksud = np.array([join_couplet(l[2], l[3]) for l in lines])
    books = np.array([p.info["collection"] for p in pantun])
    is_test = np.isin(books, list(TEST_BOOKS))
    train_idx, test_all = np.flatnonzero(~is_test), np.flatnonzero(is_test)

    # Duplicate control with plain LaBSE embeddings from Phase 2.
    cache = np.load(PROJECT_ROOT / "results" / "embeddings" / "labse.npz")
    assert list(cache["ids"]) == [p.id for p in pantun], "LaBSE cache does not match the corpus"
    P, M = cache["pembayang"], cache["maksud"]
    near_p = (P[test_all] @ P[train_idx].T).max(axis=1) >= DUPLICATE_COSINE
    near_m = (M[test_all] @ M[train_idx].T).max(axis=1) >= DUPLICATE_COSINE
    train_text_p = {norm(t) for t in pembayang[train_idx]}
    train_text_m = {norm(t) for t in maksud[train_idx]}
    same_text = np.array([norm(pembayang[i]) in train_text_p or norm(maksud[i]) in train_text_m for i in test_all])
    duplicate = near_p | near_m | same_text
    test_idx = test_all[~duplicate]
    return pantun, lines, pembayang, maksud, books, train_idx, test_idx, int(duplicate.sum())


def rhyme_negatives(idx, lines, maksud, books, seed):
    """For each pantun in idx: another pantun (from idx) with the same end sounds and a different
    maksud, preferably from the same book. Returns {i: j}."""
    rng = np.random.default_rng(seed)
    by_key = defaultdict(list)
    for j in idx:
        by_key[(rime(last_word(lines[j][2])), rime(last_word(lines[j][3])))].append(j)
    out = {}
    for i in idx:
        pool = [j for j in by_key[(rime(last_word(lines[i][0])), rime(last_word(lines[i][1])))]
                if maksud[j] != maksud[i]]
        same_book = [j for j in pool if books[j] == books[i]]
        pool = same_book or pool
        if pool:
            out[i] = int(rng.choice(pool))
    return out


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train_bi(data):
    import torch
    from datasets import Dataset
    from sentence_transformers import (SentenceTransformer, SentenceTransformerTrainer,
                                       SentenceTransformerTrainingArguments, losses)
    _, lines, pembayang, maksud, books, train_idx, _, _ = data
    neg = rhyme_negatives(train_idx, lines, maksud, books, seed=0)
    rows = [(pembayang[i], maksud[i], maksud[j]) for i, j in neg.items()]
    print(f"[bi-encoder] {len(rows)} triplets")
    torch.manual_seed(SEED)
    model = SentenceTransformer("sentence-transformers/LaBSE", device="cpu", model_kwargs={"dtype": torch.float32})
    model.max_seq_length = 64
    model[0].auto_model.embeddings.word_embeddings.requires_grad_(False)
    ds = Dataset.from_dict({"anchor": [r[0] for r in rows], "positive": [r[1] for r in rows],
                            "negative": [r[2] for r in rows]})
    args = SentenceTransformerTrainingArguments(
        output_dir=str(PROJECT_ROOT / "models" / "_checkpoints"), num_train_epochs=1,
        per_device_train_batch_size=32, learning_rate=2e-5, warmup_ratio=0.10, seed=SEED,
        save_strategy="no", logging_steps=20, report_to=[], use_cpu=True)
    start = time.time()
    SentenceTransformerTrainer(model=model, args=args, train_dataset=ds,
                               loss=losses.MultipleNegativesRankingLoss(model)).train()
    print(f"[bi-encoder] trained in {(time.time() - start) / 60:.1f} min")
    model.save(str(BI_DIR))


def train_cross(data):
    import torch
    from datasets import Dataset
    from sentence_transformers.cross_encoder import (CrossEncoder, CrossEncoderTrainer,
                                                     CrossEncoderTrainingArguments, losses)
    _, lines, pembayang, maksud, books, train_idx, _, _ = data
    a, b, y = [], [], []
    negs = [rhyme_negatives(train_idx, lines, maksud, books, seed=s) for s in (0, 1)]
    for i in train_idx:
        if i not in negs[0]:
            continue
        a.append(pembayang[i]); b.append(maksud[i]); y.append(1.0)
        for neg in negs:
            if i in neg:
                a.append(pembayang[i]); b.append(maksud[neg[i]]); y.append(0.0)
    print(f"[cross-encoder] {len(y)} pairs ({int(sum(y))} real)")
    torch.manual_seed(SEED)
    model = CrossEncoder("FacebookAI/xlm-roberta-base", num_labels=1, max_length=96, device="cpu",
                         model_kwargs={"dtype": torch.float32})
    model.model.roberta.embeddings.word_embeddings.requires_grad_(False)
    ds = Dataset.from_dict({"pembayang": a, "maksud": b, "label": y})
    args = CrossEncoderTrainingArguments(
        output_dir=str(PROJECT_ROOT / "models" / "_checkpoints"), num_train_epochs=1,
        per_device_train_batch_size=16, learning_rate=2e-5, warmup_ratio=0.10, seed=SEED,
        save_strategy="no", logging_steps=50, report_to=[], use_cpu=True)
    start = time.time()
    CrossEncoderTrainer(model=model, args=args, train_dataset=ds,
                        loss=losses.BinaryCrossEntropyLoss(model)).train()
    print(f"[cross-encoder] trained in {(time.time() - start) / 60:.1f} min")
    model.save(str(CROSS_DIR))


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def auc(real, fake):
    u, _ = stats.mannwhitneyu(real, fake)
    return float(u / (len(real) * len(fake)))


def test_pairs(data):
    """All (pembayang index, maksud index) pairs needed for the four tests, as named lists."""
    _, lines, _, maksud, books, _, test_idx, _ = data
    t = test_idx
    pairs = {"real": [(i, i) for i in t]}
    pairs["random"] = [(t[k], t[p]) for s in range(3) for k, p in enumerate(shuffled_partner(maksud[t], s))]
    i_rm, j_rm = rhyme_matched_partner([lines[i] for i in t], maksud[t])
    pairs["rhyme_matched"] = [(t[a], t[b]) for a, b in zip(i_rm, j_rm)]
    pairs["real_rhyme_subset"] = [(t[a], t[a]) for a in i_rm]
    pairs["same_book"] = [(t[k], t[p]) for s in range(3)
                          for k, p in enumerate(shuffled_partner(maksud[t], s, books[t]))]
    no_ov = np.array([word_overlap(" ".join(lines[i][:2]), " ".join(lines[i][2:])) == 0 for i in t])
    tn = t[no_ov]
    pairs["real_no_shared"] = [(i, i) for i in tn]
    pairs["random_no_shared"] = [(tn[k], tn[p]) for s in range(3) for k, p in enumerate(shuffled_partner(maksud[tn], s))]
    return pairs


def score_bi(model, pembayang, maksud, pairs):
    need_p = sorted({i for v in pairs.values() for i, _ in v})
    need_m = sorted({j for v in pairs.values() for _, j in v})
    ep = dict(zip(need_p, model.encode(list(pembayang[need_p]), batch_size=64, normalize_embeddings=True)))
    em = dict(zip(need_m, model.encode(list(maksud[need_m]), batch_size=64, normalize_embeddings=True)))
    return {k: np.array([float(ep[i] @ em[j]) for i, j in v]) for k, v in pairs.items()}


def score_cross(model, pembayang, maksud, pairs):
    unique = sorted({p for v in pairs.values() for p in v})
    s = model.predict([(pembayang[i], maksud[j]) for i, j in unique], batch_size=64, show_progress_bar=True)
    lookup = dict(zip(unique, s))
    return {k: np.array([float(lookup[p]) for p in v]) for k, v in pairs.items()}


def summarise(sc, pairs, books):
    out = {
        "auc_random": auc(sc["real"], sc["random"]),
        "auc_rhyme_matched": auc(sc["real_rhyme_subset"], sc["rhyme_matched"]),
        "auc_same_book": auc(sc["real"], sc["same_book"]),
        "auc_no_shared_words": auc(sc["real_no_shared"], sc["random_no_shared"]),
    }
    real_books = np.array([books[i] for i, _ in pairs["real"]])
    rand_books = np.array([books[i] for i, _ in pairs["random"]])
    out["auc_random_by_book"] = {b: auc(sc["real"][real_books == b], sc["random"][rand_books == b])
                                 for b in sorted(set(real_books))}
    return out


def evaluate():
    import torch
    from sentence_transformers import SentenceTransformer
    from sentence_transformers.cross_encoder import CrossEncoder

    data = build_split()
    pantun, lines, pembayang, maksud, books, train_idx, test_idx, n_dup = data
    pairs = test_pairs(data)
    print(f"train pantun {len(train_idx)}, test pantun {len(test_idx)} (removed as duplicates: {n_dup})")
    fp32 = {"dtype": torch.float32}
    results = {"plan": "docs/pantun_training_plan.md", "n_train": int(len(train_idx)),
               "n_test": int(len(test_idx)), "n_duplicates_removed": n_dup,
               "n_pairs": {k: len(v) for k, v in pairs.items()}}
    scored = {}
    for name, kind, path in [("labse_plain", "bi", "sentence-transformers/LaBSE"),
                             ("labse_pantun", "bi", str(BI_DIR)),
                             ("xlmr_cross", "cross", str(CROSS_DIR))]:
        print(f"\n[{name}]")
        start = time.time()
        if kind == "bi":
            sc = score_bi(SentenceTransformer(path, device="cpu", model_kwargs=fp32), pembayang, maksud, pairs)
        else:
            sc = score_cross(CrossEncoder(path, device="cpu", model_kwargs=fp32), pembayang, maksud, pairs)
        scored[name] = sc
        results[name] = summarise(sc, pairs, books)
        print(f"  scored in {time.time() - start:.0f} s: " + ", ".join(
            f"{k}={v:.3f}" for k, v in results[name].items() if isinstance(v, float)))

    base = results["labse_plain"]
    tests = ["auc_random", "auc_rhyme_matched", "auc_same_book", "auc_no_shared_words"]
    results["learned_beyond_shortcuts"] = {
        m: all(results[m][t] > base[t] for t in tests) for m in ["labse_pantun", "xlmr_cross"]}

    # Examples for discussion: test pantun with NO shared words that the cross-encoder rates highest.
    real_ns = [i for i, _ in pairs["real_no_shared"]]
    order = np.argsort(-scored["xlmr_cross"]["real_no_shared"])[:10]
    results["examples_top_no_shared_words"] = [
        {"id": pantun[real_ns[k]].id, "pembayang": str(pembayang[real_ns[k]]), "maksud": str(maksud[real_ns[k]]),
         "cross_score": float(scored["xlmr_cross"]["real_no_shared"][k])} for k in order]

    OUT_JSON.write_text(json.dumps(results, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"\nDecision rule (pre-registered): {results['learned_beyond_shortcuts']}")
    print(f"Wrote {OUT_JSON.relative_to(PROJECT_ROOT)}")


# ---------------------------------------------------------------------------
# Diagnostics - ADDED AFTER SEEING THE RESULTS (not pre-registered).
# Question: did the trained models mostly learn RHYME? Random fakes do not rhyme, so
# tests 1, 3 and 4 of the plan can be passed by hearing rhyme alone.
# ---------------------------------------------------------------------------

def final_syllable(word):
    """'belayar' -> 'yar', 'peti' -> 'ti', 'pantai' -> 'tai'."""
    m = re.search(r"[^aeiou]*[aeiou]+[^aeiou]*$", word)
    return m.group(0) if m else word


def drop_last_word(line):
    words = line.split()
    return " ".join(words[:-1]) if len(words) > 1 else line


def diagnose():
    import torch
    from sentence_transformers import SentenceTransformer
    from sentence_transformers.cross_encoder import CrossEncoder

    data = build_split()
    pantun, lines, pembayang, maksud, books, _, t, _ = data
    rng = np.random.default_rng(0)

    # D1: strict rhyme-matched fakes - same whole final syllable on lines 1~3 and 2~4, same book.
    key = lambda a, b: (final_syllable(last_word(a)), final_syllable(last_word(b)))
    by = defaultdict(list)
    for j in t:
        by[(books[j],) + key(lines[j][2], lines[j][3])].append(j)
    strict = []
    for i in t:
        pool = [j for j in by[(books[i],) + key(lines[i][0], lines[i][1])] if maksud[j] != maksud[i]]
        if pool:
            strict.append((i, int(rng.choice(pool))))

    # D2: line-end words removed from every line, then real vs random (3 seeds).
    pb_cut = np.array([join_couplet(drop_last_word(l[0]), drop_last_word(l[1])) for l in lines])
    mk_cut = np.array([join_couplet(drop_last_word(l[2]), drop_last_word(l[3])) for l in lines])
    rand = [(t[k], t[p]) for s in range(3) for k, p in enumerate(shuffled_partner(maksud[t], s))]

    pairs_full = {"real_strict": [(i, i) for i, _ in strict], "strict_fake": strict}
    pairs_cut = {"real": [(i, i) for i in t], "random": rand}
    fp32 = {"dtype": torch.float32}
    out = {"note": "Post-hoc diagnostics, added after seeing the pre-registered results.",
           "n_strict_pairs": len(strict)}
    for name, kind, path in [("labse_plain", "bi", "sentence-transformers/LaBSE"),
                             ("labse_pantun", "bi", str(BI_DIR)),
                             ("xlmr_cross", "cross", str(CROSS_DIR))]:
        if kind == "bi":
            model = SentenceTransformer(path, device="cpu", model_kwargs=fp32)
            score = lambda P, M, pairs: score_bi(model, P, M, pairs)
        else:
            model = CrossEncoder(path, device="cpu", model_kwargs=fp32)
            score = lambda P, M, pairs: score_cross(model, P, M, pairs)
        s_full = score(pembayang, maksud, pairs_full)
        s_cut = score(pb_cut, mk_cut, pairs_cut)
        out[name] = {"auc_strict_rhyme_same_book": auc(s_full["real_strict"], s_full["strict_fake"]),
                     "auc_random_line_ends_removed": auc(s_cut["real"], s_cut["random"])}
        print(name, {k: round(v, 3) for k, v in out[name].items()})
    path = PROJECT_ROOT / "results" / "pantun_training_diagnostics.json"
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"strict pairs: {len(strict)}; wrote {path.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    cmd = sys.argv[1]
    if cmd == "diagnose":
        diagnose()
    if cmd == "all":
        d = build_split()
        print(f"train pantun {len(d[5])}, test pantun {len(d[6])} (removed as duplicates: {d[7]})")
        train_bi(d)
        train_cross(d)
        evaluate()
    elif cmd == "evaluate":
        evaluate()
