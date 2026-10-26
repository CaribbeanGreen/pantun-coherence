# Measuring Pembayang–Maksud Coherence in Malay Pantun Using Transformer Embeddings

CSC575 project (Group T-CDCS2306B1).

> **Private data.** The pantun library in `data/raw/` (and everything derived from it:
> `data/pantun.csv`, `results/`, the executed notebook) must not be shared outside this computer.
> It is excluded in `.gitignore`, the demo only runs on `localhost`, and no pantun text is sent
> to online services. Code and documentation can be shared; the data cannot.

## Setup (Windows, CPU only)
```
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
```

## Folders
- `data/pantun.csv` — corpus (one pantun empat kerat per row, source required)
- `src/` — code
- `notebooks/` — evaluation notebook
- `results/` — scores and charts

## Building the corpus
The book spreadsheets live in `data/raw/`. `data/pantun.csv` is generated from them:
```
python -m src.build_corpus     # data/raw/*.xlsx -> data/pantun.csv (+ data/skipped_from_raw.csv)
python -m src.data_loader      # validate + clean, prints accepted/rejected report
python tests/test_data_loader.py
```
Excluded: `Gurindam Hidup` (gurindam, not pantun) and the `Kurik Kundi Merah Saga` PDF (not extracted yet).

## Running the phases
```
python -m src.score                     # Phase 2: results/scores.csv (+ cached embeddings, ~10 min on CPU first time)
jupyter notebook notebooks/evaluation.ipynb   # Phase 3: baselines, statistics, charts, findings
streamlit run app.py                    # Phase 4: demo (or double-click "Start Demo.bat")
```
Phase 3 writes `results/baseline_summary.csv`, `overlap_summary.csv`, `by_collection.csv`,
`methods_comparison.csv`, `calibration.json`, `top_pantun.csv`, `bottom_pantun.csv` and the
`fig_*.png` charts.

Methods: five pretrained embedding models for the **meaning link** (see `src/score.py`; the
Malay Mesolitica model is loaded by `src/malay_embedding.py` without running remote code) and a
rule-based end-rhyme check for the **sound link** (`src/rhyme.py`, tests in `tests/test_rhyme.py`), and
rule-based checks of traditional pantun criteria (`src/criteria.py`, tests in `tests/test_criteria.py`).
Model choice and related research: `docs/related_work.md`. The demo saves flagged pantun
to `results/expert_review_flags.csv`.

## Data columns
`id, line1, line2, line3, line4, source, label, collection, collection_type, theme`
- `collection_type`: `traditional_anthology` (Zainal Abidin Bakar, compiled from older sources),
  `author_collection` (written by the named author) or `editorial_compilation` (DBP)
- `label`: `real` for an authentic pantun, `mismatch` for a deliberately mismatched test pantun
- Every row must have a `source`. Do not add AI-generated pantun.
