# Handoff (read this first if you are joining or continuing the project)

Last updated: 18 Nov 2026. Owner: CaribbeanGreen. This note says where the project stands, how to get it
running, and what is left to do, so anyone (a classmate, a lecturer, or a future you) can carry on.

## 1. What this is
**Semak Pantun** (CSC575, Cenderawasih): a Streamlit web app that checks a Malay *pantun empat kerat*
(rhyme, syllables, and how well the pembayang fits the maksud using transformer embeddings). It has three
views: **Pelajar** (students), **Pensyarah** (lecturers) and **Penyelidik** (researchers / experts), plus a
**Kongsi** page for the owner to share the app online with accounts, class codes and guest access.

## 2. Get it running (Windows)
1. Install Python 3.11+, then in the project folder:
   ```
   python -m venv .venv
   .venv\Scripts\pip install -r requirements.txt
   ```
2. Double-click **Start Demo.bat** (or `.venv\Scripts\streamlit run app.py`). It opens http://localhost:8501.
3. On your own computer you are the **owner** (no login). To see what a visitor sees, set
   `PANTUN_FORCE_GATE=1` before starting.
4. To try things without touching real accounts, set `PANTUN_SHARE_DIR` to an empty folder: the app then
   makes a fresh `share.db` there.

What a fresh clone does **not** have (private or not redistributable, see `.gitignore`):
- `data/pantun.csv` and `data/raw/` (the pantun library) and `results/` (accounts database, logs).
  Ask the owner; never upload them anywhere.
- `assets/irasutoya/*.png` (illustrations). Download them from the pages listed in
  `assets/irasutoya/CREDITS.md`; without them the app simply shows no pictures.
- `models/` (downloaded on first run).

## 3. Where things are
| File | What it does |
|---|---|
| `app.py` | Entry point: login gate, which pages each role sees, top bar |
| `app_pages/pelajar.py`, `pensyarah.py`, `penyelidik.py` | The three views |
| `src/share.py` | Everything about sharing: accounts, roles, sign-up, classes, inquiries, guest codes, Kongsi page |
| `src/app_core.py` | Scoring, shared CSS/animations, CSV logs |
| `src/illus.py` | Irasutoya pictures and the sign-up celebration |
| `docs/sharing_guide.md` | Full guide to the sharing system, theory to checklists (start here for Kongsi) |
| `tutorial/` | Tutorial videos for each view |

## 4. Git rules for this repo
- `main` is the stable version. Work on a **branch**, try it locally, then merge.
- The repo is **public**: never commit the pantun library, `results/`, `.env`, tunnel credentials
  (`*.json` in `.cloudflared`), `cert.pem` or Irasutoya images. Check `git status` before every commit.
- No AI co-author lines in commit messages (owner's preference).

## 5. Current state
- **`main` is up to date** with everything below; work on a new branch from it.
- Latest work (all merged): Irasutoya pictures and sign-up celebration; same-name check at sign-up;
  lecturer-expiry handling (classes without an active lecturer, Pindah kelas, expiry warnings, 1-year
  lecturer accounts, retired usernames); fix for the Semakan crash after answering an inquiry.
- Old branches `illustrations` and `business-case-sync` are fully merged and can be deleted.
- Hosting: temporary, via Cloudflare Tunnel at pantun.aimanjamal.com (**Start Sharing.bat**), off by default.

## 6. Follow-up list (open items)
Tick them off here when done.

- [x] Merge `illustrations` into `main` (done 17 Nov 2026).
- [ ] Delete the old `illustrations` and `business-case-sync` branches (local and GitHub).
- [ ] Decide whether the GitHub repo should stay **public** (fine for a course project, but think about it
      before adding anything personal).
- [ ] Optional: a small showcase page on Vercel (Vercel cannot run Streamlit itself; it would only describe
      the app and link to it).
- [ ] Optional: let teachers see when their own account ends (today only the owner sees the warning).
- [ ] Optional: email reminders before a lecturer account ends (needs an email service; not set up).
- [ ] Optional: export of a class's inquiries to PDF/CSV for the lecturer's records.
- [ ] Before any paid/commercial use: re-check Irasutoya's terms (max 20 images per commercial work) and the
      licence of every dataset in `data/external/`.

## 7. How to test a change quickly
```
set PANTUN_SHARE_DIR=%TEMP%\pantun-test
.venv\Scripts\streamlit run app.py --server.port 8502
```
That one is the owner view. In a second terminal start a visitor view on the same test data:
```
set PANTUN_SHARE_DIR=%TEMP%\pantun-test
set PANTUN_FORCE_GATE=1
.venv\Scripts\streamlit run app.py --server.port 8503
```
Then walk through: sign up as a lecturer on 8503, approve on 8502 (Kongsi), create a class, sign up a student
with its code, send an inquiry, answer it.
