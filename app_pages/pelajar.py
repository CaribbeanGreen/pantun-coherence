"""Pupil view, "Murid / Pupil" (business case Section 6.2, Exhibits 2 and 3): praise first, never "failure".

Top menu (Exhibit 2, label 2): Semak Pantun, Belajar Pantun, Sejarah Saya.
On a desktop the form is on the left and the result on the right; on a phone they stack (Exhibit 3).
Every sentence is written in Malay and English with tr() (src/lang.py); the pantun itself always stays Malay.
"""

import html
from datetime import datetime

import pandas as pd
import streamlit as st

from src.app_core import (result_banner, CHECK, EXAMPLES, GOLD, TEAL, analyse, card, card_html, cards_row,
                          check_lines, confetti, dial, dials, example_name, help_button, lean_words, load_calibration,
                          pantun_card, rhyme_text, tour)
from src import illus
from src.lang import role, tr
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
    line = tr("Baris", "Line")
    with st.container(key="s_lines"):
        st.markdown(f":blue-badge[![](/app/static/i/yashinoki.png) **Pembayang** · {line.lower()} 1–2]")
        st.text_input(f"{line} 1", key="s_l1", label_visibility="collapsed", placeholder=f"{line} 1")
        st.text_input(f"{line} 2", key="s_l2", label_visibility="collapsed", placeholder=f"{line} 2")
        st.markdown(f":orange-badge[![](/app/static/i/mail.png) **Maksud** · {line.lower()} 3–4]")
        st.text_input(f"{line} 3", key="s_l3", label_visibility="collapsed", placeholder=f"{line} 3")
        st.text_input(f"{line} 4", key="s_l4", label_visibility="collapsed", placeholder=f"{line} 4")

    if st.button(tr("Semak Pantun Saya", "Check My Pantun"), key="s_go", type="primary", icon=":material/search:",
                 width="stretch"):
        with st.spinner(tr("Membaca pantun anda…", "Reading your pantun…")):
            check_now()
    for p in st.session_state.get("s_problems", []):
        st.warning(p, icon=":material/edit:")

    with st.container(horizontal=True, vertical_alignment="center"):
        st.caption(tr("Tiada pantun? Cuba contoh:", "No pantun? Try an example:"))
        for name in EXAMPLES:
            st.button(example_name(name), key=f"s_ex_{name}", type="tertiary", on_click=use_lines,
                      args=(EXAMPLES[name],))

    card("", "<img class=cz-i alt src=/app/static/i/book_open_yoko.png> " + tr(
        "<b>Tahukah anda?</b> Pembayang selalunya menggunakan unsur alam seperti buah, laut dan burung. Ia memberi "
        "<b>petunjuk</b> kepada maksud.",
        "<b>Did you know?</b> The pembayang (first two lines) often uses nature, such as fruit, the sea and birds. "
        "It gives a <b>hint</b> of the maksud (the message)."))


