# Handoff — bilingual app + Murid/Cikgu (branch `bilingual-murid-cikgu`, 2026-11-24, limit at 98%)

**Do not merge to `main` until done and tested: a push to main deploys to the live NAS within ~1 min.**

## User decisions (final)
- Rename page **Kongsi → Tetapan / Settings** (owner page; new url_path `tetapan`).
- Display names: **Murid / Pupil** (role key `pelajar`), **Cikgu / Teacher** (`pensyarah`), **Penguji / Tester**,
  **Penyelidik & Pakar / Researcher & Expert** (`penyelidik`). Internal keys, URLs (/pelajar, /pensyarah) and DB
  roles stay unchanged. Target users are school pupils and teachers, not university students.
- Whole app in **one language at a time**: a **BM / EN switch each visitor flips** for themselves; **default BM**,
  owner can change the default in Settings (`share_state.json` key `default_lang`).
- Afterwards: a **spoken demo walkthrough script, in both Malay and English**, ~5 min, role by role:
  1. Murid  2. Cikgu  3. Cikgu + Penguji  4. Penyelidik & Pakar (for showing progress to the lecturer).

## Done
- `src/lang.py` (new, untested): `tr(ms, en)`, `role(key)`, `ROLE_NAMES`, `current()`, `default_lang()`,
  `switch_lang()` (segmented control, persists in session + `?lang=`).

## Next steps
1. `app.py`: import `role, switch_lang, tr`; VIEWS titles via `role()`; "Borang Penguji" → `tr("Borang Penguji",
   "Tester Form")`; owner page title `tr("Tetapan","Settings")`, `url_path="tetapan"`, icon `:material/settings:`;
   show `switch_lang()` at the top of every page (e.g. right-aligned container before `nav.run()`).
2. `src/share.py`: `ROLES` (line ~398) → Malay names via `lang.role(k, "ms")` for log notes; UI uses `lang.role(k)`
   (lines ~778, 1323, 1435, 1464); `owner_page()` title/tabs/captions bilingual + a "Bahasa lalai / Default
   language" control writing `default_lang`; `state()` setdefault `default_lang="ms"`; user_bar strings.
   Caption "jalankan Start Sharing.bat" is outdated (hosted on NAS now) — remove.
3. Translate pages one by one with `tr()`: pelajar.py (316 lines, mostly Malay), penguji.py (186), pensyarah.py
   (552, mixed), penyelidik.py (254, mostly English), then dashboard.py, tester.py, app_core.py, illus.py stages.
   Replace "Pelajar/Pensyarah/pelajar/pensyarah/student/lecturer" in display text with Murid/Cikgu (pupil/teacher).
4. Test locally (Start Demo.bat → localhost:8501, both languages, owner + `PANTUN_FORCE_GATE=1` visitor view),
   run `tests/*.py`, then merge to main (deploys to NAS) and check pantun.aimanjamal.com.
5. Write the bilingual demo script (docs/ or a doc for the lecturer).

Check usage (`get_usage`) regularly; write/update this file when near the 5-hour limit.
