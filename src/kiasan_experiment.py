"""Kiasan experiment: fine-tune LaBSE on Malay peribahasa, then test it on pantun.

The plan (settings, tests, decision rule) was fixed BEFORE running:
see docs/kiasan_experiment_plan.md. Nothing here is tuned on pantun.

Run from the project root:
    python -m src.kiasan_experiment train      # ~30-60 min on CPU, saves models/labse-peribahasa
    python -m src.kiasan_experiment evaluate   # writes results/kiasan_experiment.json

Training uses ONLY the peribahasa pairs (mesolitica/peribahasa-instructions).
The private pantun library is used only for testing and never leaves this computer.
"""

import json
import re
import sys
import time

import numpy as np
import pandas as pd
from scipy import stats

from src.data_loader import PROJECT_ROOT, load_pantun

PERIBAHASA_DIR = PROJECT_ROOT / "data" / "external" / "peribahasa"
MODEL_DIR = PROJECT_ROOT / "models" / "labse-peribahasa"
BASE_MODEL = "sentence-transformers/LaBSE"
OUT_JSON = PROJECT_ROOT / "results" / "kiasan_experiment.json"

# Fixed settings from the pre-registration.
EPOCHS, BATCH, LR, WARMUP, SEED, MAX_LEN = 1, 32, 2e-5, 0.10, 42, 64


def load_peribahasa(split):
    """List of (phrase, meaning) pairs; split = 'train' or 'test'."""
    df = pd.read_json(PERIBAHASA_DIR / f"{split}.json")
    df.columns = ["phrase", "meaning"]
    df = df.dropna()
    df = df[(df["phrase"].str.strip() != "") & (df["meaning"].str.strip() != "")]
    return list(zip(df["phrase"].str.strip(), df["meaning"].str.strip()))


def norm(text):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z\s-]", " ", text.lower())).strip()


def leaked_pantun(pantun, phrases):
    """Ids of pantun whose maksud contains a training peribahasa of >= 3 words."""
    long_phrases = {norm(p) for p in phrases if len(norm(p).split()) >= 3}
    leaked = set()
    for p in pantun:
        m = " " + norm(" ".join(p.lines[2:])) + " "
        if any(" " + ph + " " in m for ph in long_phrases):
            leaked.add(p.id)
    return leaked


def load_base():
    import torch
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(BASE_MODEL, device="cpu", model_kwargs={"dtype": torch.float32})


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train():
    import torch
    from datasets import Dataset
    from sentence_transformers import (SentenceTransformerTrainer,
                                       SentenceTransformerTrainingArguments, losses)

    torch.manual_seed(SEED)
    pairs = load_peribahasa("train")
    print(f"Training pairs: {len(pairs)}")
    model = load_base()
    model.max_seq_length = MAX_LEN
    # Freeze the token-embedding table (pre-registered): only transformer layers are trained.
    model[0].auto_model.embeddings.word_embeddings.requires_grad_(False)

    data = Dataset.from_dict({"anchor": [p for p, _ in pairs], "positive": [m for _, m in pairs]})
    args = SentenceTransformerTrainingArguments(
        output_dir=str(PROJECT_ROOT / "models" / "_checkpoints"),
        num_train_epochs=EPOCHS, per_device_train_batch_size=BATCH, learning_rate=LR,
        warmup_ratio=WARMUP, seed=SEED, save_strategy="no", logging_steps=20, report_to=[],
        use_cpu=True,
    )
    trainer = SentenceTransformerTrainer(model=model, args=args, train_dataset=data,
                                         loss=losses.MultipleNegativesRankingLoss(model))
    start = time.time()
    trainer.train()
    print(f"Training took {(time.time() - start) / 60:.1f} min")
    model.save(str(MODEL_DIR))
    print(f"Saved to {MODEL_DIR}")


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------

def peribahasa_top1(model, pairs):
    """Share of held-out phrases whose own meaning is the most similar of all meanings."""
    a = model.encode([p for p, _ in pairs], normalize_embeddings=True)
    b = model.encode([m for _, m in pairs], normalize_embeddings=True)
    return float(np.mean(np.argmax(a @ b.T, axis=1) == np.arange(len(pairs))))