def result_screen(res):
    """Screen B (Exhibits 2 and 3, labels 5-7): dials, praise, tip, reminder, disagree button."""
    if res["sound"] == 10 and res["rules"] == 4:
        headline, pic = tr("Bagus! Rima anda cantik", "Great! Your rhyme is lovely"), "trophy"
    elif res["sound"] >= 7.5:
        headline, pic = tr("Hampir sempurna!", "Almost perfect!"), "thumbs_up"
    elif res["rules"] >= 3:
        headline, pic = tr("Usaha yang baik!", "Good effort!"), "gutspose_man"
    else:
        headline, pic = tr("Mari cuba lagi bersama!", "Let's try again together!"), "owl"   # never shown as failure
    result_banner(tr("Hasil semakan", "Your result"), headline, pic)
    if st.session_state.pop("s_celebrate", False):
        confetti()

    _, _, meaning_caption = lean_words(res["lean"])
    meaning_colour = GOLD if res["lean"] != "not_belong" else CHECK
    dials([
        dial(f"{res['sound']:g}/10", res["sound"] / 10, TEAL, tr("Bunyi", "Sound"), tr("Rima a-b-a-b", "Rhyme a-b-a-b"),
             "<img class=cz-i alt src=/app/static/i/music.png>", delay=0.1),
        dial(f"{100 * res['p_avg']:.0f}%", res["p_avg"], meaning_colour, tr("Makna", "Meaning"), meaning_caption,
             "<img class=cz-i alt src=/app/static/i/think.png>", delay=0.25),
        dial(f"{res['rules']}/4", res["rules"] / 4, "#1B6E78", tr("Peraturan", "Rules"),
             tr("Bentuk pantun", "Pantun form"), "<img class=cz-i alt src=/app/static/i/clipboard.png>", delay=0.4),
    ])

    # What you did well (praise first)
    crit = {c["name"].split(" ")[0]: c["passed"] for c in res["criteria"]}
    good = [tr("4 baris lengkap", "All 4 lines")]
    if crit.get("8–12"):
        good.append(tr("8–12 suku kata setiap baris", "8–12 syllables in every line"))
    if crit.get("End"):
        good.append(tr(f"Rima akhir {rhyme_text(res)}", f"End rhyme {rhyme_text(res)}"))
    if crit.get("Pembayang"):
        good.append(tr("Pembayang guna unsur alam", "Pembayang uses nature"))
    if res["bonus"]:
        good.append(tr("Bonus rima tengah", "Bonus: middle rhyme"))

    # One tip
    if res["shared"]:
        word = html.escape(res["shared"][0])
        tip = tr(f'Perkataan <b>"{word}"</b> muncul dalam kedua-dua bahagian. Itu satu petunjuk yang baik!',
                 f'The word <b>"{word}"</b> appears in both halves. That is a good hint!')
    elif not crit.get("End"):
        tip = tr("Cuba pastikan baris 1 berima dengan baris 3, dan baris 2 dengan baris 4 (a-b-a-b).",
                 "Try to make line 1 rhyme with line 3, and line 2 with line 4 (a-b-a-b).")
    elif not crit.get("8–12"):
        tip = tr("Cuba jadikan setiap baris 8 hingga 12 suku kata.", "Try to give every line 8 to 12 syllables.")
    elif not crit.get("Pembayang"):
        tip = tr("Cuba gunakan unsur alam dalam pembayang, seperti buah, laut atau burung.",
                 "Try to use nature in the pembayang, such as fruit, the sea or birds.")
    else:
        tip = tr("Pastikan pembayang memberi petunjuk kepada maksud, melalui bunyi, perkataan atau kiasan.",
                 "Make sure the pembayang hints at the maksud, through sound, words or kiasan (figurative meaning).")

    # Side by side on a desktop, stacked on a phone
    # Duolingo-style buddy: cheers for a strong result, keeps studying with you otherwise
    buddy = (illus.img("gutspose_man", 92, "flex:none", "cheer") if res["sound"] >= 7.5
             else illus.img("study_woman_normal", 92, "flex:none", "float"))
    cards_row([
        card_html(tr("Apa yang anda buat dengan baik", "What you did well"),
                  '<div style="display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between">'
                  '<div style="flex:1 1 170px">'
                  + "<br>".join(f"<img class=cz-i alt src=/app/static/i/ok_mark.png> {html.escape(g)}" for g in good) + f"</div>{buddy}</div>",
                  background="#E8F0EF", border="#C9DEDB", delay=0.6),
        card_html("<img class=cz-i alt src=/app/static/i/bulb.png> " + tr("Petua", "Tip"), tip, delay=0.75),
    ])
    card("", "<img class=cz-i alt src=/app/static/i/handshake.png> " + tr(
        "<b>Ingat:</b> komputer belum pandai faham kiasan. Skor rendah <b>tidak</b> bermaksud pantun anda tidak "
        "baik. Cikgu anda membuat keputusan akhir.",
        "<b>Remember:</b> computers are not yet good at understanding kiasan. A low score does <b>not</b> mean "
        "your pantun is bad. Your teacher makes the final decision."),
         background="#F8ECCF", border="#EBD39A", delay=0.9)

    with st.expander(tr("Kenapa skor makna dekat 50%?", "Why is the meaning score near 50%?"), icon=":material/help:"):
        test = load_calibration()["held_out_test"]
        unsure, right = 100 * test["share_cannot_tell"], 100 * test["accuracy_when_it_leans"]
        st.markdown(tr(
            "Pembayang dan maksud biasanya tentang **perkara yang berbeza** — itulah keindahan pantun. "
            "Komputer hanya boleh lihat sama ada topiknya serupa, jadi ia sukar menilai **kiasan**. "
            f"Untuk **{unsure:.0f}%** pantun, komputer tidak pasti. "
            f"Apabila skor **60% atau lebih**, ia betul kira-kira **{right:.0f}%** daripada masa itu.",
            "The pembayang and the maksud are usually about **different things** — that is the beauty of a pantun. "
            "The computer can only see whether the topics are alike, so it finds **kiasan** hard to judge. "
            f"For **{unsure:.0f}%** of pantun, the computer is not sure. "
            f"When the score is **60% or more**, it is right about **{right:.0f}%** of the time."))

    me = current_user()
    with st.popover("![](/app/static/i/raise_hand.png) " + tr("Saya tidak setuju — minta cikgu semak",
                                                              "I disagree — ask my teacher to check"), width="stretch"):
        with st.form("s_flag", border=False):
            class_code = ""
            owner = tr("pemilik", "the owner")
            if me["kind"] == "member":                 # signed-in pupil: goes to their class teacher
                classes = student_classes_ok(me["username"])
                if classes:
                    class_code = st.selectbox(tr("Hantar kepada", "Send to"), [c["code"] for c in classes],
                                              format_func=lambda k: next(
                                                  f"{c['name']} · " + ((c["teacher_name"] or owner) if c["teacher_ok"]
                                                                       else tr("pemilik (cikgu tidak aktif)",
                                                                               "the owner (teacher not active)"))
                                                  for c in classes if c["code"] == k))
                    if not all(c["teacher_ok"] for c in classes):
                        st.caption(tr("Jika cikgu kelas tidak aktif, pertanyaan anda dihantar kepada pemilik laman.",
                                      "If the class teacher is not active, your question goes to the site owner."))
                else:
                    st.caption(tr("Anda belum menyertai kelas: ia akan dihantar kepada pemilik laman. Sertai kelas di "
                                  "tab **Sejarah Saya**.",
                                  "You have not joined a class yet: it will go to the site owner. Join a class on "
                                  "the **My History** tab."))
            else:
                st.caption(tr("Dihantar kepada semua cikgu. Ia **sementara**: dipadam apabila akses tetamu tamat.",
                              "Sent to every teacher. It is **temporary**: deleted when guest access ends."))
            if me["kind"] != "member":
                me = {**me, "name": st.text_input(tr("Nama anda (pilihan)", "Your name (optional)")) or me["name"]}
            comment = st.text_area(tr("Kenapa anda tidak setuju? (pilihan)", "Why do you disagree? (optional)"))
            if st.form_submit_button(tr("Hantar kepada cikgu", "Send to my teacher"), type="primary"):
                add_inquiry(me, res["lines"], res, comment, class_code)
                st.success(tr("Terima kasih! Cikgu anda akan menyemak pantun ini.",
                              "Thank you! Your teacher will check this pantun."))


