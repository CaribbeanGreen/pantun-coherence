"""Teacher view, "Cikgu / Teacher" (business case Section 6.3, Exhibit 4; SRF11, SRF12): desktop.

Side menu (label 1): Papan pemuka, Kelas saya, Kod kelas & murid, Semakan, Laporan (in English: Dashboard,
My class, Class codes & pupils, Reviews, Report). Text follows the visitor's language (src/lang.py); decisions are
saved with fixed keys (setuju, ubah, pakar) and Malay notes, whatever language the teacher reads.
Upload a class CSV -> every pantun is checked -> a work queue shows what needs attention first ->
the instructor agrees, changes the decision, or sends it to an expert. Every decision is logged
to results/instructor_decisions.csv (with time, so the MOV "time to first feedback" can be measured).
Results export as CSV or PDF (SRF11).
"""

import io
from datetime import datetime

import numpy as np
import pandas as pd
import streamlit as st

from src.app_core import (DECISIONS_CSV, EXAMPLES, TEAL, analyse, check_lines, help_button, lean_words,
                          pantun_card, read_log, rhyme_text, save_decision, tour)
from src import dashboard as dz
from src import illus
from src.data_loader import load_pantun
from src.lang import role, tr
from src.share import (class_students, classes_of, create_class, current_user, get_member, inquiries_for,
                       remove_from_class, require_view, reset_key, resolve_inquiry, set_class_active, teacher_has_student)

require_view("pensyarah")      # teachers (and the owner) only; pupils and guests never see this page
ME = current_user()

_ACTIONS = {"setuju": ("✔ Setuju", "✔ Agreed"), "ubah": ("✎ Diubah", "✎ Changed"),
            "pakar": ("⚑ Dihantar kepada pakar", "⚑ Sent to an expert")}


def action_name(key):
    return tr(*_ACTIONS[key]) if key in _ACTIONS else key


TEMPLATE = "pelajar,baris1,baris2,baris3,baris4\nS001,Pisang emas dibawa belayar,Masak sebiji di atas peti,Hutang emas boleh dibayar,Hutang budi dibawa mati\n"
# Side menu: fixed keys (the chosen one survives a language switch), names in the reader's language.
MENU = ["dash", "class", "codes", "review", "report"]
MENU_PIC = {"dash": "home", "class": "book", "codes": "school", "review": "notebook", "report": "chart"}


def menu_name(key):
    names = {"dash": ("Papan pemuka", "Dashboard"), "class": ("Kelas saya", "My class"),
             "codes": ("Kod kelas & murid", "Class codes & pupils"), "review": ("Semakan", "Reviews"),
             "report": ("Laporan", "Report")}
    return f"![](/app/static/i/{MENU_PIC[key]}.png) " + tr(*names[key])


st.session_state.setdefault("p_class", [])         # one dict per submission
st.session_state.setdefault("p_decisions", {})     # pupil -> (action, note, time)
st.session_state.setdefault("p_class_name", tr("Kelas 4 Bestari · Pantun Nasihat", "Class 4 Bestari · Advice Pantun"))
if st.session_state.get("p_menu") not in MENU:     # e.g. an old Malay menu label from before
    st.session_state["p_menu"] = MENU[0]

# Fixed teal side menu (Exhibit 4, label 1). This style only loads on this page.
st.html(f"""<style>
section[data-testid="stSidebar"] {{background:linear-gradient(180deg,#2F6BFF,#21B6E8)}}
section[data-testid="stSidebar"] * {{color:#fff}}
section[data-testid="stSidebar"] [role="radiogroup"] label {{padding:9px 11px;border-radius:16px;margin:3px 0;font-weight:800}}
section[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {{background:#FFC83D;box-shadow:0 4px 0 #D99400}}
section[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) * {{color:#17324D}}
</style>""")


@st.cache_data
def demo_class():
    """Sample class from the corpus (real pantun) + one mixed-up and one 3-line entry for testing."""
    pantun, _ = load_pantun()
    rng = np.random.default_rng(7)
    picks = rng.choice(len(pantun), 14, replace=False)
    rows = [[f"S{k + 1:03d}", *pantun[i].lines] for k, i in enumerate(picks[:12])]
    a, b = pantun[picks[12]].lines, pantun[picks[13]].lines
    rows.append(["S013", a[0], a[1], b[2], b[3]])            # halves from two different pantun
    rows.append(["S014", b[0], b[1], b[2], ""])              # only 3 lines
    return pd.DataFrame(rows, columns=["pelajar", "baris1", "baris2", "baris3", "baris4"])


def read_class_csv(data):
    """Accept columns pelajar/id/student and baris1-4 or line1-4 (any letter case)."""
    df = pd.read_csv(data, dtype=str, keep_default_na=False)
    cols = {c.lower().strip(): c for c in df.columns}
    id_col = next((cols[c] for c in ["pelajar", "id", "student", "id pelajar"] if c in cols), df.columns[0])
    line_cols = [next((cols[c] for c in [f"baris{i}", f"baris {i}", f"line{i}", f"line {i}"] if c in cols), None)
                 for i in range(1, 5)]
    if None in line_cols:
        raise ValueError(tr("Fail perlu lajur baris1, baris2, baris3, baris4 (atau line1–line4).",
                            "The file needs the columns baris1, baris2, baris3, baris4 (or line1–line4)."))
    return [(str(r[id_col]).strip(), [str(r[c]) for c in line_cols]) for _, r in df.iterrows()]


