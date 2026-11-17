"""Sharing the app online: member accounts, a guest code that changes every 30 s, and a device monitor.

Full explanation and rebuild guide: docs/sharing_guide.md.

Who can get in (visitors come through the Cloudflare tunnel; their requests carry Cloudflare headers):
  - MEMBERS (Ahli): the owner creates an account on the Kongsi page and gives the person a personal key that is
    valid for a chosen time (1 day, 1 week, ...). They log in with username + key; the browser is remembered for
    up to 24 hours (never past the key's end). Every login is kept in a permanent history. The owner can extend,
    reset the key, sign out all devices, or revoke the account at any time.
  - GUESTS (Tetamu): while the owner has switched guest sharing ON, anyone with the current 6-digit code
    (TOTP, RFC 6238, 30-second step, as in Google Authenticator) gets in; the browser is remembered for 2 hours. Each "round" of sharing
    starts fresh, and the owner can remove a guest device or block its IP address.
  - On this computer (the owner) the app opens as normal and has the extra "Kongsi" page.

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

from src import illus
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


GUEST_MODES = {"tutup": "🔒 Tutup", "kod": "🎟️ Kod sahaja", "terbuka": "🌐 Terbuka"}


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


ROLES = {"pelajar": "Pelajar", "pensyarah": "Pensyarah", "penyelidik": "Penyelidik / Pakar"}
# Which views each kind of user may open (page url names). The owner (this computer) sees everything.
# Teachers may also switch to the expert view ("mod pakar").
ROLE_VIEWS = {"owner": ["pelajar", "pensyarah", "penyelidik"], "pelajar": ["pelajar"],
              "pensyarah": ["pensyarah", "penyelidik", "pelajar"], "penyelidik": ["penyelidik", "pelajar"],
              "guest": ["pelajar"]}
PASSWORD_MIN = 8
SIGNUPS_PER_IP, SIGNUP_WINDOW = 5, 3600      # at most 5 new accounts per IP address per hour
GUEST_INQUIRY_TTL = 24 * 3600                 # guest / open-mode inquiries are deleted after 24 h at most
SELF_SIGNUP_DAYS = 365                        # self-made accounts last a year (owner can shorten or revoke)
_signups: list = []


def _check_username(username):
    username = str(username).strip().lower()
    if not USERNAME_RE.match(username):
        raise ValueError("Nama pengguna: 3–24 aksara, huruf kecil, nombor, titik, sengkang atau garis bawah.")
    return username


def add_member(username, name, days, note="", role="pelajar", lecturer=""):
    """Owner creates an account. Returns the new key (shown once; only its hash is stored)."""
    username = _check_username(username)
    if role not in ROLES:
        raise ValueError("Peranan tidak sah.")
    key, salt = new_key(), secrets.token_hex(16)
    try:
        with _lock, closing(_db()) as con, con:
            con.execute("INSERT INTO members(username, name, note, key_hash, key_salt, created, expires, role, cred) "
                        "VALUES (?,?,?,?,?,?,?,?,'key')",
                        (username, name.strip() or username, note.strip(), _hash_key(key, salt), salt, time.time(),
                         time.time() + days * 86400, role))
    except sqlite3.IntegrityError:
        raise ValueError(f"Nama pengguna '{username}' sudah wujud.") from None
    _log("ahli: dicipta", username, note=f"{ROLES[role]}, {days:g} hari")
    return key


def sign_up(name, username, password, password2, role, class_code, ip):
    """Self sign-up from the login screen. Students join with a class code and can log in at once;
    teachers wait for the owner's approval. Returns the new member's status ('aktif' or 'menunggu')."""
    username = _check_username(username)
    name = str(name).strip()
    if not name:
        raise ValueError("Isi nama penuh anda.")
    if len(password) < PASSWORD_MIN:
        raise ValueError(f"Kata laluan sekurang-kurangnya {PASSWORD_MIN} aksara.")
    if password != password2:
        raise ValueError("Kedua-dua kata laluan tidak sama.")
    if password.lower() == username:
        raise ValueError("Kata laluan tidak boleh sama dengan nama pengguna.")
    if role not in ("pelajar", "pensyarah"):
        raise ValueError("Pilih Pelajar atau Pensyarah.")
    cls = get_class(class_code) if role == "pelajar" else None
    if role == "pelajar" and (not cls or not cls["active"]):
        raise ValueError("Kod kelas tidak sah. Minta kod daripada pensyarah anda.")
    now = time.time()
    with _lock:
        _signups[:] = [(t, a) for t, a in _signups if now - t < SIGNUP_WINDOW]
        if sum(1 for _, a in _signups if a == ip) >= SIGNUPS_PER_IP:
            raise ValueError("Terlalu banyak pendaftaran dari rangkaian ini. Cuba lagi dalam sejam.")
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
        raise ValueError(f"Nama pengguna '{username}' sudah digunakan. Pilih yang lain.") from None
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
        raise ValueError(f"Kata laluan baharu sekurang-kurangnya {PASSWORD_MIN} aksara.")
    if new != new2:
        raise ValueError("Kedua-dua kata laluan baharu tidak sama.")
    if authenticate(username, old)[0] != "ok":
        raise ValueError("Kata laluan semasa salah.")
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
    """{username: name} of active lecturer members."""
    with closing(_db()) as con:
        return {r["username"]: r["name"] for r in
                con.execute("SELECT username, name FROM members WHERE role='pensyarah' AND status='aktif' ORDER BY name")}


# ---- Classes (teachers make them; students join with the code) ------------------------------------

def _new_class_code():
    return "".join(secrets.choice(KEY_ALPHABET) for _ in range(6))      # e.g. K7QM2X


def create_class(teacher, name):
    name = str(name).strip()
    if not name:
        raise ValueError("Isi nama kelas, contohnya 'BM2 · Pantun Nasihat'.")
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
    raise ValueError("Tidak dapat membuat kod kelas. Cuba lagi.")


def get_class(code):
    code = re.sub(r"[^A-Z0-9]", "", str(code).upper())
    with closing(_db()) as con:
        r = con.execute("SELECT * FROM classes WHERE code=?", (code,)).fetchone()
    return dict(r) if r else None


def classes_of(teacher=None):
    """A teacher's classes with student counts (teacher=None: every class, for the owner)."""
    q = ("SELECT c.*, COUNT(cm.username) AS n_students, m.name AS teacher_name FROM classes c "
         "LEFT JOIN class_members cm ON cm.code = c.code LEFT JOIN members m ON m.username = c.teacher "
         + ("WHERE c.teacher = ? " if teacher is not None else "") + "GROUP BY c.code ORDER BY c.created DESC")
    with closing(_db()) as con:
        return [dict(r) for r in con.execute(q, (teacher,) if teacher is not None else ())]


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


