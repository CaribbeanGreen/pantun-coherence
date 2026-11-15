"""Temporary sharing with a rotating 6-digit code (like an authenticator app), with a device monitor.

How it works (full guide: docs/sharing_guide.md):
  - On this computer (the owner) the app opens as normal and has an extra "Kongsi" page.
  - Visitors come through the Cloudflare tunnel (their requests carry Cloudflare headers). They see a code
    screen, and nothing else, until they type the current code.
  - A code only works while the owner has switched sharing ON (a "round"). Sharing switches itself off after
    the chosen time. Switching it off, or pressing "Keluarkan semua", starts a new round and locks everyone out.
  - The code changes every 15 seconds (TOTP, RFC 6238, HMAC-SHA1). With GRACE_STEPS = 1 the code from the
    previous 15 s is also accepted, so there is time to read it out. Set it to 0 to accept the current code only.
  - Every visitor who gets in is listed on the Kongsi page (name, device, IP, country, last active). The owner
    can remove one device, or remove it and block its IP address for the rest of the round.
  - Wrong codes are limited per IP address and overall; too many wrong codes pause the code screen.

The secret and the on/off state live in results/share_state.json; the access log is results/share_log.csv.
Both stay on this computer (results/ is in .gitignore). The device list lives in memory and is cleared
when a new round starts or the app restarts.
"""

import csv
import hashlib
import hmac
import json
import os
import re
import secrets
import struct
import threading
import time
from datetime import datetime

import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx

from src.data_loader import PROJECT_ROOT

STATE_FILE = PROJECT_ROOT / "results" / "share_state.json"
LOG_FILE = PROJECT_ROOT / "results" / "share_log.csv"
PUBLIC_URL = "https://pantun.aimanjamal.com"

PERIOD = 15                 # seconds per code
DIGITS = 6
GRACE_STEPS = 1             # also accept the code from this many earlier periods (0 = current code only)
IP_FAILS, IP_WINDOW = 5, 600            # 5 wrong codes per IP address in 10 minutes
ALL_FAILS, ALL_WINDOW = 30, 3600        # 30 wrong codes from everyone in 1 hour -> code screen paused
HEARTBEAT = 10              # an open visitor page checks in every 10 s (and is locked if removed)
ONLINE_FOR = 3 * HEARTBEAT  # "online" if seen in the last 30 s

_lock = threading.RLock()
_reg = {"round": None, "devices": {}, "blocked": set(), "fails": []}   # in memory, one per server


# ---- On/off state (file) -------------------------------------------------------------------------

def _read():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _write(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f)
    os.replace(tmp, STATE_FILE)        # atomic: never a half-written file


def state():
    """Current sharing state. Creates the secret the first time. Turns sharing off when its time is up."""
    with _lock:
        s = _read()
        changed = False
        if not s.get("secret"):
            s.update(secret=secrets.token_hex(20), enabled=False, until=0, round="")
            changed = True
        if s.get("enabled") and time.time() >= s.get("until", 0):
            s.update(enabled=False, round="")
            changed = True
            _log("tamat masa")
        if changed:
            _write(s)
        return s


def set_sharing(on, hours=1.0):
    """Switch sharing on for `hours`, or off. Each switch starts a new round, so old visitors are locked out."""
    with _lock:
        s = _read()
        if on:
            s.update(enabled=True, until=time.time() + hours * 3600, round=secrets.token_hex(8))
        else:
            s.update(enabled=False, until=0, round="")
        _write(s)
    _log("perkongsian hidup" if on else "perkongsian mati", note=f"{hours:g} jam" if on else "")


def kick_all():
    """New round with the same end time: every device must type a fresh code again."""
    with _lock:
        s = _read()
        if s.get("enabled"):
            s["round"] = secrets.token_hex(8)
            _write(s)
    _log("keluarkan semua")


# ---- Codes (TOTP, RFC 6238) ----------------------------------------------------------------------