def load_class(entries):
    """Check and score every submission (with a progress bar)."""
    busy = tr("Menyemak pantun kelas…", "Checking the class's pantun…")
    rows, bar = [], st.progress(0.0, text=busy)
    loaded = datetime.now()
    for k, (student, raw) in enumerate(entries):
        lines, problems = check_lines(raw)
        res = None if problems else analyse(lines)
        rows.append({"student": student, "raw": raw, "lines": lines, "problems": problems, "res": res,
                     "loaded": loaded})
        bar.progress((k + 1) / len(entries), text=f"{busy} {k + 1}/{len(entries)}")
    bar.empty()
    st.session_state["p_class"] = rows
    st.session_state["p_decisions"] = {}


def form_chip(row):
    if row["problems"]:
        n = len([l for l in row["raw"] if l.strip()])
        return f"✖ {n} " + tr("baris", "lines") if n != 4 else "✖ format"
    res = row["res"]
    if res["rules"] == 4:
        return "✔ 4/4"
    end_ok = next(c["passed"] for c in res["criteria"] if c["name"].startswith("End"))
    return f"✖ {res['rules']}/4" + ("" if end_ok else " " + tr("rima", "rhyme"))


def meaning_chip(row):
    if row["res"] is None:
        return "—"
    icon, label, _ = lean_words(row["res"]["lean"])
    return f"{icon} {label}"


def needs_review(row):
    return row["student"] not in st.session_state["p_decisions"]


def export_table(rows, dec):
    """Class results. The column names stay the same in both languages (the CSV can be read back by other tools);
    the values are in the reader's language."""
    return pd.DataFrame([{
        "pelajar": r["student"], "baris1": r["raw"][0], "baris2": r["raw"][1], "baris3": r["raw"][2],
        "baris4": r["raw"][3], "bentuk": form_chip(r),
        "bunyi": "" if r["res"] is None else f"{r['res']['sound']:g}/10",
        "makna_%": "" if r["res"] is None else round(100 * r["res"]["p_avg"]),
        "makna": meaning_chip(r),
        "keputusan": action_name(dec[r["student"]][0]) if r["student"] in dec else "",
        "catatan": dec.get(r["student"], ("", ""))[1],
    } for r in rows])