def join_class(username, code):
    cls = get_class(code)
    if not cls or not cls["active"]:
        raise ValueError("Kod kelas tidak sah atau kelas sudah ditutup.")
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
        raise ValueError("Anda tidak dibenarkan menyemak pertanyaan ini.")
    with _lock, closing(_db()) as con, con:
        con.execute("UPDATE inquiries SET status='selesai', handled_by=?, reply=? WHERE id=?",
                    (user["username"] or "pemilik", reply.strip(), int(inquiry_id)))
    _log("pertanyaan: selesai", user["username"] or "pemilik", note=str(inquiry_id))


def current_user():
    """Who is using this session: {'kind': owner|member|guest|public, 'role', 'username', 'name'}."""
    if not is_visitor():
        return {"kind": "owner", "role": "owner", "username": "", "name": "Pemilik", "lecturer": ""}
    kind = st.session_state.get("share_kind")
    if kind == "member":
        m = get_member(st.session_state.get("share_user")) or {}
        return {"kind": "member", "role": m.get("role", "pelajar"), "username": m.get("username", ""),
                "name": m.get("name", ""), "lecturer": ""}
    if kind == "public":
        return {"kind": "public", "role": "guest", "username": "", "name": "Pelawat", "lecturer": ""}
    dev = _reg["devices"].get(st.session_state.get("share_did"), {})
    return {"kind": "guest", "role": "guest", "username": "", "name": dev.get("name", "Tetamu"), "lecturer": ""}


def allowed_views():
    return ROLE_VIEWS.get(current_user()["role"], ["pelajar"])


def require_view(view):
    """Stop a page that this user may not open (the menu already hides it; this also guards direct links)."""
    if view not in allowed_views():
        st.warning("Halaman ini hanya untuk pengguna yang dibenarkan.", icon=":material/lock:")
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


