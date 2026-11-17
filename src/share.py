"""Temporary sharing with a rotating 6-digit code (like an authenticator app), with a device monitor.

How it works (full guide: docs/sharing_guide.md):
  - On this computer (the owner) the app opens as normal and has an extra "Kongsi" page.
  - Visitors come through the Cloudflare tunnel (their requests carry Cloudflare headers). They see a code
    screen, and nothing else, until they type the current code.
  - A code only works while the owner has switched sharing ON (a "round"). Sharing switches itself off after
    the chosen time. Switching it off, or pressing "Keluarkan semua", starts a new round and locks everyone out.
  - The code changes every 15 seconds (TOTP, RFC 6238, HMAC-SHA1). With GRACE_STEPS = 1 the code from the
    previous 15 s is also accepted, so there is time to read it out. Set it to 0 to accept the current code only.
  - After a correct code the browser keeps a signed pass (cookie) for REMEMBER_FOR (2 hours), so refreshing or
    reopening the site does not ask again. The pass dies early if the round changes or the owner removes/blocks
    the device, and an open page is locked when it expires.
  - Every device that gets in is listed on the Kongsi page (name, device, IP, country, last active). The owner
    can remove one device, or remove it and block its IP address for the rest of the round.
  - Wrong codes are limited per IP address and overall; too many wrong codes pause the code screen.

Files (all in results/, which is in .gitignore and stays on this computer):
  share_state.json    secret + on/off + round      share_devices.json   devices and blocked IPs of this round
  share_log.csv       access log
PANTUN_SHARE_DIR=<folder> keeps them somewhere else (used for testing without touching a live share).
"""

import base64
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
from pathlib import Path

import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx

from src.data_loader import PROJECT_ROOT

SHARE_DIR = Path(os.environ.get("PANTUN_SHARE_DIR") or PROJECT_ROOT / "results")
STATE_FILE = SHARE_DIR / "share_state.json"
DEVICES_FILE = SHARE_DIR / "share_devices.json"
LOG_FILE = SHARE_DIR / "share_log.csv"
PUBLIC_URL = "https://pantun.aimanjamal.com"
COOKIE = "cz_pass"

PERIOD = 15                 # seconds per code
DIGITS = 6
GRACE_STEPS = 1             # also accept the code from this many earlier periods (0 = current code only)
REMEMBER_FOR = 2 * 3600     # a device stays signed in for 2 hours (never past the end of sharing)
IP_FAILS, IP_WINDOW = 5, 600            # 5 wrong codes per IP address in 10 minutes
ALL_FAILS, ALL_WINDOW = 30, 3600        # 30 wrong codes from everyone in 1 hour -> code screen paused
HEARTBEAT = 10              # an open visitor page checks in every 10 s (and is locked if removed or expired)
ONLINE_FOR = 3 * HEARTBEAT  # "online" if seen in the last 30 s

_lock = threading.RLock()
_reg = {"round": None, "devices": {}, "blocked": set(), "fails": []}   # in memory, saved to DEVICES_FILE


# ---- On/off state (file) -------------------------------------------------------------------------

def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f)
    os.replace(tmp, path)              # atomic: never a half-written file


def state():
    """Current sharing state. Creates the secret the first time. Turns sharing off when its time is up."""
    with _lock:
        s = _read(STATE_FILE)
        changed = False
        if not s.get("secret"):
            s.update(secret=secrets.token_hex(20), enabled=False, until=0, round="")
            changed = True
        if s.get("enabled") and time.time() >= s.get("until", 0):
            s.update(enabled=False, round="")
            changed = True
            _log("tamat masa")
        if changed:
            _write(STATE_FILE, s)
        return s


def set_sharing(on, hours=1.0):
    """Switch sharing on for `hours`, or off. Each switch starts a new round, so old visitors are locked out."""
    with _lock:
        s = state()
        if on:
            s.update(enabled=True, until=time.time() + hours * 3600, round=secrets.token_hex(8))
        else:
            s.update(enabled=False, until=0, round="")
        _write(STATE_FILE, s)
    _log("perkongsian hidup" if on else "perkongsian mati", note=f"{hours:g} jam" if on else "")


def kick_all():
    """New round with the same end time: every device must type a fresh code again."""
    with _lock:
        s = state()
        if s.get("enabled"):
            s["round"] = secrets.token_hex(8)
            _write(STATE_FILE, s)
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


# ---- Remembered pass (signed cookie) -------------------------------------------------------------

def _pass_key(secret):
    """Separate key for signing passes, derived from the code secret (so a pass can't be used as a code)."""
    return hmac.new(bytes.fromhex(secret), b"cz-remember-pass", hashlib.sha256).digest()