def export_pdf(class_name, table):
    """A4 landscape PDF report of the class results (SRF11). Made with matplotlib, no extra package."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    cols = ["pelajar", "baris1", "baris3", "bentuk", "bunyi", "makna", "keputusan", "catatan"]
    heads = tr(["Murid", "Baris 1 (pembayang)", "Baris 3 (maksud)", "Bentuk", "Bunyi", "Makna", "Keputusan",
                "Catatan"],
               ["Pupil", "Line 1 (pembayang)", "Line 3 (maksud)", "Form", "Sound", "Meaning", "Decision", "Note"])
    widths = [0.07, 0.21, 0.21, 0.08, 0.06, 0.13, 0.15, 0.09]
    cut = lambda s, n: s if len(s) <= n else s[: n - 1] + "…"
    body = [[cut(str(v), 40) for v in r] for r in table[cols].itertuples(index=False)]
    per_page = 22
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        for start in range(0, max(len(body), 1), per_page):
            fig = plt.figure(figsize=(11.69, 8.27))
            fig.text(0.04, 0.95, f"Cenderawasih · Semak Pantun — {class_name}", fontsize=15, weight="bold",
                     color=TEAL)
            fig.text(0.04, 0.915, tr(f"{len(body)} hantaran · dieksport {datetime.now():%d/%m/%Y %H:%M} · "
                                     f"halaman {start // per_page + 1}",
                                     f"{len(body)} entries · exported {datetime.now():%d/%m/%Y %H:%M} · "
                                     f"page {start // per_page + 1}"), fontsize=9, color="#52606D")
            ax = fig.add_axes([0.04, 0.08, 0.92, 0.81])
            ax.axis("off")
            chunk = body[start:start + per_page] or [[""] * len(cols)]
            t = ax.table(cellText=chunk, colLabels=heads, colWidths=widths, loc="upper left", cellLoc="left")
            t.auto_set_font_size(False)
            t.set_fontsize(7.5)
            t.scale(1, 1.45)
            for (r, _), cell in t.get_celld().items():
                cell.set_edgecolor("#E3DCCB")
                if r == 0:
                    cell.set_facecolor("#E8F0EF")
                    cell.set_text_props(weight="bold", color=TEAL)
            fig.text(0.04, 0.035, tr("Skor ialah anggaran komputer. Cikgu membuat keputusan akhir.",
                                     "Scores are the computer's estimate. The teacher makes the final decision."),
                     fontsize=8, color="#52606D")
            pdf.savefig(fig)
            plt.close(fig)
    return buf.getvalue()


def export_buttons(rows, dec, key):
    table = export_table(rows, dec)
    name = st.session_state["p_class_name"]
    with st.container(horizontal=True, width="content"):
        st.download_button(tr("Eksport CSV", "Export CSV"), table.to_csv(index=False).encode("utf-8-sig"),
                           file_name="keputusan_kelas.csv", icon=":material/download:", key=f"csv_{key}")
        st.download_button(tr("Eksport PDF", "Export PDF"), lambda: export_pdf(name, table), file_name="keputusan_kelas.pdf",
                           mime="application/pdf", icon=":material/picture_as_pdf:", key=f"pdf_{key}")


def summary_cards(rows, dec):
    """Exhibit 4, label 3: counts and the average time to first feedback (for the MOV)."""
    times = [(t - r["loaded"]).total_seconds() / 60 for r in rows if r["student"] in dec
             for (_, _, t) in [dec[r["student"]]]]
    with st.container(horizontal=True):
        st.metric(tr("pantun disemak", "pantun checked"), len(rows), border=True)
        st.metric(tr("gagal peraturan bentuk", "fail the form rules"),
                  sum(1 for r in rows if not form_chip(r).startswith("✔")), border=True)
        st.metric(tr("dihantar kepada pakar", "sent to an expert"), sum(1 for a, _, _ in dec.values() if a == "pakar"),
                  border=True)
        st.metric(tr("purata maklum balas pertama", "average time to first feedback"),
                  f"{np.mean(times):.1f} min" if times else "—", border=True,
                  help=tr("Masa dari muat naik hingga keputusan cikgu. Digunakan untuk mengukur MOV.",
                          "Time from upload to the teacher's decision. Used to measure the MOV."))


# ---- Side menu ----------------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### ![](/app/static/i/hornbill.png) Cenderawasih")
    section = st.radio("Menu", MENU, key="p_menu", label_visibility="collapsed", format_func=menu_name)
    st.caption(tr("Sistem membantu; cikgu membuat keputusan akhir.", "The system helps; the teacher decides."))

rows, dec = st.session_state["p_class"], st.session_state["p_decisions"]
with st.container(horizontal=True, horizontal_alignment="right"):
    help_button("pensyarah")


# ---- Papan pemuka: the teacher's home ------------------------------------------------------------
def go_to(i):
    st.session_state["p_menu"] = MENU[i]


def my_decisions():
    log = read_log(DECISIONS_CSV)
    if log.empty or ME["kind"] == "owner":
        return log
    return log[log["instructor"] == ME["username"]]


def activity(inq, log):
    """Newest things that happened in this lecturer's classes: inquiries in, replies out, decisions made."""
    items = []
    for r in inq.itertuples():
        who = dz.esc(r.who or tr("Tanpa nama", "No name"))
        text = (tr(f"Pertanyaan <b>{who}</b> dijawab", f"<b>{who}</b>'s question answered") if r.status == "selesai"
                else tr(f"<b>{who}</b> menghantar pertanyaan", f"<b>{who}</b> sent a question"))
        items.append((float(r.time), r.who or "?", text))
    if not log.empty:
        for r in log.tail(10).itertuples():
            t = pd.to_datetime(r.timestamp, errors="coerce")
            if pd.notna(t):
                when = t.tz_localize(dz.MYT).timestamp() if t.tzinfo is None else t.timestamp()
                act, who = dz.esc(action_name(r.action)), dz.esc(r.student)
                items.append((when, r.student, tr(f"Keputusan <b>{act}</b> untuk {who}",
                                                  f"Decision <b>{act}</b> for {who}")))
    return sorted(items, key=lambda x: -x[0])[:3]