def learn_screen():
    """Belajar Pantun: the parts of a pantun empat kerat that the checker looks at."""
    with st.container(horizontal=True, vertical_alignment="center"):
        st.html(illus.img("book_open_yoko", 70, "", "pop") or "<span></span>", width="content")
        st.subheader(tr("Mengenal pantun empat kerat", "Getting to know the four-line pantun"), anchor=False)
    left, right = st.columns(2, gap="large")
    with left:
        pantun_card(EXAMPLES["Pisang emas"])
        st.caption(tr("Baris 1–2 (teal) ialah **pembayang**. Baris 3–4 (perang) ialah **maksud**.",
                      "Lines 1–2 (teal) are the **pembayang**. Lines 3–4 (brown) are the **maksud**."))
        # Pembayang imagery from nature, as in the example: pisang, belayar (perahu), burung
        pics = [("fruit_banana", tr("pisang", "banana")), ("norimono_yacht", tr("belayar", "sailing")),
                ("kotori", tr("burung", "bird"))]
        tags = [(illus.img(n, 84, f"animation-delay:{i * 0.4:.1f}s", "float"), w) for i, (n, w) in enumerate(pics)]
        if all(t for t, _ in tags):
            st.html('<div style="display:flex;justify-content:space-around;margin-top:10px;font-family:Nunito,sans-serif">'
                    + "".join(f'<div style="text-align:center">{t}<div style="color:#5b6670;font-size:.9rem;'
                              f'margin-top:4px">{w}</div></div>' for t, w in tags) + "</div>")
            st.caption(tr("Pembayang selalunya meminjam gambaran alam seperti ini.",
                          "The pembayang often borrows pictures from nature like these."))
    with right:
        st.markdown(tr(
            "**1. Empat baris.** Pantun empat kerat ada 4 baris: 2 baris pembayang dan 2 baris maksud.\n\n"
            "**2. Pembayang.** Selalunya tentang alam: buah, laut, burung, pokok. Ia menyediakan bunyi "
            "dan memberi petunjuk kepada maksud.\n\n"
            "**3. Maksud.** Inilah pesanan sebenar pantun, contohnya nasihat atau budi.\n\n"
            "**4. Rima a-b-a-b.** Bunyi akhir baris 1 sama dengan baris 3, dan baris 2 sama dengan baris 4 "
            "(belay**ar** / dibay**ar**, pe**ti** / ma**ti**).\n\n"
            "**5. Suku kata.** Setiap baris biasanya ada 8 hingga 12 suku kata.\n\n"
            "**6. Kiasan.** Pembayang sering mengiaskan maksud. Komputer belum pandai menilai kiasan, "
            "jadi cikgu membuat keputusan akhir.",
            "**1. Four lines.** A pantun empat kerat has 4 lines: 2 lines of pembayang and 2 lines of maksud.\n\n"
            "**2. Pembayang.** Usually about nature: fruit, the sea, birds, trees. It sets up the sound "
            "and hints at the maksud.\n\n"
            "**3. Maksud.** The real message of the pantun, for example advice or gratitude (budi).\n\n"
            "**4. Rhyme a-b-a-b.** The end sound of line 1 matches line 3, and line 2 matches line 4 "
            "(belay**ar** / dibay**ar**, pe**ti** / ma**ti**).\n\n"
            "**5. Syllables.** Each line usually has 8 to 12 syllables.\n\n"
            "**6. Kiasan.** The pembayang often hints at the maksud through figurative meaning. Computers are "
            "not yet good at judging kiasan, so the teacher makes the final decision."))
    st.markdown(tr("**Cuba sendiri**", "**Try it yourself**"))
    with st.container(horizontal=True):
        for name in EXAMPLES:
            if st.button(tr(f"Guna \"{example_name(name)}\"", f"Use \"{example_name(name)}\""),
                         key=f"s_learn_{name}", type="secondary", on_click=use_lines, args=(EXAMPLES[name],)):
                st.toast(tr("Contoh dimasukkan. Buka tab **Semak Pantun** dan tekan butang semak.",
                            "Example filled in. Open the **Check Pantun** tab and press the check button."))


