"""Instructor view (business case Section 6.3, Exhibit 4; SRF11, SRF12): Malay, desktop.

Side menu (label 1): Papan pemuka, Kelas saya, Kod kelas & pelajar, Semakan, Laporan.
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

from src.app_core import (DECISIONS_CSV, EXAMPLES, FLAGS_CSV, LEAN_MALAY, TEAL, analyse, check_lines, help_button,
                          pantun_card, read_log, rhyme_text, save_decision, tour)
from src import dashboard as dz
from src import illus
from src.data_loader import load_pantun
from src.share import (class_students, classes_of, create_class, current_user, get_member, inquiries_for,
                       remove_from_class, require_view, reset_key, resolve_inquiry, set_class_active, teacher_has_student)

require_view("pensyarah")      # lecturers (and the owner) only; students and guests never see this page
ME = current_user()

ACTIONS = {"setuju": "✔ Setuju", "ubah": "✎ Diubah", "pakar": "⚑ Dihantar kepada pakar"}
TEMPLATE = "pelajar,baris1,baris2,baris3,baris4\nS001,Pisang emas dibawa belayar,Masak sebiji di atas peti,Hutang emas boleh dibayar,Hutang budi dibawa mati\n"
MENU = ["![](/app/static/i/home.png) Papan pemuka", "![](/app/static/i/book.png) Kelas saya", "![](/app/static/i/school.png) Kod kelas & pelajar", "![](/app/static/i/notebook.png) Semakan", "![](/app/static/i/chart.png) Laporan"]

st.session_state.setdefault("p_class", [])         # one dict per submission
st.session_state.setdefault("p_decisions", {})     # student -> (action, note, time)
st.session_state.setdefault("p_class_name", "Kelas BM2 · Pantun Nasihat")

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
        raise ValueError("Fail perlu lajur baris1, baris2, baris3, baris4 (atau line1–line4).")
    return [(str(r[id_col]).strip(), [str(r[c]) for c in line_cols]) for _, r in df.iterrows()]


def load_class(entries):
    """Check and score every submission (with a progress bar)."""
    rows, bar = [], st.progress(0.0, text="Menyemak pantun kelas…")
    loaded = datetime.now()
    for k, (student, raw) in enumerate(entries):
        lines, problems = check_lines(raw)
        res = None if problems else analyse(lines)
        rows.append({"student": student, "raw": raw, "lines": lines, "problems": problems, "res": res,
                     "loaded": loaded})
        bar.progress((k + 1) / len(entries), text=f"Menyemak pantun kelas… {k + 1}/{len(entries)}")
    bar.empty()
    st.session_state["p_class"] = rows
    st.session_state["p_decisions"] = {}


def form_chip(row):
    if row["problems"]:
        n = len([l for l in row["raw"] if l.strip()])
        return f"✖ {n} baris" if n != 4 else "✖ format"
    res = row["res"]
    if res["rules"] == 4:
        return "✔ 4/4"
    end_ok = next(c["passed"] for c in res["criteria"] if c["name"].startswith("End"))
    return f"✖ {res['rules']}/4" + ("" if end_ok else " rima")


def meaning_chip(row):
    if row["res"] is None:
        return "—"
    icon, label, _ = LEAN_MALAY[row["res"]["lean"]]
    return f"{icon} {label}"


def needs_review(row):
    return row["student"] not in st.session_state["p_decisions"]


def export_table(rows, dec):
    return pd.DataFrame([{
        "pelajar": r["student"], "baris1": r["raw"][0], "baris2": r["raw"][1], "baris3": r["raw"][2],
        "baris4": r["raw"][3], "bentuk": form_chip(r),
        "bunyi": "" if r["res"] is None else f"{r['res']['sound']:g}/10",
        "makna_%": "" if r["res"] is None else round(100 * r["res"]["p_avg"]),
        "makna": meaning_chip(r),
        "keputusan": ACTIONS.get(dec.get(r["student"], ("",))[0], ""),
        "catatan": dec.get(r["student"], ("", ""))[1],
    } for r in rows])


def export_pdf(class_name, table):
    """A4 landscape PDF report of the class results (SRF11). Made with matplotlib, no extra package."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    cols = ["pelajar", "baris1", "baris3", "bentuk", "bunyi", "makna", "keputusan", "catatan"]
    heads = ["Pelajar", "Baris 1 (pembayang)", "Baris 3 (maksud)", "Bentuk", "Bunyi", "Makna", "Keputusan",
             "Catatan"]
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
            fig.text(0.04, 0.915, f"{len(body)} hantaran · dieksport {datetime.now():%d/%m/%Y %H:%M} · "
                                  f"halaman {start // per_page + 1}", fontsize=9, color="#52606D")
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
            fig.text(0.04, 0.035, "Skor ialah anggaran komputer. Pensyarah membuat keputusan akhir.",
                     fontsize=8, color="#52606D")
            pdf.savefig(fig)
            plt.close(fig)
    return buf.getvalue()