def dashboard_page():
    st.html(dz.CSS)
    classes = classes_of(None if ME["kind"] == "owner" else ME["username"])
    students_of = {c["code"]: class_students(c["code"]) for c in classes}
    people = {s["username"] for group in students_of.values() for s in group}
    inq, log = inquiries_for(ME), my_decisions()
    waiting = inq[inq["status"] != "selesai"]
    answered = len(inq) - len(waiting)
    open_by_class = waiting["class_code"].value_counts().to_dict() if not waiting.empty else {}
    account = get_member(ME["username"]) if ME["kind"] == "member" else None

    with st.container(key="d_hero"):
        illus.stage(*dz.hero(ME["name"], len(waiting), len(classes), account["expires"] if account else None))
    with st.container(key="d_kpis"):
        st.html(dz.kpis([
            ("<img class=cz-i alt src=/app/static/i/school.png>", sum(1 for c in classes if c["active"]),
             tr("kelas aktif", "active classes"), "#2AA7E0", False),
            ("<img class=cz-i alt src=/app/static/i/backpack.png>", len(people), tr("murid", "pupils"), "#9B5DE5", False),
            ("<img class=cz-i alt src=/app/static/i/hourglass.png>", len(waiting), tr("menunggu jawapan", "waiting"),
             "#FF6B5E", len(waiting) > 0),
            ("<img class=cz-i alt src=/app/static/i/ok_mark.png>", answered, tr("pertanyaan dijawab", "questions answered"),
             "#1E9A50", False),
            ("<img class=cz-i alt src=/app/static/i/notebook.png>", len(log), tr("keputusan direkod", "decisions recorded"),
             "#F08A00", False),
        ]))

    with st.container(key="d_actions", horizontal=True):
        st.button(tr("Semak kelas", "Check a class"), key="d_go_class", icon=":material/upload_file:", width="stretch",
                  on_click=go_to, args=(1,))
        st.button(tr("Cipta kelas & kod", "Create class & code"), key="d_go_codes", icon=":material/add_circle:", width="stretch",
                  on_click=go_to, args=(2,))
        st.button(tr("Jawab pertanyaan", "Answer questions"), key="d_go_review", icon=":material/forum:", width="stretch",
                  on_click=go_to, args=(3,))
        st.button(tr("Lihat laporan", "See the report"), key="d_go_report", icon=":material/bar_chart:", width="stretch",
                  on_click=go_to, args=(4,))

    left, right = st.columns([3, 2], gap="medium")
    with left:
        steps = [(tr("Cipta kelas pertama anda", "Create your first class"), bool(classes)),
                 (tr("Kongsi kod kelas: seorang murid menyertai", "Share the class code: a pupil joins"), bool(people)),
                 (tr("Semak pantun atau jawab satu pertanyaan", "Check a pantun or answer a question"),
                  bool(answered or len(log)))]
        if not all(d for _, d in steps):
            with st.container(border=True, key="d_start"):
                st.html('<p class="dz-h"><img class=cz-i alt src=/app/static/i/rocket.png> ' + tr("Langkah bermula", "Getting started") + '</p>' + dz.checklist(steps))
        with st.container(border=True, key="d_waiting"):
            st.html('<p class="dz-h"><img class=cz-i alt src=/app/static/i/raise_hand.png> '
                    + tr("Perlu perhatian anda", "Needs your attention") + '</p>')
            if waiting.empty:
                illus.show("gutspose_man", 76, "float")
                st.html('<p class="dz-sub" style="text-align:center;margin:0">'
                        + tr("Tiada pertanyaan menunggu. Syabas!", "No questions waiting. Well done!") + '</p>')
            else:
                st.html(dz.inquiry_items(waiting.head(4)))
                if len(waiting) > 4:
                    st.caption(tr(f"dan {len(waiting) - 4} lagi", f"and {len(waiting) - 4} more"))
        st.html('<p class="dz-h" style="margin-top:6px"><img class=cz-i alt src=/app/static/i/school.png> '
                + tr("Kelas saya", "My classes") + '</p>')
        if classes:
            st.html(dz.class_cards(classes, students_of, open_by_class))
        else:
            illus.show("box_kara_hako", 80, "float")
            st.html('<p class="dz-sub" style="text-align:center">'
                    + tr("Belum ada kelas. Tekan <b>Cipta kelas &amp; kod</b>.",
                         "No classes yet. Press <b>Create class &amp; code</b>.") + '</p>')
    with right:
        with st.container(border=True, key="d_poem"):
            st.html('<p class="dz-h"><img class=cz-i alt src=/app/static/i/hibiscus.png> ' + tr("Pantun hari ini", "Today's pantun") + '</p>' + dz.poem(dz.poem_of_day(EXAMPLES)))
        if rows:
            done = sum(1 for r in rows if r["student"] in dec)
            with st.container(border=True, key="d_progress"):
                st.html(f'<p class="dz-h"><img class=cz-i alt src=/app/static/i/book.png> {dz.esc(st.session_state["p_class_name"])}</p>'
                        '<div class="dz-sub">' + tr(f"{done} daripada {len(rows)} pantun sudah diputuskan",
                                                    f"{done} of {len(rows)} pantun decided") + '</div>'
                        f'<div class="dz-meter"><i style="width:{100 * done / len(rows):.0f}%"></i></div>')
        with st.container(border=True, key="d_trend"):
            st.html('<p class="dz-h"><img class=cz-i alt src=/app/static/i/chart.png> ' + tr("Pertanyaan, 14 hari", "Questions, 14 days") + '</p>' + dz.bars(dz.daily_counts(inq["time"].tolist())))
        feed = activity(inq, log)
        with st.container(border=True, key="d_feed"):
            st.html('<p class="dz-h"><img class=cz-i alt src=/app/static/i/clock.png> '
                    + tr("Aktiviti terkini", "Latest activity") + '</p>'
                    + (dz.feed(feed) if feed else '<p class="dz-sub">' + tr("Aktiviti kelas anda akan muncul di sini.",
                                                                          "Your classes' activity will appear here.")
                       + '</p>'))