def user_bar():
    """Small 'name · role · Log keluar' row for visitors, shown above every page."""
    if not is_visitor():
        return
    u = current_user()
    with st.container(horizontal=True, horizontal_alignment="right", vertical_alignment="center", key="cz_userbar"):
        if u["kind"] == "public":
            st.caption("👤 **Pelawat** · tanpa log masuk")
            st.button("Log masuk / Daftar", icon=":material/login:", type="tertiary", on_click=_want_login,
                      key="cz_login")
            return
        st.caption(f"👤 **{u['name']}** · {ROLES.get(u['role'], 'Tetamu')}")
        if u["kind"] == "member":
            with st.popover("Tukar kata laluan", icon=":material/password:", type="tertiary"):
                with st.form("cz_pw", border=False, clear_on_submit=True):
                    old = st.text_input("Kata laluan / kunci semasa", type="password")
                    new = st.text_input("Kata laluan baharu", type="password")
                    new2 = st.text_input("Ulang kata laluan baharu", type="password")
                    if st.form_submit_button("Simpan", type="primary"):
                        try:
                            change_password(u["username"], old, new, new2)
                            st.success("Kata laluan ditukar. Peranti lain akan dilog keluar.")
                        except ValueError as e:
                            st.error(str(e))
        st.button("Log keluar", icon=":material/logout:", type="tertiary", on_click=sign_out, key="cz_logout")


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
    with _lock, closing(_db()) as con, con:
        con.execute("DELETE FROM members WHERE username=?", (username,))
    _log("ahli: dipadam", username, note="sejarah log masuk disimpan")


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
.st-key-share_gate { max-width: 460px; margin: 0 auto; }
.st-key-share_gate input[maxlength="6"] { text-align: center; font-size: 1.9rem !important; letter-spacing: .5em;
  font-family: 'JetBrains Mono', monospace !important; }
