"""Borang Penguji: a guided form for friends who test the site and help tune the scores (src/tester.py).

Answers stay in this browser session while the tester moves between pages (Streamlit forgets a widget once its page
is left, so every answer is also copied to a draft). Scoring a pantun works like the pupil page.
Answers are saved in Malay; English readers see them through tester.shown().
"""

import streamlit as st

from src import illus, tester
from src.app_core import EXAMPLES, analyse, check_lines, example_name, lean_words, pantun_card
from src.lang import tr
from src.share import _client, allowed_views, current_user

ME = current_user()
DRAFT = "t_draft"
st.session_state.setdefault(DRAFT, {})


def keep(key):
    st.session_state[DRAFT][key] = st.session_state.get(key)


def field(widget, label, key, **kw):
    """A widget whose answer survives a visit to another page."""
    if key not in st.session_state and key in st.session_state[DRAFT]:
        st.session_state[key] = st.session_state[DRAFT][key]
    return widget(label, key=key, on_change=keep, args=(key,), **kw)


def value(key, default=None):
    return st.session_state.get(key, st.session_state[DRAFT].get(key, default))


def groups():
    views = allowed_views()
    return [(v, *g) for v, g in tester.tasks().items() if v == "akaun" or v in views]


def submit():
    tasks = {}
    for _, _, items in groups():
        for k, _ in items:
            result = value(f"t_task_{k}")
            if result:
                tasks[k] = (result, value(f"t_note_{k}", ""))
    stars = {k: (value(f"t_star_{k}") + 1 if value(f"t_star_{k}") is not None else None)
             for k, _ in tester.rating_questions()}
    try:
        tester.save_report(ME, _client()["ip"], value("t_name", ""), value("t_background", ""), value("t_device", ""),
                           value("t_browser", ""), tasks, stars, value("t_recommend", 7), value("t_liked", ""),
                           value("t_confusing", ""), value("t_ideas", ""))
    except ValueError as e:
        st.session_state["t_error"] = str(e)
        return
    for k in [k for k in st.session_state if str(k).startswith("t_")]:
        del st.session_state[k]
    st.session_state["t_sent"] = True


def score_pantun():
    lines, problems = check_lines([x for x in st.session_state["t_text"].splitlines() if x.strip()])
    st.session_state.pop("t_res", None)
    st.session_state["t_problems"] = problems
    if not problems:
        with st.spinner(tr("Menyemak pantun…", "Checking the pantun…")):
            st.session_state["t_res"] = analyse(lines)


def use_example(name):
    st.session_state["t_text"] = "\n".join(EXAMPLES[name])
    keep("t_text")
    st.session_state.pop("t_res", None)


def save_judgement():
    try:
        tester.save_rating(ME, _client()["ip"], value("t_name", ""), st.session_state["t_res"],
                           st.session_state.get("t_human"), st.session_state.get("t_mv"),
                           st.session_state.get("t_sv"), st.session_state.get("t_jc", ""))
    except ValueError as e:
        st.session_state["t_j_error"] = str(e)
        return
    st.session_state["t_count"] = st.session_state.get("t_count", 0) + 1
    for k in ("t_res", "t_human", "t_mv", "t_sv", "t_jc"):
        st.session_state.pop(k, None)
    st.session_state["t_text"] = ""
    keep("t_text")
    st.session_state["t_j_ok"] = True


# ---- Page -----------------------------------------------------------------------------------------
if st.session_state.pop("t_sent", False):
    illus.celebrate(tr("Terima kasih!", "Thank you!") + " <img class=cz-i alt src=/app/static/i/cracker.png>",
                    tr("Maklum balas anda sudah diterima dan akan membantu menambah baik Semak Pantun.",
                       "Your feedback has arrived and will help make Semak Pantun better."))
    st.success(tr("Borang dihantar. Anda boleh tutup halaman ini.", "Form sent. You can close this page."),
               icon=":material/check_circle:")
    st.stop()

illus.stage("penguji", tr("Borang Penguji", "Tester Form"),
            tr("Terima kasih kerana membantu! Lebih kurang 20 minit.", "Thank you for helping! About 20 minutes."),
            tr("Misi penguji", "Tester mission"))