# ---- Kelas saya: upload, summary, work queue, review panel ---------------------------------------
def class_page():
    illus.stage("kelas", tr("Kelas Saya", "My Class"),
                tr("Muat naik pantun kelas, semak, dan buat keputusan.", "Upload your class's pantun, check them, and decide."),
                tr("Semak kelas", "Check a class"))
    with st.container(horizontal=True, vertical_alignment="bottom"):
        st.text_input(tr("Nama kelas", "Class name"), key="p_class_name", width=420)
        if rows:
            export_buttons(rows, dec, "top")
    if rows:
        st.caption(tr(f"{len(rows)} hantaran · dikemas kini {rows[0]['loaded']:%H:%M}",
                      f"{len(rows)} entries · updated {rows[0]['loaded']:%H:%M}"))

    with st.container(border=True, key="p_upload"):
        up = st.file_uploader(tr("Seret fail CSV kelas ke sini (ID murid, baris 1–4) atau pilih fail",
                                 "Drag the class CSV file here (pupil ID, lines 1–4) or choose a file"), type="csv")
        with st.container(horizontal=True):
            st.download_button(tr("Muat turun templat CSV", "Download the CSV template"), TEMPLATE.encode("utf-8"),
                               file_name="templat_kelas.csv", icon=":material/description:", type="tertiary")
            use_demo = st.button(tr("Guna kelas contoh", "Use the sample class"), icon=":material/science:", type="tertiary")
        if up is not None and st.button(tr("Semak fail ini", "Check this file"), type="primary", icon=":material/play_arrow:"):
            try:
                load_class(read_class_csv(io.BytesIO(up.getvalue())))
                st.rerun()
            except ValueError as e:
                st.error(str(e), icon=":material/error:")
        if use_demo:
            d = demo_class()
            load_class([(r.pelajar, [r.baris1, r.baris2, r.baris3, r.baris4]) for r in d.itertuples()])
            st.rerun()

    if not rows:
        st.info(tr("Muat naik fail CSV kelas, atau tekan **Guna kelas contoh** untuk mencuba.",
                   "Upload a class CSV file, or press **Use the sample class** to try it out."), icon=":material/upload:")
        return

    summary_cards(rows, dec)

    queue, panel = st.columns([3, 2], gap="large")
    with queue.container(key="p_queue"):
        n_review = sum(needs_review(r) for r in rows)
        filters = {"review": tr(f"Perlu semakan ({n_review})", f"Needs review ({n_review})"), "all": tr("Semua", "All"),
                   "form": tr("Gagal bentuk", "Form fails"), "unsure": tr("Makna: tidak pasti", "Meaning: not sure")}
        filt = st.segmented_control(tr("Tapis", "Filter"), list(filters), format_func=filters.get, default="review",
                                    key="p_filter", label_visibility="collapsed")
        shown = [r for r in rows if (
            filt is None or filt == "all"
            or (filt == "review" and needs_review(r))
            or (filt == "form" and not form_chip(r).startswith("✔"))
            or (filt == "unsure" and r["res"] is not None and r["res"]["lean"] == "cannot_tell"))]
        table = pd.DataFrame([{
            role("pelajar"): r["student"], tr("Bentuk", "Form"): form_chip(r),
            tr("Bunyi", "Sound"): "—" if r["res"] is None else f"{r['res']['sound']:g}/10",
            tr("Makna", "Meaning"): meaning_chip(r),
            tr("Keputusan cikgu", "Teacher's decision"): action_name(dec[r["student"]][0]) if r["student"] in dec else "—",
        } for r in shown])
        event = st.dataframe(table, hide_index=True, on_select="rerun", selection_mode="single-row",
                             key="p_table", alt=tr("Senarai kerja: pantun murid dan status semakan",
                                                   "Work list: pupils' pantun and review status"))
        st.caption(tr("Pilih satu baris untuk menyemaknya. Status sentiasa ditunjuk dengan ikon dan perkataan.",
                      "Pick a row to review it. Status is always shown with an icon and a word."))

    with panel.container(key="p_panel"):
        sel = event.selection.rows if event and event.selection else []
        if not sel or not shown:
            st.info(tr("Pilih pantun dalam senarai untuk menyemak.", "Pick a pantun in the list to review it."),
                    icon=":material/touch_app:")
            return
        row = shown[sel[0]]
        st.subheader(tr("Semak", "Review") + f": {row['student']}", anchor=False)
        if row["problems"]:
            st.markdown("\n".join(f"- {line}" for line in row["raw"] if line.strip()))
            for p in row["problems"]:
                st.error(p, icon=":material/rule:")
        else:
            res = row["res"]
            pantun_card(row["lines"])
            end_ok = next(c["passed"] for c in res["criteria"] if c["name"].startswith("End"))
            icon, _, caption = lean_words(res["lean"])
            st.markdown(
                f"{'✔' if res['rules'] == 4 else '✖'} {tr('Bentuk', 'Form')} {res['rules']}/4 · "
                f"{'✔' if end_ok else '✖'} {tr('Rima', 'Rhyme')} {rhyme_text(res)}  \n"
                f"{icon} {tr('Makna', 'Meaning')}: **{caption.lower()}** ({100 * res['p_avg']:.0f}%)  \n"
                + (tr("Perkataan dikongsi", "Shared words") + f": *{', '.join(res['shared'])}*" if res["shared"]
                   else tr("Tiada perkataan dikongsi", "No shared words")))
        hint = tr("Catatan untuk murid…", "Note for the pupil…")
        note = st.text_area(hint, key=f"p_note_{row['student']}", label_visibility="collapsed", placeholder=hint)

        def decide(action, extra=""):
            text = (extra + " " + note).strip()
            dec[row["student"]] = (action, text, datetime.now())
            save_decision(st.session_state["p_class_name"], row["student"], action, text,
                          row["lines"] if not row["problems"] else row["raw"], row["res"], ME["username"])

        if st.button(tr("Setuju dengan sistem", "Agree with the system"), type="primary", icon=":material/check:",
                     width="stretch", disabled=bool(row["problems"])):
            decide("setuju")
            st.rerun()
        with st.popover(tr("Ubah keputusan", "Change the decision"), icon=":material/edit:", width="stretch"):
            # Saved in Malay in the log (e.g. "[Sepadan]"), shown in the reader's language.
            choices = {"Sepadan": "Match", "Perlu dibaiki": "Needs work", "Tidak sepadan": "Does not match"}
            choice = st.segmented_control(tr("Keputusan anda", "Your decision"), list(choices),
                                          format_func=lambda c: tr(c, choices[c]), key=f"p_choice_{row['student']}")
            if st.button(tr("Simpan keputusan", "Save the decision"), disabled=choice is None,
                         key=f"p_save_{row['student']}"):
                decide("ubah", f"[{choice}]")
                st.rerun()
        if st.button(tr("Hantar kepada pakar", "Send to an expert"), icon=":material/flag:", width="stretch"):
            decide("pakar")
            st.rerun()
        if row["student"] in dec:
            a, n, t = dec[row["student"]]
            st.caption(tr("Keputusan direkod", "Decision recorded") + f": {action_name(a)} · {t:%H:%M}"
                       + (f" · {n}" if n else ""))
        st.caption(tr("Sistem membantu; **cikgu membuat keputusan akhir.** Setiap keputusan direkod.",
                      "The system helps; **the teacher makes the final decision.** Every decision is recorded."))