def export_buttons(rows, dec, key):
    table = export_table(rows, dec)
    name = st.session_state["p_class_name"]
    with st.container(horizontal=True, width="content"):
        st.download_button("Eksport CSV", table.to_csv(index=False).encode("utf-8-sig"),
                           file_name="keputusan_kelas.csv", icon=":material/download:", key=f"csv_{key}")
        st.download_button("Eksport PDF", lambda: export_pdf(name, table), file_name="keputusan_kelas.pdf",
                           mime="application/pdf", icon=":material/picture_as_pdf:", key=f"pdf_{key}")


def summary_cards(rows, dec):
    """Exhibit 4, label 3: counts and the average time to first feedback (for the MOV)."""
    times = [(t - r["loaded"]).total_seconds() / 60 for r in rows if r["student"] in dec
             for (_, _, t) in [dec[r["student"]]]]
    with st.container(horizontal=True):
        st.metric("pantun disemak", len(rows), border=True)
        st.metric("gagal peraturan bentuk", sum(1 for r in rows if not form_chip(r).startswith("✔")), border=True)
        st.metric("dihantar kepada pakar", sum(1 for a, _, _ in dec.values() if a == "pakar"), border=True)
        st.metric("purata maklum balas pertama", f"{np.mean(times):.1f} min" if times else "—", border=True,
                  help="Masa dari muat naik hingga keputusan pensyarah. Digunakan untuk mengukur MOV.")


# ---- Side menu ----------------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### ![](/app/static/i/hornbill.png) Cenderawasih")
    section = st.radio("Menu", MENU, key="p_menu", label_visibility="collapsed")
    st.caption("Sistem membantu; pensyarah membuat keputusan akhir.")

rows, dec = st.session_state["p_class"], st.session_state["p_decisions"]
with st.container(horizontal=True, horizontal_alignment="right"):
    help_button("pensyarah")


