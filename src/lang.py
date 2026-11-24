"""Two languages for the whole app: Bahasa Melayu (default) and English.

How it works (kept deliberately simple, so each sentence can be read in both languages right where it is used):
    tr("Semak pantun", "Check a pantun")   -> the text in the visitor's chosen language
    role("pelajar")                         -> "Murid" or "Pupil" (role names live only here)

Each visitor chooses with the BM / EN switch at the top of every page (switch_lang()). The choice is kept for the
browser session and in the address (?lang=en), so it survives a page reload. Visitors who have not chosen get the
owner's default from the Settings page (share_state.json, "default_lang"; Bahasa Melayu if never set).

Internal names stay the same (page addresses /pelajar, /pensyarah, roles saved in the database), so existing links
and accounts keep working; only what people read changes.
"""

import streamlit as st

LANGS = {"ms": "BM", "en": "EN"}
DEFAULT = "ms"

# Display names of the roles. Target users are school pupils and their teachers (not university students).
ROLE_NAMES = {
    "pelajar": ("Murid", "Pupil"),
    "pensyarah": ("Cikgu", "Teacher"),
    "penyelidik": ("Penyelidik & Pakar", "Researcher & Expert"),
    "penguji": ("Penguji", "Tester"),
    "tetamu": ("Tetamu", "Guest"),
    "pelawat": ("Pelawat", "Visitor"),
}


def default_lang():
    """The owner's default language (Settings page). Imported here to avoid a circular import with share.py."""
    from src.share import state
    lang = state().get("default_lang", DEFAULT)
    return lang if lang in LANGS else DEFAULT


def current():
    """'ms' or 'en' for this visitor."""
    asked = st.query_params.get("lang")
    if asked in LANGS:                                   # a link or reload with ?lang=..
        st.session_state["cz_lang"] = asked
    return st.session_state.get("cz_lang") or default_lang()


def tr(ms, en):
    """The Malay or the English text, whichever this visitor reads."""
    return en if current() == "en" else ms


def role(key, lang=None):
    """Display name of a role ('pelajar' -> 'Murid' / 'Pupil'). lang='ms' forces Malay (used in the event log)."""
    ms, en = ROLE_NAMES.get(key, (key, key))
    return en if (lang or current()) == "en" else ms


def _changed():
    picked = st.session_state.get("cz_lang_pick")
    if picked in LANGS:
        st.session_state["cz_lang"] = picked
        st.query_params["lang"] = picked


def switch_lang():
    """The small BM / EN switch shown at the top of every page."""
    now = current()
    st.session_state.setdefault("cz_lang_pick", now)
    if st.session_state["cz_lang_pick"] != now:           # e.g. after ?lang= in the address
        st.session_state["cz_lang_pick"] = now
    st.segmented_control("Bahasa / Language", list(LANGS), format_func=LANGS.get, key="cz_lang_pick",
                         on_change=_changed, label_visibility="collapsed", required=True)