# ---- Semakan: requests from pupils and the decision log ------------------------------------------
def kind_label(kind):
    names = {"pelajar": ("Murid kelas", "Class pupil"), "tetamu": ("Tetamu (sementara)", "Guest (temporary)"),
             "pemilik": ("Pemilik", "Owner"), "lama": ("Lama", "Old")}
    return tr(*names[kind]) if kind in names else kind


def review_page():
    illus.stage("semakan", tr("Semakan", "Reviews"),
                tr("Pertanyaan “Saya tidak setuju” daripada murid anda.", "“I disagree” questions from your pupils."),
                tr("Jawab murid", "Answer your pupils"))
    st.caption(tr("Murid kelas anda: disimpan. Tetamu dan pelawat: dihantar kepada semua cikgu dan dipadam "
                  "apabila akses tetamu tamat.",
                  "Your class pupils: kept. Guests and visitors: sent to every teacher and deleted when guest "
                  "access ends."))
    inq = inquiries_for(ME)       # privacy: only your classes' pupils, plus current guests
    if inq.empty:
        illus.show("box_kara_hako", 90, "float")
        st.info(tr("Tiada pertanyaan. Murid boleh tekan **Saya tidak setuju** untuk meminta cikgu menyemak.",
                   "No questions. Pupils can press **I disagree** to ask the teacher to check."),
                icon=":material/inbox:")
    else:
        show_done = st.toggle(tr("Tunjuk yang sudah dijawab", "Show answered ones"), key="p_show_done")
        view = inq if show_done else inq[inq["status"] != "selesai"]
        table = pd.DataFrame({
            tr("Masa", "Time"): pd.to_datetime(view["time"], unit="s").dt.tz_localize("UTC")
                                  .dt.tz_convert("Asia/Kuala_Lumpur").dt.strftime("%d/%m %H:%M"),
            tr("Daripada", "From"): view["who"], tr("Jenis", "Kind"): view["kind"].map(kind_label),
            tr("Kelas", "Class"): view["class_name"].fillna(""), tr("Baris 1", "Line 1"): view["line1"],
            tr("Komen", "Comment"): view["comment"], tr("Makna %", "Meaning %"): view["meaning_pct"],
            "Status": view["status"].map({"baru": tr("Baru", "New"), "selesai": tr("Dijawab", "Answered")}),
        })
        if view.empty:
            st.success(tr("Semua pertanyaan sudah dijawab. Hidupkan **Tunjuk yang sudah dijawab** untuk melihatnya.",
                          "Every question is answered. Switch on **Show answered ones** to see them."),
                       icon=":material/task_alt:")
        # The table's key follows the toggle, so a row picked in one list isn't reused in the other.
        table_key = f"p_inq_table_{show_done}"
        ev = None if view.empty else st.dataframe(table, hide_index=True, on_select="rerun",
                                                  selection_mode="single-row", key=table_key,
                                                  alt=tr("Pertanyaan murid dan tetamu", "Pupils' and guests' questions"))
        sel = ev.selection.rows if ev and ev.selection else []
        # A remembered selection can point past the end once a row is answered (it leaves the list): ignore it.
        sel = [i for i in sel if 0 <= i < len(view)]
        if sel:
            row = view.iloc[sel[0]]
            with st.container(border=True):
                pantun_card([row["line1"], row["line2"], row["line3"], row["line4"]])
                st.markdown(f"**{row['who']}** · {kind_label(row['kind'])}"
                            + (f" · {row['class_name']}" if row["class_name"] else "")
                            + f"  \n{tr('Bunyi', 'Sound')} {row['sound']:g}/10 · {tr('Makna', 'Meaning')} "
                              f"{row['meaning_pct']}% · {tr('Peraturan', 'Rules')} {row['rules']}/4"
                            + (f"  \n> {row['comment']}" if row["comment"] else ""))
                if row["status"] == "selesai":
                    st.success(tr("Dijawab", "Answered") + f": {row['reply'] or tr('(tiada catatan)', '(no note)')}",
                               icon=":material/check:")
                else:
                    with st.form(f"p_reply_{row['id']}", border=False):
                        reply = st.text_area(tr("Jawapan kepada murid", "Reply to the pupil"),
                                             placeholder=tr("cth. Pembayang anda mengiaskan ...",
                                                            "e.g. Your pembayang hints at ..."))
                        if st.form_submit_button(tr("Tandakan dijawab", "Mark as answered"), type="primary",
                                                 icon=":material/check:"):
                            resolve_inquiry(int(row["id"]), ME, reply)
                            st.session_state.pop(table_key, None)    # forget the picked row: it may leave the list
                            st.rerun()
    st.subheader(tr("Log keputusan cikgu", "Teacher's decision log"), anchor=False)
    log = read_log(DECISIONS_CSV)
    if not log.empty and ME["kind"] != "owner":
        log = log[log["instructor"] == ME["username"]]          # only this teacher's own decisions
    if log.empty:
        st.info(tr("Belum ada keputusan direkod.", "No decisions recorded yet."), icon=":material/history:")
    else:
        log = log.assign(action=log["action"].map(action_name))
        st.dataframe(log[["timestamp", "class", "student", "action", "note", "line1", "line3"]].iloc[::-1],
                     hide_index=True, alt=tr("Setiap keputusan cikgu, terbaru dahulu", "Every teacher decision, newest first"))
        st.caption(tr("Setiap keputusan disimpan dalam results/instructor_decisions.csv (SRF12).",
                      "Every decision is saved in results/instructor_decisions.csv (SRF12)."))