def make_pass(s, device_id, name, expires):
    body = base64.urlsafe_b64encode(json.dumps({"r": s["round"], "d": device_id, "n": name, "e": int(expires)},
                                               separators=(",", ":")).encode()).decode().rstrip("=")
    sig = hmac.new(_pass_key(s["secret"]), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def read_pass(s, token):
    """The pass's contents if it is genuine, unexpired and for the current round; otherwise None."""
    try:
        body, sig = token.split(".", 1)
        good = hmac.new(_pass_key(s["secret"]), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, good):
            return None
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except (ValueError, AttributeError, TypeError):
        return None
    if data.get("r") != s["round"] or time.time() >= data.get("e", 0):
        return None
    return data


def _set_cookie(token, max_age):
    """Store the pass in this browser (JavaScript, because Streamlit can only read cookies)."""
    value = json.dumps(token)
    st.html(f"""<script>
document.cookie = "{COOKIE}=" + {value} + "; Max-Age={int(max_age)}; Path=/; SameSite=Strict"
                  + (location.protocol === "https:" ? "; Secure" : "");
</script>""", unsafe_allow_javascript=True)


def _clear_cookie():
    st.html(f"""<script>document.cookie = "{COOKIE}=; Max-Age=0; Path=/; SameSite=Strict";</script>""",
            unsafe_allow_javascript=True)


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
    """The device list for this round. A new round starts empty; after an app restart it is read back from disk."""
    with _lock:
        if _reg["round"] != round_id:
            saved = _read(DEVICES_FILE)
            if saved.get("round") == round_id and round_id:
                _reg.update(round=round_id, devices=saved.get("devices", {}), blocked=set(saved.get("blocked", [])),
                            fails=[])
            else:
                _reg.update(round=round_id, devices={}, blocked=set(), fails=[])
        return _reg


def _save_registry():
    with _lock:
        _write(DEVICES_FILE, {"round": _reg["round"], "devices": _reg["devices"], "blocked": sorted(_reg["blocked"])})


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


def remove_device(device_id, block_ip=False):
    """Owner action: lock one device out (open pages within HEARTBEAT seconds, and its pass stops working);
    optionally block its IP address for the rest of this round."""
    with _lock:
        dev = _reg["devices"].get(device_id)
        if not dev:
            return
        dev["status"] = "disekat" if block_ip else "dikeluarkan"
        if block_ip:
            _reg["blocked"].add(dev["ip"])
        _save_registry()
    _log("disekat" if block_ip else "dikeluarkan", dev["name"], dev["ip"], dev["country"], dev["device"])


def unblock_ip(ip):
    with _lock:
        _reg["blocked"].discard(ip)
        _save_registry()
    _log("buka sekatan", ip=ip)


def _admit(reg, s, device_id, name, me, expires, event):
    """Mark this session (browser tab) as signed in as `device_id` until `expires`."""
    with _lock:
        dev = reg["devices"].get(device_id)
        if dev is None:
            dev = reg["devices"][device_id] = {"id": device_id, "name": name, **me, "first": time.time(),
                                               "status": "aktif", "visits": 0}
        dev.update(ip=me["ip"], country=me["country"], device=me["device"], last=time.time(),
                   until=expires, visits=dev.get("visits", 0) + 1)
        _save_registry()
    _log(event, dev["name"], me["ip"], me["country"], me["device"])
    st.session_state.update(share_ok=s["round"], share_did=device_id, share_exp=expires)


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


def _lock_out():
    for k in ("share_ok", "share_did", "share_exp", "share_cookie"):
        st.session_state.pop(k, None)


def gate():
    """Stop the page for visitors who have no valid code or pass for the current round, or were removed."""
    if not is_visitor():
        return
    s = state()
    if not s["enabled"]:
        _lock_out()
        _screen("Perkongsian ditutup",
                "Pemilik belum membuka akses ke Semak Pantun. Minta mereka hidupkan perkongsian dan berikan kod.",
                "Sharing is closed. Ask the owner to switch it on and give you a code.")
        st.stop()

    reg, me, now = _registry(s["round"]), _client(), time.time()

    # Already signed in during this tab's session?
    did = st.session_state.get("share_did")
    if st.session_state.get("share_ok") != s["round"] or now >= st.session_state.get("share_exp", 0):
        did = None
        # A remembered pass from an earlier visit (refresh, new tab, browser reopened within 2 hours)?
        p = read_pass(s, st.context.cookies.get(COOKIE, ""))
        if p:
            dev = reg["devices"].get(p["d"])
            if (dev is None or dev["status"] == "aktif") and me["ip"] not in reg["blocked"]:
                _admit(reg, s, p["d"], p["n"], me, p["e"], "masuk semula (diingati)")
                did = p["d"]

    dev = reg["devices"].get(did) if did else None
    if me["ip"] in reg["blocked"] or (dev and dev["status"] == "disekat"):
        _lock_out()
        _clear_cookie()
        _screen("Akses disekat", "Pemilik telah menyekat peranti ini.", "The owner has blocked this device.")
        st.stop()
    if dev and dev["status"] == "dikeluarkan":
        _lock_out()
        _clear_cookie()
        _screen("Akses ditarik balik", "Pemilik telah mengeluarkan peranti ini.",
                "The owner removed this device from the site.")
        st.stop()
    if dev:
        dev["last"] = now
        token = st.session_state.pop("share_cookie", None)
        if token:                                   # first run after a correct code: remember this browser
            _set_cookie(token, st.session_state["share_exp"] - now)
        _watch()
        return

    _screen("Masukkan kod akses", "Minta kod 6 digit daripada pemilik. Kod bertukar setiap 15 saat.",
            "Enter the 6-digit code from the owner. It changes every 15 seconds.")
    with st.container(key="share_gate"):
        with st.form("share_form", border=False):
            name = st.text_input("Nama anda", max_chars=40, placeholder="Nama anda (supaya pemilik kenal)")
            code = st.text_input("Kod", max_chars=DIGITS, placeholder="••••••", label_visibility="collapsed")
            remember = st.checkbox("Ingat peranti ini selama 2 jam", value=True,
                                   help="Tidak perlu kod lagi jika anda muat semula halaman dalam masa 2 jam.")
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
                expires = min(time.time() + REMEMBER_FOR, s["until"])
                device_id = secrets.token_hex(6)
                _admit(reg, s, device_id, name, me, expires, "masuk")
                if remember:
                    st.session_state["share_cookie"] = make_pass(s, device_id, name, expires)
                st.rerun()
            else:
                with _lock:
                    reg["fails"].append((time.time(), me["ip"]))
                _log("kod salah", name, me["ip"], me["country"], me["device"])
                st.error("Kod tidak sah atau sudah tamat. Minta kod baharu.", icon=":material/error:")
    st.stop()


@st.fragment(run_every=HEARTBEAT)
def _watch():
    """Heartbeat from an open visitor page: marks it online, and locks it if the owner removed it, switched
    sharing off, started a new round, or its 2 hours are up."""
    s = state()
    reg = _registry(s["round"]) if s["enabled"] else None
    dev = reg["devices"].get(st.session_state.get("share_did")) if reg else None
    if (not s["enabled"] or st.session_state.get("share_ok") != s["round"] or not dev or dev["status"] != "aktif"
            or dev["ip"] in reg["blocked"] or time.time() >= st.session_state.get("share_exp", 0)):
        _lock_out()
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
                       f"{HEARTBEAT} saat. Peranti diingati selama {REMEMBER_FOR // 3600} jam selepas memasukkan kod.")
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
    """Device monitor: who is in, from where, and buttons to remove or block them."""
    s = state()
    if not s["enabled"]:
        return
    reg = _registry(s["round"])
    now = time.time()
    with _lock:
        devices = sorted(reg["devices"].values(), key=lambda d: -d["first"])
        blocked = sorted(reg["blocked"])
    _, everyone = _fail_counts(reg, None)
    online = [d for d in devices if d["status"] == "aktif" and now - d.get("last", 0) < ONLINE_FOR]

    st.subheader("Peranti yang disambung", anchor=False)
    with st.container(horizontal=True):
        st.metric("dalam talian sekarang", len(online), border=True)
        st.metric("peranti pusingan ini", len(devices), border=True)
        st.metric("kod salah (1 jam)", everyone, border=True,
                  help=f"Pada {ALL_FAILS}, skrin kod dijeda untuk semua. Mulakan semula perkongsian untuk set semula.")
        st.metric("IP disekat", len(blocked), border=True)
    if everyone >= ALL_FAILS:
        st.warning("Terlalu banyak kod salah: skrin kod dijeda. Seseorang mungkin cuba meneka. Matikan dan "
                   "hidupkan semula perkongsian untuk set semula.", icon=":material/warning:")

    if not devices:
        st.caption("Belum ada pelawat masuk dalam pusingan ini.")
    for d in devices:
        is_online = d["status"] == "aktif" and now - d.get("last", 0) < ONLINE_FOR
        status = {"aktif": "🟢 Dalam talian" if is_online else "⚪ Tidak aktif",
                  "dikeluarkan": "⛔ Dikeluarkan", "disekat": "🚫 Disekat"}[d["status"]]
        until = (f" · diingati hingga {datetime.fromtimestamp(d['until']):%H:%M}"
                 if d["status"] == "aktif" and d.get("until") else "")
        with st.container(border=True, horizontal=True, vertical_alignment="center"):
            st.markdown(f"**{d['name']}**  \n{d['device']} · `{d['ip']}` · {d['country']}  \n"
                        f":gray[Masuk {datetime.fromtimestamp(d['first']):%H:%M} · aktif {_ago(d.get('last', d['first']))}"
                        f" · {d.get('visits', 1)} lawatan{until} · {status}]")
            if d["status"] == "aktif":
                st.button("Keluarkan", key=f"kick_{d['id']}", icon=":material/logout:", width="content",
                          on_click=remove_device, args=(d["id"],))
                st.button("Sekat IP", key=f"block_{d['id']}", icon=":material/block:", width="content",
                          on_click=remove_device, args=(d["id"], True))
    for ip in blocked:
        with st.container(horizontal=True, vertical_alignment="center"):
            st.markdown(f"🚫 `{ip}` disekat untuk pusingan ini")
            st.button("Buka sekatan", key=f"unblock_{ip}", type="tertiary", on_click=unblock_ip, args=(ip,))
    st.caption(f"Senarai dikemas kini setiap 5 saat. Peranti yang dikeluarkan dikunci dalam {HEARTBEAT} saat. "
               "Satu peranti = satu pelayar; muat semula halaman tidak membuat peranti baharu.")