st.caption(tr("Anda boleh buka halaman lain dalam tab ini untuk mencuba, kemudian kembali: jawapan anda kekal selagi "
              "tab ini tidak dimuat semula.",
              "You can open other pages in this tab to try things, then come back: your answers stay as long as "
              "this tab is not reloaded."))

all_tasks = [k for _, _, items in groups() for k, _ in items]
answered = sum(1 for k in all_tasks if value(f"t_task_{k}"))
judged = st.session_state.get("t_count", 0)
st.progress(min(1.0, (answered + min(judged, tester.RATING_TARGET)) / (len(all_tasks) + tester.RATING_TARGET)),
            text=tr(f"{answered}/{len(all_tasks)} ujian · {judged}/{tester.RATING_TARGET} pantun dinilai",
                    f"{answered}/{len(all_tasks)} tests · {judged}/{tester.RATING_TARGET} pantun rated"))

with st.container(border=True, key="t_about"):
    st.subheader(tr("1 · Tentang anda", "1 · About you"), anchor=False)
    c1, c2 = st.columns(2)
    pick = tr("Pilih", "Choose")
    with c1:
        if ME["kind"] == "member":
            st.session_state[DRAFT].setdefault("t_name", ME["name"])
        field(st.text_input, tr("Nama", "Name"), "t_name", max_chars=tester.LIMITS["short"])
        field(st.selectbox, tr("Latar belakang", "Background"), "t_background", options=tester.BACKGROUND, index=None,
              placeholder=pick, format_func=tester.shown)
    with c2:
        field(st.selectbox, tr("Peranti", "Device"), "t_device", options=tester.DEVICES, index=None, placeholder=pick,
              format_func=tester.shown)
        field(st.text_input, tr("Pelayar (pilihan)", "Browser (optional)"), "t_browser", max_chars=tester.LIMITS["short"],
              placeholder=tr("cth. Chrome, Safari", "e.g. Chrome, Safari"))

with st.container(border=True, key="t_tasks"):
    st.subheader(tr("2 · Cuba setiap tugasan", "2 · Try each task"), anchor=False)
    st.caption(tr("Tandakan hasilnya. Jika ada masalah, ceritakan apa yang anda buat dan apa yang berlaku.",
                  "Mark the result. If there was a problem, say what you did and what happened."))
    tabs = st.tabs([f"{illus.ic(tester.GROUP_PIC[g[0]])} {g[1]}" for g in groups()])
    for tab, (_, _, items) in zip(tabs, groups()):
        with tab:
            for k, text in items:
                st.markdown(f"**{text}**")
                result = field(st.segmented_control, tr("Hasil", "Result"), f"t_task_{k}", options=tester.RESULTS,
                               format_func=lambda r: f"{illus.ic(tester.RESULT_PIC[r])} {tester.shown(r)}",
                               label_visibility="collapsed")
                if result in tester.RESULTS[1:3]:
                    field(st.text_input, tr("Apa yang berlaku?", "What happened?"), f"t_note_{k}",
                          max_chars=tester.LIMITS["text"])

