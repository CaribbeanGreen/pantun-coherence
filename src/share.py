"""Temporary sharing with a rotating 6-digit code (like an authenticator app).

How it works:
  - On this computer (the owner) the app opens as normal and has an extra "Kongsi" page.
  - Visitors come through the Cloudflare tunnel (requests carry Cloudflare headers). They see a code
    screen, and nothing else, until they type the current code.
  - The code only works while the owner has switched sharing ON. Sharing switches itself off after the
    chosen time. Switching it off (or on again) locks out every visitor straight away.
  - The code changes every 15 seconds (TOTP, RFC 6238, HMAC-SHA1). The code from the previous 15 s is
    also accepted, so there is time to read it out.

The secret and the on/off state live in results/share_state.json (never committed: results/ is in .gitignore).
"""

import hashlib
import hmac
import json
import os
import secrets
import struct
import threading
import time
from datetime import datetime

import streamlit as st

from src.data_loader import PROJECT_ROOT

STATE_FILE = PROJECT_ROOT / "results" / "share_state.json"
PERIOD = 15                 # seconds per code
DIGITS = 6
TRIES_PER_SESSION = 5       # wrong codes allowed per visitor per minute
TRIES_GLOBAL = 20           # wrong codes allowed from everyone per minute
PUBLIC_URL = "https://pantun.aimanjamal.com"

_lock = threading.Lock()
_global_fails: list[float] = []


# ---- State ---------------------------------------------------------------------------------------

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
    os.replace(tmp, STATE_FILE)


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


# ---- Codes ---------------------------------------------------------------------------------------

def code_at(secret, t):
    """TOTP code for time t (RFC 6238 with a 15 s step)."""
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
    return any(hmac.compare_digest(code, code_at(s["secret"], now - k * PERIOD)) for k in (0, 1))


# ---- Who is asking -------------------------------------------------------------------------------

def is_visitor():
    """True for requests that come through Cloudflare (the public address). Cloudflare always adds these
    headers, so a visitor cannot hide them. PANTUN_FORCE_GATE=1 shows the visitor screen locally (testing)."""
    if os.environ.get("PANTUN_FORCE_GATE") == "1":
        return True
    h = st.context.headers
    return bool(h.get("Cf-Ray") or h.get("Cf-Connecting-Ip"))


def _too_many(key, limit, window=60):
    now = time.time()
    if key is None:
        with _lock:
            _global_fails[:] = [t for t in _global_fails if now - t < window]
            return len(_global_fails) >= limit
    fails = [t for t in st.session_state.get(key, []) if now - t < window]
    st.session_state[key] = fails
    return len(fails) >= limit


def _record_fail():
    now = time.time()
    st.session_state.setdefault("share_fails", []).append(now)
    with _lock:
        _global_fails.append(now)


# ---- Visitor gate --------------------------------------------------------------------------------

_GATE_CSS = """<style>
.cz-gate { max-width: 440px; margin: 7vh auto 0; text-align: center; font-family: 'Nunito', sans-serif; }
.cz-gate .logo { width: 54px; height: 54px; border-radius: 50%; background: #DEB251; margin: 0 auto 14px;
  box-shadow: 0 8px 24px rgba(222, 178, 81, .45); }
.cz-gate h1 { font-size: 1.9rem; font-weight: 900; color: #0C525C; margin: 0; padding: 0; }
.cz-gate p { color: #45525a; font-size: 1.02rem; line-height: 1.55; margin: 8px 0 0; }
.st-key-share_gate { max-width: 440px; margin: 0 auto; }
.st-key-share_gate input { text-align: center; font-size: 1.9rem !important; letter-spacing: .5em;
  font-family: 'JetBrains Mono', monospace !important; }
.st-key-share_gate [data-testid="InputInstructions"] { display: none; }
</style>"""


