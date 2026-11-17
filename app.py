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
from src.share import gate, is_visitor, owner_page

st.set_page_config(page_title="Semak Pantun · Cenderawasih", page_icon=":material/menu_book:",
                   layout="wide")

logo = Path(__file__).parent / "assets" / "cenderawasih_logo.jpg"
if logo.exists():
    st.logo(str(logo), size="large")
fonts()          # Lora for pantun text, Nunito for the student view
start_warmup()   # load the models in the background so results come within 7 seconds (SRNF02)
gate()           # visitors from the public address must type the current share code (src/share.py)

pages = [
    st.Page("app_pages/pelajar.py", title="Pelajar", icon=":material/school:", default=True),
    st.Page("app_pages/pensyarah.py", title="Pensyarah", icon=":material/co_present:"),
    st.Page("app_pages/penyelidik.py", title="Penyelidik & Pakar", icon=":material/science:"),
]
if not is_visitor():   # only on this computer: switch sharing on/off and see the code
    pages.append(st.Page(owner_page, title="Kongsi", icon=":material/share:", url_path="kongsi"))
nav = st.navigation(pages, position="top")

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
