"""Student view (business case Section 6.2, Exhibits 2 and 3): Malay, praise first, never "failure".

Top menu (Exhibit 2, label 2): Semak Pantun, Belajar Pantun, Sejarah Saya.
On a desktop the form is on the left and the result on the right; on a phone they stack (Exhibit 3).
"""

import html
from datetime import datetime

import pandas as pd
import streamlit as st

from src.app_core import (CHECK, EXAMPLES, GOLD, TEAL, LEAN_MALAY, analyse, banner, card, card_html, cards_row,
                          check_lines, dial, dials, load_calibration, pantun_card, rhyme_text, save_flag)

KEYS = ["s_l1", "s_l2", "s_l3", "s_l4"]

# Nunito for this view only (Exhibit 1: round letters feel friendly). Large buttons for fingers (Exhibit 3, label 3).
st.html("<style>.st-key-pelajar, .st-key-pelajar input, .st-key-pelajar button, .st-key-pelajar p"
        " {font-family:'Nunito',sans-serif !important}"
        ".st-key-pelajar input {font-family:'Lora',serif !important; font-size:1.1rem}"
        ".st-key-pelajar button[kind=primary] {min-height:48px; font-size:1.05rem}</style>")

for k in KEYS:
    st.session_state.setdefault(k, "")
if not any(st.session_state[k] for k in KEYS):
    for k, line in zip(KEYS, EXAMPLES["Pisang emas"]):
        st.session_state[k] = line
st.session_state.setdefault("s_history", [])


def use_lines(lines):
    for k, line in zip(KEYS, lines):
        st.session_state[k] = line
    st.session_state.pop("s_result", None)


def check_now():
    lines, problems = check_lines([st.session_state[k] for k in KEYS])
    st.session_state.pop("s_result", None)
    st.session_state["s_problems"] = problems
    if not problems:
        res = analyse(lines)
        st.session_state["s_result"] = res
        st.session_state["s_history"].insert(0, {"time": datetime.now(), "lines": lines, "sound": res["sound"],
                                                 "meaning": res["p_avg"], "rules": res["rules"],
                                                 "lean": res["lean"]})


def write_screen():
    """Screen A (Exhibit 3): write a pantun."""
    st.markdown(":blue-badge[🖼️ **Pembayang** · baris 1–2]")
    st.text_input("Baris 1", key="s_l1", label_visibility="collapsed", placeholder="Baris 1")
    st.text_input("Baris 2", key="s_l2", label_visibility="collapsed", placeholder="Baris 2")
    st.markdown(":orange-badge[💬 **Maksud** · baris 3–4]")
    st.text_input("Baris 3", key="s_l3", label_visibility="collapsed", placeholder="Baris 3")
    st.text_input("Baris 4", key="s_l4", label_visibility="collapsed", placeholder="Baris 4")

    if st.button("Semak Pantun Saya", type="primary", icon=":material/search:", width="stretch"):
        with st.spinner("Membaca pantun anda…"):
            check_now()
    for p in st.session_state.get("s_problems", []):
        st.warning(p, icon=":material/edit:")

    with st.container(horizontal=True, vertical_alignment="center"):
        st.caption("Tiada pantun? Cuba contoh:")
        for name in EXAMPLES:
            st.button(name, key=f"s_ex_{name}", type="tertiary", on_click=use_lines, args=(EXAMPLES[name],))

    card("", "📘 <b>Tahukah anda?</b> Pembayang selalunya menggunakan unsur alam seperti buah, laut dan "
         "burung. Ia memberi <b>petunjuk</b> kepada maksud.")