def account_panel():
    """For signed-in members: their classes (join with a code) and their inquiries with the teacher's reply."""
    me = current_user()
    if me["kind"] != "member":
        return
    with st.container(border=True):
        st.markdown("**![](/app/static/i/school.png) " + tr("Kelas saya", "My classes") + "**")
        classes = student_classes_ok(me["username"])
        if classes:
            st.markdown("  \n".join(
                f"· **{c['name']}** ({c['code']}) · {c['teacher_name'] or tr('pemilik', 'owner')}"
                + ("" if c["teacher_ok"] else " · :orange[" + tr("cikgu tidak aktif: pertanyaan dihantar kepada pemilik",
                                                                 "teacher not active: questions go to the owner") + "]")
                for c in classes))
        else:
            st.caption(tr("Belum menyertai kelas.", "Not in a class yet."))
        with st.form("s_join", border=False, clear_on_submit=True):
            c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
            code = c1.text_input(tr("Sertai kelas lain", "Join another class"), max_chars=8,
                                 placeholder=tr("kod kelas daripada cikgu", "class code from your teacher"))
            if c2.form_submit_button(tr("Sertai", "Join"), icon=":material/group_add:"):
                try:
                    cls = join_class(me["username"], code)
                    st.success(tr(f"Anda kini dalam kelas **{cls['name']}**.", f"You are now in **{cls['name']}**."))
                except ValueError as e:
                    st.error(str(e))
        mine = my_inquiries(me["username"])
        if not mine.empty:
            st.markdown("**![](/app/static/i/raise_hand.png) " + tr("Pertanyaan saya", "My questions") + "**")
            mine["time"] = pd.to_datetime(mine["time"], unit="s").dt.tz_localize("UTC") \
                .dt.tz_convert("Asia/Kuala_Lumpur").dt.strftime("%d/%m %H:%M")
            mine["status"] = mine["status"].map({"baru": tr("Menunggu", "Waiting"),
                                                 "selesai": tr("Dijawab", "Answered")}).fillna(mine["status"])
            st.dataframe(mine.rename(columns={
                "time": tr("Masa", "Time"), "line1": tr("Baris 1", "Line 1"), "line3": tr("Baris 3", "Line 3"),
                "comment": tr("Komen saya", "My comment"), "status": "Status",
                "reply": tr("Jawapan cikgu", "Teacher's reply")}), hide_index=True)


