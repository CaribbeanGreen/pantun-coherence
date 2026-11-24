"""Sharing the app online: member accounts, a guest code that changes every 30 s, and a device monitor.

Full explanation and rebuild guide: docs/sharing_guide.md.

Who can get in (visitors come through the Cloudflare tunnel; their requests carry Cloudflare headers):
  - MEMBERS (Ahli): the owner creates an account on the Tetapan page and gives the person a personal key that is
    valid for a chosen time (1 day, 1 week, ...). They log in with username + key; the browser is remembered for
    up to 24 hours (never past the key's end). Every login is kept in a permanent history. The owner can extend,
    reset the key, sign out all devices, or revoke the account at any time.
  - GUESTS (Tetamu): while the owner has switched guest sharing ON, anyone with the current 6-digit code
    (TOTP, RFC 6238, 30-second step, as in Google Authenticator) gets in; the browser is remembered for 2 hours. Each "round" of sharing
    starts fresh, and the owner can remove a guest device or block its IP address.
  - On this computer (the owner) the app opens as normal and has the extra "Tetapan / Settings" page.

Storage (results/ is in .gitignore and never leaves this computer):
  share.db             SQLite: members (hashed keys only), every login, the event log
  share_state.json     code secret, guest sharing on/off and round, members on/off
  share_devices.json   guest devices and blocked IPs of the current round
PANTUN_SHARE_DIR=<folder> keeps them somewhere else (used for testing without touching a live share).
"""

import base64
import csv
import hashlib
import hmac
import html
import io
import json
import os
import re
import secrets
import sqlite3
import struct
import threading
import time
import unicodedata
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit.runtime.scriptrunner import get_script_run_ctx

from src import access_login, illus, lang
from src.lang import current as current_lang, role as role_name, tr
from src.data_loader import PROJECT_ROOT

SHARE_DIR = Path(os.environ.get("PANTUN_SHARE_DIR") or PROJECT_ROOT / "results")
STATE_FILE = SHARE_DIR / "share_state.json"
DEVICES_FILE = SHARE_DIR / "share_devices.json"
DB_FILE = SHARE_DIR / "share.db"
OLD_LOG = SHARE_DIR / "share_log.csv"      # earlier versions logged here; imported into the database once
PUBLIC_URL = "https://pantun.aimanjamal.com"
COOKIE = "cz_pass"

PERIOD, DIGITS = 30, 6      # guest code: 6 digits, new every 30 s (the Google Authenticator standard)
GRACE_STEPS = 1             # also accept the previous guest code (0 = current code only)
GUEST_REMEMBER = 2 * 3600   # a guest browser is remembered for 2 hours
MEMBER_REMEMBER = 24 * 3600 # a member browser is remembered for 24 hours (never past the key's end)
KEY_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"   # no 0/O, 1/I/L: easy to read out
KEY_LENGTH = 12             # 31^12 ≈ 7.9 × 10^17 possible keys (~60 bits)
IP_FAILS, IP_WINDOW = 5, 600            # 5 wrong guest codes or member logins per IP in 10 minutes
ALL_FAILS, ALL_WINDOW = 30, 3600        # 30 wrong guest codes from everyone in 1 hour -> guest code paused
HEARTBEAT = 10              # open visitor pages check in every 10 s (locked if removed, revoked or expired)
ONLINE_FOR = 3 * HEARTBEAT
USERNAME_RE = re.compile(r"^[a-z0-9._-]{3,24}$")

_lock = threading.RLock()
_reg = {"round": None, "devices": {}, "blocked": set()}   # guests of the current round (saved to DEVICES_FILE)
_fails: list = []                                          # (time, ip, kind) of wrong codes/logins, in memory
_live: dict = {}                                           # session id -> member session info (for "online")


# ---- Small file helpers --------------------------------------------------------------------------

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


