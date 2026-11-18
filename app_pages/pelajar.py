"""Student view (business case Section 6.2, Exhibits 2 and 3): Malay, praise first, never "failure".

Top menu (Exhibit 2, label 2): Semak Pantun, Belajar Pantun, Sejarah Saya.
On a desktop the form is on the left and the result on the right; on a phone they stack (Exhibit 3).
"""

import html
from datetime import datetime

import pandas as pd
import streamlit as st

from src.app_core import (result_banner, CHECK, EXAMPLES, GOLD, TEAL, LEAN_MALAY, analyse, banner, card, card_html, cards_row,
                          check_lines, confetti, dial, dials, help_button, load_calibration, pantun_card, rhyme_text,
                          save_flag, tour)
from src import illus
from src.share import add_inquiry, current_user, join_class, my_inquiries, sign_out, student_classes_ok

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
        st.session_state["s_celebrate"] = res["sound"] == 10 and res["rules"] == 4   # confetti once
        st.session_state["s_history"].insert(0, {"time": datetime.now(), "lines": lines, "sound": res["sound"],
                                                 "meaning": res["p_avg"], "rules": res["rules"],
                                                 "lean": res["lean"]})


def write_screen():
    """Screen A (Exhibit 3): write a pantun."""
    with st.container(key="s_lines"):
        st.markdown(":blue-badge[![](/app/static/i/yashinoki.png) **Pembayang** · baris 1–2]")
        st.text_input("Baris 1", key="s_l1", label_visibility="collapsed", placeholder="Baris 1")
        st.text_input("Baris 2", key="s_l2", label_visibility="collapsed", placeholder="Baris 2")
        st.markdown(":orange-badge[![](/app/static/i/mail.png) **Maksud** · baris 3–4]")
        st.text_input("Baris 3", key="s_l3", label_visibility="collapsed", placeholder="Baris 3")
        st.text_input("Baris 4", key="s_l4", label_visibility="collapsed", placeholder="Baris 4")

    if st.button("Semak Pantun Saya", key="s_go", type="primary", icon=":material/search:", width="stretch"):
        with st.spinner("Membaca pantun anda…"):
            check_now()
    for p in st.session_state.get("s_problems", []):
        st.warning(p, icon=":material/edit:")

    with st.container(horizontal=True, vertical_alignment="center"):
        st.caption("Tiada pantun? Cuba contoh:")
        for name in EXAMPLES:
            st.button(name, key=f"s_ex_{name}", type="tertiary", on_click=use_lines, args=(EXAMPLES[name],))

    card("", "<img class=cz-i alt src=/app/static/i/book_open_yoko.png> <b>Tahukah anda?</b> Pembayang selalunya menggunakan unsur alam seperti buah, laut dan "
         "burung. Ia memberi <b>petunjuk</b> kepada maksud.")