def auc(real, fake):
    u, _ = stats.mannwhitneyu(real, fake)
    return float(u / (len(real) * len(fake)))


def pantun_tests(emb_p, emb_m, lines, maksud, keep):
    """The three pre-registered pantun tests, on pantun where keep is True."""
    from src.evaluate import rhyme_matched_partner, shuffled_partner, word_overlap

    idx_keep = np.flatnonzero(keep)
    real = np.sum(emb_p * emb_m, axis=1)

    # 1. real vs random pairing (10 seeds); partners drawn from the kept pantun only
    rand = [np.sum(emb_p[idx_keep] * emb_m[idx_keep][shuffled_partner(maksud[idx_keep], s)], axis=1)
            for s in range(10)]
    auc_random = auc(real[idx_keep], np.concatenate(rand))

    # 2. real vs rhyme-matched fake
    sub_lines = [lines[i] for i in idx_keep]
    i_rm, j_rm = rhyme_matched_partner(sub_lines, maksud[idx_keep])
    gi, gj = idx_keep[i_rm], idx_keep[j_rm]
    auc_rhyme = auc(real[gi], np.sum(emb_p[gi] * emb_m[gj], axis=1))

    # 3. real vs random, only pantun with no shared words between halves
    no_ov = np.array([word_overlap(" ".join(lines[i][:2]), " ".join(lines[i][2:])) == 0 for i in idx_keep])
    idx_no = idx_keep[no_ov]
    rand_no = [np.sum(emb_p[idx_no] * emb_m[idx_no][shuffled_partner(maksud[idx_no], s)], axis=1)
               for s in range(10)]
    auc_no = auc(real[idx_no], np.concatenate(rand_no))
    return {"auc_random": auc_random, "auc_rhyme_matched": auc_rhyme, "auc_no_shared_words": auc_no,
            "n_pantun": int(len(idx_keep)), "n_rhyme_matched": int(len(gi)), "n_no_shared_words": int(len(idx_no))}


def evaluate():
    import torch
    from sentence_transformers import SentenceTransformer
    from src.data_loader import join_couplet

    accepted, _ = load_pantun()
    lines = [p.lines for p in accepted]
    pembayang = [join_couplet(l[0], l[1]) for l in lines]
    maksud = np.array([join_couplet(l[2], l[3]) for l in lines])

    train_pairs, test_pairs = load_peribahasa("train"), load_peribahasa("test")
    leaked = leaked_pantun(accepted, [p for p, _ in train_pairs])
    keep = np.array([p.id not in leaked for p in accepted])
    print(f"Leakage control: {len(leaked)} pantun excluded (maksud contains a training peribahasa)")

    results = {"plan": "docs/kiasan_experiment_plan.md", "excluded_pantun": len(leaked)}
    for name, loader in [("labse", load_base),
                         ("labse_peribahasa", lambda: SentenceTransformer(
                             str(MODEL_DIR), device="cpu", model_kwargs={"dtype": torch.float32}))]:
        print(f"\n[{name}]")
        model = loader()
        top1 = peribahasa_top1(model, test_pairs)
        print(f"  peribahasa held-out top-1: {top1:.3f}")
        start = time.time()
        emb = model.encode(pembayang + list(maksud), batch_size=64, normalize_embeddings=True,
                           show_progress_bar=True)
        print(f"  embedded pantun in {time.time() - start:.0f} s")
        n = len(pembayang)
        tests = pantun_tests(emb[:n], emb[n:], lines, maksud, keep)
        print("  " + ", ".join(f"{k}={v:.3f}" if isinstance(v, float) else f"{k}={v}" for k, v in tests.items()))
        results[name] = {"peribahasa_top1": top1, **tests}

    base, tuned = results["labse"], results["labse_peribahasa"]
    results["helps"] = bool(tuned["auc_random"] > base["auc_random"]
                            and tuned["auc_rhyme_matched"] > base["auc_rhyme_matched"])
    OUT_JSON.parent.mkdir(exist_ok=True)
    OUT_JSON.write_text(json.dumps(results, indent=1))
    print(f"\nDecision rule (pre-registered): helps = {results['helps']}")
    print(f"Wrote {OUT_JSON.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    {"train": train, "evaluate": evaluate}[sys.argv[1]]()
