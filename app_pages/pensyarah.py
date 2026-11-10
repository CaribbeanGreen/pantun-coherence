"""Instructor view (business case Section 6.3, Exhibit 4; SRF11, SRF12): Malay, desktop.

Side menu (label 1): Kelas saya, Semakan, Laporan.
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

from src.app_core import (DECISIONS_CSV, FLAGS_CSV, LEAN_MALAY, TEAL, analyse, check_lines, pantun_card,
                          read_log, rhyme_text, save_decision)
from src.data_loader import load_pantun

ACTIONS = {"setuju": "✔ Setuju", "ubah": "✎ Diubah", "pakar": "⚑ Dihantar kepada pakar"}
TEMPLATE = "pelajar,baris1,baris2,baris3,baris4\nS001,Pisang emas dibawa belayar,Masak sebiji di atas peti,Hutang emas boleh dibayar,Hutang budi dibawa mati\n"
MENU = ["📚 Kelas saya", "📝 Semakan", "📊 Laporan"]

st.session_state.setdefault("p_class", [])         # one dict per submission
st.session_state.setdefault("p_decisions", {})     # student -> (action, note, time)
st.session_state.setdefault("p_class_name", "Kelas BM2 · Pantun Nasihat")

# Fixed teal side menu (Exhibit 4, label 1). This style only loads on this page.
st.html(f"""<style>
section[data-testid="stSidebar"] {{background:{TEAL}}}
section[data-testid="stSidebar"] * {{color:#fff}}
section[data-testid="stSidebar"] [role="radiogroup"] label {{padding:8px 10px;border-radius:8px;margin:2px 0}}
section[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {{background:rgba(255,255,255,.16);
  box-shadow:inset 3px 0 0 #DEB251;font-weight:700}}
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
    st.markdown("### 🟡 Cenderawasih")
    section = st.radio("Menu", MENU, key="p_menu", label_visibility="collapsed")
    st.caption("Sistem membantu; pensyarah membuat keputusan akhir.")

rows, dec = st.session_state["p_class"], st.session_state["p_decisions"]


# ---- Kelas saya: upload, summary, work queue, review panel ---------------------------------------
def class_page():
    with st.container(horizontal=True, vertical_alignment="bottom"):
        st.text_input("Nama kelas", key="p_class_name", width=420)
        if rows:
            export_buttons(rows, dec, "top")
    if rows:
        st.caption(f"{len(rows)} hantaran · dikemas kini {rows[0]['loaded']:%H:%M}")

    with st.container(border=True):
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
    with queue:
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

    with panel:
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
                          row["lines"] if not row["problems"] else row["raw"], row["res"])

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
def review_page():
    st.subheader("Permintaan semakan daripada pelajar", anchor=False)
    requests = read_log(FLAGS_CSV)
    requests = requests[requests["view"] == "pelajar"] if not requests.empty else requests
    if requests.empty:
        st.info("Tiada permintaan. Pelajar boleh tekan **Saya tidak setuju** untuk meminta guru menyemak.",
                icon=":material/inbox:")
    else:
        st.dataframe(requests[["timestamp", "who", "line1", "line2", "line3", "line4", "comment",
                               "sound", "meaning_pct", "rules"]].iloc[::-1], hide_index=True,
                     alt="Pantun yang pelajar minta guru semak")
    st.subheader("Log keputusan pensyarah", anchor=False)
    log = read_log(DECISIONS_CSV)
    if log.empty:
        st.info("Belum ada keputusan direkod.", icon=":material/history:")
    else:
        log = log.assign(action=log["action"].map(ACTIONS).fillna(log["action"]))
        st.dataframe(log[["timestamp", "class", "student", "action", "note", "line1", "line3"]].iloc[::-1],
                     hide_index=True, alt="Setiap keputusan pensyarah, terbaru dahulu")
        st.caption("Setiap keputusan disimpan dalam results/instructor_decisions.csv (SRF12).")


# ---- Laporan: class summary and export ----------------------------------------------------------
def report_page():
    st.subheader(f"Laporan · {st.session_state['p_class_name']}", anchor=False)
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


{MENU[0]: class_page, MENU[1]: review_page, MENU[2]: report_page}[section]()