# ---- Laporan: class summary and export ----------------------------------------------------------
def report_page():
    illus.stage("laporan", tr("Laporan", "Report"), dz.esc(st.session_state["p_class_name"]),
                tr("Ringkasan kelas", "Class summary"))
    if not rows:
        st.info(tr("Muat naik kelas dalam **Kelas saya** dahulu.", "Upload a class in **My class** first."),
                icon=":material/upload:")
        return
    summary_cards(rows, dec)
    left, right = st.columns(2, gap="large")
    with left:
        st.markdown(tr("**Bentuk pantun**", "**Pantun form**"))
        st.bar_chart(pd.Series([form_chip(r) for r in rows]).value_counts().rename("pantun"), horizontal=True,
                     color=TEAL, height=220)
    with right:
        st.markdown(tr("**Makna**", "**Meaning**"))
        st.bar_chart(pd.Series([meaning_chip(r) for r in rows]).value_counts().rename("pantun"), horizontal=True,
                     color="#DEB251", height=220)
    st.markdown(tr("**Muat turun keputusan kelas**", "**Download the class results**"))
    export_buttons(rows, dec, "report")


# ---- Kod kelas & murid: classes with join codes, and their pupils ---------------------------------
def _temp_key(student):
    if ME["kind"] == "owner" or teacher_has_student(ME["username"], student):
        st.session_state["p_temp_key"] = (student, reset_key(student))