def history_screen():
    """Sejarah Saya: the pantun checked in this session (kept in the browser session only)."""
    account_panel()
    hist = st.session_state["s_history"]
    if not hist:
        illus.show("box_kara_hako", 100, "float")
        st.info(tr("Belum ada pantun yang disemak. Semak satu pantun dan ia akan muncul di sini.",
                   "No pantun checked yet. Check one and it will appear here."), icon=":material/history:")
        return
    table = pd.DataFrame([{
        tr("Masa", "Time"): f"{h['time']:%H:%M}", tr("Baris 1", "Line 1"): h["lines"][0],
        tr("Baris 3", "Line 3"): h["lines"][2], tr("Bunyi", "Sound"): f"{h['sound']:g}/10",
        tr("Makna", "Meaning"): f"{100 * h['meaning']:.0f}%", tr("Peraturan", "Rules"): f"{h['rules']}/4",
    } for h in hist])
    ev = st.dataframe(table, hide_index=True, on_select="rerun", selection_mode="single-row", key="s_hist_table",
                      alt=tr("Pantun yang anda semak dalam sesi ini", "Pantun you checked in this session"))
    sel = ev.selection.rows if ev and ev.selection else []
    if sel:
        pantun_card(hist[sel[0]]["lines"])
        if st.button(tr("Buka semula pantun ini", "Open this pantun again"), icon=":material/edit:", on_click=use_lines,
                     args=(hist[sel[0]]["lines"],)):
            st.toast(tr("Pantun dimasukkan semula. Buka tab **Semak Pantun**.",
                        "Pantun filled in again. Open the **Check Pantun** tab."))
    st.caption(tr(f"{len(hist)} pantun disemak dalam sesi ini. Sejarah hilang apabila tab pelayar ditutup.",
                  f"{len(hist)} pantun checked in this session. The history is lost when the browser tab closes."))