# ---- Papan pemuka: the lecturer's home ------------------------------------------------------------
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
        who = dz.esc(r.who or "Tanpa nama")
        text = f"Pertanyaan <b>{who}</b> dijawab" if r.status == "selesai" else f"<b>{who}</b> menghantar pertanyaan"
        items.append((float(r.time), r.who or "?", text))
    if not log.empty:
        for r in log.tail(10).itertuples():
            t = pd.to_datetime(r.timestamp, errors="coerce")
            if pd.notna(t):
                when = t.tz_localize(dz.MYT).timestamp() if t.tzinfo is None else t.timestamp()
                items.append((when, r.student, f"Keputusan <b>{dz.esc(ACTIONS.get(r.action, r.action))}</b> "
                                               f"untuk {dz.esc(r.student)}"))
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
            ("<img class=cz-i alt src=/app/static/i/school.png>", sum(1 for c in classes if c["active"]), "kelas aktif", "#2AA7E0", False),
            ("<img class=cz-i alt src=/app/static/i/backpack.png>", len(people), "pelajar", "#9B5DE5", False),
            ("<img class=cz-i alt src=/app/static/i/hourglass.png>", len(waiting), "menunggu jawapan", "#FF6B5E", len(waiting) > 0),
            ("<img class=cz-i alt src=/app/static/i/ok_mark.png>", answered, "pertanyaan dijawab", "#1E9A50", False),
            ("<img class=cz-i alt src=/app/static/i/notebook.png>", len(log), "keputusan direkod", "#F08A00", False),
        ]))

    with st.container(key="d_actions", horizontal=True):
        st.button("Semak kelas", key="d_go_class", icon=":material/upload_file:", width="stretch",
                  on_click=go_to, args=(1,))
        st.button("Cipta kelas & kod", key="d_go_codes", icon=":material/add_circle:", width="stretch",
                  on_click=go_to, args=(2,))
        st.button("Jawab pertanyaan", key="d_go_review", icon=":material/forum:", width="stretch",
                  on_click=go_to, args=(3,))
        st.button("Lihat laporan", key="d_go_report", icon=":material/bar_chart:", width="stretch",
                  on_click=go_to, args=(4,))

    left, right = st.columns([3, 2], gap="medium")
    with left:
        steps = [("Cipta kelas pertama anda", bool(classes)),
                 ("Kongsi kod kelas: seorang pelajar menyertai", bool(people)),
                 ("Semak pantun atau jawab satu pertanyaan", bool(answered or len(log)))]
        if not all(d for _, d in steps):
            with st.container(border=True, key="d_start"):
                st.html('<p class="dz-h"><img class=cz-i alt src=/app/static/i/rocket.png> Langkah bermula</p>' + dz.checklist(steps))
        with st.container(border=True, key="d_waiting"):
            st.html('<p class="dz-h"><img class=cz-i alt src=/app/static/i/raise_hand.png> Perlu perhatian anda</p>')
            if waiting.empty:
                illus.show("gutspose_man", 76, "float")
                st.html('<p class="dz-sub" style="text-align:center;margin:0">Tiada pertanyaan menunggu. Syabas!</p>')
            else:
                st.html(dz.inquiry_items(waiting.head(4)))
                if len(waiting) > 4:
                    st.caption(f"dan {len(waiting) - 4} lagi")
        st.html('<p class="dz-h" style="margin-top:6px"><img class=cz-i alt src=/app/static/i/school.png> Kelas saya</p>')
        if classes:
            st.html(dz.class_cards(classes, students_of, open_by_class))
        else:
            illus.show("box_kara_hako", 80, "float")
            st.html('<p class="dz-sub" style="text-align:center">Belum ada kelas. Tekan <b>Cipta kelas &amp; kod</b>.</p>')
    with right:
        with st.container(border=True, key="d_poem"):
            st.html('<p class="dz-h"><img class=cz-i alt src=/app/static/i/hibiscus.png> Pantun hari ini</p>' + dz.poem(dz.poem_of_day(EXAMPLES)))
        if rows:
            done = sum(1 for r in rows if r["student"] in dec)
            with st.container(border=True, key="d_progress"):
                st.html(f'<p class="dz-h"><img class=cz-i alt src=/app/static/i/book.png> {dz.esc(st.session_state["p_class_name"])}</p>'
                        f'<div class="dz-sub">{done} daripada {len(rows)} pantun sudah diputuskan</div>'
                        f'<div class="dz-meter"><i style="width:{100 * done / len(rows):.0f}%"></i></div>')
        with st.container(border=True, key="d_trend"):
            st.html('<p class="dz-h"><img class=cz-i alt src=/app/static/i/chart.png> Pertanyaan, 14 hari</p>' + dz.bars(dz.daily_counts(inq["time"].tolist())))
        feed = activity(inq, log)
        with st.container(border=True, key="d_feed"):
            st.html('<p class="dz-h"><img class=cz-i alt src=/app/static/i/clock.png> Aktiviti terkini</p>'
                    + (dz.feed(feed) if feed else '<p class="dz-sub">Aktiviti kelas anda akan muncul di sini.</p>'))


