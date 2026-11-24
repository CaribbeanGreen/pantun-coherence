"""Pieces of the teacher's home page (Cikgu -> Papan pemuka / Dashboard). Everything shown comes from real data.
Text is in the reader's language (src/lang.py).

The functions here only turn data into HTML, so app_pages/pensyarah.py stays about what the page does.
All names and pantun text come from users, so they are always escaped.
"""

import html
from datetime import datetime, timedelta, timezone

import pandas as pd

from src import illus
from src.lang import current as lang_now, tr

MYT = timezone(timedelta(hours=8))
HARI = ["Isnin", "Selasa", "Rabu", "Khamis", "Jumaat", "Sabtu", "Ahad"]
BULAN = ["Januari", "Februari", "Mac", "April", "Mei", "Jun", "Julai", "Ogos", "September", "Oktober", "November",
         "Disember"]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]


def _month(m):
    return (MONTHS if lang_now() == "en" else BULAN)[m - 1]
AVATAR = ["#0C525C", "#8A4B1C", "#2F7D4F", "#A15C00", "#1B6E78", "#B4443C"]

CSS = """<style>
@keyframes dz-up { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: none; } }
@keyframes dz-grow { from { transform: scaleY(0); } to { transform: scaleY(1); } }
.dz-kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }
.dz-kpi { position: relative; background: var(--c); border: 4px solid #fff; border-radius: 24px; padding: 11px 15px; min-height: 104px;
  box-shadow: 0 6px 0 rgba(23, 50, 77, .2); animation: dz-up .5s both; animation-delay: var(--d); overflow: hidden; color: #fff; }
.dz-kpi span { position: absolute; right: 7px; top: 9px; line-height: 0; } .dz-kpi span img { height: 54px !important; min-width: 54px; max-width: 54px !important; margin: 0 !important; vertical-align: top !important; animation: ks-float 3s ease-in-out var(--d) infinite; }
@keyframes ks-float { 50% { transform: translateY(5px) rotate(4deg); } }
.dz-kpi b { display: block; font: 800 2.6rem/1.05 'Baloo 2', sans-serif; color: #fff; text-shadow: 0 3px 0 rgba(23, 50, 77, .25); }
.dz-kpi em { font-style: normal; color: #fff; font-size: .92rem; font-weight: 900; }
.dz-h { font: 800 1.35rem/1.25 'Baloo 2', sans-serif !important; color: #17324D; margin: 0 0 6px; }
.dz-sub { color: #52606D; font-size: .84rem; }
.dz-item { display: flex; gap: 11px; align-items: flex-start; padding: 10px 2px; border-top: 1px solid #F0EADC; }
.dz-item:first-of-type { border-top: 0; }
.dz-av { flex: none; width: 34px; height: 34px; border-radius: 50%; color: #fff; display: grid; place-items: center;
  font-weight: 800; font-size: .78rem; background: var(--c); border: 2px solid #fff; }
.dz-item div { min-width: 0; }
.dz-item b { color: #1F2A2E; }
.dz-line { font-family: 'Lora', serif; color: #1B6E78; display: block; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; }
.dz-classes { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 12px; }
.dz-class { background: #fff; border-radius: 22px; padding: 14px 16px 12px;
  border: 3px solid #BDE7FF; border-top: 9px solid #FFC83D; box-shadow: 0 5px 0 #CDEEFF; animation: dz-up .5s both; animation-delay: var(--d); }
.dz-class.off { border-top-color: #B9BDB8; }
.dz-class h4 { margin: 0; padding: 0; font-size: 1rem; color: #0C525C; font-weight: 800; }
.dz-code { display: inline-block; margin: 7px 0 9px; font-family: 'JetBrains Mono', monospace; font-weight: 600;
  letter-spacing: .12em; background: #E8F0EF; color: #0C525C; padding: 2px 9px; border-radius: 7px; }
.dz-faces { display: flex; align-items: center; min-height: 34px; }
.dz-faces .dz-av { margin-left: -8px; } .dz-faces .dz-av:first-child { margin-left: 0; }
.dz-faces span.dz-sub { margin-left: 8px; }
.dz-tag { display: inline-block; margin-top: 8px; font-size: .78rem; font-weight: 700; border-radius: 99px; padding: 2px 9px; }
.dz-tag.wait { background: #FDF4DD; color: #A15C00; } .dz-tag.ok { background: #E6F2EA; color: #2F7D4F; }
.dz-tag.off { background: #F7E7E5; color: #B4443C; }
.dz-bars { display: flex; align-items: flex-end; gap: 5px; height: 92px; margin-top: 6px; }
.dz-bars i { flex: 1; min-height: 3px; height: var(--h); background: var(--c, #0C525C); border-radius: 4px 4px 0 0;
  transform-origin: bottom; animation: dz-grow .6s cubic-bezier(.22,.8,.3,1) both; animation-delay: var(--d); }
.dz-axis { display: flex; justify-content: space-between; color: #52606D; font-size: .75rem; margin-top: 4px;
  border-top: 1px solid #E3DCCB; padding-top: 3px; }
.dz-poem { background: #F7EFE3; border-radius: 12px; padding: 14px 16px; font-family: 'Lora', serif; line-height: 1.6;
  border-left: 4px solid #DEB251; }
.dz-poem .a { color: #1B6E78; } .dz-poem .b { color: #8A4B1C; }
.dz-step { display: flex; gap: 11px; align-items: center; padding: 8px 0; color: #1F2A2E; }
.dz-step i { flex: none; width: 26px; height: 26px; border-radius: 50%; display: grid; place-items: center; font-style: normal;
  font-weight: 800; background: #EFE8DA; color: #52606D; font-size: .85rem; }
.dz-step.done i { background: #2F7D4F; color: #fff; } .dz-step.done span { color: #52606D; text-decoration: line-through; }
.dz-meter { height: 9px; background: #EFE8DA; border-radius: 9px; overflow: hidden; margin: 8px 0 3px; }
.dz-meter i { display: block; height: 100%; background: linear-gradient(90deg, #0C525C, #2F7D4F); border-radius: 9px; }
[class*="st-key-d_go"] button { min-height: 68px; }
@media (prefers-reduced-motion: reduce) { .dz-kpi, .dz-class, .dz-bars i { animation: none; } }
</style>"""


