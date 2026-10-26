"""Phase 2 - Coherence scoring.

For every pantun, embed the pembayang (lines 1-2) and the maksud (lines 3-4)
with each sentence-embedding model, and take the cosine similarity between
the two vectors. That number is the "coherence score" for that model.

Embeddings are cached in results/embeddings/ so the slow part only runs once.
Phase 3 (evaluation) reuses the cached embeddings for the shuffled baseline.

Run from the project root:
    python -m src.score
"""

import csv
import hashlib
import sys
import time
from pathlib import Path

import numpy as np

from src.data_loader import PROJECT_ROOT, load_pantun

RESULTS_DIR = PROJECT_ROOT / "results"
CACHE_DIR = RESULTS_DIR / "embeddings"
SCORES_CSV = RESULTS_DIR / "scores.csv"

# Models compared. "short" is the column name used in scores.csv.
# "prefix" is text some models require in front of every input:
#   multilingual-e5 was trained with "query: " / "passage: " prefixes. Its model
#   card says to use "query: " on BOTH sides for symmetric tasks like
#   semantic similarity, which is what pembayang-vs-maksud is.
#
# Models 4 and 5 were added after a literature check, BEFORE seeing their results:
#   - e5_large_instruct: best model for Malay in the SEA-BED benchmark (Ponwitayarat et al.,
#     2025, arXiv:2508.12243). Instruct models need a task instruction; for semantic
#     similarity the e5-instruct authors use "Retrieve semantically similar text."
#   - mesolitica: Malaysian embedding model (Zolkepli et al., 2024, arXiv:2402.03053),
#     loaded with our own code in src/malay_embedding.py (no remote code is run).
MODELS = [
    {"short": "minilm", "name": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "prefix": ""},
    {"short": "labse",  "name": "sentence-transformers/LaBSE",                                 "prefix": ""},
    {"short": "e5",     "name": "intfloat/multilingual-e5-base",                               "prefix": "query: "},
    {"short": "e5_large_instruct", "name": "intfloat/multilingual-e5-large-instruct",
     "prefix": "Instruct: Retrieve semantically similar text.\nQuery: "},
    {"short": "mesolitica", "name": "mesolitica/llama2-embedding-600m-8k-contrastive", "prefix": "",
     "loader": "mesolitica"},
]


def load_encoder(model_info):
    """Return an object with .encode(texts, ...) for one model."""
    if model_info.get("loader") == "mesolitica":
        from src.malay_embedding import MesoliticaEncoder
        return MesoliticaEncoder(model_info["name"])
    import torch
    from sentence_transformers import SentenceTransformer
    # float32: some models are stored in float16, which is very slow on a CPU.
    return SentenceTransformer(model_info["name"], device="cpu", model_kwargs={"dtype": torch.float32})

BATCH_SIZE = 64


def fingerprint(texts):
    """Short hash of a list of texts, to tell if a cache still matches the data."""
    return hashlib.sha256("\n".join(texts).encode("utf-8")).hexdigest()[:16]


def get_embeddings(model_info, ids, pembayang, maksud):
    """Return (pembayang_vectors, maksud_vectors) for one model, using the cache if valid.

    Vectors are L2-normalised (length 1), so cosine similarity = dot product.
    """
    cache_file = CACHE_DIR / f"{model_info['short']}.npz"
    key = fingerprint([model_info["name"], model_info["prefix"]] + pembayang + maksud)

    if cache_file.exists():
        cached = np.load(cache_file, allow_pickle=False)
        if str(cached["key"]) == key:
            print(f"  using cached embeddings: {cache_file.relative_to(PROJECT_ROOT)}")
            return cached["pembayang"], cached["maksud"]
        print("  cache is out of date (data or settings changed) - re-embedding")

    model = load_encoder(model_info)
    prefix = model_info["prefix"]
    start = time.time()
    vecs = model.encode(
        [prefix + t for t in pembayang + maksud],
        batch_size=BATCH_SIZE,
        normalize_embeddings=True,
        show_progress_bar=True,
        convert_to_numpy=True,
    )
    print(f"  embedded {len(vecs)} texts in {time.time() - start:.0f} s")

    n = len(pembayang)
    emb_p, emb_m = vecs[:n], vecs[n:]
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    np.savez(cache_file, key=key, ids=np.array(ids), pembayang=emb_p, maksud=emb_m)
    return emb_p, emb_m


def cosine_rowwise(a, b):
    """Cosine similarity between row i of a and row i of b (rows already unit length)."""
    return np.sum(a * b, axis=1)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    accepted, rejected = load_pantun()
    print(f"Loaded {len(accepted)} pantun ({len(rejected)} rows rejected by the loader)")

    ids = [p.id for p in accepted]
    pembayang = [p.pembayang for p in accepted]
    maksud = [p.maksud for p in accepted]

    scores = {}
    for m in MODELS:
        print(f"\n[{m['short']}] {m['name']}")
        emb_p, emb_m = get_embeddings(m, ids, pembayang, maksud)
        scores[m["short"]] = cosine_rowwise(emb_p, emb_m)
        s = scores[m["short"]]
        print(f"  score: mean {s.mean():.3f}, sd {s.std():.3f}, min {s.min():.3f}, max {s.max():.3f}")

    RESULTS_DIR.mkdir(exist_ok=True)
    with open(SCORES_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "label", "collection", "collection_type", "theme",
                         "pembayang", "maksud"] + [m["short"] for m in MODELS])
        for i, p in enumerate(accepted):
            writer.writerow([p.id, p.label, p.info["collection"], p.info["collection_type"],
                             p.info["theme"], p.pembayang, p.maksud]
                            + [f"{scores[m['short']][i]:.4f}" for m in MODELS])
    print(f"\nWrote {SCORES_CSV.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()