# ---- Kelas saya: upload, summary, work queue, review panel ---------------------------------------
def class_page():
    illus.stage("kelas", "Kelas Saya", "Muat naik pantun kelas, semak, dan buat keputusan.", "Semak kelas")
    with st.container(horizontal=True, vertical_alignment="bottom"):
        st.text_input("Nama kelas", key="p_class_name", width=420)
        if rows:
            export_buttons(rows, dec, "top")
    if rows:
        st.caption(f"{len(rows)} hantaran · dikemas kini {rows[0]['loaded']:%H:%M}")

    with st.container(border=True, key="p_upload"):
        up = st.file_uploader("Seret fail CSV kelas ke sini (ID pelajar, baris 1–4) atau pilih fail", type="csv")
        with st.container(horizontal=True):
            st.download_button("Muat turun templat CSV", TEMPLATE.encode("utf-8"), file_name="templat_kelas.csv",
                               icon=":material/description:", type="tertiary")
            use_demo = st.button("Guna kelas contoh", icon=":material/science:", type="tertiary")
        if up is not None and st.button("Semak fail ini", type="primary", icon=":material/play_arrow:"):
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
        st.info("Muat naik fail CSV kelas, atau tekan **Guna kelas contoh** untuk mencuba.", icon=":material/upload:")
        return

    summary_cards(rows, dec)

    queue, panel = st.columns([3, 2], gap="large")
    with queue.container(key="p_queue"):
        n_review = sum(needs_review(r) for r in rows)
        filt = st.segmented_control(
            "Tapis", [f"Perlu semakan ({n_review})", "Semua", "Gagal bentuk", "Makna: tidak pasti"],
            default=f"Perlu semakan ({n_review})", key="p_filter", label_visibility="collapsed")
        shown = [r for r in rows if (
            filt is None or filt == "Semua"
            or (filt.startswith("Perlu") and needs_review(r))
            or (filt == "Gagal bentuk" and not form_chip(r).startswith("✔"))
            or (filt == "Makna: tidak pasti" and r["res"] is not None and r["res"]["lean"] == "cannot_tell"))]
        table = pd.DataFrame([{
            "Pelajar": r["student"], "Bentuk": form_chip(r),
            "Bunyi": "—" if r["res"] is None else f"{r['res']['sound']:g}/10",
            "Makna": meaning_chip(r),
            "Keputusan pensyarah": ACTIONS.get(dec.get(r["student"], ("",))[0], "—"),
        } for r in shown])
        event = st.dataframe(table, hide_index=True, on_select="rerun", selection_mode="single-row",
                             key="p_table", alt="Senarai kerja: pantun pelajar dan status semakan")
        st.caption("Pilih satu baris untuk menyemaknya. Status sentiasa ditunjuk dengan ikon dan perkataan.")

    with panel.container(key="p_panel"):
        sel = event.selection.rows if event and event.selection else []
        if not sel or not shown:
            st.info("Pilih pantun dalam senarai untuk menyemak.", icon=":material/touch_app:")
            return
        row = shown[sel[0]]
        st.subheader(f"Semak: {row['student']}", anchor=False)
        if row["problems"]:
            st.markdown("\n".join(f"- {line}" for line in row["raw"] if line.strip()))
            for p in row["problems"]:
                st.error(p, icon=":material/rule:")
        else:
            res = row["res"]
            pantun_card(row["lines"])
            end_ok = next(c["passed"] for c in res["criteria"] if c["name"].startswith("End"))
            st.markdown(
                f"{'✔' if res['rules'] == 4 else '✖'} Bentuk {res['rules']}/4 · "
                f"{'✔' if end_ok else '✖'} Rima {rhyme_text(res)}  \n"
                f"{LEAN_MALAY[res['lean']][0]} Makna: **{LEAN_MALAY[res['lean']][2].lower()}** "
                f"({100 * res['p_avg']:.0f}%)  \n"
                + (f"Perkataan dikongsi: *{', '.join(res['shared'])}*" if res["shared"] else "Tiada perkataan dikongsi"))
        note = st.text_area("Catatan untuk pelajar…", key=f"p_note_{row['student']}", label_visibility="collapsed",
                            placeholder="Catatan untuk pelajar…")

        def decide(action, extra=""):
            text = (extra + " " + note).strip()
            dec[row["student"]] = (action, text, datetime.now())
            save_decision(st.session_state["p_class_name"], row["student"], action, text,
                          row["lines"] if not row["problems"] else row["raw"], row["res"], ME["username"])

        if st.button("Setuju dengan sistem", type="primary", icon=":material/check:", width="stretch",
                     disabled=bool(row["problems"])):
            decide("setuju")
            st.rerun()
        with st.popover("Ubah keputusan", icon=":material/edit:", width="stretch"):
            choice = st.segmented_control("Keputusan anda", ["Sepadan", "Perlu dibaiki", "Tidak sepadan"],
                                          key=f"p_choice_{row['student']}")
            if st.button("Simpan keputusan", disabled=choice is None, key=f"p_save_{row['student']}"):
                decide("ubah", f"[{choice}]")
                st.rerun()
        if st.button("Hantar kepada pakar", icon=":material/flag:", width="stretch"):
            decide("pakar")
            st.rerun()
        if row["student"] in dec:
            a, n, t = dec[row["student"]]
            st.caption(f"Keputusan direkod: {ACTIONS[a]} · {t:%H:%M}" + (f" · {n}" if n else ""))
        st.caption("Sistem membantu; **pensyarah membuat keputusan akhir.** Setiap keputusan direkod.")