def esc(v):
    return html.escape(str(v if v is not None else ""))


def now_myt():
    return datetime.now(MYT)


def greeting(t=None):
    h = (t or now_myt()).hour
    if lang_now() == "en":
        return "Good morning" if 5 <= h < 12 else "Good afternoon" if 12 <= h < 19 else "Good evening"
    return "Selamat pagi" if 5 <= h < 12 else "Selamat tengah hari" if h < 14 and h >= 12 else \
        "Selamat petang" if 14 <= h < 19 else "Selamat malam"


def malay_date(t=None):
    t = t or now_myt()
    day = (DAYS if lang_now() == "en" else HARI)[t.weekday()]
    return f"{day}, {t.day} {_month(t.month)} {t.year}"


def ago(ts, now=None):
    """'5 min lalu' for a time in seconds since 1970."""
    d = max(0, int((now or now_myt().timestamp()) - ts))
    if lang_now() == "en":
        return "just now" if d < 60 else f"{d // 60} min ago" if d < 3600 else f"{d // 3600} h ago" \
            if d < 86400 else f"{d // 86400} days ago"
    return "baru sahaja" if d < 60 else f"{d // 60} min lalu" if d < 3600 else f"{d // 3600} jam lalu" \
        if d < 86400 else f"{d // 86400} hari lalu"


def initials(name):
    parts = [p for p in str(name).split() if p[:1].isalnum()]
    return esc("".join(p[0] for p in parts[:2]).upper() or "?")


def avatar(name):
    colour = AVATAR[sum(map(ord, str(name))) % len(AVATAR)]
    return f'<div class="dz-av" style="--c:{colour}" title="{esc(name)}">{initials(name)}</div>'


def hero(name, n_open, n_classes, expires=None, t=None):
    """Arguments for illus.stage: the greeting at the top of the page."""
    t = t or now_myt()
    if n_open:
        line = tr(f"<b>{n_open} pertanyaan</b> murid sedang menunggu jawapan anda.",
                  f"<b>{n_open} pupil question{'s' if n_open != 1 else ''}</b> waiting for your answer.")
    elif n_classes:
        line = tr("Tiada pertanyaan tertunggak. Kelas anda dalam keadaan baik!",
                  "No questions waiting. Your classes are in good shape!")
    else:
        line = tr("Mari mulakan dengan mencipta kelas pertama anda.", "Let's start by creating your first class.")
    pill = ""
    if expires:
        when = datetime.fromtimestamp(expires, MYT)
        pill = tr("Akaun sah hingga", "Account valid until") + f" {when.day} {_month(when.month)} {when.year}"
    return "dash", f"{greeting(t)}, {esc(name)}!", line, malay_date(t), pill


def kpis(items):
    """items: [(icon, value, label, colour, highlighted)]"""
    cards = "".join(f'<div class="dz-kpi{" hot" if hot else ""}" style="--c:{c};--d:{i * .07:.2f}s"><span>{icon}</span>'
                    f"<b>{esc(v)}</b><em>{esc(label)}</em></div>" for i, (icon, v, label, c, hot) in enumerate(items))
    return f'<div class="dz-kpis">{cards}</div>'