def code_at(secret, t):
    """6-digit code for time t: HMAC-SHA1(secret, number of 15-s steps since 1970), then 'dynamic truncation'."""
    counter = int(t // PERIOD)
    digest = hmac.new(bytes.fromhex(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    number = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(number % 10 ** DIGITS).zfill(DIGITS)


def verify(code):
    s = state()
    if not s["enabled"]:
        return False
    code = "".join(ch for ch in str(code) if ch.isdigit())
    now = time.time()
    return any(hmac.compare_digest(code, code_at(s["secret"], now - k * PERIOD)) for k in range(GRACE_STEPS + 1))


# ---- Who is asking -------------------------------------------------------------------------------

def is_visitor():
    """True for requests that come through Cloudflare (the public address). Cloudflare always adds these
    headers, so a visitor cannot hide them. PANTUN_FORCE_GATE=1 shows the visitor screen locally (testing)."""
    if os.environ.get("PANTUN_FORCE_GATE") == "1":
        return True
    h = st.context.headers
    return bool(h.get("Cf-Ray") or h.get("Cf-Connecting-Ip"))


def _session_id():
    ctx = get_script_run_ctx()
    return ctx.session_id if ctx else "?"


def device_label(ua):
    """'Chrome · Android' style label from a browser's User-Agent text."""
    ua = ua or ""
    os_name = next((n for p, n in [(r"iPhone", "iPhone"), (r"iPad", "iPad"), (r"Android", "Android"),
                                   (r"Windows", "Windows"), (r"Mac OS X|Macintosh", "Mac"), (r"CrOS", "Chromebook"),
                                   (r"Linux", "Linux")] if re.search(p, ua)), "?")
    browser = next((n for p, n in [(r"Edg/", "Edge"), (r"SamsungBrowser", "Samsung"), (r"OPR/|Opera", "Opera"),
                                   (r"Firefox/|FxiOS", "Firefox"), (r"Chrome/|CriOS", "Chrome"),
                                   (r"Safari/", "Safari")] if re.search(p, ua)), "?")
    return f"{browser} · {os_name}"


def _client():
    h = st.context.headers
    ua = h.get("User-Agent", "")
    return {"ip": h.get("Cf-Connecting-Ip") or st.context.ip_address or "?",
            "country": h.get("Cf-Ipcountry", "?"), "ua": ua, "device": device_label(ua)}


# ---- Device register and access log --------------------------------------------------------------

def _registry(round_id):
    """The device list for this round (a new round starts with an empty list and no blocked IPs)."""
    with _lock:
        if _reg["round"] != round_id:
            _reg.update(round=round_id, devices={}, blocked=set(), fails=[])
        return _reg


def _log(event, name="", ip="", country="", device="", note=""):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    new = not LOG_FILE.exists()
    with _lock, open(LOG_FILE, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["masa", "peristiwa", "nama", "ip", "negara", "peranti", "catatan"])
        w.writerow([datetime.now().isoformat(timespec="seconds"), event, name, ip, country, device, note])


def _fail_counts(reg, ip):
    now = time.time()
    with _lock:
        reg["fails"] = [(t, a) for t, a in reg["fails"] if now - t < max(IP_WINDOW, ALL_WINDOW)]
        mine = sum(1 for t, a in reg["fails"] if a == ip and now - t < IP_WINDOW)
        everyone = sum(1 for t, _ in reg["fails"] if now - t < ALL_WINDOW)
    return mine, everyone


def remove_device(sid, block_ip=False):
    """Owner action: lock one device out now (within HEARTBEAT seconds); optionally block its IP for this round."""
    with _lock:
        dev = _reg["devices"].get(sid)
        if not dev:
            return
        dev["status"] = "disekat" if block_ip else "dikeluarkan"
        if block_ip:
            _reg["blocked"].add(dev["ip"])
    _log("disekat" if block_ip else "dikeluarkan", dev["name"], dev["ip"], dev["country"], dev["device"])


def unblock_ip(ip):
    with _lock:
        _reg["blocked"].discard(ip)
    _log("buka sekatan", ip=ip)


# ---- Visitor screens -----------------------------------------------------------------------------

_GATE_CSS = """<style>
.cz-gate { max-width: 440px; margin: 7vh auto 0; text-align: center; font-family: 'Nunito', sans-serif; }
.cz-gate .logo { width: 54px; height: 54px; border-radius: 50%; background: #DEB251; margin: 0 auto 14px;
  box-shadow: 0 8px 24px rgba(222, 178, 81, .45); }
.cz-gate h1 { font-size: 1.9rem; font-weight: 900; color: #0C525C; margin: 0; padding: 0; }
.cz-gate p { color: #45525a; font-size: 1.02rem; line-height: 1.55; margin: 8px 0 0; }
.st-key-share_gate { max-width: 440px; margin: 0 auto; }
.st-key-share_gate input[maxlength="6"] { text-align: center; font-size: 1.9rem !important; letter-spacing: .5em;
  font-family: 'JetBrains Mono', monospace !important; }
.st-key-share_gate [data-testid="InputInstructions"] { display: none; }
</style>"""


def _screen(title, malay, english):
    st.html(_GATE_CSS + f"""<div class="cz-gate"><div class="logo"></div><h1>{title}</h1><p>{malay}</p>
        <p style="font-size:.92rem;color:#6b7478">{english}</p></div>""")


def gate():
    """Stop the page for visitors who have not typed a valid code in the current round, or were removed."""
    if not is_visitor():
        return
    s = state()
    if not s["enabled"]:
        st.session_state.pop("share_ok", None)
        _screen("Perkongsian ditutup",
                "Pemilik belum membuka akses ke Semak Pantun. Minta mereka hidupkan perkongsian dan berikan kod.",
                "Sharing is closed. Ask the owner to switch it on and give you a code.")
        st.stop()

    reg, sid, me = _registry(s["round"]), _session_id(), _client()
    dev = reg["devices"].get(sid)
    if me["ip"] in reg["blocked"] or (dev and dev["status"] == "disekat"):
        st.session_state.pop("share_ok", None)
        _screen("Akses disekat", "Pemilik telah menyekat peranti ini.", "The owner has blocked this device.")
        st.stop()
    if dev and dev["status"] == "dikeluarkan":
        st.session_state.pop("share_ok", None)
        # The record stays in the owner's list. Reloading the page starts a new session, which needs a new code
        # (use "Sekat IP" to keep someone out completely).
        _screen("Akses ditarik balik", "Pemilik telah mengeluarkan peranti ini.",
                "The owner removed this device from the site.")
        st.stop()
    if st.session_state.get("share_ok") == s["round"] and dev:
        dev["last"] = time.time()
        _watch()
        return

    _screen("Masukkan kod akses", "Minta kod 6 digit daripada pemilik. Kod bertukar setiap 15 saat.",
            "Enter the 6-digit code from the owner. It changes every 15 seconds.")
    with st.container(key="share_gate"):
        with st.form("share_form", border=False):
            name = st.text_input("Nama anda", max_chars=40, placeholder="Nama anda (supaya pemilik kenal)")
            code = st.text_input("Kod", max_chars=DIGITS, placeholder="••••••", label_visibility="collapsed")
            go = st.form_submit_button("Masuk", type="primary", icon=":material/lock_open:", width="stretch")
        if go:
            mine, everyone = _fail_counts(reg, me["ip"])
            name = name.strip() or "(tiada nama)"
            if everyone >= ALL_FAILS:
                st.error("Skrin kod dijeda kerana terlalu banyak kod salah. Minta pemilik memulakan semula "
                         "perkongsian.", icon=":material/pause_circle:")
            elif mine >= IP_FAILS:
                st.error("Terlalu banyak kod salah dari rangkaian ini. Cuba lagi dalam 10 minit.",
                         icon=":material/timer:")
            elif verify(code):
                with _lock:
                    reg["devices"][sid] = {"sid": sid, "name": name, **me, "first": time.time(),
                                           "last": time.time(), "status": "aktif"}
                _log("masuk", name, me["ip"], me["country"], me["device"])
                st.session_state["share_ok"] = s["round"]
                st.rerun()
            else:
                with _lock:
                    reg["fails"].append((time.time(), me["ip"]))
                _log("kod salah", name, me["ip"], me["country"], me["device"])
                st.error("Kod tidak sah atau sudah tamat. Minta kod baharu.", icon=":material/error:")
    st.stop()


@st.fragment(run_every=HEARTBEAT)
def _watch():
    """Heartbeat from an open visitor page: marks it online, and locks it if the owner removed it,
    switched sharing off, or started a new round."""
    s = state()
    reg = _registry(s["round"]) if s["enabled"] else None
    dev = reg["devices"].get(_session_id()) if reg else None
    if (not s["enabled"] or st.session_state.get("share_ok") != s["round"] or not dev or dev["status"] != "aktif"
            or dev["ip"] in reg["blocked"]):
        st.session_state.pop("share_ok", None)
        st.rerun()
    dev["last"] = time.time()


# ---- Owner page ----------------------------------------------------------------------------------

def owner_page():
    """'Kongsi' page (owner only): switch sharing on/off, show the live code, and watch/remove devices."""
    st.title("Kongsi Semak Pantun", anchor=False)
    st.caption(f"Alamat awam: {PUBLIC_URL} · hanya orang yang ada kod boleh masuk")
    s = state()

    with st.container(border=True):
        if s["enabled"]:
            ends = datetime.fromtimestamp(s["until"])
            st.success(f"Perkongsian **HIDUP** sehingga {ends:%H:%M} ({ends:%d/%m}).", icon=":material/share:")
            with st.container(horizontal=True):
                if st.button("Matikan perkongsian sekarang", type="primary", icon=":material/block:"):
                    set_sharing(False)
                    st.rerun()
                if st.button("Keluarkan semua peranti", icon=":material/group_remove:",
                             help="Semua pelawat perlu memasukkan kod baharu. Perkongsian kekal hidup."):
                    kick_all()
                    st.rerun()
            st.caption("Mematikan perkongsian atau mengeluarkan semua akan mengunci pelawat dalam masa "
                       f"{HEARTBEAT} saat.")
        else:
            st.info("Perkongsian **MATI**. Pelawat tidak boleh masuk dan tiada kod yang sah.", icon=":material/lock:")
            hours = st.segmented_control("Berapa lama?", [0.5, 1, 2, 4, 8], default=1, required=True,
                                         format_func=lambda h: "30 min" if h == 0.5 else f"{h:g} jam")
            if st.button("Hidupkan perkongsian", type="primary", icon=":material/share:"):
                set_sharing(True, hours)
                st.rerun()

    if s["enabled"]:
        live_code()
        devices_panel()
    if LOG_FILE.exists():
        st.download_button("Muat turun log akses (CSV)", LOG_FILE.read_bytes(), file_name="share_log.csv",
                           icon=":material/download:", type="tertiary")


@st.fragment(run_every=1)
def live_code():
    s = state()
    if not s["enabled"]:
        st.rerun()                      # time is up: redraw the whole page
    now = time.time()
    left = PERIOD - (now % PERIOD)
    code = code_at(s["secret"], now)
    deg = 360 * left / PERIOD
    grace = (f"kod sebelumnya masih diterima {PERIOD * GRACE_STEPS} saat lagi" if GRACE_STEPS
             else "hanya kod semasa diterima")
    st.html(f"""
<div style="display:flex;align-items:center;gap:22px;justify-content:center;margin:18px 0 6px;font-family:'Nunito',sans-serif">
  <div style="font:800 3.4rem 'JetBrains Mono',monospace;letter-spacing:.18em;color:#0C525C">{code[:3]}&nbsp;{code[3:]}</div>
  <div role="img" aria-label="{int(left)} saat lagi" style="width:62px;height:62px;border-radius:50%;
       background:conic-gradient(#DEB251 {deg:.0f}deg,#E6E1D6 0);display:flex;align-items:center;justify-content:center">
    <div style="width:46px;height:46px;border-radius:50%;background:#FBF7EE;display:flex;align-items:center;
         justify-content:center;font-weight:800;color:#1F2A2E">{int(left)}s</div>
  </div>
</div>
<div style="text-align:center;color:#5b6670;font-size:.95rem">Berikan kod ini kepada pelawat. Ia bertukar setiap {PERIOD} saat ({grace}).</div>""")


def _ago(t):
    d = int(time.time() - t)
    return f"{d} s lalu" if d < 60 else f"{d // 60} min lalu" if d < 3600 else f"{d // 3600} jam lalu"


@st.fragment(run_every=5)
def devices_panel():
    """Exhibit-style device monitor: who is in, from where, and buttons to remove or block them."""
    s = state()
    if not s["enabled"]:
        return
    reg = _registry(s["round"])
    now = time.time()
    with _lock:
        devices = sorted(reg["devices"].values(), key=lambda d: -d["first"])
        blocked = sorted(reg["blocked"])
    _, everyone = _fail_counts(reg, None)
    online = [d for d in devices if d["status"] == "aktif" and now - d["last"] < ONLINE_FOR]

    st.subheader("Peranti yang disambung", anchor=False)
    with st.container(horizontal=True):
        st.metric("dalam talian sekarang", len(online), border=True)
        st.metric("masuk pusingan ini", len(devices), border=True)
        st.metric("kod salah (1 jam)", everyone, border=True,
                  help=f"Pada {ALL_FAILS}, skrin kod dijeda untuk semua. Mulakan semula perkongsian untuk set semula.")
        st.metric("IP disekat", len(blocked), border=True)
    if everyone >= ALL_FAILS:
        st.warning("Terlalu banyak kod salah: skrin kod dijeda. Seseorang mungkin cuba meneka. Matikan dan "
                   "hidupkan semula perkongsian untuk set semula.", icon=":material/warning:")

    if not devices:
        st.caption("Belum ada pelawat masuk dalam pusingan ini.")
    for d in devices:
        is_online = d["status"] == "aktif" and now - d["last"] < ONLINE_FOR
        status = {"aktif": "🟢 Dalam talian" if is_online else "⚪ Tidak aktif",
                  "dikeluarkan": "⛔ Dikeluarkan", "disekat": "🚫 Disekat"}[d["status"]]
        with st.container(border=True, horizontal=True, vertical_alignment="center"):
            st.markdown(f"**{d['name']}**  \n{d['device']} · `{d['ip']}` · {d['country']}  \n"
                        f":gray[Masuk {datetime.fromtimestamp(d['first']):%H:%M} · aktif {_ago(d['last'])} · {status}]")
            if d["status"] == "aktif":
                st.button("Keluarkan", key=f"kick_{d['sid']}", icon=":material/logout:", width="content",
                          on_click=remove_device, args=(d["sid"],))
                st.button("Sekat IP", key=f"block_{d['sid']}", icon=":material/block:", width="content",
                          on_click=remove_device, args=(d["sid"], True))
    for ip in blocked:
        with st.container(horizontal=True, vertical_alignment="center"):
            st.markdown(f"🚫 `{ip}` disekat untuk pusingan ini")
            st.button("Buka sekatan", key=f"unblock_{ip}", type="tertiary", on_click=unblock_ip, args=(ip,))
    st.caption(f"Senarai dikemas kini setiap 5 saat. Peranti yang dikeluarkan dikunci dalam {HEARTBEAT} saat. "
               "Setiap tab pelayar dikira sebagai satu peranti.")