# ---- Semakan: requests from students and the decision log ----------------------------------------
KIND_LABEL = {"pelajar": "Pelajar kelas", "tetamu": "Tetamu (sementara)", "pemilik": "Pemilik",
              "lama": "Lama"}


def review_page():
    illus.stage("semakan", "Semakan", "Pertanyaan “Saya tidak setuju” daripada pelajar anda.", "Jawab pelajar")
    st.caption("Pelajar kelas anda: disimpan. Tetamu dan pelawat: dihantar kepada semua pensyarah dan dipadam "
               "apabila akses tetamu tamat.")
    inq = inquiries_for(ME)       # privacy: only your classes' students, plus current guests
    if inq.empty:
        illus.show("box_kara_hako", 90, "float")
        st.info("Tiada pertanyaan. Pelajar boleh tekan **Saya tidak setuju** untuk meminta guru menyemak.",
                icon=":material/inbox:")
    else:
        show_done = st.toggle("Tunjuk yang sudah dijawab", key="p_show_done")
        view = inq if show_done else inq[inq["status"] != "selesai"]
        table = pd.DataFrame({
            "Masa": pd.to_datetime(view["time"], unit="s").dt.tz_localize("UTC").dt.tz_convert("Asia/Kuala_Lumpur")
                      .dt.strftime("%d/%m %H:%M"),
            "Daripada": view["who"], "Jenis": view["kind"].map(KIND_LABEL),
            "Kelas": view["class_name"].fillna(""), "Baris 1": view["line1"], "Komen": view["comment"],
            "Makna %": view["meaning_pct"], "Status": view["status"].map({"baru": "Baru", "selesai": "Dijawab"}),
        })
        if view.empty:
            st.success("Semua pertanyaan sudah dijawab. Hidupkan **Tunjuk yang sudah dijawab** untuk melihatnya.",
                       icon=":material/task_alt:")
        # The table's key follows the toggle, so a row picked in one list isn't reused in the other.
        table_key = f"p_inq_table_{show_done}"
        ev = None if view.empty else st.dataframe(table, hide_index=True, on_select="rerun",
                                                  selection_mode="single-row", key=table_key,
                                                  alt="Pertanyaan pelajar dan tetamu")
        sel = ev.selection.rows if ev and ev.selection else []
        # A remembered selection can point past the end once a row is answered (it leaves the list): ignore it.
        sel = [i for i in sel if 0 <= i < len(view)]
        if sel:
            row = view.iloc[sel[0]]
            with st.container(border=True):
                pantun_card([row["line1"], row["line2"], row["line3"], row["line4"]])
                st.markdown(f"**{row['who']}** · {KIND_LABEL.get(row['kind'], row['kind'])}"
                            + (f" · {row['class_name']}" if row["class_name"] else "")
                            + f"  \nBunyi {row['sound']:g}/10 · Makna {row['meaning_pct']}% · Peraturan {row['rules']}/4"
                            + (f"  \n> {row['comment']}" if row["comment"] else ""))
                if row["status"] == "selesai":
                    st.success(f"Dijawab: {row['reply'] or '(tiada catatan)'}", icon=":material/check:")
                else:
                    with st.form(f"p_reply_{row['id']}", border=False):
                        reply = st.text_area("Jawapan kepada pelajar", placeholder="cth. Pembayang anda mengiaskan ...")
                        if st.form_submit_button("Tandakan dijawab", type="primary", icon=":material/check:"):
                            resolve_inquiry(int(row["id"]), ME, reply)
                            st.session_state.pop(table_key, None)    # forget the picked row: it may leave the list
                            st.rerun()
    st.subheader("Log keputusan pensyarah", anchor=False)
    log = read_log(DECISIONS_CSV)
    if not log.empty and ME["kind"] != "owner":
        log = log[log["instructor"] == ME["username"]]          # only this lecturer's own decisions
    if log.empty:
        st.info("Belum ada keputusan direkod.", icon=":material/history:")
    else:
        log = log.assign(action=log["action"].map(ACTIONS).fillna(log["action"]))
        st.dataframe(log[["timestamp", "class", "student", "action", "note", "line1", "line3"]].iloc[::-1],
                     hide_index=True, alt="Setiap keputusan pensyarah, terbaru dahulu")
        st.caption("Setiap keputusan disimpan dalam results/instructor_decisions.csv (SRF12).")