def gate():
    """Stop the page for visitors who have not typed a valid code during the current sharing round."""
    if not is_visitor():
        return
    s = state()
    if not s["enabled"]:
        st.session_state.pop("share_ok", None)
        st.html(_GATE_CSS + """<div class="cz-gate"><div class="logo"></div><h1>Perkongsian ditutup</h1>
            <p>Pemilik belum membuka akses ke Semak Pantun. Minta mereka hidupkan perkongsian dan berikan kod.</p>
            <p style="font-size:.92rem;color:#6b7478">Sharing is closed. Ask the owner to switch it on and give you a code.</p></div>""")
        st.stop()
    if st.session_state.get("share_ok") == s["round"]:
        _watch()
        return

    st.html(_GATE_CSS + """<div class="cz-gate"><div class="logo"></div><h1>Masukkan kod akses</h1>
        <p>Minta kod 6 digit daripada pemilik. Kod bertukar setiap 15 saat.</p>
        <p style="font-size:.92rem;color:#6b7478">Enter the 6-digit code from the owner. It changes every 15 seconds.</p></div>""")
    with st.container(key="share_gate"):
        with st.form("share_form", border=False):
            code = st.text_input("Kod", max_chars=DIGITS, placeholder="••••••", label_visibility="collapsed")
            go = st.form_submit_button("Masuk", type="primary", icon=":material/lock_open:", width="stretch")
        if go:
            if _too_many("share_fails", TRIES_PER_SESSION) or _too_many(None, TRIES_GLOBAL):
                st.error("Terlalu banyak cubaan. Tunggu seminit dan cuba lagi.", icon=":material/timer:")
            elif verify(code):
                st.session_state["share_ok"] = s["round"]
                st.rerun()
            else:
                _record_fail()
                st.error("Kod tidak sah atau sudah tamat. Minta kod baharu.", icon=":material/error:")
    st.stop()


@st.fragment(run_every=20)
def _watch():
    """Every 20 s, lock an open visitor page if the owner switched sharing off (or it timed out)."""
    s = state()
    if not s["enabled"] or st.session_state.get("share_ok") != s["round"]:
        st.session_state.pop("share_ok", None)
        st.rerun()


# ---- Owner page ----------------------------------------------------------------------------------

def owner_page():
    """'Kongsi' page (owner only): switch sharing on/off and show the live code."""
    st.title("Kongsi Semak Pantun", anchor=False)
    st.caption(f"Alamat awam: {PUBLIC_URL} · hanya orang yang ada kod boleh masuk")
    s = state()

    with st.container(border=True):
        if s["enabled"]:
            ends = datetime.fromtimestamp(s["until"])
            st.success(f"Perkongsian **HIDUP** sehingga {ends:%H:%M} ({ends:%d/%m}).", icon=":material/share:")
            if st.button("Matikan perkongsian sekarang", type="primary", icon=":material/block:"):
                set_sharing(False)
                st.rerun()
            st.caption("Mematikan atau menghidupkan semula akan mengunci semua pelawat yang sedang masuk.")
        else:
            st.info("Perkongsian **MATI**. Pelawat tidak boleh masuk dan tiada kod yang sah.", icon=":material/lock:")
            hours = st.segmented_control("Berapa lama?", [0.5, 1, 2, 4, 8], default=1, required=True,
                                         format_func=lambda h: "30 min" if h == 0.5 else f"{h:g} jam")
            if st.button("Hidupkan perkongsian", type="primary", icon=":material/share:"):
                set_sharing(True, hours)
                st.rerun()

    if s["enabled"]:
        live_code()


@st.fragment(run_every=1)
def live_code():
    s = state()
    if not s["enabled"]:
        st.rerun()                      # time is up: redraw the whole page
    now = time.time()
    left = PERIOD - (now % PERIOD)
    code = code_at(s["secret"], now)
    deg = 360 * left / PERIOD
    st.html(f"""
<div style="display:flex;align-items:center;gap:22px;justify-content:center;margin:18px 0 6px;font-family:'Nunito',sans-serif">
  <div style="font:800 3.4rem 'JetBrains Mono',monospace;letter-spacing:.18em;color:#0C525C">{code[:3]}&nbsp;{code[3:]}</div>
  <div role="img" aria-label="{int(left)} saat lagi" style="width:62px;height:62px;border-radius:50%;
       background:conic-gradient(#DEB251 {deg:.0f}deg,#E6E1D6 0);display:flex;align-items:center;justify-content:center">
    <div style="width:46px;height:46px;border-radius:50%;background:#FBF7EE;display:flex;align-items:center;
         justify-content:center;font-weight:800;color:#1F2A2E">{int(left)}s</div>
  </div>
</div>
<div style="text-align:center;color:#5b6670;font-size:.95rem">Berikan kod ini kepada pelawat. Ia bertukar setiap {PERIOD} saat
 (kod sebelumnya masih diterima {PERIOD} saat lagi).</div>""")
