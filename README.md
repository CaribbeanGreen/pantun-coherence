# Measuring Pembayang–Maksud Coherence in Malay Pantun Using Transformer Embeddings

CSC575 project (Group T-CDCS2306B1).

> **Private data.** The pantun library in `data/raw/` (and everything derived from it:
> `data/pantun.csv`, `results/`, the executed notebook) must not be shared outside this computer.
> It is excluded in `.gitignore`, the demo only runs on `localhost`, and no pantun text is sent
> to online services. Code and documentation can be shared; the data cannot.

## How to run the demo (quick start)
The project lives in `D:\CODES\pantun-coherence`. Setup (below) only has to be done once.

**Easiest:** double-click **`Start Demo.bat`**. A black window opens and your browser opens
http://localhost:8501. Keep the black window open while you use the demo, and close it to stop.

**From PowerShell:**
```
cd D:\CODES\pantun-coherence
.venv\Scripts\activate
streamlit run app.py
```
Then open http://localhost:8501 (stop with `Ctrl+C`).

What to expect:
- The page appears in a few seconds. The five models then load in the background (about 1–2 minutes
  after starting). After that each check takes 1–4 seconds (business case SRNF02: under 7 seconds).
- Three views at the top, as in the business case (Section 6):
  - **Pelajar** (students): Semak Pantun, Belajar Pantun and Sejarah Saya tabs. Form and result side
    by side on a desktop, stacked on a phone.
  - **Pensyarah** (instructors): side menu with Kelas saya (class CSV upload, work list, decisions),
    Semakan (student requests, decision log) and Laporan (summary, CSV and PDF export).
  - **Penyelidik & Pakar** (researchers / experts): per-model numbers, findings, expert queue and rating form.
- Needs `data/pantun.csv` and `results/` (made by the steps below). Uses about 9.5 GB RAM.
- If the folder is moved to another drive, `.venv` stops working. Delete `.venv` and run Setup again.

## Sharing online for a while (pantun.aimanjamal.com)
The app can be opened from anywhere through a Cloudflare Tunnel, protected by a code:
1. Start the demo (`Start Demo.bat`), then double-click **`Start Sharing.bat`**. Keep its window open;
   close it to take the site offline.
2. In the demo on this computer, open the **Kongsi** page (only shown here, never to visitors), choose how
   long (30 min – 8 h) and press **Hidupkan perkongsian**.
3. Give visitors the 6-digit code shown there. It changes every 15 seconds; the previous code is also accepted.

While sharing is off (or after the time runs out) visitors only see "Perkongsian ditutup" and no code works.
Switching sharing off locks out everyone who is already in (within 20 seconds). Code: `src/share.py`.
Tunnel settings: `%USERPROFILE%\.cloudflared\pantun.yml` (keep the credentials file there secret).

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