def inquiry_items(df, now=None):
    out = []
    for r in df.itertuples():
        where = r.class_name if isinstance(r.class_name, str) and r.class_name else \
            {"tetamu": tr("Tetamu", "Guest"), "pemilik": tr("Tiada kelas", "No class"),
             "lama": tr("Rekod lama", "Old record")}.get(r.kind, "")
        out.append(f'<div class="dz-item">{avatar(r.who or "?")}<div><b>{esc(r.who or tr("Tanpa nama", "No name"))}</b> '
                   f'<span class="dz-sub">· {esc(where)} · {ago(r.time, now)}</span>'
                   f'<span class="dz-line">{esc(r.line1)}</span></div></div>')
    return "".join(out)


def class_cards(classes, students_of, open_by_class):
    cards = []
    for i, c in enumerate(classes):
        people = students_of.get(c["code"], [])
        faces = "".join(avatar(p["name"]) for p in people[:5])
        extra = f"+{len(people) - 5} " + tr("lagi", "more") if len(people) > 5 else ""
        count = (tr(f"{len(people)} murid", f"{len(people)} pupils") if people else
                 tr("Belum ada murid. Kongsi kod ini.", "No pupils yet. Share this code."))
        n = open_by_class.get(c["code"], 0)
        if not c["teacher_ok"]:
            tag, off = f'<span class="dz-tag off">{tr("Cikgu tidak aktif", "Teacher not active")}</span>', True
        elif not c["active"]:
            tag, off = f'<span class="dz-tag off">{tr("Kod ditutup", "Code closed")}</span>', True
        elif n:
            tag, off = (f'<span class="dz-tag wait"><img class=cz-i alt src=/app/static/i/hourglass.png> {n} '
                        f'{tr("menunggu jawapan", "waiting")}</span>'), False
        else:
            tag, off = f'<span class="dz-tag ok">✔ {tr("Semua terjawab", "All answered")}</span>', False
        cards.append(f'<div class="dz-class{" off" if off else ""}" style="--d:{min(i, 6) * .06:.2f}s"><h4>{esc(c["name"])}</h4>'
                     f'<span class="dz-code">{esc(c["code"])}</span><div class="dz-faces">{faces}'
                     f'<span class="dz-sub">{esc(extra or count)}</span></div>{tag}</div>')
    return f'<div class="dz-classes">{"".join(cards)}</div>'


def daily_counts(times, days=14, now=None):
    """Inquiries per day for the last `days` days (oldest first), by Malaysian date."""
    today = datetime.fromtimestamp(now, MYT).date() if now else now_myt().date()
    span = [today - timedelta(days=k) for k in range(days - 1, -1, -1)]
    seen = pd.Series([datetime.fromtimestamp(float(t), MYT).date() for t in times], dtype=object).value_counts()
    return [(d, int(seen.get(d, 0))) for d in span]


def bars(counts):
    top = max((n for _, n in counts), default=0) or 1
    cells = "".join(f'<i title="{d.day}/{d.month}: {n}" style="--h:{max(4, round(100 * n / top))}%;'
                    f'--c:{"#DEB251" if k == len(counts) - 1 else "#0C525C" if n else "#E3DCCB"};--d:{k * .025:.2f}s"></i>'
                    for k, (d, n) in enumerate(counts))
    first, last = counts[0][0], counts[-1][0]
    label = tr("Pertanyaan setiap hari, 14 hari terakhir", "Questions per day, last 14 days")
    return (f'<div class="dz-bars" role="img" aria-label="{label}">{cells}</div>'
            f'<div class="dz-axis"><span>{first.day}/{first.month}</span><span>{tr("hari ini", "today")}</span></div>')


def poem(lines):
    e = [esc(l.rstrip(" ,;.")) for l in lines]
    return (f'<div class="dz-poem"><div class="a">{e[0]},<br>{e[1]};</div><div class="b">{e[2]},<br>{e[3]}.</div></div>')


def poem_of_day(examples, t=None):
    """A different real example each day (the mixed-up test example is left out)."""
    names = [n for n in examples if "ujian" not in n]
    return examples[names[(t or now_myt()).toordinal() % len(names)]]


def checklist(steps):
    """steps: [(text, done)]. A progress meter and the list."""
    n = sum(d for _, d in steps)
    rows = "".join(f'<div class="dz-step{" done" if d else ""}"><i>{"✓" if d else k + 1}</i><span>{esc(s)}</span></div>'
                   for k, (s, d) in enumerate(steps))
    return (f'<div class="dz-sub">{tr(f"{n} daripada {len(steps)} selesai", f"{n} of {len(steps)} done")}</div><div class="dz-meter">'
            f'<i style="width:{100 * n / len(steps):.0f}%"></i></div>{rows}')


def feed(items, now=None):
    """items: [(time, who, text)], newest first."""
    return "".join(f'<div class="dz-item">{avatar(w)}<div>{text}<br><span class="dz-sub">{ago(t, now)}</span></div></div>'
                   for t, w, text in items)
