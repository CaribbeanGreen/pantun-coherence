"""Pantun Checker by Cenderawasih — Phase 4 demo, designed as in the business case (Section 6).

Three views, one for each group of users (Exhibit 1 = design system):
    Pelajar     (students, Exhibits 2-3)           - Malay, desktop or phone, dials and praise first
    Pensyarah   (instructors, Exhibit 4)           - Malay, class upload, work queue, CSV/PDF export
    Penyelidik  (researchers / experts, Exhibit 5) - English, every number, expert rating form

Start it by double-clicking "Start Demo.bat", or from a terminal:
    streamlit run app.py

The scores are similarities between sentence embeddings plus rule checks. They are NOT an
objective judgement of literary quality, and every view says so.
"""

from pathlib import Path

import streamlit as st

from src.app_core import fonts, start_warmup
from src.lang import role, switch_lang, tr
from src.share import allowed_views, current_user, gate, is_visitor, owner_page, state, user_bar

st.set_page_config(page_title="Semak Pantun · Cenderawasih", page_icon=":material/menu_book:",
                   layout="wide")

logo = Path(__file__).parent / "assets" / "cenderawasih_logo.jpg"
if logo.exists():
    st.logo(str(logo), size="large")
fonts()          # Lora for pantun text, Nunito for the student view
start_warmup()   # load the models in the background so results come within 7 seconds (SRNF02)
st.html("""<style>
.st-key-cz_langbar button[aria-checked="true"] { background: #1E9A50 !important; border-color: #1E9A50 !important; }
.st-key-cz_langbar button[aria-checked="true"] p { color: #fff !important; font-weight: 800; }
</style>""")   # the chosen language is a filled green pill, the other stays white
with st.container(horizontal=True, horizontal_alignment="right", key="cz_langbar"):
    switch_lang()  # BM / EN, each visitor chooses for themselves (src/lang.py); also on the login screen
gate()           # visitors from the public address must type the current share code (src/share.py)

# Each person sees only the views their role allows (src/share.py ROLE_VIEWS), and lands on their own one:
# students and guests on Pelajar, lecturers on Pensyarah, experts on Penyelidik. The owner sees all.
# Titles come from src/lang.py (Murid / Pupil, Cikgu / Teacher, ...); the page addresses stay /pelajar, /pensyarah.
VIEWS = {"pelajar": ("app_pages/pelajar.py", role("pelajar"), ":material/school:"),
         "pensyarah": ("app_pages/pensyarah.py", role("pensyarah"), ":material/co_present:"),
         "penyelidik": ("app_pages/penyelidik.py", role("penyelidik"), ":material/science:")}
allowed = allowed_views()
home = allowed[0] if current_user()["kind"] == "member" else "pelajar"
# Pelajar is always the default page (served at "/"); a page marked default loses its own address, so making
# Pensyarah the default gave "Page not found" at /pensyarah. Teachers and experts are sent home once instead.
by_view = {v: st.Page(VIEWS[v][0], title=VIEWS[v][1], icon=VIEWS[v][2], default=(v == "pelajar"))
           for v in ["pelajar", "pensyarah", "penyelidik"] if v in allowed}
pages = list(by_view.values())
if not is_visitor() or state()["tester_open"]:   # visitors see the tester form only while the owner has it open
    pages.append(st.Page("app_pages/penguji.py", title=tr("Borang Penguji", "Tester Form"),
                         icon=":material/rate_review:", url_path="penguji"))
if not is_visitor():   # only on this computer: members, guest code, devices and log
    pages.append(st.Page(owner_page, title=tr("Tetapan", "Settings"), icon=":material/settings:",
                         url_path="tetapan"))
nav = st.navigation(pages, position="top")
if home != "pelajar" and not st.session_state.get("cz_home_done"):
    st.session_state["cz_home_done"] = True
    if nav.url_path in ("", "pelajar"):
        st.switch_page(by_view[home])
user_bar()             # visitors: "name · role · Log keluar"

# On a phone Streamlit hides the top menu behind a small button, so visitors only saw the first view.
# This row of links shows the views on narrow screens only.
st.html("""<style>
.st-key-cz_mobnav { display: none; }
@media (max-width: 767px) {
  .st-key-cz_mobnav { display: flex; gap: 6px; overflow-x: auto; padding: 4px 0 10px;
                      border-bottom: 1px solid rgba(222, 178, 81, .45); margin-bottom: 6px; }
  .st-key-cz_mobnav [data-testid="stPageLink"] a { background: #fff; border: 1.5px solid #E3DCCB; border-radius: 999px;
                      padding: 4px 12px; white-space: nowrap; }
}
</style>""")
with st.container(key="cz_mobnav", horizontal=True):
    for p in pages:
        st.page_link(p, label=p.title, icon=p.icon, width="content")
nav.run()

# Small credit for the illustrations (only when they are on this computer; see src/illus.py)
from src import illus  # noqa: E402
if illus.available():
    st.caption(f"<div style='text-align:center;opacity:.7'>{illus.CREDIT}</div>", unsafe_allow_html=True)
