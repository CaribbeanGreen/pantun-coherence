# Measuring Pembayang–Maksud Coherence in Malay Pantun Using Transformer Embeddings

> **Joining the project or picking it up later?** Start with [docs/FOLLOW_UP.md](docs/FOLLOW_UP.md): setup, where things are, git rules and the open follow-up list.

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

## Sharing online (pantun.aimanjamal.com)
The app can be opened from anywhere through a Cloudflare Tunnel:
- **Accounts**: students sign up with a **class code** from their teacher; teachers sign up and wait for your
  approval; experts or anyone else you create on the **Kongsi** page (only shown on this computer). Each
  person sees only their own views (student / teacher + expert mode / expert). Every login is kept.
- **Classes and inquiries**: teachers create classes and codes, manage their students, and answer their
  students' "Saya tidak setuju" inquiries. Guest inquiries go to all teachers and are deleted when guest
  access ends.
- **Access without an account** (Kongsi): 🔒 Tutup (accounts only), 🎟️ Kod sahaja (30-second guest code) or
  🌐 Terbuka (anyone can use the student page), for a time you choose.
- **Lecturer accounts ending**: their classes stop taking new students and you see their inquiries;
  Kongsi warns 3 days ahead and can move a class to another lecturer (**Pindah**).

To go online: start `Start Demo.bat`, then double-click **`Start Sharing.bat`** (keep its window open; close it
to go offline). Data stays on this computer in `results/share.db` (SQLite; keys stored only as scrypt hashes).
Full explanation, theory, checklists and rebuild guide: `docs/sharing_guide.md`. Code: `src/share.py`.
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

## Illustrations (いらすとや)
The friendly pictures (login key, pantun nature images, cheering buddy, sign-up celebration) are by Irasutoya
(https://www.irasutoya.com/), used free for this non-commercial course project. Their terms forbid
redistributing the images, and this repository is public, so the files stay on this computer in
`assets/irasutoya/` (git-ignored). `assets/irasutoya/CREDITS.md` lists each file and its page so they can be
downloaded again. Without the folder the app still works, just without pictures. Code: `src/illus.py`.