# ---- Page -------------------------------------------------------------------------------------------
_, middle, _ = st.columns([1, 12, 1])
with middle.container(key="pelajar"):
    with st.container(horizontal=True, horizontal_alignment="right"):
        help_button("pelajar")
    tab_check, tab_learn, tab_hist = st.tabs([
        "![](/app/static/i/magnifier.png) " + tr("Semak Pantun", "Check Pantun"),
        "![](/app/static/i/book_open_yoko.png) " + tr("Belajar Pantun", "Learn Pantun"),
        "![](/app/static/i/clock.png) " + tr("Sejarah Saya", "My History")])
    with tab_check:
        illus.stage("semak", tr("Semak Pantun Anda!", "Check Your Pantun!"),
                    tr("Adakah pembayang dan maksud anda sepadan? Tulis 4 baris, kemudian tekan butang.",
                       "Do your pembayang and maksud go together? Write 4 lines, then press the button."),
                    "Cenderawasih")
        left, right = st.columns([1, 1], gap="large")
        with left:
            write_screen()
        with right.container(key="s_right"):
            res = st.session_state.get("s_result")
            if res:
                result_screen(res)
            else:
                card(tr("Hasil semakan", "Your result"), tr(
                    "Hasil anda akan muncul di sini: <b>Bunyi</b> (rima), <b>Makna</b> (tanda pembayang dan maksud "
                    "sepadan) dan <b>Peraturan</b> (bentuk pantun).",
                    "Your result will appear here: <b>Sound</b> (rhyme), <b>Meaning</b> (signs that the pembayang "
                    "and maksud go together) and <b>Rules</b> (the pantun form)."),
                     background="#FFFFFF")
    with tab_learn:
        illus.stage("belajar", tr("Belajar Pantun", "Learn Pantun"),
                    tr("Kenali pembayang, maksud, rima dan kiasan dengan cara yang seronok.",
                       "Get to know pembayang, maksud, rhyme and kiasan the fun way."), tr("Jom belajar", "Let's learn"))
        learn_screen()
    with tab_hist:
        illus.stage("sejarah", tr("Sejarah Saya", "My History"),
                    tr("Kelas anda, jawapan cikgu dan pantun yang sudah disemak.",
                       "Your classes, your teacher's replies and the pantun you have checked."),
                    tr("Perjalanan anda", "Your journey"))
        history_screen()

    # A teacher or expert who came in with the guest code (or open mode) can switch to their own account here.
    if current_user()["kind"] in ("guest", "public"):
        with st.container(horizontal=True, horizontal_alignment="center"):
            st.caption(tr(f"{role('pensyarah')} atau pakar?", f"{role('pensyarah')} or expert?"))
            st.button(tr("Log masuk dengan akaun anda", "Log in with your account"), icon=":material/login:",
                      type="tertiary", on_click=lambda: (sign_out(), st.session_state.update(cz_want_login=True)),
                      key="s_staff_login")

tour("pelajar", [
    (".st-key-s_lines", tr("Tulis pantun anda", "Write your pantun") + " <img class=cz-i alt src=/app/static/i/pencil.png>",
     tr("Baris 1–2 ialah <b>pembayang</b>, baris 3–4 ialah <b>maksud</b>. Tiada pantun? Tekan satu contoh di bawah.",
        "Lines 1–2 are the <b>pembayang</b>, lines 3–4 the <b>maksud</b>. No pantun? Press an example below.")),
    (".st-key-s_go", tr("Tekan Semak", "Press Check") + " <img class=cz-i alt src=/app/static/i/magnifier.png>",
     tr("Komputer menyemak <b>bunyi, makna dan peraturan</b> dalam beberapa saat.",
        "The computer checks <b>sound, meaning and rules</b> in a few seconds.")),
    (".st-key-s_right", tr("Baca hasil anda", "Read your result") + " <img class=cz-i alt src=/app/static/i/target.png>",
     tr("Tiga dial: <b>Bunyi</b> (rima), <b>Makna</b> (tanda sepadan) dan <b>Peraturan</b> (bentuk). "
        "Pujian dahulu, kemudian petua. Tidak setuju? Minta cikgu semak.",
        "Three dials: <b>Sound</b> (rhyme), <b>Meaning</b> (signs of a match) and <b>Rules</b> (form). "
        "Praise first, then a tip. Disagree? Ask your teacher to check.")),
    (".st-key-pelajar [role='tablist']", tr("Belajar & Sejarah", "Learn & History")
     + " <img class=cz-i alt src=/app/static/i/book_open_yoko.png>",
     tr("<b>Belajar Pantun</b> untuk teori dengan contoh. <b>Sejarah Saya</b> untuk pantun yang anda semak.",
        "<b>Learn Pantun</b> for the theory with examples. <b>My History</b> for the pantun you checked.")),
    (".st-key-help_pelajar", tr("Perlukan bantuan?", "Need help?") + " <img class=cz-i alt src=/app/static/i/play.png>",
     tr("Tekan <b>Cara guna</b> bila-bila masa untuk video tutorial.",
        "Press <b>How to use</b> any time for the tutorial video.")),
])