with st.container(border=True, key="t_tune"):
    st.subheader(tr("3 · Nilai skor pantun", "3 · Judge the pantun scores"), anchor=False)
    st.caption(tr(f"Bantu kami menala skor: semak sekurang-kurangnya **{tester.RATING_TARGET} pantun**, kemudian beri "
                  "pendapat anda. Cuba yang bagus, yang biasa, dan yang pembayangnya tidak berkaitan.",
                  f"Help us tune the scores: check at least **{tester.RATING_TARGET} pantun**, then give your opinion. "
                  "Try good ones, ordinary ones, and ones whose pembayang has nothing to do with the maksud."))
    with st.container(horizontal=True, vertical_alignment="center"):
        st.caption(tr("Contoh:", "Examples:"), width="content")
        for name in EXAMPLES:
            st.button(example_name(name), key=f"t_ex_{name}", type="tertiary", on_click=use_example, args=(name,))
    field(st.text_area, tr("Pantun (4 baris)", "Pantun (4 lines)"), "t_text", height=120,
          placeholder=tr("Satu baris pantun setiap baris", "One pantun line on each line"))
    st.button(tr("Semak skor", "Check the score"), key="t_go", type="primary", icon=":material/search:",
              on_click=score_pantun)
    for p in st.session_state.get("t_problems", []):
        st.warning(p, icon=":material/rule:")
    if st.session_state.pop("t_j_ok", False):
        st.success(tr("Penilaian disimpan. Cuba pantun seterusnya!", "Rating saved. Try the next pantun!"),
                   icon=":material/check:")
    res = st.session_state.get("t_res")
    if res:
        left, right = st.columns(2, gap="large")
        with left:
            pantun_card(res["lines"])
            icon, label, _ = lean_words(res["lean"])
            with st.container(horizontal=True):
                st.metric(tr("Bunyi", "Sound"), f"{res['sound']:g}/10", border=True)
                st.metric(tr("Makna", "Meaning"), f"{100 * res['p_avg']:.0f}%", border=True)
                st.metric(tr("Peraturan", "Rules"), f"{res['rules']}/4", border=True)
            st.caption(tr("Sistem", "System") + f": {icon} {label}")
        with right:
            st.segmented_control(tr("Pada pendapat anda, pembayang dan maksud…", "In your opinion, the pembayang and maksud…"),
                                 tester.HUMAN, key="t_human", format_func=tester.shown)
            st.segmented_control(tr("Skor Makna ini…", "This Meaning score is…"), tester.SCORE_VERDICT, key="t_mv",
                                 format_func=tester.shown)
            st.segmented_control(tr("Skor Bunyi ini…", "This Sound score is…"), tester.SCORE_VERDICT, key="t_sv",
                                 format_func=tester.shown)
            st.text_input(tr("Komen (pilihan)", "Comment (optional)"), key="t_jc", max_chars=tester.LIMITS["text"])
            st.button(tr("Simpan penilaian", "Save rating"), key="t_save", type="primary", icon=":material/save:", on_click=save_judgement,
                      disabled=not st.session_state.get("t_human"))
            if st.session_state.get("t_j_error"):
                st.error(st.session_state.pop("t_j_error"), icon=":material/error:")

with st.container(border=True, key="t_overall"):
    st.subheader(tr("4 · Pendapat keseluruhan", "4 · Overall opinion"), anchor=False)
    questions = tester.rating_questions()
    cols = st.columns(len(questions))
    for col, (k, label) in zip(cols, questions):
        with col:
            st.markdown(f"**{label}**")
            if f"t_star_{k}" not in st.session_state and f"t_star_{k}" in st.session_state[DRAFT]:
                st.session_state[f"t_star_{k}"] = st.session_state[DRAFT][f"t_star_{k}"]
            st.feedback("stars", key=f"t_star_{k}", on_change=keep, args=(f"t_star_{k}",))
    st.session_state[DRAFT].setdefault("t_recommend", 7)
    field(st.slider, tr("Sejauh mana anda akan mencadangkan laman ini kepada rakan? (0 hingga 10)",
                        "How likely are you to recommend this site to a friend? (0 to 10)"), "t_recommend",
          min_value=0, max_value=10)
    field(st.text_area, tr("Apa yang paling anda suka?", "What did you like most?"), "t_liked",
          max_chars=tester.LIMITS["text"], height=80)
    field(st.text_area, tr("Apa yang mengelirukan atau rosak?", "What was confusing or broken?"), "t_confusing",
          max_chars=tester.LIMITS["text"], height=80)
    field(st.text_area, tr("Apa yang patut ditambah atau diubah?", "What should be added or changed?"), "t_ideas",
          max_chars=tester.LIMITS["text"], height=80)

if st.session_state.get("t_error"):
    st.error(st.session_state.pop("t_error"), icon=":material/error:")
st.button(tr("Hantar borang", "Send the form"), key="t_submit", type="primary", icon=":material/send:", on_click=submit, width="stretch")