def result_screen(res):
    """Screen B (Exhibits 2 and 3, labels 5-7): dials, praise, tip, reminder, disagree button."""
    if res["sound"] == 10 and res["rules"] == 4:
        headline = "Bagus! Rima anda cantik 🎉"
    elif res["sound"] >= 7.5:
        headline = "Hampir sempurna! 👏"
    elif res["rules"] >= 3:
        headline = "Usaha yang baik! 👍"
    else:
        headline = "Mari cuba lagi bersama! 💪"   # a low score is never shown as failure
    banner("Hasil semakan", headline)

    _, _, meaning_caption = LEAN_MALAY[res["lean"]]
    meaning_colour = GOLD if res["lean"] != "not_belong" else CHECK
    dials([
        dial(f"{res['sound']:g}/10", res["sound"] / 10, TEAL, "Bunyi", "Rima a-b-a-b", "🎵"),
        dial(f"{100 * res['p_avg']:.0f}%", res["p_avg"], meaning_colour, "Makna", meaning_caption, "💭"),
        dial(f"{res['rules']}/4", res["rules"] / 4, "#1B6E78", "Peraturan", "Bentuk pantun", "📋"),
    ])

    # What you did well (praise first)
    crit = {c["name"].split(" ")[0]: c["passed"] for c in res["criteria"]}
    good = ["4 baris lengkap"]
    if crit.get("8–12"):
        good.append("8–12 suku kata setiap baris")
    if crit.get("End"):
        good.append(f"Rima akhir {rhyme_text(res)}")
    if crit.get("Pembayang"):
        good.append("Pembayang guna unsur alam")
    if res["bonus"]:
        good.append("Bonus ⭐ rima tengah")

    # One tip
    if res["shared"]:
        tip = (f'Perkataan <b>"{html.escape(res["shared"][0])}"</b> muncul dalam kedua-dua bahagian. '
               "Itu satu petunjuk yang baik!")
    elif not crit.get("End"):
        tip = "Cuba pastikan baris 1 berima dengan baris 3, dan baris 2 dengan baris 4 (a-b-a-b)."
    elif not crit.get("8–12"):
        tip = "Cuba jadikan setiap baris 8 hingga 12 suku kata."
    elif not crit.get("Pembayang"):
        tip = "Cuba gunakan unsur alam dalam pembayang, seperti buah, laut atau burung."
    else:
        tip = "Pastikan pembayang memberi petunjuk kepada maksud, melalui bunyi, perkataan atau kiasan."

    # Side by side on a desktop, stacked on a phone
    cards_row([
        card_html("Apa yang anda buat dengan baik", "<br>".join(f"✅ {html.escape(g)}" for g in good),
                  background="#E8F0EF", border="#C9DEDB"),
        card_html("💡 Petua", tip),
    ])
    card("", "🤝 <b>Ingat:</b> komputer belum pandai faham kiasan. Skor rendah <b>tidak</b> bermaksud "
         "pantun anda tidak baik. Guru anda membuat keputusan akhir.",
         background="#F8ECCF", border="#EBD39A")

    with st.expander("Kenapa skor makna dekat 50%?", icon=":material/help:"):
        test = load_calibration()["held_out_test"]
        st.markdown(
            "Pembayang dan maksud biasanya tentang **perkara yang berbeza** — itulah keindahan pantun. "
            "Komputer hanya boleh lihat sama ada topiknya serupa, jadi ia sukar menilai **kiasan**. "
            f"Untuk **{100 * test['share_cannot_tell']:.0f}%** pantun, komputer tidak pasti. "
            f"Apabila skor **60% atau lebih**, ia betul kira-kira **{100 * test['accuracy_when_it_leans']:.0f}%** "
            "daripada masa itu.")

    with st.popover("🙋 Saya tidak setuju — minta guru semak", width="stretch"):
        with st.form("s_flag", border=False):
            who = st.text_input("Nama atau ID pelajar (pilihan)")
            comment = st.text_area("Kenapa anda tidak setuju? (pilihan)")
            if st.form_submit_button("Hantar kepada guru", type="primary"):
                save_flag("pelajar", res["lines"], res, comment, who)
                st.success("Terima kasih! Guru anda akan menyemak pantun ini.")


