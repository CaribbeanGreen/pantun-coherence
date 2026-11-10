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

st.set_page_config(page_title="Semak Pantun · Cenderawasih", page_icon=":material/menu_book:",
                   layout="wide")

logo = Path(__file__).parent / "assets" / "cenderawasih_logo.jpg"
if logo.exists():
    st.logo(str(logo), size="large")
fonts()          # Lora for pantun text, Nunito for the student view
start_warmup()   # load the models in the background so results come within 7 seconds (SRNF02)

page = st.navigation(
    [
        st.Page("app_pages/pelajar.py", title="Pelajar", icon=":material/school:", default=True),
        st.Page("app_pages/pensyarah.py", title="Pensyarah", icon=":material/co_present:"),
        st.Page("app_pages/penyelidik.py", title="Penyelidik & Pakar", icon=":material/science:"),
    ],
    position="top",
)
page.run()
