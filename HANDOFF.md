# Handoff (read this first if you are joining or continuing the project)

Last updated: 18 Nov 2026 (tester form, lecturer dashboard, new videos). Owner: CaribbeanGreen. This note says where the project stands, how to get it
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
| `app_pages/penguji.py`, `src/tester.py` | Borang Penguji, and its results on Kongsi → 🧪 Penguji |
| `src/dashboard.py` | Pieces of the lecturer's Papan pemuka |
| `src/share.py` | Everything about sharing: accounts, roles, sign-up, classes, inquiries, guest codes, Kongsi page |
| `src/app_core.py` | Scoring, shared CSS/animations, CSV logs |
| `src/illus.py` | Irasutoya pictures and the sign-up celebration |
| `docs/sharing_guide.md` | Full guide to the sharing system, theory to checklists (start here for Kongsi) |
| `tutorial/` | Sources of the tutorial videos. **Change a screen? Update its page here and re-render** (see section 8) |

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
- Branch **`tester-dashboard-videos`** (Borang Penguji, lecturer Papan pemuka, kids-show look, re-made tutorial
  videos) was tried live by the owner and **merged into `main` on 23 Nov 2026** (fast-forward, pushed).
- Old branches `illustrations` and `business-case-sync` were merged and deleted.
- Hosting: temporary, via Cloudflare Tunnel at pantun.aimanjamal.com (**Start Sharing.bat**), off by default.
- **Owner admin from anywhere (23 Nov 2026):** https://studio.aimanjamal.com → Cloudflare Access login
  (email one-time code, owner emails only) → the app sees a signed token and treats the request like this
  computer (Kongsi page). Code: `src/access_login.py` + `is_visitor()` in `src/share.py`; tests:
  `tests/test_access_login.py`. Settings in `.env` (never in git): `PANTUN_ACCESS_TEAM`, `PANTUN_ACCESS_AUD`,
  `PANTUN_OWNER_EMAILS`. Cloudflare side: Zero Trust → Access controls → Applications → **Pantun Studio**
  (policy "owner only", login method One-time PIN only).
- Tunnel config lives outside the repo: `%USERPROFILE%\.cloudflared\pantun.yml` (routes pantun + studio).
  Use `http://127.0.0.1:8501`, **not** `localhost`: Windows resolves localhost to IPv6 `[::1]` first, Streamlit
  listens on IPv4 only, and visitors get 502 Bad gateway.

## 6. Follow-up list (open items)
Tick them off here when done.

- [x] Merge `illustrations` into `main` (done 17 Nov 2026).
- [x] Delete the old `illustrations` and `business-case-sync` branches (done 18 Nov 2026).
- [ ] Owner tries `tester-dashboard-videos` locally, then merge into `main`.
- [ ] Run a test round: Kongsi → 🧪 Penguji, switch the form on, create an account per friend, send the invite.
- [ ] After at least 20 sure ratings, read **Penalaan skor** and decide whether the meaning score needs changing (nothing changes automatically).
- [ ] Decide whether the GitHub repo should stay **public** (fine for a course project, but think about it
      before adding anything personal).
- [ ] Optional: a small showcase page on Vercel (Vercel cannot run Streamlit itself; it would only describe
      the app and link to it).
- [x] Teachers see when their own account ends (on Papan pemuka).
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

## 8. Re-making the tutorial videos
The videos are animated pages (`tutorial/*.html`, shared code in `stage.js`), not screen recordings, so they do not
update by themselves. After changing a screen, edit its page, then:
```
py -3.11 -m venv videnv
videnv\Scripts\pip install playwright imageio-ffmpeg
videnv\Scripts\python tutorial\render.py pelajar pensyarah penyelidik
```
It uses Microsoft Edge and writes `assets/tutorial/*.mp4` (about 10 to 20 minutes for all three). The pictures in
`assets/irasutoya/` must be on the computer.

## 9. Latest work (19 Nov 2026)
Merged into `main` on 23 Nov 2026 (from branch `tester-dashboard-videos`): bright kids-show look (`src/kids_theme.py`),
Irasutoya pictures instead of emoji and icons, a stage with 15 characters on each section (`SCENES` in `src/illus.py`),
and re-rendered tutorial videos. A browser check counted 16+ different pictures in all 17 app sections.

**Next:**
1. On a fresh clone, run `python tools/fetch_irasutoya.py` (pictures are not on GitHub).
2. ~~Owner tries the site, then push the branch and merge it into `main`.~~ Done 23 Nov 2026.
3. Commercial use would break Irasutoya's limit of 20 pictures per work: re-check the terms first.