.st-key-share_gate input[maxlength="14"] { font-family: 'JetBrains Mono', monospace !important; letter-spacing: .12em; }
.st-key-share_gate [data-testid="InputInstructions"] { display: none; }
</style>"""


def _screen(title, malay, english, pic="", anim="wiggle"):
    """Centre screen for visitors. `pic` is an Irasutoya picture (src/illus.py); without it, the gold logo dot."""
    art = illus.img(pic, 120, "margin:0 auto 10px", anim) if pic else ""
    st.html(_GATE_CSS + f"""<div class="cz-gate">{art or '<div class="logo"></div>'}<h1>{title}</h1><p>{malay}</p>
        <p style="font-size:.92rem;color:#6b7478">{english}</p></div>""")


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
            _screen("Akses disekat", "Pemilik telah menyekat peranti ini.", "The owner has blocked this device.",
                    "box_kara_hako", "pop")
        else:
            _screen("Akses ditarik balik", "Akses anda telah ditamatkan oleh pemilik atau telah luput.",
                    "Your access was ended by the owner or has expired.", "box_kara_hako", "pop")
        st.stop()

    if not s["members"] and not s["enabled"] and not s.get("open"):
        _screen("Perkongsian ditutup",
                "Pemilik belum membuka akses ke Semak Pantun. Minta mereka hidupkan perkongsian.",
                "Sharing is closed. Ask the owner to switch it on.", "yashinoki", "float")
        st.stop()

    _screen("Semak Pantun", "Log masuk dengan akaun anda, daftar akaun baharu, atau masuk dengan kod tetamu.",
            "Log in, sign up (students need a class code from their teacher), or use a guest code.",
            "key", "wiggle")
    with st.container(key="share_gate"):
        if s.get("open"):
            st.button("← Teruskan tanpa log masuk", type="tertiary", key="cz_back_open",
                      on_click=lambda: st.session_state.pop("cz_want_login", None))
        tabs = (["👤 Log masuk", "📝 Daftar"] if s["members"] else []) + (["🎟️ Tetamu (kod)"] if s["enabled"] else [])
        forms = {"👤 Log masuk": _member_form, "📝 Daftar": _signup_form, "🎟️ Tetamu (kod)": _guest_form}
        for tab, label in zip(st.tabs(tabs), tabs):
            with tab:
                forms[label](s, me)
    st.stop()


def _signup_form(s, me):
    illus.show("study_woman_normal", 110, "float")
    with st.form("signup_form", border=False, clear_on_submit=False):
        role = st.radio("Saya seorang", ["pelajar", "pensyarah"], horizontal=True,
                        format_func={"pelajar": "🎒 Pelajar", "pensyarah": "🧑‍🏫 Pensyarah"}.get)
        name = st.text_input("Nama penuh", max_chars=60)
        user = st.text_input("Nama pengguna", max_chars=24, placeholder="huruf kecil, cth. aina.r")
        pw = st.text_input("Kata laluan", type="password", placeholder=f"sekurang-kurangnya {PASSWORD_MIN} aksara")
        pw2 = st.text_input("Ulang kata laluan", type="password")
        code = st.text_input("Kod kelas (pelajar sahaja)", max_chars=8, placeholder="daripada pensyarah, cth. K7QM2X")
        st.caption("Pensyarah: akaun anda aktif selepas diluluskan oleh pemilik. Pelajar: terus boleh log masuk.")
        go = st.form_submit_button("Daftar", type="primary", icon=":material/person_add:", width="stretch")
    if go:
        try:
            status = sign_up(name, user, pw, pw2, role, code, me["ip"])
        except ValueError as e:
            st.error(str(e), icon=":material/error:")
            return
        first = html.escape(str(name).strip().split(" ")[0]) or "anda"
        if status == "aktif":
            illus.celebrate("Tahniah! 🎉", f"Selamat datang ke Semak Pantun, <b>{first}</b>! Akaun pelajar anda sudah "
                                         "sedia. Log masuk dan mula menyemak pantun.")
            st.success("Akaun dicipta! Sila log masuk di tab **Log masuk**.", icon=":material/check_circle:")
        else:
            illus.celebrate("Tahniah! 🎉", f"Terima kasih, <b>{first}</b>! Akaun pensyarah anda sudah didaftarkan dan "
                                         "akan aktif sebaik sahaja diluluskan oleh pemilik.", "job_senesi")
            st.info("Akaun pensyarah dicipta dan **menunggu kelulusan pemilik**. Cuba log masuk selepas diluluskan.",
                    icon=":material/hourglass_top:")


def _member_form(s, me):
    with st.form("member_form", border=False):
        user = st.text_input("Nama pengguna", max_chars=24, placeholder="nama pengguna")
        key = st.text_input("Kata laluan atau kunci", type="password")
        remember = st.checkbox("Ingat peranti ini (sehingga 24 jam)", value=True)
        go = st.form_submit_button("Log masuk", type="primary", icon=":material/login:", width="stretch")
    if go:
        if _fail_counts(me["ip"])[0] >= IP_FAILS:
            st.error("Terlalu banyak cubaan salah dari rangkaian ini. Cuba lagi dalam 10 minit.", icon=":material/timer:")
            return
        verdict, m = authenticate(user, key)
        if verdict == "pending":
            st.info("Akaun pensyarah anda masih **menunggu kelulusan** pemilik.", icon=":material/hourglass_top:")
            return
        if not m:
            _fail(me["ip"], "member")
            _log("ahli: log masuk gagal", str(user).strip().lower()[:24], me["ip"], me["country"], me["device"])
            st.error("Nama pengguna atau kata laluan salah, atau akaun sudah luput.", icon=":material/error:")
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
        name = st.text_input("Nama anda", max_chars=40, placeholder="Nama anda (supaya pemilik kenal)")
        code = st.text_input("Kod", max_chars=DIGITS, placeholder="••••••", label_visibility="collapsed")
        remember = st.checkbox("Ingat peranti ini selama 2 jam", value=True)
        go = st.form_submit_button("Masuk", type="primary", icon=":material/lock_open:", width="stretch")
    if go:
        mine, guests = _fail_counts(me["ip"])
        name = name.strip() or "(tiada nama)"
        reg = _registry(s["round"])
        if me["ip"] in reg["blocked"]:
            st.error("Peranti ini disekat oleh pemilik.", icon=":material/block:")
        elif guests >= ALL_FAILS:
            st.error("Kod tetamu dijeda kerana terlalu banyak kod salah. Minta pemilik memulakan semula.",
                     icon=":material/pause_circle:")
        elif mine >= IP_FAILS:
            st.error("Terlalu banyak cubaan salah dari rangkaian ini. Cuba lagi dalam 10 minit.", icon=":material/timer:")
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
            st.error("Kod tidak sah atau sudah tamat. Minta kod baharu.", icon=":material/error:")


@st.fragment(run_every=HEARTBEAT)
def _watch():
    """Heartbeat from an open visitor page: marks it online, and locks it as soon as access ends."""
    if _session_ok(state(), _client()) != "ok":
        _lock_out()
        st.rerun()


# ---- Owner page ----------------------------------------------------------------------------------

def owner_page():
    """'Kongsi' page (owner only): members, guest sharing with the live code, and the event log."""
    st.title("Kongsi Semak Pantun", anchor=False)
    st.caption(f"Alamat awam: {PUBLIC_URL} · jalankan Start Sharing.bat supaya alamat ini hidup")
    tab_m, tab_g, tab_l = st.tabs(["👤 Ahli", "🌐 Akses tanpa akaun", "📜 Log"])
    with tab_m:
        members_panel()
    with tab_g:
        guests_panel()
    with tab_l:
        log_panel()


DURATIONS = {"1 hari": 1, "3 hari": 3, "1 minggu": 7, "2 minggu": 14, "1 bulan": 30}


def _when(t):
    if not t:
        return "—"
    d = datetime.fromtimestamp(t)
    return d.strftime("%d/%m %H:%M" if d.year == datetime.now().year else "%d/%m/%Y")


def _ago(t):
    d = int(time.time() - t)
    return f"{d} s lalu" if d < 60 else f"{d // 60} min lalu" if d < 3600 else \
        f"{d // 3600} jam lalu" if d < 86400 else f"{d // 86400} hari lalu"


def _key_message(username, key, expires):
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
    st.toggle("Benarkan ahli log masuk", key="owner_members_on", on_change=_members_toggled,
              help="Matikan untuk menutup akses semua ahli serta-merta (kunci mereka kekal).")

    pending = [m for m in list_members() if m["status"] == "menunggu"]
    if pending:
        with st.container(border=True):
            st.markdown(f"**🧑‍🏫 Pensyarah menunggu kelulusan ({len(pending)})**")
            for m in pending:
                with st.container(horizontal=True, vertical_alignment="center"):
                    st.markdown(f"**{m['name']}** · `{m['username']}` · :gray[daftar {_when(m['created'])}]")
                    st.button("Luluskan", key=f"ok_{m['username']}", icon=":material/check:", type="primary",
                              on_click=approve_teacher, args=(m["username"], True))
                    st.button("Tolak", key=f"no_{m['username']}", icon=":material/close:", type="tertiary",
                              on_click=approve_teacher, args=(m["username"], False))
            st.caption("Luluskan hanya orang yang anda kenal sebagai pensyarah: mereka boleh melihat pertanyaan "
                       "pelajar kelas mereka dan pertanyaan tetamu.")

    shown = st.session_state.get("owner_new_key")
    if shown:
        with st.container(border=True):
            st.success(f"Kunci untuk **{shown['user']}**. Ia hanya dipaparkan **sekali**: salin dan hantar sekarang.",
                       icon=":material/key:")
            st.code(_key_message(shown["user"], shown["key"], shown["expires"]), language=None)
            if st.button("Sudah disalin", icon=":material/check:"):
                st.session_state.pop("owner_new_key")
                st.rerun()

    # Students sign up themselves with a class code, so the owner only creates experts (no sign-up for them)
    # and, as a shortcut, teachers who are approved straight away.
    with st.expander("➕ Cipta akaun pakar atau pensyarah", expanded=False):
        st.caption("Pakar hanya boleh dicipta di sini (tiada pendaftaran sendiri). Pensyarah yang dicipta di sini "
                   "terus diluluskan. Pelajar pula mendaftar sendiri dengan kod kelas daripada pensyarah.")
        with st.form("add_member", clear_on_submit=True):
            c1, c2 = st.columns(2)
            username = c1.text_input("Nama pengguna", placeholder="cth. drhasiah", max_chars=24)
            name = c2.text_input("Nama penuh", placeholder="cth. Dr. Hasiah")
            role = st.selectbox("Peranan", ["penyelidik", "pensyarah"], format_func=ROLES.get,
                                help="Penyelidik / Pakar: Penyelidik + Pelajar. "
                                     "Pensyarah: Pensyarah + mod pakar + Pelajar.")
            c3, c4 = st.columns(2)
            dur = c3.selectbox("Sah selama", list(DURATIONS), index=2)
            note = c4.text_input("Catatan (pilihan)", placeholder="cth. penyelia CSC575")
            if st.form_submit_button("Cipta akaun dan kunci", type="primary", icon=":material/person_add:"):
                try:
                    key = add_member(username, name, DURATIONS[dur], note, role)
                    m = get_member(username.strip().lower())
                    st.session_state["owner_new_key"] = {"user": m["username"], "key": key, "expires": m["expires"]}
                    st.rerun()
                except ValueError as e:
                    st.error(str(e), icon=":material/error:")

    members_list()


@st.fragment(run_every=10)
def members_list():
    if st.session_state.pop("owner_need_rerun", False):
        st.rerun()                     # a new key was made: redraw the whole page so it shows at the top
    members, now = list_members(), time.time()
    with _lock:
        live = {k: v for k, v in _live.items() if now - v["last"] < ONLINE_FOR}
    online = {v["user"] for v in live.values()}
    with st.container(horizontal=True):
        st.metric("ahli", len(members), border=True)
        st.metric("aktif", sum(1 for m in members if m["status"] == "aktif" and now < m["expires"]), border=True)
        st.metric("dalam talian", len(online), border=True)
        st.metric("log masuk (7 hari)", _count_logins(7), border=True)
    if not members:
        st.caption("Belum ada ahli. Tambah ahli di atas, kemudian hantar kunci kepada mereka.")
    for m in members:
        u = m["username"]
        expired = now >= m["expires"]
        status = ("🕓 Menunggu kelulusan" if m["status"] == "menunggu" else "⛔ Dibatalkan" if m["status"] != "aktif"
                  else "⏳ Luput" if expired else "🟢 Dalam talian" if u in online else "✅ Aktif")
        last = f"{_ago(m['last_login'])}" if m["last_login"] else "belum pernah"
        with st.container(border=True):
            role_txt = ROLES.get(m.get("role", "pelajar"), "Pelajar")
            if m.get("role") == "pelajar":
                cls = ", ".join(c["code"] for c in student_classes(u))
                role_txt += f" · kelas {cls}" if cls else " · tiada kelas"
            st.markdown(f"**{m['name']}** · `{u}` · :blue-badge[{role_txt}] · {status}  \n"
                        f":gray[Sah hingga {_when(m['expires'])} · {m['n_logins']} log masuk · terakhir {last}"
                        + (f" · {m['note']}" if m["note"] else "") + "]")
            if m["status"] == "menunggu":
                st.caption("Luluskan atau tolak di kotak **Pensyarah menunggu kelulusan** di atas.")
                continue
            with st.container(horizontal=True):
                st.button("+1 hari", key=f"x1_{u}", on_click=extend_member, args=(u, 1), type="tertiary")
                st.button("+1 minggu", key=f"x7_{u}", on_click=extend_member, args=(u, 7), type="tertiary")
                st.button("Kunci baharu", key=f"rk_{u}", icon=":material/key:", type="tertiary",
                          on_click=_reset_and_show, args=(u,))
                st.button("Log keluar peranti", key=f"so_{u}", icon=":material/logout:", type="tertiary",
                          on_click=sign_out_member, args=(u,))
                if m["status"] == "aktif":
                    st.button("Batalkan", key=f"rv_{u}", icon=":material/block:", type="tertiary",
                              on_click=set_member_status, args=(u, False))
                else:
                    st.button("Aktifkan semula", key=f"ra_{u}", icon=":material/check_circle:", type="tertiary",
                              on_click=set_member_status, args=(u, True))
                st.button("Padam", key=f"del_{u}", icon=":material/delete:", type="tertiary",
                          on_click=delete_member, args=(u,), help="Akaun dipadam; sejarah log masuk disimpan.")
                with st.popover("Tukar peranan", icon=":material/badge:", type="tertiary"):
                    new_role = st.selectbox("Peranan", list(ROLES), format_func=ROLES.get, key=f"role_{u}",
                                            index=list(ROLES).index(m.get("role") or "pelajar"))
                    st.button("Simpan", key=f"saverole_{u}", type="primary", on_click=_save_role, args=(u,))
            if m["n_logins"]:
                with st.expander(f"Sejarah log masuk ({m['n_logins']})"):
                    h = member_logins(u)
                    h["time"] = h["time"].map(_when)
                    st.dataframe(h.rename(columns={"time": "masa", "country": "negara", "device": "peranti",
                                                   "how": "cara"}), hide_index=True)


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
        st.markdown("**Akses tanpa akaun**: siapa boleh masuk tanpa log masuk? Halaman pensyarah dan pakar "
                    "sentiasa perlukan akaun.")
        st.markdown("""
