# Project brief for Claude Code

## Goal
Measure pembayang–maksud coherence in Malay pantun empat kerat using pretrained transformer
sentence-embedding models. This is a measurement study, not model training.

- Pembayang = lines 1–2, maksud = lines 3–4.
- Coherence score = cosine similarity between the pembayang embedding and the maksud embedding.

## Environment
- Windows, Python 3.11, virtual env in `.venv`, CPU only (AMD GPU — do not attempt CUDA/ROCm setup).
- Corpus is small (hundreds of pantun), so CPU is fine.

## Build in phases — finish and verify one before starting the next
1. **Data loader** (`src/data_loader.py`): load `data/pantun.csv`, validate exactly 4 non-empty lines and a
   non-empty `source`, normalise whitespace/punctuation, return pembayang and maksud strings. Report rejected rows.
2. **Scoring** (`src/score.py`): embed pembayang and maksud with 2–3 models and compute cosine similarity.
   Candidates: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, `sentence-transformers/LaBSE`,
   `intfloat/multilingual-e5-base` (check its required "query: "/"passage: " prefixes). Optionally a Malay-specific
   embedding model from the Mesolitica org on Hugging Face — verify it is a sentence-embedding model first.
   Cache embeddings to disk. Output `results/scores.csv` (one row per pantun, one column per model).
3. **Evaluation** (`notebooks/evaluation.ipynb`):
   - Shuffled baseline: pair each pembayang with a random other pantun's maksud (fixed seed, several shuffles).
   - Compare real vs shuffled score distributions per model (histogram/boxplot), report mean difference,
     effect size and a significance test (e.g. Mann–Whitney U or permutation test).
   - If `label == mismatch` rows exist, check they score lower than real ones.
   - List the highest- and lowest-scoring real pantun for qualitative discussion.
4. **Demo** (`app.py`, Streamlit): paste a 4-line pantun → structure check, coherence score per model,
   percentile vs the corpus, plain-language explanation, and a "flag for expert review" option.
   Must not claim the score is an objective literary judgement.

## Rules
- Never generate or invent pantun to fill the dataset.
- Never tune the method just to make results look better; report negative findings honestly.
- Keep code simple and commented — this is a student project that will be explained in a viva.
