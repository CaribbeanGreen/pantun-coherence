# Handoff — bilingual app + Murid/Cikgu (branch `bilingual-murid-cikgu`)

Last updated: 24 Nov 2026 (afternoon). **Do not merge to `main` without the owner's go-ahead: a push to main deploys
to the live NAS within ~1 min.**

## User decisions (final)
- Rename page **Kongsi → Tetapan / Settings** (owner page; url_path `tetapan`).
- Display names: **Murid / Pupil** (role key `pelajar`), **Cikgu / Teacher** (`pensyarah`), **Penguji / Tester**,
  **Penyelidik & Pakar / Researcher & Expert** (`penyelidik`). Internal keys, URLs (/pelajar, /pensyarah) and DB
  roles stay unchanged. Target users are school pupils and teachers, not university students.
- Whole app in **one language at a time**: a **BM / EN switch each visitor flips** for themselves; **default BM**,
  owner can change the default in Settings (`share_state.json` key `default_lang`).
- Afterwards: a **spoken demo walkthrough script, in both Malay and English**, ~5 min, role by role:
  1. Murid  2. Cikgu  3. Cikgu + Penguji  4. Penyelidik & Pakar (for showing progress to the lecturer).

## Done (all committed on the branch, not pushed yet unless noted in git)
- `src/lang.py`: `tr(ms, en)`, `role(key)`, `switch_lang()`; outside Streamlit (tests) it returns Malay.
- `app.py`: BM / EN switch at the top of every page **and the login screen** (chosen one is a filled green pill),
  page titles from `role()`, owner page = Tetapan / Settings at `/tetapan`.
- `src/share.py`: login, sign-up, error messages, user bar, Settings page (Members, Access, Tester, **Language**
  tab with the default-language control, Log). Event log stays in Malay on purpose (one language for records).
- Pages translated: `pelajar.py`, `penguji.py`, `pensyarah.py` (menu uses fixed keys now), `penyelidik.py`
  (now has Malay too); helpers `app_core.py` (`lean_words`, `example_name`, `check_lines`/`tour`/`help_button`
  follow the language), `dashboard.py`, `tester.py`.
- Saved data does not change with the language: tester answers stay Malay (`tester.shown()` translates for
  display), expert ratings stay English (`penyelidik.shown()`), teacher decisions keep keys `setuju/ubah/pakar`.
- Tested 24 Nov: all `tests/*.py` pass; local owner (8502) + visitor (8503) copies on a throwaway
  `PANTUN_SHARE_DIR`: every page in both languages without errors, pupil result, teacher sample class, teacher
  sign-up in EN (errors + celebration in EN), owner approval list in BM, default language EN → new visitor sees EN.
  Launch configs: `.claude/launch.json` (`pantun-test-owner`, `pantun-test-visitor`).

## Next steps
1. Owner tries the branch locally (Start Demo.bat), then decide: merge into `main` (deploys to the NAS) and check
   pantun.aimanjamal.com.
2. Write the bilingual demo script (see decisions above).
3. Known gaps: the tutorial videos for Murid and Cikgu are Malay only (the English help text says so; re-render
   with English pages later if wanted, see HANDOFF.md section 8). Table contents of research result CSVs stay
   English. `HANDOFF.md` still says "Kongsi" for the live `main`; update it when this branch is merged.