def result_screen(res):
    """Screen B (Exhibits 2 and 3, labels 5-7): dials, praise, tip, reminder, disagree button."""
    if res["sound"] == 10 and res["rules"] == 4:
        headline, pic = "Bagus! Rima anda cantik", "trophy"
    elif res["sound"] >= 7.5:
        headline, pic = "Hampir sempurna!", "thumbs_up"
    elif res["rules"] >= 3:
        headline, pic = "Usaha yang baik!", "gutspose_man"
    else:
        headline, pic = "Mari cuba lagi bersama!", "owl"   # a low score is never shown as failure
    result_banner("Hasil semakan", headline, pic)
    if st.session_state.pop("s_celebrate", False):
        confetti()

    _, _, meaning_caption = LEAN_MALAY[res["lean"]]
    meaning_colour = GOLD if res["lean"] != "not_belong" else CHECK
    dials([
        dial(f"{res['sound']:g}/10", res["sound"] / 10, TEAL, "Bunyi", "Rima a-b-a-b", "<img class=cz-i alt src=/app/static/i/music.png>", delay=0.1),
        dial(f"{100 * res['p_avg']:.0f}%", res["p_avg"], meaning_colour, "Makna", meaning_caption, "<img class=cz-i alt src=/app/static/i/think.png>", delay=0.25),
        dial(f"{res['rules']}/4", res["rules"] / 4, "#1B6E78", "Peraturan", "Bentuk pantun", "<img class=cz-i alt src=/app/static/i/clipboard.png>", delay=0.4),
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
        good.append("Bonus rima tengah")

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
    # Duolingo-style buddy: cheers for a strong result, keeps studying with you otherwise
    buddy = (illus.img("gutspose_man", 92, "flex:none", "cheer") if res["sound"] >= 7.5
             else illus.img("study_woman_normal", 92, "flex:none", "float"))
    cards_row([
        card_html("Apa yang anda buat dengan baik",
                  '<div style="display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between">'
                  '<div style="flex:1 1 170px">'
                  + "<br>".join(f"<img class=cz-i alt src=/app/static/i/ok_mark.png> {html.escape(g)}" for g in good) + f"</div>{buddy}</div>",
                  background="#E8F0EF", border="#C9DEDB", delay=0.6),
        card_html("<img class=cz-i alt src=/app/static/i/bulb.png> Petua", tip, delay=0.75),
    ])
    card("", "<img class=cz-i alt src=/app/static/i/handshake.png> <b>Ingat:</b> komputer belum pandai faham kiasan. Skor rendah <b>tidak</b> bermaksud "
         "pantun anda tidak baik. Guru anda membuat keputusan akhir.",
         background="#F8ECCF", border="#EBD39A", delay=0.9)

    with st.expander("Kenapa skor makna dekat 50%?", icon=":material/help:"):
        test = load_calibration()["held_out_test"]
        st.markdown(
            "Pembayang dan maksud biasanya tentang **perkara yang berbeza** — itulah keindahan pantun. "
            "Komputer hanya boleh lihat sama ada topiknya serupa, jadi ia sukar menilai **kiasan**. "
            f"Untuk **{100 * test['share_cannot_tell']:.0f}%** pantun, komputer tidak pasti. "
            f"Apabila skor **60% atau lebih**, ia betul kira-kira **{100 * test['accuracy_when_it_leans']:.0f}%** "
            "daripada masa itu.")

    me = current_user()
    with st.popover("![](/app/static/i/raise_hand.png) Saya tidak setuju — minta guru semak", width="stretch"):
        with st.form("s_flag", border=False):
            class_code = ""
            if me["kind"] == "member":                 # signed-in student: goes to their class teacher
                classes = student_classes_ok(me["username"])
                if classes:
                    class_code = st.selectbox("Hantar kepada", [c["code"] for c in classes],
                                              format_func=lambda k: next(
                                                  f"{c['name']} · " + ((c["teacher_name"] or "pemilik") if c["teacher_ok"]
                                                                       else "pemilik (pensyarah tidak aktif)")
                                                  for c in classes if c["code"] == k))
                    if not all(c["teacher_ok"] for c in classes):
                        st.caption("Jika pensyarah kelas tidak aktif, pertanyaan anda dihantar kepada pemilik laman.")
                else:
                    st.caption("Anda belum menyertai kelas: ia akan dihantar kepada pemilik laman. Sertai kelas di "
                               "tab **Sejarah Saya**.")
            else:
                st.caption("Dihantar kepada semua pensyarah. Ia **sementara**: dipadam apabila akses tetamu tamat.")
            if me["kind"] != "member":
                me = {**me, "name": st.text_input("Nama anda (pilihan)") or me["name"]}
            comment = st.text_area("Kenapa anda tidak setuju? (pilihan)")
            if st.form_submit_button("Hantar kepada guru", type="primary"):
                add_inquiry(me, res["lines"], res, comment, class_code)
                st.success("Terima kasih! Guru anda akan menyemak pantun ini.")


def learn_screen():
    """Belajar Pantun: the parts of a pantun empat kerat that the checker looks at."""
    with st.container(horizontal=True, vertical_alignment="center"):
        st.html(illus.img("book_open_yoko", 70, "", "pop") or "<span></span>", width="content")
        st.subheader("Mengenal pantun empat kerat", anchor=False)
    left, right = st.columns(2, gap="large")
    with left:
        pantun_card(EXAMPLES["Pisang emas"])
        st.caption("Baris 1–2 (teal) ialah **pembayang**. Baris 3–4 (perang) ialah **maksud**.")
        # Pembayang imagery from nature, as in the example: pisang, belayar (perahu), burung
        pics = [("fruit_banana", "pisang"), ("norimono_yacht", "belayar"), ("kotori", "burung")]
        tags = [(illus.img(n, 84, f"animation-delay:{i * 0.4:.1f}s", "float"), w) for i, (n, w) in enumerate(pics)]
        if all(t for t, _ in tags):
            st.html('<div style="display:flex;justify-content:space-around;margin-top:10px;font-family:Nunito,sans-serif">'
                    + "".join(f'<div style="text-align:center">{t}<div style="color:#5b6670;font-size:.9rem;'
                              f'margin-top:4px">{w}</div></div>' for t, w in tags) + "</div>")
            st.caption("Pembayang selalunya meminjam gambaran alam seperti ini.")
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
                st.toast("Contoh dimasukkan. Buka tab **Semak Pantun** dan tekan butang semak.")


def account_panel():
    """For signed-in members: their classes (join with a code) and their inquiries with the teacher's reply."""
    me = current_user()
    if me["kind"] != "member":
        return
    with st.container(border=True):
        st.markdown("**![](/app/static/i/school.png) Kelas saya**")
        classes = student_classes_ok(me["username"])
        if classes:
            st.markdown("  \n".join(f"· **{c['name']}** ({c['code']}) · {c['teacher_name'] or 'pemilik'}"
                                    + ("" if c["teacher_ok"] else " · :orange[pensyarah tidak aktif: pertanyaan "
                                                                  "dihantar kepada pemilik]") for c in classes))
        else:
            st.caption("Belum menyertai kelas.")
        with st.form("s_join", border=False, clear_on_submit=True):
            c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
            code = c1.text_input("Sertai kelas lain", max_chars=8, placeholder="kod kelas daripada pensyarah")
            if c2.form_submit_button("Sertai", icon=":material/group_add:"):
                try:
                    cls = join_class(me["username"], code)
                    st.success(f"Anda kini dalam kelas **{cls['name']}**.")
                except ValueError as e:
                    st.error(str(e))
        mine = my_inquiries(me["username"])
        if not mine.empty:
            st.markdown("**![](/app/static/i/raise_hand.png) Pertanyaan saya**")
            mine["time"] = pd.to_datetime(mine["time"], unit="s").dt.tz_localize("UTC") \
                .dt.tz_convert("Asia/Kuala_Lumpur").dt.strftime("%d/%m %H:%M")
            mine["status"] = mine["status"].map({"baru": "Menunggu", "selesai": "Dijawab"}).fillna(mine["status"])
            st.dataframe(mine.rename(columns={"time": "Masa", "line1": "Baris 1", "line3": "Baris 3",
                                              "comment": "Komen saya", "status": "Status", "reply": "Jawapan guru"}),
                         hide_index=True)


def history_screen():
    """Sejarah Saya: the pantun checked in this session (kept in the browser session only)."""
    account_panel()
    hist = st.session_state["s_history"]
    if not hist:
        illus.show("box_kara_hako", 100, "float")
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
            st.toast("Pantun dimasukkan semula. Buka tab **Semak Pantun**.")
    st.caption(f"{len(hist)} pantun disemak dalam sesi ini. Sejarah hilang apabila tab pelayar ditutup.")


# ---- Page -------------------------------------------------------------------------------------------
_, middle, _ = st.columns([1, 12, 1])
with middle.container(key="pelajar"):
    with st.container(horizontal=True, horizontal_alignment="right"):
        help_button("pelajar")
    tab_check, tab_learn, tab_hist = st.tabs(["![](/app/static/i/magnifier.png) Semak Pantun", "![](/app/static/i/book_open_yoko.png) Belajar Pantun", "![](/app/static/i/clock.png) Sejarah Saya"])
    with tab_check:
        illus.stage("semak", "Semak Pantun Anda!", "Adakah pembayang dan maksud anda sepadan? Tulis 4 baris, kemudian tekan butang.", "Cenderawasih")
        left, right = st.columns([1, 1], gap="large")
        with left:
            write_screen()
        with right.container(key="s_right"):
            res = st.session_state.get("s_result")
            if res:
                result_screen(res)
            else:
                card("Hasil semakan", "Hasil anda akan muncul di sini: <b>Bunyi</b> (rima), <b>Makna</b> "
                     "(tanda pembayang dan maksud sepadan) dan <b>Peraturan</b> (bentuk pantun).",
                     background="#FFFFFF")
    with tab_learn:
        illus.stage("belajar", "Belajar Pantun", "Kenali pembayang, maksud, rima dan kiasan dengan cara yang seronok.", "Jom belajar")
        learn_screen()
    with tab_hist:
        illus.stage("sejarah", "Sejarah Saya", "Kelas anda, jawapan guru dan pantun yang sudah disemak.", "Perjalanan anda")
        history_screen()

    # A lecturer or expert who came in with the guest code (or open mode) can switch to their own account here.
    if current_user()["kind"] in ("guest", "public"):
        with st.container(horizontal=True, horizontal_alignment="center"):
            st.caption("Pensyarah atau pakar?")
            st.button("Log masuk dengan akaun anda", icon=":material/login:", type="tertiary",
                      on_click=lambda: (sign_out(), st.session_state.update(cz_want_login=True)),
                      key="s_staff_login")

tour("pelajar", [
    (".st-key-s_lines", "Tulis pantun anda <img class=cz-i alt src=/app/static/i/pencil.png>",
     "Baris 1–2 ialah <b>pembayang</b>, baris 3–4 ialah <b>maksud</b>. Tiada pantun? Tekan satu contoh di bawah."),
    (".st-key-s_go", "Tekan Semak <img class=cz-i alt src=/app/static/i/magnifier.png>", "Komputer menyemak <b>bunyi, makna dan peraturan</b> dalam beberapa saat."),
    (".st-key-s_right", "Baca hasil anda <img class=cz-i alt src=/app/static/i/target.png>",
     "Tiga dial: <b>Bunyi</b> (rima), <b>Makna</b> (tanda sepadan) dan <b>Peraturan</b> (bentuk). "
     "Pujian dahulu, kemudian petua. Tidak setuju? Minta guru semak."),
    (".st-key-pelajar [role='tablist']", "Belajar & Sejarah <img class=cz-i alt src=/app/static/i/book_open_yoko.png>",
     "<b>Belajar Pantun</b> untuk teori dengan contoh. <b>Sejarah Saya</b> untuk pantun yang anda semak."),
    (".st-key-help_pelajar", "Perlukan bantuan? <img class=cz-i alt src=/app/static/i/play.png>", "Tekan <b>Cara guna</b> bila-bila masa untuk video tutorial."),
])