def learn_screen():
    """Belajar Pantun: the parts of a pantun empat kerat that the checker looks at."""
    st.subheader("Mengenal pantun empat kerat", anchor=False)
    left, right = st.columns(2, gap="large")
    with left:
        pantun_card(EXAMPLES["Pisang emas"])
        st.caption("Baris 1–2 (teal) ialah **pembayang**. Baris 3–4 (perang) ialah **maksud**.")
    with right:
        st.markdown(
            "**1. Empat baris.** Pantun empat kerat ada 4 baris: 2 baris pembayang dan 2 baris maksud.\n\n"
            "**2. Pembayang.** Selalunya tentang alam: buah, laut, burung, pokok. Ia menyediakan bunyi "
            "dan memberi petunjuk kepada maksud.\n\n"
            "**3. Maksud.** Inilah pesanan sebenar pantun, contohnya nasihat atau budi.\n\n"
            "**4. Rima a-b-a-b.** Bunyi akhir baris 1 sama dengan baris 3, dan baris 2 sama dengan baris 4 "
            "(belay**ar** / dibay**ar**, pe**ti** / ma**ti**).\n\n"
            "**5. Suku kata.** Setiap baris biasanya ada 8 hingga 12 suku kata.\n\n"
            "**6. Kiasan.** Pembayang sering mengiaskan maksud. Komputer belum pandai menilai kiasan, "
            "jadi guru membuat keputusan akhir.")
    st.markdown("**Cuba sendiri**")
    with st.container(horizontal=True):
        for name in EXAMPLES:
            if st.button(f"Guna \"{name}\"", key=f"s_learn_{name}", type="secondary",
                         on_click=use_lines, args=(EXAMPLES[name],)):
                st.toast("Contoh dimasukkan. Buka tab **Semak Pantun** dan tekan butang semak.", icon="✨")


def history_screen():
    """Sejarah Saya: the pantun checked in this session (kept in the browser session only)."""
    hist = st.session_state["s_history"]
    if not hist:
        st.info("Belum ada pantun yang disemak. Semak satu pantun dan ia akan muncul di sini.",
                icon=":material/history:")
        return
    table = pd.DataFrame([{
        "Masa": f"{h['time']:%H:%M}", "Baris 1": h["lines"][0], "Baris 3": h["lines"][2],
        "Bunyi": f"{h['sound']:g}/10", "Makna": f"{100 * h['meaning']:.0f}%", "Peraturan": f"{h['rules']}/4",
    } for h in hist])
    ev = st.dataframe(table, hide_index=True, on_select="rerun", selection_mode="single-row", key="s_hist_table",
                      alt="Pantun yang anda semak dalam sesi ini")
    sel = ev.selection.rows if ev and ev.selection else []
    if sel:
        pantun_card(hist[sel[0]]["lines"])
        if st.button("Buka semula pantun ini", icon=":material/edit:", on_click=use_lines,
                     args=(hist[sel[0]]["lines"],)):
            st.toast("Pantun dimasukkan semula. Buka tab **Semak Pantun**.", icon="✏️")
    st.caption(f"{len(hist)} pantun disemak dalam sesi ini. Sejarah hilang apabila tab pelayar ditutup.")


# ---- Page -------------------------------------------------------------------------------------------
_, middle, _ = st.columns([1, 12, 1])
with middle.container(key="pelajar"):
    banner("Cenderawasih · Semak Pantun", "Semak Pantun Anda ✨",
           "Adakah pembayang dan maksud anda sepadan? Tulis 4 baris, kemudian tekan butang.")
    tab_check, tab_learn, tab_hist = st.tabs(["🔍 Semak Pantun", "📘 Belajar Pantun", "🕘 Sejarah Saya"])
    with tab_check:
        left, right = st.columns([1, 1], gap="large")
        with left:
            write_screen()
        with right:
            res = st.session_state.get("s_result")
            if res:
                result_screen(res)
            else:
                card("Hasil semakan", "Hasil anda akan muncul di sini: <b>Bunyi</b> (rima), <b>Makna</b> "
                     "(tanda pembayang dan maksud sepadan) dan <b>Peraturan</b> (bentuk pantun).",
                     background="#F7F3EA")
    with tab_learn:
        learn_screen()
    with tab_hist:
        history_screen()