# ---- Database (SQLite) ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS members (
    username     TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    note         TEXT DEFAULT '',
    key_hash     TEXT NOT NULL,          -- scrypt hash of the key (the key itself is never stored)
    key_salt     TEXT NOT NULL,
    key_version  INTEGER NOT NULL DEFAULT 1,   -- +1 when the key is reset: old key and passes stop working
    session_gen  INTEGER NOT NULL DEFAULT 1,   -- +1 on "sign out all devices": passes stop working, key stays
    created      REAL NOT NULL,
    expires      REAL NOT NULL,
    status       TEXT NOT NULL DEFAULT 'aktif' -- aktif | dibatalkan
);
CREATE TABLE IF NOT EXISTS logins (
    id        INTEGER PRIMARY KEY,
    username  TEXT NOT NULL,
    time      REAL NOT NULL,
    ip        TEXT, country TEXT, device TEXT,
    how       TEXT                       -- 'kunci' (typed the key) | 'diingati' (remembered browser)
);
CREATE INDEX IF NOT EXISTS logins_user ON logins(username, time);
CREATE TABLE IF NOT EXISTS events (
    id       INTEGER PRIMARY KEY,
    time     REAL NOT NULL,
    event    TEXT NOT NULL,
    who      TEXT DEFAULT '', ip TEXT DEFAULT '', country TEXT DEFAULT '', device TEXT DEFAULT '', note TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS classes (          -- a teacher's class; students join with its code
    code     TEXT PRIMARY KEY,
    name     TEXT NOT NULL,
    teacher  TEXT NOT NULL,                   -- teacher's username ('' = made by the owner)
    created  REAL NOT NULL,
    active   INTEGER NOT NULL DEFAULT 1       -- 0: the code no longer lets new students join
);
CREATE TABLE IF NOT EXISTS class_members (
    code     TEXT NOT NULL,
    username TEXT NOT NULL,
    joined   REAL NOT NULL,
    PRIMARY KEY (code, username)
);
CREATE TABLE IF NOT EXISTS retired_usernames (  -- deleted accounts: the name is never given out again, so
    username TEXT PRIMARY KEY,                   -- nobody inherits someone else's classes or inquiries
    time     REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS inquiries (        -- "Saya tidak setuju" requests
    id          INTEGER PRIMARY KEY,
    time        REAL NOT NULL,
    kind        TEXT NOT NULL,                -- pelajar (kept) | tetamu (temporary) | pemilik | lama (old CSV)
    who         TEXT DEFAULT '',
    username    TEXT DEFAULT '',
    class_code  TEXT DEFAULT '',
    round       TEXT DEFAULT '',              -- tetamu: the guest round / open-mode round it belongs to
    expires     REAL DEFAULT 0,               -- tetamu: deleted after this time
    line1 TEXT, line2 TEXT, line3 TEXT, line4 TEXT,
    comment     TEXT DEFAULT '',
    sound       REAL, meaning_pct INTEGER, rules INTEGER,
    status      TEXT DEFAULT 'baru',          -- baru | selesai
    handled_by  TEXT DEFAULT '',
    reply       TEXT DEFAULT ''
);
"""


def _db():
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_FILE, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def _init_db():
    with _lock, closing(_db()) as con, con:
        con.execute("PRAGMA journal_mode=WAL")
        con.executescript(SCHEMA)
        cols = {r["name"] for r in con.execute("PRAGMA table_info(members)")}
        if "role" not in cols:          # added later: which views a member may open
            con.execute("ALTER TABLE members ADD COLUMN role TEXT NOT NULL DEFAULT 'pelajar'")
        if "lecturer" not in cols:      # earlier version: a student's lecturer (now classes do this)
            con.execute("ALTER TABLE members ADD COLUMN lecturer TEXT NOT NULL DEFAULT ''")
        if "cred" not in cols:          # 'key' = owner-issued key, 'password' = chosen by the person at sign-up
            con.execute("ALTER TABLE members ADD COLUMN cred TEXT NOT NULL DEFAULT 'key'")
        old_flags = SHARE_DIR / "expert_review_flags.csv"
        if old_flags.exists() and not con.execute("SELECT 1 FROM inquiries LIMIT 1").fetchone():
            with open(old_flags, encoding="utf-8") as f:   # earlier complaints: kept, visible to the owner only
                for r in csv.DictReader(f):
                    try:
                        t = datetime.fromisoformat(r["timestamp"]).timestamp()
                    except (KeyError, ValueError):
                        continue
                    con.execute("INSERT INTO inquiries(time, kind, who, username, line1, line2, line3, line4, comment,"
                                " sound, meaning_pct, rules) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                                (t, "lama", r.get("who", ""), r.get("student_user", ""), r.get("line1"), r.get("line2"),
                                 r.get("line3"), r.get("line4"), r.get("comment", ""), r.get("sound") or None,
                                 r.get("meaning_pct") or None, r.get("rules") or None))
        if OLD_LOG.exists() and not con.execute("SELECT 1 FROM events LIMIT 1").fetchone():
            with open(OLD_LOG, encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    try:
                        t = datetime.fromisoformat(r["masa"]).timestamp()
                    except (KeyError, ValueError):
                        continue
                    con.execute("INSERT INTO events(time, event, who, ip, country, device, note) VALUES (?,?,?,?,?,?,?)",
                                (t, r.get("peristiwa", ""), r.get("nama", ""), r.get("ip", ""), r.get("negara", ""),
                                 r.get("peranti", ""), r.get("catatan", "")))


_init_db()


def _log(event, who="", ip="", country="", device="", note=""):
    with _lock, closing(_db()) as con, con:
        con.execute("INSERT INTO events(time, event, who, ip, country, device, note) VALUES (?,?,?,?,?,?,?)",
                    (time.time(), event, who, ip, country, device, note))


def events_csv():
    with closing(_db()) as con:
        df = pd.read_sql("SELECT time, event, who, ip, country, device, note FROM events ORDER BY time", con)
    df["time"] = pd.to_datetime(df["time"], unit="s").dt.tz_localize("UTC").dt.tz_convert("Asia/Kuala_Lumpur") \
        .dt.strftime("%Y-%m-%d %H:%M:%S")
    return df.rename(columns={"time": "masa", "event": "peristiwa", "who": "siapa", "country": "negara",
                              "device": "peranti", "note": "catatan"}).to_csv(index=False).encode("utf-8-sig")


# ---- Sharing state (file) ------------------------------------------------------------------------

def state():
    """Current state. Creates the code secret the first time. Turns guest sharing off when its time is up."""
    with _lock:
        s = _read(STATE_FILE)
        changed = False
        if not s.get("secret"):
            s.update(secret=secrets.token_hex(20), enabled=False, until=0, round="", members=True)
            changed = True
        s.setdefault("members", True)
        s.setdefault("tester_open", False)
        s.setdefault("default_lang", lang.DEFAULT)   # BM or EN for visitors who have not chosen
        for k, v in (("open", False), ("open_round", ""), ("open_until", 0)):
            s.setdefault(k, v)
        if s.get("enabled") and time.time() >= s.get("until", 0):
            s.update(enabled=False, round="")
            changed = True
            _log("tetamu: tamat masa")
        if s.get("open") and time.time() >= s.get("open_until", 0):
            s.update(open=False, open_round="")
            changed = True
            _log("terbuka: tamat masa")
        if changed:
            _write(STATE_FILE, s)
        return s


def set_sharing(on, hours=1.0):
    """Guest sharing on for `hours`, or off. Each switch starts a new round: earlier guests are locked out."""
    with _lock:
        s = state()
        if on:
            s.update(enabled=True, until=time.time() + hours * 3600, round=secrets.token_hex(8))
        else:
            s.update(enabled=False, until=0, round="")
        _write(STATE_FILE, s)
    _log("tetamu: perkongsian hidup" if on else "tetamu: perkongsian mati", note=f"{hours:g} jam" if on else "")


GUEST_MODES = {"tutup": ("![](/app/static/i/lock.png) Tutup", "![](/app/static/i/lock.png) Closed"),
               "kod": ("![](/app/static/i/ticket.png) Kod sahaja", "![](/app/static/i/ticket.png) Code only"),
               "terbuka": ("![](/app/static/i/globe.png) Terbuka", "![](/app/static/i/globe.png) Open")}


def mode_name(mode):
    return tr(*GUEST_MODES[mode])


def guest_mode(s=None):
    s = s or state()
    return "terbuka" if s.get("open") else "kod" if s.get("enabled") else "tutup"


def set_guest_mode(mode, hours=1.0):
    """The owner's one setting for access without an account:
    tutup = nobody (accounts only) · kod = only people given the 30-second code · terbuka = anyone, student page.
    Every change starts new rounds, so earlier guests and open-mode visitors are locked out."""
    with _lock:
        s = state()
        until = time.time() + hours * 3600
        s.update(enabled=mode == "kod", until=until if mode == "kod" else 0,
                 round=secrets.token_hex(8) if mode == "kod" else "",
                 open=mode == "terbuka", open_until=until if mode == "terbuka" else 0,
                 open_round=secrets.token_hex(8) if mode == "terbuka" else "")
        _write(STATE_FILE, s)
    _log(f"akses tanpa akaun: {mode}", note=f"{hours:g} jam" if mode != "tutup" else "")
    _purge_inquiries()


def set_members(on):
    with _lock:
        s = state()
        s["members"] = bool(on)
        _write(STATE_FILE, s)
    _log("ahli: log masuk dibuka" if on else "ahli: log masuk ditutup")


def set_tester_open(on):
    """Show or hide the Borang Penguji page for visitors (the owner always sees it)."""
    with _lock:
        s = state()
        s["tester_open"] = bool(on)
        _write(STATE_FILE, s)
    _log("penguji: borang dibuka" if on else "penguji: borang ditutup")


def kick_all():
    """New guest round with the same end time: every guest must type a fresh code."""
    with _lock:
        s = state()
        if s.get("enabled"):
            s["round"] = secrets.token_hex(8)
            _write(STATE_FILE, s)
    _log("tetamu: keluarkan semua")


# ---- Guest codes (TOTP, RFC 6238) ----------------------------------------------------------------

def code_at(secret, t):
    """6-digit code for time t: HMAC-SHA1(secret, number of 30-s steps since 1970), then 'dynamic truncation'."""
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


# ---- Member keys ---------------------------------------------------------------------------------

def new_key():
    raw = "".join(secrets.choice(KEY_ALPHABET) for _ in range(KEY_LENGTH))
    return "-".join(raw[i:i + 4] for i in range(0, KEY_LENGTH, 4))       # e.g. K7QM-2XPA-9DHT


def _norm_key(key):
    return re.sub(r"[^A-Z0-9]", "", str(key).upper())


def _hash_secret(secret, salt, cred="key"):
    """scrypt: deliberately slow and memory-hungry, so a stolen database can't be cracked quickly.
    Owner-issued keys ignore case and dashes; passwords people choose are used exactly as typed."""
    raw = _norm_key(secret) if cred == "key" else unicodedata.normalize("NFC", str(secret))
    return hashlib.scrypt(raw.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1, dklen=32).hex()


def _hash_key(key, salt):
    return _hash_secret(key, salt, "key")


_DUMMY_SALT = secrets.token_hex(16)


def authenticate(username, secret):
    """('ok', member) | ('pending', None) for a teacher awaiting approval | ('bad', None).
    Always does the same slow hash, so the response time doesn't reveal whether a username exists."""
    username = str(username).strip().lower()
    with closing(_db()) as con:
        m = con.execute("SELECT * FROM members WHERE username = ?", (username,)).fetchone()
    if m is None:
        _hash_secret(secret, _DUMMY_SALT, "password")
        return "bad", None
    if not hmac.compare_digest(_hash_secret(secret, m["key_salt"], m["cred"]), m["key_hash"]):
        return "bad", None
    if m["status"] == "menunggu":
        return "pending", None
    if m["status"] != "aktif" or time.time() >= m["expires"]:
        return "bad", None
    return "ok", dict(m)


def check_member(username, key):
    """The member row if username + key/password are right and the account is active and unexpired, else None."""
    verdict, m = authenticate(username, key)
    return m if verdict == "ok" else None


def get_member(username):
    with closing(_db()) as con:
        m = con.execute("SELECT * FROM members WHERE username = ?", (username,)).fetchone()
    return dict(m) if m else None


def list_members():
    with closing(_db()) as con:
        rows = con.execute("""
            SELECT m.*, COUNT(l.id) AS n_logins, MAX(l.time) AS last_login
            FROM members m LEFT JOIN logins l ON l.username = m.username
            GROUP BY m.username ORDER BY m.created DESC""").fetchall()
    return [dict(r) for r in rows]


def member_logins(username, limit=200):
    with closing(_db()) as con:
        return pd.read_sql("SELECT time, ip, country, device, how FROM logins WHERE username = ? "
                           "ORDER BY time DESC LIMIT ?", con, params=(username, limit))


# Account roles. The names people read come from src/lang.py (Murid / Pupil, Cikgu / Teacher, ...); these Malay
# names are only for the event log, which stays in one language.
ROLES = {k: role_name(k, "ms") for k in ("pelajar", "pensyarah", "penyelidik", "penguji")}
# Which views each kind of user may open (page url names). The owner (this computer) sees everything.
# Teachers get their own page and the pupil page as a preview (used as themselves: it never opens a pupil's
# account). They do not see the expert page: its queue holds every teacher's cases. Testers ("penguji", made on
# Tetapan -> Penguji) open all three pages so they can try every task; on the expert page they see only the
# cases they sent themselves.
ROLE_VIEWS = {"owner": ["pelajar", "pensyarah", "penyelidik"], "pelajar": ["pelajar"],
              "pensyarah": ["pensyarah", "pelajar"], "penyelidik": ["penyelidik", "pelajar"],
              "penguji": ["pensyarah", "penyelidik", "pelajar"], "guest": ["pelajar"]}
PASSWORD_MIN = 8
SIGNUPS_PER_IP, SIGNUP_WINDOW = 5, 3600      # at most 5 new accounts per IP address per hour
GUEST_INQUIRY_TTL = 24 * 3600                 # guest / open-mode inquiries are deleted after 24 h at most
SELF_SIGNUP_DAYS = 365                        # self-made accounts last a year (owner can shorten or revoke)
_signups: list = []


def _check_username(username):
    username = str(username).strip().lower()
    if not USERNAME_RE.match(username):
        raise ValueError(tr("Nama pengguna: 3–24 aksara, huruf kecil, nombor, titik, sengkang atau garis bawah.",
                            "Username: 3–24 characters: small letters, numbers, dot, dash or underscore."))
    with closing(_db()) as con:
        if con.execute("SELECT 1 FROM retired_usernames WHERE username=?", (username,)).fetchone():
            raise ValueError(tr(f"Nama pengguna '{username}' pernah digunakan oleh akaun yang telah dipadam dan tidak "
                                "boleh digunakan semula. Pilih yang lain.",
                                f"The username '{username}' belonged to a deleted account and cannot be used again. "
                                "Choose another one."))
    return username


def add_member(username, name, days, note="", role="pelajar", lecturer=""):
    """Owner creates an account. Returns the new key (shown once; only its hash is stored)."""
    username = _check_username(username)
    if role not in ROLES:
        raise ValueError(tr("Peranan tidak sah.", "Invalid role."))
    key, salt = new_key(), secrets.token_hex(16)
    try:
        with _lock, closing(_db()) as con, con:
            con.execute("INSERT INTO members(username, name, note, key_hash, key_salt, created, expires, role, cred) "
                        "VALUES (?,?,?,?,?,?,?,?,'key')",
                        (username, name.strip() or username, note.strip(), _hash_key(key, salt), salt, time.time(),
                         time.time() + days * 86400, role))
    except sqlite3.IntegrityError:
        raise ValueError(tr(f"Nama pengguna '{username}' sudah wujud.", f"The username '{username}' already exists.")) from None
    _log("ahli: dicipta", username, note=f"{ROLES[role]}, {days:g} hari")
    return key


def sign_up(name, username, password, password2, role, class_code, ip):
    """Self sign-up from the login screen. Students join with a class code and can log in at once;
    teachers wait for the owner's approval. Returns the new member's status ('aktif' or 'menunggu')."""
    username = _check_username(username)
    name = str(name).strip()
    if not name:
        raise ValueError(tr("Isi nama penuh anda.", "Fill in your full name."))
    if len(password) < PASSWORD_MIN:
        raise ValueError(tr(f"Kata laluan sekurang-kurangnya {PASSWORD_MIN} aksara.",
                            f"The password needs at least {PASSWORD_MIN} characters."))
    if password != password2:
        raise ValueError(tr("Kedua-dua kata laluan tidak sama.", "The two passwords are not the same."))
    if password.lower() == username:
        raise ValueError(tr("Kata laluan tidak boleh sama dengan nama pengguna.",
                            "The password cannot be the same as the username."))
    if role not in ("pelajar", "pensyarah"):
        raise ValueError(tr(f"Pilih {role_name('pelajar')} atau {role_name('pensyarah')}.",
                            f"Choose {role_name('pelajar')} or {role_name('pensyarah')}."))
    cls = get_class(class_code) if role == "pelajar" else None
    if role == "pelajar" and (not cls or not cls["active"]):
        raise ValueError(tr("Kod kelas tidak sah. Minta kod daripada cikgu anda.",
                            "That class code is not valid. Ask your teacher for the code."))
    if cls and not cls["teacher_ok"]:
        raise ValueError(teacher_gone())
    name = " ".join(name.split())
    with closing(_db()) as con:
        if con.execute("SELECT 1 FROM members WHERE username=?", (username,)).fetchone():
            raise ValueError(tr(f"Nama pengguna '{username}' sudah digunakan. Pilih yang lain.",
                                f"The username '{username}' is taken. Choose another one."))
        if cls:   # two students with the same name in one class: the teacher could not tell them apart
            same = con.execute("SELECT 1 FROM class_members c JOIN members m ON m.username = c.username "
                               "WHERE c.code=? AND lower(m.name)=?", (cls["code"], name.lower())).fetchone()
            where = tr("dalam kelas ini", "in this class")
        else:
            same = con.execute("SELECT 1 FROM members WHERE role='pensyarah' AND status!='dibatalkan' "
                               "AND lower(name)=?", (name.lower(),)).fetchone()
            where = tr("sebagai cikgu", "as a teacher")
    if same:
        raise ValueError(tr(f"Nama '{name}' sudah berdaftar {where}. Jika itu akaun anda, log masuk sahaja. "
                            "Jika bukan, tulis nama penuh anda (cth. tambah nama bapa) supaya mudah dibezakan.",
                            f"The name '{name}' is already registered {where}. If that is your account, just log in. "
                            "If not, write your full name (e.g. add your father's name) so people can tell you apart."))
    now = time.time()
    with _lock:
        _signups[:] = [(t, a) for t, a in _signups if now - t < SIGNUP_WINDOW]
        if sum(1 for _, a in _signups if a == ip) >= SIGNUPS_PER_IP:
            raise ValueError(tr("Terlalu banyak pendaftaran dari rangkaian ini. Cuba lagi dalam sejam.",
                                "Too many sign-ups from this network. Try again in an hour."))
        _signups.append((now, ip))
    status = "aktif" if role == "pelajar" else "menunggu"
    salt = secrets.token_hex(16)
    try:
        with _lock, closing(_db()) as con, con:
            con.execute("INSERT INTO members(username, name, note, key_hash, key_salt, created, expires, status, role,"
                        " cred) VALUES (?,?,?,?,?,?,?,?,?,'password')",
                        (username, name, "daftar sendiri", _hash_secret(password, salt, "password"), salt, now,
                         now + SELF_SIGNUP_DAYS * 86400, status, role))
            if cls:
                con.execute("INSERT INTO class_members(code, username, joined) VALUES (?,?,?)", (cls["code"], username, now))
    except sqlite3.IntegrityError:
        raise ValueError(tr(f"Nama pengguna '{username}' sudah digunakan. Pilih yang lain.",
                                f"The username '{username}' is taken. Choose another one.")) from None
    _log("daftar: " + ("pelajar" if role == "pelajar" else "pensyarah (menunggu kelulusan)"), username, ip,
         note=f"kelas {cls['code']}" if cls else "")
    return status


def approve_teacher(username, ok=True):
    with _lock, closing(_db()) as con, con:
        if ok:
            con.execute("UPDATE members SET status='aktif' WHERE username=? AND status='menunggu'", (username,))
        else:
            con.execute("DELETE FROM members WHERE username=? AND status='menunggu'", (username,))
    _log("pensyarah: diluluskan" if ok else "pensyarah: ditolak", username)


def change_password(username, old, new, new2):
    if len(new) < PASSWORD_MIN:
        raise ValueError(tr(f"Kata laluan baharu sekurang-kurangnya {PASSWORD_MIN} aksara.",
                            f"The new password needs at least {PASSWORD_MIN} characters."))
    if new != new2:
        raise ValueError(tr("Kedua-dua kata laluan baharu tidak sama.", "The two new passwords are not the same."))
    if authenticate(username, old)[0] != "ok":
        raise ValueError(tr("Kata laluan semasa salah.", "The current password is wrong."))
    salt = secrets.token_hex(16)
    with _lock, closing(_db()) as con, con:
        con.execute("UPDATE members SET key_hash=?, key_salt=?, cred='password', key_version=key_version+1 "
                    "WHERE username=?", (_hash_secret(new, salt, "password"), salt, username))
    _log("ahli: tukar kata laluan", username)


def set_member_role(username, role, lecturer=""):
    with _lock, closing(_db()) as con, con:
        con.execute("UPDATE members SET role=? WHERE username=?", (role, username))
    _log("ahli: peranan ditukar", username, note=ROLES.get(role, role))


def lecturers():
    """{username: name} of lecturers who can look after a class now (approved and not expired)."""
    with closing(_db()) as con:
        return {r["username"]: r["name"] for r in
                con.execute("SELECT username, name FROM members WHERE role='pensyarah' AND status='aktif' "
                            "AND expires > ? ORDER BY name", (time.time(),))}


# ---- Classes (teachers make them; students join with the code) ------------------------------------

def _new_class_code():
    return "".join(secrets.choice(KEY_ALPHABET) for _ in range(6))      # e.g. K7QM2X


def create_class(teacher, name):
    name = str(name).strip()
    if not name:
        raise ValueError(tr("Isi nama kelas, contohnya '4 Bestari · Pantun Nasihat'.",
                            "Fill in a class name, for example '4 Bestari · Pantun Nasihat'."))
    for _ in range(10):
        code = _new_class_code()
        try:
            with _lock, closing(_db()) as con, con:
                con.execute("INSERT INTO classes(code, name, teacher, created) VALUES (?,?,?,?)",
                            (code, name, teacher, time.time()))
            _log("kelas: dicipta", teacher or "pemilik", note=f"{name} ({code})")
            return code
        except sqlite3.IntegrityError:
            continue
    raise ValueError(tr("Tidak dapat membuat kod kelas. Cuba lagi.", "Could not make a class code. Try again."))


def teacher_active(teacher):
    """Is this class teacher able to look after the class? ('' = the owner, always.) An expired, revoked,
    deleted or no-longer-lecturer account is not: its classes stop taking new students and the owner sees
    their inquiries until the account is extended or the class is moved."""
    if not teacher:
        return True
    m = get_member(teacher)
    return (bool(m) and m["status"] == "aktif" and m.get("role") in ("pensyarah", "penguji")   # testers try classes too
            and time.time() < m["expires"])


def teacher_gone():
    return tr("Cikgu kelas ini tidak aktif buat masa ini, jadi kelas tidak menerima murid baharu. "
              "Minta kod kelas lain daripada cikgu anda.",
              "This class's teacher is not active right now, so the class is not taking new pupils. "
              "Ask your teacher for another class code.")


def get_class(code):
    code = re.sub(r"[^A-Z0-9]", "", str(code).upper())
    with closing(_db()) as con:
        r = con.execute("SELECT * FROM classes WHERE code=?", (code,)).fetchone()
    return {**dict(r), "teacher_ok": teacher_active(r["teacher"])} if r else None


def classes_of(teacher=None):
    """A teacher's classes with student counts (teacher=None: every class, for the owner)."""
    q = ("SELECT c.*, COUNT(cm.username) AS n_students, m.name AS teacher_name FROM classes c "
         "LEFT JOIN class_members cm ON cm.code = c.code LEFT JOIN members m ON m.username = c.teacher "
         + ("WHERE c.teacher = ? " if teacher is not None else "") + "GROUP BY c.code ORDER BY c.created DESC")
    with closing(_db()) as con:
        rows = [dict(r) for r in con.execute(q, (teacher,) if teacher is not None else ())]
    return [{**r, "teacher_ok": teacher_active(r["teacher"])} for r in rows]


def set_class_active(code, active):
    with _lock, closing(_db()) as con, con:
        con.execute("UPDATE classes SET active=? WHERE code=?", (1 if active else 0, code))
    _log("kelas: dibuka" if active else "kelas: ditutup", note=code)


def class_students(code):
    with closing(_db()) as con:
        return [dict(r) for r in con.execute(
            "SELECT m.username, m.name, m.status, cm.joined, (SELECT MAX(time) FROM logins l WHERE l.username = "
            "m.username) AS last_login FROM class_members cm JOIN members m ON m.username = cm.username "
            "WHERE cm.code = ? ORDER BY m.name", (code,))]


def student_classes(username):
    with closing(_db()) as con:
        return [dict(r) for r in con.execute(
            "SELECT c.code, c.name, c.teacher, m.name AS teacher_name FROM class_members cm JOIN classes c "
            "ON c.code = cm.code LEFT JOIN members m ON m.username = c.teacher WHERE cm.username = ? "
            "ORDER BY cm.joined", (username,))]


def student_classes_ok(username):
    """student_classes with 'teacher_ok' (is someone looking after each class right now)."""
    return [{**c, "teacher_ok": teacher_active(c["teacher"])} for c in student_classes(username)]


def transfer_class(code, new_teacher):
    """Owner moves a class (its students and all its inquiries, which follow the class code) to another lecturer."""
    cls = get_class(code)
    if not cls:
        raise ValueError(tr("Kelas tidak dijumpai.", "Class not found."))
    if new_teacher and new_teacher not in lecturers():
        raise ValueError(tr("Pilih cikgu yang aktif.", "Choose an active teacher."))
    with _lock, closing(_db()) as con, con:
        con.execute("UPDATE classes SET teacher=? WHERE code=?", (new_teacher, cls["code"]))
    _log("kelas: dipindah", new_teacher or "pemilik", note=f"{cls['name']} ({cls['code']}) daripada "
                                                           f"{cls['teacher'] or 'pemilik'}")


def join_class(username, code):
    cls = get_class(code)
    if not cls or not cls["active"]:
        raise ValueError(tr("Kod kelas tidak sah atau kelas sudah ditutup.", "The class code is not valid or the class is closed."))
    if not cls["teacher_ok"]:
        raise ValueError(teacher_gone())
    with _lock, closing(_db()) as con, con:
        con.execute("INSERT OR IGNORE INTO class_members(code, username, joined) VALUES (?,?,?)",
                    (cls["code"], username, time.time()))
    _log("kelas: pelajar menyertai", username, note=cls["code"])
    return cls


def remove_from_class(code, username):
    with _lock, closing(_db()) as con, con:
        con.execute("DELETE FROM class_members WHERE code=? AND username=?", (code, username))
    _log("kelas: pelajar dikeluarkan", username, note=code)


def teacher_has_student(teacher, student):
    with closing(_db()) as con:
        return bool(con.execute("SELECT 1 FROM class_members cm JOIN classes c ON c.code = cm.code "
                                "WHERE c.teacher = ? AND cm.username = ?", (teacher, student)).fetchone())


# ---- Inquiries ("Saya tidak setuju") ------------------------------------------------------------

def _valid_guest_rounds(s):
    rounds = []
    if s["enabled"]:
        rounds.append("tetamu:" + s["round"])
    if s.get("open"):
        rounds.append("terbuka:" + s.get("open_round", ""))
    return rounds


def _purge_inquiries(s=None):
    """Guest and open-mode inquiries are temporary: gone when their round ends, and after 24 h at most."""
    s = s or state()
    rounds = _valid_guest_rounds(s)
    marks = ",".join("?" * len(rounds)) or "''"
    with _lock, closing(_db()) as con, con:
        n = con.execute(f"DELETE FROM inquiries WHERE kind='tetamu' AND (expires < ? OR round NOT IN ({marks}))",
                        (time.time(), *rounds)).rowcount
    if n:
        _log("pertanyaan tetamu dipadam (tamat)", note=str(n))


def add_inquiry(user, lines, res, comment, class_code=""):
    """Save a 'Saya tidak setuju' request. Students' go to their class teacher and are kept; guests' go to all
    approved teachers and are deleted when the guest session (or open mode) ends."""
    s, now = state(), time.time()
    kind, rnd, expires = "pemilik", "", 0
    if user["kind"] == "member":
        kind = "pelajar"
        if class_code and class_code not in {c["code"] for c in student_classes(user["username"])}:
            class_code = ""
    elif user["kind"] == "guest" and s["enabled"]:
        kind, rnd, expires = "tetamu", "tetamu:" + s["round"], min(s["until"], now + GUEST_INQUIRY_TTL)
    elif user["kind"] == "public" and s.get("open"):
        kind, rnd, expires = "tetamu", "terbuka:" + s.get("open_round", ""), now + GUEST_INQUIRY_TTL
    with _lock, closing(_db()) as con, con:
        con.execute("INSERT INTO inquiries(time, kind, who, username, class_code, round, expires, line1, line2, line3,"
                    " line4, comment, sound, meaning_pct, rules) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (now, kind, user["name"], user["username"], class_code if kind == "pelajar" else "", rnd, expires,
                     *lines, comment, res["sound"], round(100 * res["p_avg"]), res["rules"]))
    _log(f"pertanyaan: {kind}", user["username"] or user["name"], note=class_code)


def inquiries_for(user):
    """Inquiries this user may see: the owner sees all; an approved teacher sees their classes' students and
    the current temporary guest inquiries; nobody else sees any."""
    _purge_inquiries()
    base = ("SELECT i.*, c.name AS class_name FROM inquiries i LEFT JOIN classes c ON c.code = i.class_code ")
    with closing(_db()) as con:
        if user["kind"] == "owner":
            return pd.read_sql(base + "ORDER BY i.time DESC", con)
        if user["role"] == "pensyarah":
            return pd.read_sql(base + "WHERE (i.kind='pelajar' AND c.teacher = ?) OR i.kind='tetamu' "
                               "ORDER BY i.time DESC", con, params=(user["username"],))
        return pd.read_sql(base + "WHERE 0", con)          # nobody else: an empty table with the same columns


def my_inquiries(username):
    with closing(_db()) as con:
        return pd.read_sql("SELECT time, line1, line3, comment, status, reply FROM inquiries WHERE username = ? "
                           "ORDER BY time DESC", con, params=(username,))


def resolve_inquiry(inquiry_id, user, reply):
    if inquiry_id not in set(inquiries_for(user)["id"]):
        raise ValueError(tr("Anda tidak dibenarkan menyemak pertanyaan ini.", "You may not answer this question."))
    with _lock, closing(_db()) as con, con:
        con.execute("UPDATE inquiries SET status='selesai', handled_by=?, reply=? WHERE id=?",
                    (user["username"] or "pemilik", reply.strip(), int(inquiry_id)))
    _log("pertanyaan: selesai", user["username"] or "pemilik", note=str(inquiry_id))


def current_user():
    """Who is using this session: {'kind': owner|member|guest|public, 'role', 'username', 'name'}."""
    if not is_visitor():
        return {"kind": "owner", "role": "owner", "username": "", "name": tr("Pemilik", "Owner"), "lecturer": ""}
    kind = st.session_state.get("share_kind")
    if kind == "member":
        m = get_member(st.session_state.get("share_user")) or {}
        return {"kind": "member", "role": m.get("role", "pelajar"), "username": m.get("username", ""),
                "name": m.get("name", ""), "lecturer": ""}
    if kind == "public":
        return {"kind": "public", "role": "guest", "username": "", "name": role_name("pelawat"), "lecturer": ""}
    dev = _reg["devices"].get(st.session_state.get("share_did"), {})
    return {"kind": "guest", "role": "guest", "username": "", "name": dev.get("name", role_name("tetamu")), "lecturer": ""}


def allowed_views():
    return ROLE_VIEWS.get(current_user()["role"], ["pelajar"])


def require_view(view):
    """Stop a page that this user may not open (the menu already hides it; this also guards direct links)."""
    if view not in allowed_views():
        st.warning(tr("Halaman ini hanya untuk pengguna yang dibenarkan.", "This page is only for users who are allowed."),
                   icon=":material/lock:")
        st.stop()


def sign_out():
    """Visitor's 'Log keluar': forget this session and this browser's pass, then show the login screen."""
    who = current_user()
    _log("log keluar", who["username"] or who["name"])
    _lock_out()
    st.session_state["cz_signed_out"] = True        # don't sign straight back in from the old cookie


def _want_login():
    """Open-mode visitor pressed 'Log masuk / Daftar': show the login screen."""
    _lock_out()
    st.session_state["cz_want_login"] = True


# Each kind of account has its own small character in the top bar (pictures in static/i, see src/illus.py).
AVATARS = {"pelajar": ("student", "#9B5DE5"), "pensyarah": ("job_senesi", "#2AA7E0"),
           "penyelidik": ("owl", "#1E9A50"), "penguji": ("study_woman_normal", "#E0457B"),
           "owner": ("hornbill", "#F08A00"), "guest": ("kotori", "#5B6670")}
_CHIP_CSS = """<style>
.cz-chip { display: inline-flex; align-items: center; gap: 8px; padding: 3px 12px 3px 3px; border-radius: 999px;
  background: #fff; border: 2px solid var(--c); font-family: 'Nunito', sans-serif; line-height: 1.15; }
.cz-chip .av { width: 36px; height: 36px; border-radius: 50%; background: color-mix(in srgb, var(--c) 18%, #fff);
  display: flex; align-items: center; justify-content: center; overflow: hidden; flex: none; }
.cz-chip .av img { width: 30px; height: 30px; object-fit: contain; }
.cz-chip b { display: block; font-size: .92rem; color: #17324D; max-width: 160px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap; }
.cz-chip small { font-size: .74rem; font-weight: 800; color: var(--c); }
</style>"""


def user_chip(name, role_key, role_txt):
    """Round avatar + name + role, as HTML (the name comes from the user, so it is escaped)."""
    pic, colour = AVATARS.get(role_key, AVATARS["guest"])
    img = f'<img alt="" src="/app/static/i/{pic}.png">' if illus.has(pic) else ""
    return (f'{_CHIP_CSS}<div class="cz-chip" style="--c:{colour}"><span class="av">{img}</span>'
            f'<span><b>{html.escape(str(name))}</b><small>{html.escape(role_txt)}</small></span></div>')


def user_bar():
    """Small 'avatar · name · role · Log keluar' chip, shown in the top bar of every page (app.py puts it next to
    the BM / EN switch). The owner gets a chip too, without the buttons."""
    u = current_user()
    if u["kind"] == "owner":
        st.html(user_chip(u["name"], "owner", tr("Pemilik", "Owner")), width="content")
        return
    if u["kind"] == "public":
        st.html(user_chip(role_name("pelawat"), "guest", tr("tanpa log masuk", "not logged in")), width="content")
        st.button(tr("Log masuk / Daftar", "Log in / Sign up"), icon=":material/login:", type="tertiary",
                  on_click=_want_login, key="cz_login")
        return
    role_key = u["role"] if u["role"] in ROLES else "guest"
    role_txt = role_name(u["role"]) if u["role"] in ROLES else role_name("tetamu")
    st.html(user_chip(u["name"], role_key, role_txt), width="content")
    if u["kind"] == "member":
        with st.popover(tr("Tukar kata laluan", "Change password"), icon=":material/password:", type="tertiary"):
            with st.form("cz_pw", border=False, clear_on_submit=True):
                old = st.text_input(tr("Kata laluan / kunci semasa", "Current password / key"), type="password")
                new = st.text_input(tr("Kata laluan baharu", "New password"), type="password")
                new2 = st.text_input(tr("Ulang kata laluan baharu", "Repeat new password"), type="password")
                if st.form_submit_button(tr("Simpan", "Save"), type="primary"):
                    try:
                        change_password(u["username"], old, new, new2)
                        st.success(tr("Kata laluan ditukar. Peranti lain akan dilog keluar.",
                                      "Password changed. Other devices will be logged out."))
                    except ValueError as e:
                        st.error(str(e))
    st.button(tr("Log keluar", "Log out"), icon=":material/logout:", type="tertiary", on_click=sign_out, key="cz_logout")


def reset_key(username, days=None):
    """New key (old key and every remembered browser stop working). Optionally set a new validity."""
    key, salt = new_key(), secrets.token_hex(16)
    with _lock, closing(_db()) as con, con:
        con.execute("UPDATE members SET key_hash=?, key_salt=?, cred='key', key_version=key_version+1, status='aktif'"
                    + (", expires=?" if days else "") + " WHERE username=?",
                    (_hash_key(key, salt), salt, *( [time.time() + days * 86400] if days else []), username))
    _log("ahli: kunci baharu", username)
    return key


def extend_member(username, days):
    with _lock, closing(_db()) as con, con:
        con.execute("UPDATE members SET expires = MAX(expires, ?) + ? WHERE username=?",
                    (time.time(), days * 86400, username))
    _log("ahli: dilanjutkan", username, note=f"+{days:g} hari")


def set_member_status(username, active):
    with _lock, closing(_db()) as con, con:
        con.execute("UPDATE members SET status=? WHERE username=?", ("aktif" if active else "dibatalkan", username))
    _log("ahli: diaktifkan semula" if active else "ahli: dibatalkan", username)


def sign_out_member(username):
    with _lock, closing(_db()) as con, con:
        con.execute("UPDATE members SET session_gen = session_gen + 1 WHERE username=?", (username,))
    _log("ahli: log keluar semua peranti", username)


def delete_member(username):
    """Delete an account. Its username is retired for good; a lecturer's classes stay (closed to new students
    until the owner moves them to another lecturer with transfer_class)."""
    with _lock, closing(_db()) as con, con:
        con.execute("DELETE FROM members WHERE username=?", (username,))
        con.execute("INSERT OR IGNORE INTO retired_usernames(username, time) VALUES (?,?)", (username, time.time()))
    _log("ahli: dipadam", username, note="sejarah log masuk disimpan; nama pengguna tidak boleh diguna semula")


def _record_login(username, me, how):
    with _lock, closing(_db()) as con, con:
        con.execute("INSERT INTO logins(username, time, ip, country, device, how) VALUES (?,?,?,?,?,?)",
                    (username, time.time(), me["ip"], me["country"], me["device"], how))
    _log("ahli: log masuk" if how == "kunci" else "ahli: masuk semula (diingati)", username, me["ip"],
         me["country"], me["device"])


# ---- Remembered pass (signed cookie) -------------------------------------------------------------

def _pass_key(secret):
    """Key for signing passes, derived from the code secret (so a pass can't be used as a code)."""
    return hmac.new(bytes.fromhex(secret), b"cz-remember-pass", hashlib.sha256).digest()


def make_pass(s, payload):
    body = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = hmac.new(_pass_key(s["secret"]), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def read_pass(s, token):
    """The pass's contents if its signature is genuine and it hasn't expired; otherwise None."""
    try:
        body, sig = token.split(".", 1)
        good = hmac.new(_pass_key(s["secret"]), body.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, good):
            return None
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except (ValueError, AttributeError, TypeError):
        return None
    return data if isinstance(data, dict) and time.time() < data.get("e", 0) else None


def _set_cookie(token, max_age):
    """Store the pass in this browser (JavaScript, because Streamlit can only read cookies)."""
    st.html(f"""<script>
document.cookie = "{COOKIE}=" + {json.dumps(token)} + "; Max-Age={int(max_age)}; Path=/; SameSite=Strict"
                  + (location.protocol === "https:" ? "; Secure" : "");
</script>""", unsafe_allow_javascript=True)


def _clear_cookie():
    st.html(f"""<script>document.cookie = "{COOKIE}=; Max-Age=0; Path=/; SameSite=Strict";</script>""",
            unsafe_allow_javascript=True)


# ---- Who is asking -------------------------------------------------------------------------------

def is_visitor():
    """True for requests that come through Cloudflare (the public address). Cloudflare always adds these
    headers, so a visitor cannot hide them. PANTUN_FORCE_GATE=1 shows the visitor screen locally (testing).
    Exception: the owner logged in through Cloudflare Access on the admin address (signed token checked in
    src/access_login.py) is treated like this computer, so the owner can manage the app from anywhere."""
    if os.environ.get("PANTUN_FORCE_GATE") == "1":
        return True
    h = st.context.headers
    if not (h.get("Cf-Ray") or h.get("Cf-Connecting-Ip")):
        return False                                   # this computer
    return access_login.owner_email(h.get("Cf-Access-Jwt-Assertion")) is None


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
            "country": h.get("Cf-Ipcountry", "?"), "device": device_label(ua)}


# ---- Wrong-attempt limits ------------------------------------------------------------------------

def _fail(ip, kind):
    with _lock:
        _fails.append((time.time(), ip, kind))


def _fail_counts(ip):
    """(wrong attempts from this IP in 10 min, wrong guest codes from everyone in 1 hour)."""
    now = time.time()
    with _lock:
        _fails[:] = [f for f in _fails if now - f[0] < max(IP_WINDOW, ALL_WINDOW)]
        mine = sum(1 for t, a, _ in _fails if a == ip and now - t < IP_WINDOW)
        guests = sum(1 for t, _, k in _fails if k == "guest" and now - t < ALL_WINDOW)
    return mine, guests


# ---- Guest device register -----------------------------------------------------------------------

def _registry(round_id):
    """Guest devices of this round. A new round starts empty; after an app restart it is read back from disk."""
    with _lock:
        if _reg["round"] != round_id:
            saved = _read(DEVICES_FILE)
            if round_id and saved.get("round") == round_id:
                _reg.update(round=round_id, devices=saved.get("devices", {}), blocked=set(saved.get("blocked", [])))
            else:
                _reg.update(round=round_id, devices={}, blocked=set())
        return _reg


def _save_registry():
    with _lock:
        _write(DEVICES_FILE, {"round": _reg["round"], "devices": _reg["devices"], "blocked": sorted(_reg["blocked"])})


def remove_device(device_id, block_ip=False):
    """Owner action: lock one guest device out (and its pass); optionally block its IP for the rest of the round."""
    with _lock:
        dev = _reg["devices"].get(device_id)
        if not dev:
            return
        dev["status"] = "disekat" if block_ip else "dikeluarkan"
        if block_ip:
            _reg["blocked"].add(dev["ip"])
        _save_registry()
    _log("tetamu: disekat" if block_ip else "tetamu: dikeluarkan", dev["name"], dev["ip"], dev["country"],
         dev["device"])


def unblock_ip(ip):
    with _lock:
        _reg["blocked"].discard(ip)
        _save_registry()
    _log("tetamu: buka sekatan", ip=ip)


def _admit_guest(reg, s, device_id, name, me, expires, event):
    with _lock:
        dev = reg["devices"].get(device_id)
        if dev is None:
            dev = reg["devices"][device_id] = {"id": device_id, "name": name, **me, "first": time.time(),
                                               "status": "aktif", "visits": 0}
        dev.update(ip=me["ip"], country=me["country"], device=me["device"], last=time.time(),
                   until=expires, visits=dev.get("visits", 0) + 1)
        _save_registry()
    _log(event, name, me["ip"], me["country"], me["device"])
    st.session_state.update(share_kind="guest", share_round=s["round"], share_did=device_id, share_exp=expires)


def _admit_member(m, me, expires, how):
    _record_login(m["username"], me, how)
    st.session_state.update(share_kind="member", share_user=m["username"], share_kv=m["key_version"],
                            share_sg=m["session_gen"], share_exp=expires)


# ---- Is this session still allowed? -------------------------------------------------------------

def _session_ok(s, me):
    """'ok', or why not: 'none' (not signed in), 'removed', 'blocked'."""
    kind, now = st.session_state.get("share_kind"), time.time()
    if not kind or now >= st.session_state.get("share_exp", 0):
        return "none"
    if kind == "member":
        m = get_member(st.session_state.get("share_user"))
        if (not s["members"] or not m or m["status"] != "aktif" or now >= m["expires"]
                or m["key_version"] != st.session_state.get("share_kv")
                or m["session_gen"] != st.session_state.get("share_sg")):
            return "removed"
        with _lock:
            _live[_session_id()] = {"user": m["username"], **me, "last": now}
        return "ok"
    if kind == "public":            # open mode: fine while it stays on (same open round)
        ok = s.get("open") and st.session_state.get("share_round") == "terbuka:" + s.get("open_round", "")
        return "ok" if ok else "none"
    if not s["enabled"] or st.session_state.get("share_round") != s["round"]:
        return "none"
    reg = _registry(s["round"])
    dev = reg["devices"].get(st.session_state.get("share_did"))
    if me["ip"] in reg["blocked"] or (dev and dev["status"] == "disekat"):
        return "blocked"
    if not dev or dev["status"] != "aktif":
        return "removed"
    dev["last"] = now
    return "ok"


def _try_pass(s, me):
    """Sign this session in from a remembered pass (refresh, new tab, browser reopened)."""
    p = read_pass(s, st.context.cookies.get(COOKIE, ""))
    if not p:
        return
    if p.get("t") == "m" and s["members"]:
        m = get_member(p.get("u"))
        if (m and m["status"] == "aktif" and time.time() < m["expires"] and m["key_version"] == p.get("kv")
                and m["session_gen"] == p.get("sg")):
            _admit_member(m, me, p["e"], "diingati")
    elif p.get("t") == "g" and s["enabled"] and p.get("r") == s["round"]:
        reg = _registry(s["round"])
        dev = reg["devices"].get(p.get("d"))
        if (dev is None or dev["status"] == "aktif") and me["ip"] not in reg["blocked"]:
            _admit_guest(reg, s, p["d"], p.get("n", "?"), me, p["e"], "tetamu: masuk semula (diingati)")


def _lock_out():
    for k in [k for k in st.session_state if str(k).startswith("share_")]:
        st.session_state.pop(k, None)
    st.session_state.pop("cz_home_done", None)      # next login: send teachers/experts to their page again
    with _lock:
        _live.pop(_session_id(), None)


# ---- Visitor screens -----------------------------------------------------------------------------

_GATE_CSS = """<style>
.cz-gate { max-width: 460px; margin: 6vh auto 0; text-align: center; font-family: 'Nunito', sans-serif; }
.cz-gate .logo { width: 54px; height: 54px; border-radius: 50%; background: #DEB251; margin: 0 auto 14px;
  box-shadow: 0 8px 24px rgba(222, 178, 81, .45); }
.cz-gate h1 { font-size: 1.9rem; font-weight: 900; color: #0C525C; margin: 0; padding: 0; }
.cz-gate p { color: #45525a; font-size: 1.02rem; line-height: 1.55; margin: 8px 0 0; }
.st-key-share_gate { max-width: 560px; margin: 14px auto 0; }
.st-key-share_gate input[maxlength="6"] { text-align: center; font-size: 1.9rem !important; letter-spacing: .5em;
  font-family: 'JetBrains Mono', monospace !important; }
.st-key-share_gate input[maxlength="14"] { font-family: 'JetBrains Mono', monospace !important; letter-spacing: .12em; }
.st-key-share_gate [data-testid="InputInstructions"] { display: none; }
</style>"""


def _screen(title, malay, english, pic="", anim="wiggle"):
    """Centre screen for visitors, in the visitor's language. (`pic` and `anim` are no longer used: every screen
    shows the login stage of src/illus.py.)"""
    st.html(_GATE_CSS + illus.stage_html("login", title, tr(malay, english), "Cenderawasih"))


def gate():
    """Stop the page for visitors who are not signed in as a member or an admitted guest."""
    if not is_visitor():
        return
    s, me = state(), _client()

    verdict = _session_ok(s, me)
    if verdict == "none":
        _lock_out()
        if st.session_state.get("cz_signed_out"):   # just pressed "Log keluar": forget the pass in this browser
            _clear_cookie()
        else:
            _try_pass(s, me)
            verdict = _session_ok(s, me)
    if verdict == "none" and s.get("open") and not st.session_state.get("cz_want_login"):
        # Open mode: straight to the student page, no login (teacher and expert pages still need one).
        st.session_state.update(share_kind="public", share_round="terbuka:" + s["open_round"],
                                share_exp=s["open_until"])
        if st.session_state.get("cz_public_round") != s["open_round"]:
            st.session_state["cz_public_round"] = s["open_round"]
            _log("terbuka: pelawat masuk", "", me["ip"], me["country"], me["device"])
        verdict = "ok"
    if verdict == "ok":
        st.session_state.pop("cz_signed_out", None)
        token = st.session_state.pop("share_cookie", None)
        if token:                                    # first run after a correct login: remember this browser
            _set_cookie(token, st.session_state["share_exp"] - time.time())
        _watch()
        return
    if verdict in ("blocked", "removed"):
        _lock_out()
        _clear_cookie()
        if verdict == "blocked":
            _screen(tr("Akses disekat", "Access blocked"), "Pemilik telah menyekat peranti ini.", "The owner has blocked this device.",
                    "box_kara_hako", "pop")
        else:
            _screen(tr("Akses ditarik balik", "Access withdrawn"), "Akses anda telah ditamatkan oleh pemilik atau telah luput.",
                    "Your access was ended by the owner or has expired.", "box_kara_hako", "pop")
        st.stop()

    if not s["members"] and not s["enabled"] and not s.get("open"):
        _screen(tr("Perkongsian ditutup", "Sharing is closed"),
                "Pemilik belum membuka akses ke Semak Pantun. Minta mereka hidupkan perkongsian.",
                "The owner has not opened Semak Pantun yet. Ask them to switch sharing on.", "yashinoki", "float")
        st.stop()

    _screen("Semak Pantun", "Log masuk dengan akaun anda, daftar akaun baharu, atau masuk dengan kod tetamu.",
            "Log in, sign up (pupils need a class code from their teacher), or use a guest code.",
            "key", "wiggle")
    with st.container(key="share_gate"):
        if s.get("open"):
            st.button(tr("← Teruskan tanpa log masuk", "← Continue without logging in"), type="tertiary", key="cz_back_open",
                      on_click=lambda: st.session_state.pop("cz_want_login", None))
        labels = {"login": "![](/app/static/i/gutspose_man.png) " + tr("Log masuk", "Log in"),
                  "signup": "![](/app/static/i/notebook.png) " + tr("Daftar", "Sign up"),
                  "guest": "![](/app/static/i/ticket.png) " + tr("Tetamu (kod)", "Guest (code)")}
        forms = {"login": _member_form, "signup": _signup_form, "guest": _guest_form}
        keys = (["login", "signup"] if s["members"] else []) + (["guest"] if s["enabled"] else [])
        for tab, k in zip(st.tabs([labels[k] for k in keys]), keys):
            with tab:
                forms[k](s, me)
    st.stop()


def _signup_form(s, me):
    with st.form("signup_form", border=False, clear_on_submit=False):
        pics = {"pelajar": "![](/app/static/i/backpack.png) ", "pensyarah": "![](/app/static/i/job_senesi.png) "}
        role = st.radio(tr("Saya seorang", "I am a"), ["pelajar", "pensyarah"], horizontal=True,
                        format_func=lambda k: pics[k] + role_name(k))
        name = st.text_input(tr("Nama penuh", "Full name"), max_chars=60)
        user = st.text_input(tr("Nama pengguna", "Username"), max_chars=24,
                             placeholder=tr("huruf kecil, cth. aina.r", "small letters, e.g. aina.r"))
        pw = st.text_input(tr("Kata laluan", "Password"), type="password",
                           placeholder=tr(f"sekurang-kurangnya {PASSWORD_MIN} aksara", f"at least {PASSWORD_MIN} characters"))
        pw2 = st.text_input(tr("Ulang kata laluan", "Repeat password"), type="password")
        code = st.text_input(tr("Kod kelas (murid sahaja)", "Class code (pupils only)"), max_chars=8,
                             placeholder=tr("daripada cikgu, cth. K7QM2X", "from your teacher, e.g. K7QM2X"))
        st.caption(tr("Cikgu: akaun anda aktif selepas diluluskan oleh pemilik. Murid: terus boleh log masuk.",
                      "Teachers: your account works once the owner approves it. Pupils: you can log in straight away."))
        go = st.form_submit_button(tr("Daftar", "Sign up"), type="primary", icon=":material/person_add:", width="stretch")
    if go:
        try:
            status = sign_up(name, user, pw, pw2, role, code, me["ip"])
        except ValueError as e:
            st.error(str(e), icon=":material/error:")
            return
        first = html.escape(str(name).strip().split(" ")[0]) or tr("anda", "you")
        if status == "aktif":
            illus.celebrate(tr("Tahniah!", "Well done!") + " <img class=cz-i alt src=/app/static/i/cracker.png>",
                            tr(f"Selamat datang ke Semak Pantun, <b>{first}</b>! Akaun murid anda sudah sedia. "
                               "Log masuk dan mula menyemak pantun.",
                               f"Welcome to Semak Pantun, <b>{first}</b>! Your pupil account is ready. "
                               "Log in and start checking pantun."))
            st.success(tr("Akaun dicipta! Sila log masuk di tab **Log masuk**.",
                          "Account created! Please log in on the **Log in** tab."), icon=":material/check_circle:")
        else:
            illus.celebrate(tr("Tahniah!", "Well done!") + " <img class=cz-i alt src=/app/static/i/cracker.png>",
                            tr(f"Terima kasih, <b>{first}</b>! Akaun cikgu anda sudah didaftarkan dan akan aktif "
                               "sebaik sahaja diluluskan oleh pemilik.",
                               f"Thank you, <b>{first}</b>! Your teacher account is registered and will work as soon "
                               "as the owner approves it."), "job_senesi")
            st.info(tr("Akaun cikgu dicipta dan **menunggu kelulusan pemilik**. Cuba log masuk selepas diluluskan.",
                       "Teacher account created and **waiting for the owner's approval**. Try logging in after that."),
                    icon=":material/hourglass_top:")


def _member_form(s, me):
    with st.form("member_form", border=False):
        user = st.text_input(tr("Nama pengguna", "Username"), max_chars=24, placeholder=tr("nama pengguna", "username"))
        key = st.text_input(tr("Kata laluan atau kunci", "Password or key"), type="password")
        remember = st.checkbox(tr("Ingat peranti ini (sehingga 24 jam)", "Remember this device (up to 24 hours)"), value=True)
        go = st.form_submit_button(tr("Log masuk", "Log in"), type="primary", icon=":material/login:", width="stretch")
    if go:
        if _fail_counts(me["ip"])[0] >= IP_FAILS:
            st.error(tr("Terlalu banyak cubaan salah dari rangkaian ini. Cuba lagi dalam 10 minit.",
                        "Too many wrong tries from this network. Try again in 10 minutes."), icon=":material/timer:")
            return
        verdict, m = authenticate(user, key)
        if verdict == "pending":
            st.info(tr("Akaun cikgu anda masih **menunggu kelulusan** pemilik.",
                       "Your teacher account is still **waiting for the owner's approval**."), icon=":material/hourglass_top:")
            return
        if not m:
            _fail(me["ip"], "member")
            _log("ahli: log masuk gagal", str(user).strip().lower()[:24], me["ip"], me["country"], me["device"])
            st.error(tr("Nama pengguna atau kata laluan salah, atau akaun sudah luput.",
                        "Wrong username or password, or the account has ended."), icon=":material/error:")
            return
        st.session_state.pop("cz_want_login", None)
        expires = min(time.time() + MEMBER_REMEMBER, m["expires"])
        _admit_member(m, me, expires, "kunci")
        if remember:
            st.session_state["share_cookie"] = make_pass(s, {"t": "m", "u": m["username"], "kv": m["key_version"],
                                                             "sg": m["session_gen"], "e": int(expires)})
        st.rerun()


def _guest_form(s, me):
    with st.form("guest_form", border=False):
        name = st.text_input(tr("Nama anda", "Your name"), max_chars=40,
                             placeholder=tr("Nama anda (supaya pemilik kenal)", "Your name (so the owner knows you)"))
        code = st.text_input(tr("Kod", "Code"), max_chars=DIGITS, placeholder="••••••", label_visibility="collapsed")
        remember = st.checkbox(tr("Ingat peranti ini selama 2 jam", "Remember this device for 2 hours"), value=True)
        go = st.form_submit_button(tr("Masuk", "Enter"), type="primary", icon=":material/lock_open:", width="stretch")
    if go:
        mine, guests = _fail_counts(me["ip"])
        name = name.strip() or "(tiada nama)"
        reg = _registry(s["round"])
        if me["ip"] in reg["blocked"]:
            st.error(tr("Peranti ini disekat oleh pemilik.", "The owner has blocked this device."), icon=":material/block:")
        elif guests >= ALL_FAILS:
            st.error(tr("Kod tetamu dijeda kerana terlalu banyak kod salah. Minta pemilik memulakan semula.",
                        "Guest codes are paused after too many wrong codes. Ask the owner to restart them."),
                     icon=":material/pause_circle:")
        elif mine >= IP_FAILS:
            st.error(tr("Terlalu banyak cubaan salah dari rangkaian ini. Cuba lagi dalam 10 minit.",
                        "Too many wrong tries from this network. Try again in 10 minutes."), icon=":material/timer:")
        elif verify(code):
            st.session_state.pop("cz_want_login", None)
            expires = min(time.time() + GUEST_REMEMBER, s["until"])
            device_id = secrets.token_hex(6)
            _admit_guest(reg, s, device_id, name, me, expires, "tetamu: masuk")
            if remember:
                st.session_state["share_cookie"] = make_pass(s, {"t": "g", "r": s["round"], "d": device_id,
                                                                 "n": name, "e": int(expires)})
            st.rerun()
        else:
            _fail(me["ip"], "guest")
            _log("tetamu: kod salah", name, me["ip"], me["country"], me["device"])
            st.error(tr("Kod tidak sah atau sudah tamat. Minta kod baharu.", "The code is wrong or has run out. Ask for a new one."),
                     icon=":material/error:")


@st.fragment(run_every=HEARTBEAT)
def _watch():
    """Heartbeat from an open visitor page: marks it online, and locks it as soon as access ends."""
    if _session_ok(state(), _client()) != "ok":
        _lock_out()
        st.rerun()


# ---- Owner page ----------------------------------------------------------------------------------

def owner_page():
    """'Tetapan / Settings' page (owner only): members, access without an account, testers, language and the log."""
    st.title(tr("Tetapan Semak Pantun", "Semak Pantun Settings"), anchor=False)
    st.caption(tr(f"Alamat awam: {PUBLIC_URL}", f"Public address: {PUBLIC_URL}"))
    kick = tr("Tetapan", "Settings")
    tab_m, tab_g, tab_t, tab_b, tab_l = st.tabs([
        "![](/app/static/i/gutspose_man.png) " + tr("Ahli", "Members"),
        "![](/app/static/i/globe.png) " + tr("Akses tanpa akaun", "Access without an account"),
        "![](/app/static/i/test_tube.png) " + role_name("penguji"),
        "![](/app/static/i/speech.png) " + tr("Bahasa", "Language"),
        "![](/app/static/i/paper.png) Log"])
    with tab_m:
        illus.stage("ahli", tr("Ahli", "Members"), tr("Akaun, peranan dan kelas.", "Accounts, roles and classes."), kick)
        members_panel()
    with tab_g:
        illus.stage("akses", tr("Akses Tanpa Akaun", "Access Without an Account"),
                    tr("Siapa boleh masuk tanpa log masuk.", "Who can get in without logging in."), kick)
        guests_panel()
    with tab_t:
        from src import tester          # imported here: tester.py itself uses this module
        illus.stage("ujian", role_name("penguji"), tr("Jemput rakan, baca hasil dan nilai skor.",
                                                      "Invite friends, read the results and judge the score."), kick)
        tester.owner_panel()
    with tab_b:
        language_panel()
    with tab_l:
        illus.stage("log", "Log", tr("Siapa masuk dan apa yang berlaku.", "Who came in and what happened."), kick)
        log_panel()


def _default_lang_changed():
    with _lock:
        s = state()
        s["default_lang"] = st.session_state["owner_default_lang"]
        _write(STATE_FILE, s)
    _log("bahasa lalai ditukar", note=s["default_lang"])


def language_panel():
    """The language visitors see before they choose one themselves (each visitor can still flip BM / EN)."""
    st.session_state.setdefault("owner_default_lang", state()["default_lang"])
    st.segmented_control(tr("Bahasa lalai", "Default language"), list(lang.LANGS), key="owner_default_lang",
                         format_func={"ms": "Bahasa Melayu", "en": "English"}.get, required=True,
                         on_change=_default_lang_changed)
    st.caption(tr("Bahasa ini dilihat oleh pelawat yang belum memilih bahasa. Setiap orang boleh menukar sendiri "
                  "dengan suis BM / EN di bahagian atas setiap halaman.",
                  "Visitors who have not chosen a language see this one. Everyone can still change it with the "
                  "BM / EN switch at the top of every page."))


DURATIONS = {"1 hari": 1, "3 hari": 3, "1 minggu": 7, "2 minggu": 14, "1 bulan": 30, "3 bulan": 91,
             "6 bulan": 182, "1 tahun": 365}
DURATIONS_EN = dict(zip(DURATIONS, ["1 day", "3 days", "1 week", "2 weeks", "1 month", "3 months", "6 months",
                                    "1 year"]))


def duration_name(k):
    return tr(k, DURATIONS_EN[k])
WARN_DAYS = 3                                   # lecturer accounts ending within this many days are flagged


def _when(t):
    if not t:
        return "—"
    d = datetime.fromtimestamp(t)
    return d.strftime("%d/%m %H:%M" if d.year == datetime.now().year else "%d/%m/%Y")


def _ago(t):
    d = int(time.time() - t)
    if current_lang() == "en":
        return f"{d} s ago" if d < 60 else f"{d // 60} min ago" if d < 3600 else \
            f"{d // 3600} h ago" if d < 86400 else f"{d // 86400} days ago"
    return f"{d} s lalu" if d < 60 else f"{d // 60} min lalu" if d < 3600 else \
        f"{d // 3600} jam lalu" if d < 86400 else f"{d // 86400} hari lalu"


def _key_message(username, key, expires):
    if current_lang() == "en":
        return (f"Semak Pantun access\nSite: {PUBLIC_URL}\nChoose 'Log in', then enter:\n"
                f"Username: {username}\nPassword: {key}\nValid until: {_when(expires)}\n"
                "You can change the password after logging in. Do not share it with anyone.")
    return (f"Akses Semak Pantun\nLaman: {PUBLIC_URL}\nPilih 'Log masuk', kemudian masukkan:\n"
            f"Nama pengguna: {username}\nKata laluan: {key}\nSah hingga: {_when(expires)}\n"
            "Anda boleh tukar kata laluan selepas log masuk. Jangan kongsi dengan orang lain.")


def _members_toggled():
    set_members(st.session_state["owner_members_on"])


def members_panel():
    s = state()
    # The switch has a fixed key and saves only when the owner flips it (on_change). Passing the saved value as
    # `value=` instead made Streamlit treat it as a new widget after every save, so it flipped back and forth.
    st.session_state.setdefault("owner_members_on", s["members"])
    st.toggle(tr("Benarkan ahli log masuk", "Let members log in"), key="owner_members_on", on_change=_members_toggled,
              help=tr("Matikan untuk menutup akses semua ahli serta-merta (kunci mereka kekal).",
                      "Switch off to close access for all members at once (their keys stay)."))

    pending = [m for m in list_members() if m["status"] == "menunggu"]
    if pending:
        with st.container(border=True):
            st.markdown(f"**![](/app/static/i/job_senesi.png) "
                        + tr(f"Cikgu menunggu kelulusan ({len(pending)})", f"Teachers waiting for approval ({len(pending)})")
                        + "**")
            for m in pending:
                with st.container(horizontal=True, vertical_alignment="center"):
                    st.markdown(f"**{m['name']}** · `{m['username']}` · :gray[{tr('daftar', 'signed up')} {_when(m['created'])}]")
                    st.button(tr("Luluskan", "Approve"), key=f"ok_{m['username']}", icon=":material/check:", type="primary",
                              on_click=approve_teacher, args=(m["username"], True))
                    st.button(tr("Tolak", "Reject"), key=f"no_{m['username']}", icon=":material/close:", type="tertiary",
                              on_click=approve_teacher, args=(m["username"], False))
            st.caption(tr("Luluskan hanya orang yang anda kenal sebagai cikgu: mereka boleh melihat pertanyaan "
                          "murid kelas mereka dan pertanyaan tetamu.",
                          "Approve only people you know are teachers: they can see questions from their classes' "
                          "pupils and from guests."))

    lecturer_warnings()

    shown = st.session_state.get("owner_new_key")
    if shown:
        with st.container(border=True):
            st.success(tr(f"Kunci untuk **{shown['user']}**. Ia hanya dipaparkan **sekali**: salin dan hantar sekarang.",
                          f"Key for **{shown['user']}**. It is shown only **once**: copy it and send it now."),
                       icon=":material/key:")
            st.code(_key_message(shown["user"], shown["key"], shown["expires"]), language=None)
            if st.button(tr("Sudah disalin", "Copied"), icon=":material/check:"):
                st.session_state.pop("owner_new_key")
                st.rerun()

    # Students sign up themselves with a class code, so the owner only creates experts (no sign-up for them)
    # and, as a shortcut, teachers who are approved straight away.
    with st.expander("![](/app/static/i/gift.png) " + tr("Cipta akaun pakar atau cikgu", "Create an expert or teacher account"),
                     expanded=False):
        st.caption(tr("Pakar hanya boleh dicipta di sini (tiada pendaftaran sendiri). Cikgu yang dicipta di sini "
                      "terus diluluskan. Murid pula mendaftar sendiri dengan kod kelas daripada cikgu.",
                      "Experts can only be created here (they cannot sign up). Teachers created here are approved "
                      "at once. Pupils sign up themselves with a class code from their teacher."))
        with st.form("add_member", clear_on_submit=True):
            c1, c2 = st.columns(2)
            username = c1.text_input(tr("Nama pengguna", "Username"), placeholder=tr("cth. drhasiah", "e.g. drhasiah"),
                                     max_chars=24)
            name = c2.text_input(tr("Nama penuh", "Full name"), placeholder=tr("cth. Dr. Hasiah", "e.g. Dr. Hasiah"))
            role = st.selectbox(tr("Peranan", "Role"), ["penyelidik", "pensyarah"], format_func=role_name,
                                help=tr(f"{role_name('penyelidik')}: halaman {role_name('penyelidik')} + "
                                        f"{role_name('pelajar')}. {role_name('pensyarah')}: {role_name('pensyarah')} "
                                        f"+ {role_name('pelajar')}.",
                                        f"{role_name('penyelidik')}: the {role_name('penyelidik')} and "
                                        f"{role_name('pelajar')} pages. {role_name('pensyarah')}: "
                                        f"{role_name('pensyarah')} + {role_name('pelajar')}."))
            c3, c4 = st.columns(2)
            dur = c3.selectbox(tr("Sah selama", "Valid for"), list(DURATIONS), index=2, format_func=duration_name,
                               help=tr("Untuk cikgu, pilih tempoh satu penggal atau lebih (cth. 6 bulan) supaya "
                                       "kelas mereka tidak tertinggal tanpa cikgu.",
                                       "For teachers, choose a school term or longer (e.g. 6 months) so their "
                                       "classes are not left without a teacher."))
            note = c4.text_input(tr("Catatan (pilihan)", "Note (optional)"),
                                 placeholder=tr("cth. penyelia CSC575", "e.g. CSC575 supervisor"))
            if st.form_submit_button(tr("Cipta akaun dan kunci", "Create account and key"), type="primary",
                                     icon=":material/person_add:"):
                try:
                    key = add_member(username, name, DURATIONS[dur], note, role)
                    m = get_member(username.strip().lower())
                    st.session_state["owner_new_key"] = {"user": m["username"], "key": key, "expires": m["expires"]}
                    st.rerun()
                except ValueError as e:
                    st.error(str(e), icon=":material/error:")

    classes_panel()
    members_list()


def lecturer_warnings():
    """Lecturers whose account ends soon or has ended while they still have classes."""
    now, soon = time.time(), time.time() + WARN_DAYS * 86400
    teachers = {c["teacher"] for c in classes_of() if c["teacher"]}
    rows = [m for m in list_members() if m.get("role") == "pensyarah" and m["status"] == "aktif"
            and m["expires"] < soon and (m["expires"] > now or m["username"] in teachers)]
    if not rows:
        return
    with st.container(border=True):
        st.markdown("**![](/app/static/i/warning.png) " + tr(f"Akaun cikgu hampir / sudah luput ({len(rows)})",
                                                             f"Teacher accounts ending soon / ended ({len(rows)})") + "**")
        for m in rows:
            u, gone = m["username"], m["expires"] <= now
            with st.container(horizontal=True, vertical_alignment="center"):
                ends = tr("luput", "ends")
                st.markdown(f"**{m['name']}** · `{u}` · " + (f":red[{ends} {_when(m['expires'])}]" if gone else
                            f":orange[{ends} {_when(m['expires'])} ({_left(m['expires'])})]"))
                st.button(tr("+1 bulan", "+1 month"), key=f"w30_{u}", on_click=extend_member, args=(u, 30), type="tertiary")
                st.button(tr("+6 bulan", "+6 months"), key=f"w182_{u}", on_click=extend_member, args=(u, 182), type="tertiary")
                st.button(tr("+1 tahun", "+1 year"), key=f"w365_{u}", on_click=extend_member, args=(u, 365), type="tertiary")
        st.caption(tr(f"Selagi akaun luput, kelasnya tidak menerima murid baharu dan pertanyaan muridnya hanya "
                      f"dilihat oleh anda ({role_name('pensyarah')} → Semakan). Lanjutkan akaun, atau pindahkan kelas "
                      "di **![](/app/static/i/school.png) Kelas**.",
                      f"While the account has ended, its classes take no new pupils and only you see their pupils' "
                      f"questions ({role_name('pensyarah')} → Reviews). Extend the account, or move the class under "
                      "**![](/app/static/i/school.png) Classes**."))


def _left(t):
    d = t - time.time()
    if current_lang() == "en":
        return f"{int(d // 3600)} h left" if d < 86400 else f"{int(d // 86400)} days left"
    return f"{int(d // 3600)} jam lagi" if d < 86400 else f"{int(d // 86400)} hari lagi"


def _open_inquiries_by_class():
    with closing(_db()) as con:
        return {r[0]: r[1] for r in con.execute("SELECT class_code, COUNT(*) FROM inquiries WHERE kind='pelajar' "
                                                "AND status='baru' AND class_code != '' GROUP BY class_code")}


def _do_transfer(code):
    try:
        transfer_class(code, st.session_state[f"tr_{code}"])
        st.session_state["owner_transfer_msg"] = ("ok", tr(f"Kelas {code} dipindahkan.", f"Class {code} moved."))
    except ValueError as e:
        st.session_state["owner_transfer_msg"] = ("err", str(e))


def classes_panel():
    """Every class, whether its lecturer is still active, and moving a class to another lecturer."""
    classes = classes_of()
    if not classes:
        return
    orphans = [c for c in classes if not c["teacher_ok"]]
    title = f"![](/app/static/i/school.png) {tr('Kelas', 'Classes')} ({len(classes)})" + (
        f" · ![](/app/static/i/warning.png) {len(orphans)} " + tr("tanpa cikgu aktif", "without an active teacher")
        if orphans else "")
    with st.expander(title, expanded=bool(orphans)):
        msg = st.session_state.pop("owner_transfer_msg", None)
        if msg:
            (st.success if msg[0] == "ok" else st.error)(msg[1])
        st.caption(tr("Pindah kelas: murid dan semua pertanyaan kelas itu ikut berpindah kepada cikgu baharu.",
                      "Moving a class: its pupils and all its questions move to the new teacher."))
        open_q, teachers = _open_inquiries_by_class(), lecturers()
        choices = {"": tr("Pemilik (saya)", "Owner (me)"), **teachers}
        for c in classes:
            who = (c["teacher_name"] or (c["teacher"] and f"{c['teacher']} ({tr('dipadam', 'deleted')})")
                   or tr("pemilik", "owner"))
            flag = "" if c["teacher_ok"] else f" · :red-badge[{tr('cikgu tidak aktif', 'teacher not active')}]"
            n_open = open_q.get(c["code"], 0)
            with st.container(horizontal=True, vertical_alignment="center"):
                st.markdown(f"**{c['name']}** `{c['code']}` · {who}{flag}  \n:gray[{c['n_students']} "
                            + tr("murid", "pupils")
                            + (" · " + tr(f"{n_open} pertanyaan belum dijawab", f"{n_open} unanswered questions")
                               if n_open else "") + "]")
                with st.popover(tr("Pindah", "Move"), icon=":material/swap_horiz:", type="tertiary"):
                    st.selectbox(tr("Pindah kepada", "Move to"), list(choices), format_func=choices.get, key=f"tr_{c['code']}",
                                 index=list(choices).index(c["teacher"]) if c["teacher"] in choices else 0)
                    st.button(tr("Pindahkan", "Move"), key=f"trgo_{c['code']}", type="primary", on_click=_do_transfer,
                              args=(c["code"],))


@st.fragment(run_every=10)
def members_list():
    if st.session_state.pop("owner_need_rerun", False):
        st.rerun()                     # a new key was made: redraw the whole page so it shows at the top
    members, now = list_members(), time.time()
    with _lock:
        live = {k: v for k, v in _live.items() if now - v["last"] < ONLINE_FOR}
    online = {v["user"] for v in live.values()}
    with st.container(horizontal=True):
        st.metric(tr("ahli", "members"), len(members), border=True)
        st.metric(tr("aktif", "active"), sum(1 for m in members if m["status"] == "aktif" and now < m["expires"]),
                  border=True)
        st.metric(tr("dalam talian", "online"), len(online), border=True)
        st.metric(tr("log masuk (7 hari)", "logins (7 days)"), _count_logins(7), border=True)
    if not members:
        st.caption(tr("Belum ada ahli. Tambah ahli di atas, kemudian hantar kunci kepada mereka.",
                      "No members yet. Add one above, then send them their key."))
    for m in members:
        u = m["username"]
        expired = now >= m["expires"]
        status = ("![](/app/static/i/clock.png) " + tr("Menunggu kelulusan", "Waiting for approval")
                  if m["status"] == "menunggu" else
                  "![](/app/static/i/ng_mark.png) " + tr("Dibatalkan", "Revoked") if m["status"] != "aktif" else
                  "![](/app/static/i/hourglass.png) " + tr("Luput", "Ended") if expired else
                  "![](/app/static/i/ok_mark.png) " + (tr("Dalam talian", "Online") if u in online else tr("Aktif", "Active")))
        last = f"{_ago(m['last_login'])}" if m["last_login"] else tr("belum pernah", "never")
        with st.container(border=True):
            role_txt = role_name(m.get("role") or "pelajar")
            if m.get("role") == "pelajar":
                cls = ", ".join(c["code"] for c in student_classes(u))
                role_txt += (f" · {tr('kelas', 'class')} {cls}" if cls else " · " + tr("tiada kelas", "no class"))
            st.markdown(f"**{m['name']}** · `{u}` · :blue-badge[{role_txt}] · {status}  \n"
                        + tr(f":gray[Sah hingga {_when(m['expires'])} · {m['n_logins']} log masuk · terakhir {last}",
                             f":gray[Valid until {_when(m['expires'])} · {m['n_logins']} logins · last {last}")
                        + (f" · {m['note']}" if m["note"] else "") + "]")
            if m["status"] == "menunggu":
                st.caption(tr("Luluskan atau tolak di kotak **Cikgu menunggu kelulusan** di atas.",
                              "Approve or reject in the **Teachers waiting for approval** box above."))
                continue
            with st.container(horizontal=True):
                st.button(tr("+1 hari", "+1 day"), key=f"x1_{u}", on_click=extend_member, args=(u, 1), type="tertiary")
                st.button(tr("+1 minggu", "+1 week"), key=f"x7_{u}", on_click=extend_member, args=(u, 7), type="tertiary")
                st.button(tr("+1 bulan", "+1 month"), key=f"x30_{u}", on_click=extend_member, args=(u, 30), type="tertiary")
                st.button(tr("Kunci baharu", "New key"), key=f"rk_{u}", icon=":material/key:", type="tertiary",
                          on_click=_reset_and_show, args=(u,))
                st.button(tr("Log keluar peranti", "Log out devices"), key=f"so_{u}", icon=":material/logout:", type="tertiary",
                          on_click=sign_out_member, args=(u,))
                if m["status"] == "aktif":
                    st.button(tr("Batalkan", "Revoke"), key=f"rv_{u}", icon=":material/block:", type="tertiary",
                              on_click=set_member_status, args=(u, False))
                else:
                    st.button(tr("Aktifkan semula", "Reactivate"), key=f"ra_{u}", icon=":material/check_circle:", type="tertiary",
                              on_click=set_member_status, args=(u, True))
                st.button(tr("Padam", "Delete"), key=f"del_{u}", icon=":material/delete:", type="tertiary",
                          on_click=delete_member, args=(u,),
                          help=tr("Akaun dipadam; sejarah log masuk disimpan. Nama pengguna ini tidak boleh didaftar "
                                  "semula. Kelas cikgu kekal: pindahkan di Kelas.",
                                  "The account is deleted; its login history is kept. This username cannot be used "
                                  "again. A teacher's classes stay: move them under Classes."))
                with st.popover(tr("Tukar peranan", "Change role"), icon=":material/badge:", type="tertiary"):
                    new_role = st.selectbox(tr("Peranan", "Role"), list(ROLES), format_func=role_name, key=f"role_{u}",
                                            index=list(ROLES).index(m.get("role") or "pelajar"))
                    st.button(tr("Simpan", "Save"), key=f"saverole_{u}", type="primary", on_click=_save_role, args=(u,))
            if m["n_logins"]:
                with st.expander(tr(f"Sejarah log masuk ({m['n_logins']})", f"Login history ({m['n_logins']})")):
                    h = member_logins(u)
                    h["time"] = h["time"].map(_when)
                    st.dataframe(h.rename(columns=tr({"time": "masa", "country": "negara", "device": "peranti",
                                                      "how": "cara"}, {"time": "time"})), hide_index=True)


def _save_role(username):
    set_member_role(username, st.session_state[f"role_{username}"])


def _reset_and_show(username):
    key = reset_key(username)
    st.session_state["owner_new_key"] = {"user": username, "key": key, "expires": get_member(username)["expires"]}
    st.session_state["owner_need_rerun"] = True


def _count_logins(days):
    with closing(_db()) as con:
        return con.execute("SELECT COUNT(*) FROM logins WHERE time > ?", (time.time() - days * 86400,)).fetchone()[0]


def guests_panel():
    """One setting for access without an account: Tutup / Kod sahaja / Terbuka."""
    s = state()
    mode = guest_mode(s)
    with st.container(border=True):
        pupil = role_name("pelajar")
        if current_lang() == "en":
            st.markdown("**Access without an account**: who can get in without logging in? The teacher and expert "
                        "pages always need an account.")
            st.markdown(f"""
| | Who can get in without an account |
|---|---|
| ![](/app/static/i/lock.png) **Closed** | Nobody: everyone must log in, guest codes do not work |
| ![](/app/static/i/ticket.png) **Code only** | Only people you give the 30-second code to ({pupil} page) |
| ![](/app/static/i/globe.png) **Open** | Anyone, straight to the {pupil} page without a code |
""")
        else:
            st.markdown("**Akses tanpa akaun**: siapa boleh masuk tanpa log masuk? Halaman cikgu dan pakar "
                        "sentiasa perlukan akaun.")
            st.markdown(f"""
| | Siapa boleh masuk tanpa akaun |
|---|---|
| ![](/app/static/i/lock.png) **Tutup** | Tiada sesiapa: semua perlu log masuk, kod tetamu tidak berfungsi |
| ![](/app/static/i/ticket.png) **Kod sahaja** | Hanya orang yang anda beri kod 30 saat (halaman {pupil}) |
| ![](/app/static/i/globe.png) **Terbuka** | Sesiapa sahaja, terus ke halaman {pupil} tanpa kod |
""")
        if mode == "tutup":
            st.info(tr("Sekarang: **![](/app/static/i/lock.png) Tutup**. Hanya pengguna berakaun boleh masuk.",
                       "Now: **![](/app/static/i/lock.png) Closed**. Only users with an account can get in."),
                    icon=":material/lock:")
        else:
            ends = datetime.fromtimestamp(s["until"] if mode == "kod" else s["open_until"])
            st.success(tr(f"Sekarang: **{mode_name(mode)}** sehingga {ends:%H:%M} ({ends:%d/%m}).",
                          f"Now: **{mode_name(mode)}** until {ends:%H:%M} ({ends:%d/%m})."),
                       icon=":material/share:")
        with st.form("guest_mode_form", border=False):
            c1, c2 = st.columns(2)
            new_mode = c1.segmented_control(tr("Tukar kepada", "Change to"), list(GUEST_MODES), format_func=mode_name,
                                            default=mode, required=True)
            hours = c2.segmented_control(tr("Selama (untuk Kod / Terbuka)", "For (Code / Open)"), [0.5, 1, 2, 4, 8],
                                         default=1, required=True,
                                         format_func=lambda h: "30 min" if h == 0.5 else f"{h:g} " + tr("jam", "h"))
            if st.form_submit_button(tr("Simpan", "Save"), type="primary", icon=":material/save:"):
                set_guest_mode(new_mode, hours)
                st.rerun()
        st.caption(tr(f"Setiap perubahan mengunci tetamu dan pelawat sedia ada dalam masa {HEARTBEAT} saat dan memadam "
                      "pertanyaan sementara mereka. Ia kembali kepada Tutup sendiri apabila masa tamat.",
                      f"Every change locks out current guests and visitors within {HEARTBEAT} seconds and deletes "
                      "their temporary questions. It goes back to Closed by itself when the time is up."))
        if mode == "kod":
            st.button(tr("Keluarkan semua tetamu", "Remove all guests"), icon=":material/group_remove:", on_click=kick_all,
                      help=tr("Semua tetamu perlu memasukkan kod baharu. Mod Kod sahaja kekal.",
                              "Every guest must enter a new code. Code-only mode stays on."))
    if mode == "kod":
        live_code()
        guest_devices()


@st.fragment(run_every=1)
def live_code():
    s = state()
    if not s["enabled"]:
        st.rerun()
    now = time.time()
    left = PERIOD - (now % PERIOD)
    code = code_at(s["secret"], now)
    deg = 360 * left / PERIOD
    grace = (tr(f"kod sebelumnya masih diterima {PERIOD * GRACE_STEPS} saat lagi",
                f"the previous code still works for {PERIOD * GRACE_STEPS} more seconds") if GRACE_STEPS
             else tr("hanya kod semasa diterima", "only the current code works"))
    give = tr(f"Berikan kod ini kepada tetamu. Ia bertukar setiap {PERIOD} saat ({grace}).",
              f"Give this code to your guests. It changes every {PERIOD} seconds ({grace}).")
    st.html(f"""
<div style="display:flex;align-items:center;gap:22px;justify-content:center;margin:18px 0 6px;font-family:'Nunito',sans-serif">
  <div style="font:800 3.4rem 'JetBrains Mono',monospace;letter-spacing:.18em;color:#0C525C">{code[:3]}&nbsp;{code[3:]}</div>
  <div role="img" aria-label="{int(left)} s" style="width:62px;height:62px;border-radius:50%;
       background:conic-gradient(#DEB251 {deg:.0f}deg,#E6E1D6 0);display:flex;align-items:center;justify-content:center">
    <div style="width:46px;height:46px;border-radius:50%;background:#FBF7EE;display:flex;align-items:center;
         justify-content:center;font-weight:800;color:#1F2A2E">{int(left)}s</div>
  </div>
</div>
<div style="text-align:center;color:#5b6670;font-size:.95rem">{give}</div>""")


@st.fragment(run_every=5)
def guest_devices():
    s = state()
    if not s["enabled"]:
        return
    reg = _registry(s["round"])
    now = time.time()
    with _lock:
        devices = sorted(reg["devices"].values(), key=lambda d: -d["first"])
        blocked = sorted(reg["blocked"])
    _, guests = _fail_counts(None)
    online = [d for d in devices if d["status"] == "aktif" and now - d.get("last", 0) < ONLINE_FOR]

    st.subheader(tr("Peranti tetamu", "Guest devices"), anchor=False)
    with st.container(horizontal=True):
        st.metric(tr("dalam talian sekarang", "online now"), len(online), border=True)
        st.metric(tr("peranti pusingan ini", "devices this round"), len(devices), border=True)
        st.metric(tr("kod salah (1 jam)", "wrong codes (1 hour)"), guests, border=True,
                  help=tr(f"Pada {ALL_FAILS}, kod tetamu dijeda. Mulakan semula kod tetamu untuk set semula.",
                          f"At {ALL_FAILS}, guest codes pause. Restart guest codes to reset."))
        st.metric(tr("IP disekat", "blocked IPs"), len(blocked), border=True)
    if guests >= ALL_FAILS:
        st.warning(tr("Terlalu banyak kod salah: kod tetamu dijeda. Seseorang mungkin cuba meneka. Matikan dan "
                      "hidupkan semula kod tetamu untuk set semula.",
                      "Too many wrong codes: guest codes are paused. Someone may be guessing. Switch guest codes "
                      "off and on again to reset."), icon=":material/warning:")
    if not devices:
        st.caption(tr("Belum ada tetamu masuk dalam pusingan ini.", "No guests have come in this round yet."))
    for d in devices:
        is_online = d["status"] == "aktif" and now - d.get("last", 0) < ONLINE_FOR
        status = {"aktif": "![](/app/static/i/ok_mark.png) " + tr("Dalam talian", "Online") if is_online
                  else "![](/app/static/i/moon.png) " + tr("Tidak aktif", "Idle"),
                  "dikeluarkan": "![](/app/static/i/ng_mark.png) " + tr("Dikeluarkan", "Removed"),
                  "disekat": "![](/app/static/i/ng_mark.png) " + tr("Disekat", "Blocked")}[d["status"]]
        until = (" · " + tr("diingati hingga", "remembered until") + f" {_when(d['until'])}"
                 if d["status"] == "aktif" and d.get("until") else "")
        with st.container(border=True, horizontal=True, vertical_alignment="center"):
            st.markdown(f"**{d['name']}**  \n{d['device']} · `{d['ip']}` · {d['country']}  \n"
                        + tr(f":gray[Masuk {_when(d['first'])} · aktif {_ago(d.get('last', d['first']))}"
                             f" · {d.get('visits', 1)} lawatan",
                             f":gray[Came in {_when(d['first'])} · active {_ago(d.get('last', d['first']))}"
                             f" · {d.get('visits', 1)} visits")
                        + f"{until} · {status}]")
            if d["status"] == "aktif":
                st.button(tr("Keluarkan", "Remove"), key=f"kick_{d['id']}", icon=":material/logout:", width="content",
                          on_click=remove_device, args=(d["id"],))
                st.button(tr("Sekat IP", "Block IP"), key=f"block_{d['id']}", icon=":material/block:", width="content",
                          on_click=remove_device, args=(d["id"], True))
    for ip in blocked:
        with st.container(horizontal=True, vertical_alignment="center"):
            st.markdown(f"![](/app/static/i/ng_mark.png) `{ip}` " + tr("disekat untuk pusingan ini", "blocked for this round"))
            st.button(tr("Buka sekatan", "Unblock"), key=f"unblock_{ip}", type="tertiary", on_click=unblock_ip, args=(ip,))


def log_panel():
    with closing(_db()) as con:
        df = pd.read_sql("SELECT time, event, who, ip, country, device, note FROM events ORDER BY time DESC LIMIT 300",
                         con)
    if df.empty:
        st.caption(tr("Belum ada peristiwa.", "Nothing has happened yet."))
        return
    df["time"] = df["time"].map(_when)
    st.caption(tr("Log ditulis dalam Bahasa Melayu.", "The log is written in Malay."))
    st.dataframe(df.rename(columns=tr({"time": "masa", "event": "peristiwa", "who": "siapa", "country": "negara",
                                       "device": "peranti", "note": "catatan"}, {})), hide_index=True)
    st.download_button(tr("Muat turun semua log (CSV)", "Download the whole log (CSV)"), events_csv(), file_name="share_log.csv",
                       icon=":material/download:", type="tertiary")