# ---- Laporan: class summary and export ----------------------------------------------------------
def report_page():
    illus.stage("laporan", "Laporan", dz.esc(st.session_state["p_class_name"]), "Ringkasan kelas")
    if not rows:
        st.info("Muat naik kelas dalam **Kelas saya** dahulu.", icon=":material/upload:")
        return
    summary_cards(rows, dec)
    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("**Bentuk pantun**")
        st.bar_chart(pd.Series([form_chip(r) for r in rows]).value_counts().rename("pantun"), horizontal=True,
                     color=TEAL, height=220)
    with right:
        st.markdown("**Makna**")
        st.bar_chart(pd.Series([meaning_chip(r) for r in rows]).value_counts().rename("pantun"), horizontal=True,
                     color="#DEB251", height=220)
    st.markdown("**Muat turun keputusan kelas**")
    export_buttons(rows, dec, "report")


# ---- Kod kelas & pelajar: classes with join codes, and their students -----------------------------
def _temp_key(student):
    if ME["kind"] == "owner" or teacher_has_student(ME["username"], student):
        st.session_state["p_temp_key"] = (student, reset_key(student))


def codes_page():
    illus.stage("kod", "Kod Kelas &amp; Pelajar", "Cipta kelas, beri kodnya kepada pelajar, dan pertanyaan mereka datang kepada anda.", "Kumpul kelas anda")
    temp = st.session_state.get("p_temp_key")
    if temp:
        st.success(f"Kata laluan sementara untuk **{temp[0]}**: `{temp[1]}` (dipaparkan sekali sahaja). Pelajar boleh "
                   "menukarnya selepas log masuk.", icon=":material/key:")
        if st.button("Sudah diberi", key="p_temp_ok"):
            st.session_state.pop("p_temp_key")
            st.rerun()
    with st.form("p_new_class", clear_on_submit=True, border=True):
        c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
        name = c1.text_input("Nama kelas baharu", placeholder="cth. BM2 · Pantun Nasihat")
        if c2.form_submit_button("Cipta kelas", type="primary", icon=":material/add:"):
            try:
                code = create_class(ME["username"], name)
                st.success(f"Kelas dicipta. Kod: **{code}**")
            except ValueError as e:
                st.error(str(e))
    classes = classes_of(None if ME["kind"] == "owner" else ME["username"])
    if not classes:
        illus.show("box_kara_hako", 90, "float")
        st.info("Belum ada kelas.", icon=":material/school:")
    for c in classes:
        with st.container(border=True):
            head, code_col = st.columns([3, 1], vertical_alignment="center")
            head.markdown(f"**{c['name']}** · {c['n_students']} pelajar"
                          + ("" if c["active"] else " · :red-badge[ditutup]")
                          + ("" if c["teacher_ok"] else " · :red-badge[pensyarah tidak aktif]")
                          + (f"  \n:gray[Pensyarah: {c['teacher_name'] or 'pemilik'}]" if ME["kind"] == "owner" else ""))
            code_col.code(c["code"], language=None)
            st.session_state.setdefault(f"p_act_{c['code']}", bool(c["active"]))   # fixed key: no flip-flop
            st.toggle("Pelajar baharu boleh menyertai dengan kod ini", key=f"p_act_{c['code']}",
                      on_change=lambda k=c["code"]: set_class_active(k, st.session_state[f"p_act_{k}"]))
            students = class_students(c["code"])
            if students:
                with st.expander(f"Pelajar ({len(students)})"):
                    for s_ in students:
                        with st.container(horizontal=True, vertical_alignment="center"):
                            st.markdown(f"**{s_['name']}** · `{s_['username']}`")
                            st.button("Kata laluan sementara", key=f"tk_{c['code']}_{s_['username']}",
                                      icon=":material/key:", type="tertiary", on_click=_temp_key,
                                      args=(s_["username"],), help="Jika pelajar lupa kata laluan.")
                            st.button("Keluarkan dari kelas", key=f"rm_{c['code']}_{s_['username']}",
                                      icon=":material/person_remove:", type="tertiary", on_click=remove_from_class,
                                      args=(c["code"], s_["username"]))