| | Siapa boleh masuk tanpa akaun |
|---|---|
| 🔒 **Tutup** | Tiada sesiapa: semua perlu log masuk, kod tetamu tidak berfungsi |
| 🎟️ **Kod sahaja** | Hanya orang yang anda beri kod 30 saat (halaman Pelajar) |
| 🌐 **Terbuka** | Sesiapa sahaja, terus ke halaman Pelajar tanpa kod |
""")
        if mode == "tutup":
            st.info("Sekarang: **🔒 Tutup**. Hanya pengguna berakaun boleh masuk.", icon=":material/lock:")
        else:
            ends = datetime.fromtimestamp(s["until"] if mode == "kod" else s["open_until"])
            st.success(f"Sekarang: **{GUEST_MODES[mode]}** sehingga {ends:%H:%M} ({ends:%d/%m}).",
                       icon=":material/share:")
        with st.form("guest_mode_form", border=False):
            c1, c2 = st.columns(2)
            new_mode = c1.segmented_control("Tukar kepada", list(GUEST_MODES), format_func=GUEST_MODES.get,
                                            default=mode, required=True)
            hours = c2.segmented_control("Selama (untuk Kod / Terbuka)", [0.5, 1, 2, 4, 8], default=1,
                                         required=True, format_func=lambda h: "30 min" if h == 0.5 else f"{h:g} jam")
            if st.form_submit_button("Simpan", type="primary", icon=":material/save:"):
                set_guest_mode(new_mode, hours)
                st.rerun()
        st.caption(f"Setiap perubahan mengunci tetamu dan pelawat sedia ada dalam masa {HEARTBEAT} saat dan memadam "
                   "pertanyaan sementara mereka. Ia kembali kepada Tutup sendiri apabila masa tamat.")
        if mode == "kod":
            st.button("Keluarkan semua tetamu", icon=":material/group_remove:", on_click=kick_all,
                      help="Semua tetamu perlu memasukkan kod baharu. Mod Kod sahaja kekal.")
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
<div style="text-align:center;color:#5b6670;font-size:.95rem">Berikan kod ini kepada tetamu. Ia bertukar setiap {PERIOD} saat ({grace}).</div>""")


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

    st.subheader("Peranti tetamu", anchor=False)
    with st.container(horizontal=True):
        st.metric("dalam talian sekarang", len(online), border=True)
        st.metric("peranti pusingan ini", len(devices), border=True)
        st.metric("kod salah (1 jam)", guests, border=True,
                  help=f"Pada {ALL_FAILS}, kod tetamu dijeda. Mulakan semula kod tetamu untuk set semula.")
        st.metric("IP disekat", len(blocked), border=True)
    if guests >= ALL_FAILS:
        st.warning("Terlalu banyak kod salah: kod tetamu dijeda. Seseorang mungkin cuba meneka. Matikan dan "
                   "hidupkan semula kod tetamu untuk set semula.", icon=":material/warning:")
    if not devices:
        st.caption("Belum ada tetamu masuk dalam pusingan ini.")
    for d in devices:
        is_online = d["status"] == "aktif" and now - d.get("last", 0) < ONLINE_FOR
        status = {"aktif": "🟢 Dalam talian" if is_online else "⚪ Tidak aktif",
                  "dikeluarkan": "⛔ Dikeluarkan", "disekat": "🚫 Disekat"}[d["status"]]
        until = f" · diingati hingga {_when(d['until'])}" if d["status"] == "aktif" and d.get("until") else ""
        with st.container(border=True, horizontal=True, vertical_alignment="center"):
            st.markdown(f"**{d['name']}**  \n{d['device']} · `{d['ip']}` · {d['country']}  \n"
                        f":gray[Masuk {_when(d['first'])} · aktif {_ago(d.get('last', d['first']))}"
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


def log_panel():
    with closing(_db()) as con:
        df = pd.read_sql("SELECT time, event, who, ip, country, device, note FROM events ORDER BY time DESC LIMIT 300",
                         con)
    if df.empty:
        st.caption("Belum ada peristiwa.")
        return
    df["time"] = df["time"].map(_when)
    st.dataframe(df.rename(columns={"time": "masa", "event": "peristiwa", "who": "siapa", "country": "negara",
                                    "device": "peranti", "note": "catatan"}), hide_index=True)
    st.download_button("Muat turun semua log (CSV)", events_csv(), file_name="share_log.csv",
                       icon=":material/download:", type="tertiary")