def codes_page():
    illus.stage("kod", tr("Kod Kelas &amp; Murid", "Class Codes &amp; Pupils"),
                tr("Cipta kelas, beri kodnya kepada murid, dan pertanyaan mereka datang kepada anda.",
                   "Create a class, give its code to your pupils, and their questions come to you."),
                tr("Kumpul kelas anda", "Gather your class"))
    temp = st.session_state.get("p_temp_key")
    if temp:
        st.success(tr(f"Kata laluan sementara untuk **{temp[0]}**: `{temp[1]}` (dipaparkan sekali sahaja). Murid boleh "
                      "menukarnya selepas log masuk.",
                      f"Temporary password for **{temp[0]}**: `{temp[1]}` (shown only once). The pupil can change it "
                      "after logging in."), icon=":material/key:")
        if st.button(tr("Sudah diberi", "Given"), key="p_temp_ok"):
            st.session_state.pop("p_temp_key")
            st.rerun()
    with st.form("p_new_class", clear_on_submit=True, border=True):
        c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
        name = c1.text_input(tr("Nama kelas baharu", "New class name"),
                             placeholder=tr("cth. 4 Bestari · Pantun Nasihat", "e.g. 4 Bestari · Advice Pantun"))
        if c2.form_submit_button(tr("Cipta kelas", "Create class"), type="primary", icon=":material/add:"):
            try:
                code = create_class(ME["username"], name)
                st.success(tr(f"Kelas dicipta. Kod: **{code}**", f"Class created. Code: **{code}**"))
            except ValueError as e:
                st.error(str(e))
    classes = classes_of(None if ME["kind"] == "owner" else ME["username"])
    if not classes:
        illus.show("box_kara_hako", 90, "float")
        st.info(tr("Belum ada kelas.", "No classes yet."), icon=":material/school:")
    for c in classes:
        with st.container(border=True):
            head, code_col = st.columns([3, 1], vertical_alignment="center")
            head.markdown(f"**{c['name']}** · {c['n_students']} " + tr("murid", "pupils")
                          + ("" if c["active"] else " · :red-badge[" + tr("ditutup", "closed") + "]")
                          + ("" if c["teacher_ok"] else " · :red-badge[" + tr("cikgu tidak aktif", "teacher not active") + "]")
                          + (f"  \n:gray[{role('pensyarah')}: {c['teacher_name'] or tr('pemilik', 'owner')}]"
                             if ME["kind"] == "owner" else ""))
            code_col.code(c["code"], language=None)
            st.session_state.setdefault(f"p_act_{c['code']}", bool(c["active"]))   # fixed key: no flip-flop
            st.toggle(tr("Murid baharu boleh menyertai dengan kod ini", "New pupils can join with this code"),
                      key=f"p_act_{c['code']}",
                      on_change=lambda k=c["code"]: set_class_active(k, st.session_state[f"p_act_{k}"]))
            students = class_students(c["code"])
            if students:
                with st.expander(f"{role('pelajar')} ({len(students)})"):
                    for s_ in students:
                        with st.container(horizontal=True, vertical_alignment="center"):
                            st.markdown(f"**{s_['name']}** · `{s_['username']}`")
                            st.button(tr("Kata laluan sementara", "Temporary password"),
                                      key=f"tk_{c['code']}_{s_['username']}",
                                      icon=":material/key:", type="tertiary", on_click=_temp_key,
                                      args=(s_["username"],), help=tr("Jika murid lupa kata laluan.",
                                                                      "If the pupil forgot the password."))
                            st.button(tr("Keluarkan dari kelas", "Remove from class"), key=f"rm_{c['code']}_{s_['username']}",
                                      icon=":material/person_remove:", type="tertiary", on_click=remove_from_class,
                                      args=(c["code"], s_["username"]))


{"dash": dashboard_page, "class": class_page, "codes": codes_page, "review": review_page,
 "report": report_page}[section]()

pic = lambda name: f" <img class=cz-i alt src=/app/static/i/{name}.png>"
tour("pensyarah", [
    ("section[data-testid='stSidebar']", tr("Menu cikgu", "Teacher menu") + pic("book"),
     tr("<b>Papan pemuka</b> untuk gambaran harian, <b>Kelas saya</b> untuk menyemak kelas, <b>Kod kelas</b> untuk "
        "murid, <b>Semakan</b> untuk pertanyaan, <b>Laporan</b> untuk ringkasan.",
        "<b>Dashboard</b> for the daily picture, <b>My class</b> to check a class, <b>Class codes</b> for pupils, "
        "<b>Reviews</b> for questions, <b>Report</b> for the summary.")),
    (".st-key-d_kpis", tr("Gambaran kelas anda", "Your classes at a glance") + pic("home"),
     tr("Kelas, murid, dan pertanyaan yang <b>menunggu jawapan</b> sekali imbas.",
        "Classes, pupils, and questions <b>waiting for an answer</b> at a glance.")),
    (".st-key-d_actions", tr("Jalan pintas", "Shortcuts") + pic("stopwatch"),
     tr("Terus ke kerja utama: semak kelas, cipta kod, jawab pertanyaan atau laporan.",
        "Straight to the main jobs: check a class, create a code, answer questions or see the report.")),
    (".st-key-d_waiting", tr("Perlu perhatian", "Needs attention") + pic("raise_hand"),
     tr("Pertanyaan terbaru daripada murid anda ditunjuk di sini.", "Your pupils' newest questions are shown here.")),
    (".st-key-p_upload", tr("Muat naik kelas", "Upload a class") + pic("folder"),
     tr("Seret fail CSV (ID murid, baris 1–4). Muat turun templat, atau cuba <b>kelas contoh</b>.",
        "Drag in a CSV file (pupil ID, lines 1–4). Download the template, or try the <b>sample class</b>.")),
    (".st-key-p_queue", tr("Senarai kerja", "Work list") + pic("folder"),
     tr("<b>Perlu semakan</b> menunjukkan kes yang belum diputuskan dahulu. Pilih satu baris untuk menyemak.",
        "<b>Needs review</b> shows the undecided cases first. Pick a row to review it.")),
    (".st-key-p_panel", tr("Buat keputusan ✔", "Decide ✔"),
     tr("<b>Setuju</b>, <b>ubah keputusan</b> atau <b>hantar kepada pakar</b>. Setiap keputusan direkod.",
        "<b>Agree</b>, <b>change the decision</b> or <b>send to an expert</b>. Every decision is recorded.")),
    (".st-key-help_pensyarah", tr("Video tutorial", "Tutorial video") + pic("play"),
     tr("Tekan <b>Cara guna</b> untuk video tutorial bila-bila masa.", "Press <b>How to use</b> for the tutorial video any time.")),
])