{MENU[0]: dashboard_page, MENU[1]: class_page, MENU[2]: codes_page, MENU[3]: review_page, MENU[4]: report_page}[section]()

tour("pensyarah", [
    ("section[data-testid='stSidebar']", "Menu pensyarah <img class=cz-i alt src=/app/static/i/book.png>",
     "<b>Papan pemuka</b> untuk gambaran harian, <b>Kelas saya</b> untuk menyemak kelas, <b>Kod kelas</b> untuk pelajar, "
     "<b>Semakan</b> untuk pertanyaan, <b>Laporan</b> untuk ringkasan."),
    (".st-key-d_kpis", "Gambaran kelas anda <img class=cz-i alt src=/app/static/i/home.png>", "Kelas, pelajar, dan pertanyaan yang <b>menunggu jawapan</b> sekali imbas."),
    (".st-key-d_actions", "Jalan pintas <img class=cz-i alt src=/app/static/i/stopwatch.png>", "Terus ke kerja utama: semak kelas, cipta kod, jawab pertanyaan atau laporan."),
    (".st-key-d_waiting", "Perlu perhatian <img class=cz-i alt src=/app/static/i/raise_hand.png>", "Pertanyaan terbaru daripada pelajar anda ditunjuk di sini."),
    (".st-key-p_upload", "Muat naik kelas <img class=cz-i alt src=/app/static/i/folder.png>",
     "Seret fail CSV (ID pelajar, baris 1–4). Muat turun templat, atau cuba <b>kelas contoh</b>."),
    (".st-key-p_queue", "Senarai kerja <img class=cz-i alt src=/app/static/i/folder.png>",
     "<b>Perlu semakan</b> menunjukkan kes yang belum diputuskan dahulu. Pilih satu baris untuk menyemak."),
    (".st-key-p_panel", "Buat keputusan ✔",
     "<b>Setuju</b>, <b>ubah keputusan</b> atau <b>hantar kepada pakar</b>. Setiap keputusan direkod."),
    (".st-key-help_pensyarah", "Video tutorial <img class=cz-i alt src=/app/static/i/play.png>", "Tekan <b>Cara guna</b> untuk video tutorial bila-bila masa."),
])
