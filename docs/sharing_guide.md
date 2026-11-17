# Sharing a local app safely with a rotating code: the full guide (0 → 100)

This guide explains, from the ground up, how **Semak Pantun** is put online at `https://pantun.aimanjamal.com`
while it keeps running on your own PC, and how the **6-digit code that changes every 15 seconds** decides who
may get in. It covers the theory (networking, DNS, tunnels, one-time-password maths, security), the design
choices in this project, and a step-by-step recipe to rebuild the whole thing yourself in a new project.

Files this guide talks about:

| File | What it is |
|---|---|
| `src/share.py` | The code gate, the share switch, the device monitor and the access log |
| `app.py` | Calls `gate()` before any page runs; adds the owner-only **Kongsi** page |
| `Start Sharing.bat` | Starts the Cloudflare Tunnel |
| `%USERPROFILE%\.cloudflared\pantun.yml` | Tunnel settings (which address goes to which local port) |
| `%USERPROFILE%\.cloudflared\cert.pem` | Your Cloudflare login certificate (**secret**) |
| `%USERPROFILE%\.cloudflared\623e5a61-….json` | The tunnel's credentials (**secret**) |
| `results/share_state.json` | The code secret and the on/off state (**secret**, never committed) |
| `results/share_log.csv` | Access log: who came in, wrong codes, removals |

---

## Part 1 · The big picture

```
 Visitor's phone/laptop                    Cloudflare (internet)                        Your PC
 ┌──────────────────┐   HTTPS   ┌───────────────────────────────┐   tunnel   ┌───────────────────────────────┐
 │ browser opens    │ ────────► │ pantun.aimanjamal.com         │ ◄────────► │ cloudflared  ──►  Streamlit   │
 │ pantun.aiman...  │ ◄──────── │ adds Cf-Connecting-Ip, Cf-Ray │  (your PC  │ (Start        localhost:8501  │
 └──────────────────┘           │ headers, forwards the request │  dialled   │  Sharing.bat) app.py → gate() │
                                └───────────────────────────────┘   out)     └───────────────────────────────┘
```

Four pieces work together:

1. **The app** (Streamlit) runs on your PC and listens only on `localhost:8501`. Nothing on the internet can
   reach `localhost` directly.
2. **The tunnel program** (`cloudflared`) on your PC *dials out* to Cloudflare and keeps that connection open.
   Requests for `pantun.aimanjamal.com` come back down this connection and are handed to `localhost:8501`.
3. **Cloudflare DNS** says "`pantun.aimanjamal.com` lives at this tunnel".
4. **The gate** inside the app: anyone arriving through Cloudflare must type the current code, and only while
   you have switched sharing on.

The tunnel decides *whether the site is reachable at all*. The gate decides *who may use it*. You need both.

---

## Part 2 · Networking basics you need

### 2.1 Ports and `localhost`
A computer runs many programs that talk on the network. Each listens on a **port** (a number). Streamlit uses
port 8501. `localhost` (or `127.0.0.1`) means "this same computer". The app is started with
`--server.address localhost`, so **only programs on your PC** can connect to it. That is the first safety layer.

### 2.2 Why you can't simply "open a port"
At home your PC sits behind a **router** that does **NAT** (many devices share one public IP address). Strangers on
the internet cannot start a connection to your PC unless you set up *port forwarding* on the router, which:
- exposes your PC directly to the whole internet (scanners find open ports within minutes),
- needs a fixed public IP (many Malaysian ISPs use CGNAT, so it may not even work),
- needs you to manage HTTPS certificates yourself.

### 2.3 What a tunnel does instead
A tunnel flips the direction: your PC makes an **outgoing** connection to Cloudflare (outgoing is always allowed),
and Cloudflare sends visitors' requests *back through that same connection*. Nothing on your router changes and
your PC's address is never published. Close `cloudflared` and the site simply disappears.

`cloudflared` connects to Cloudflare on **port 7844**, using QUIC (UDP) or HTTP/2 (TCP). If a network blocks
7844, the tunnel can't connect (see Troubleshooting).

### 2.4 DNS, CNAME
**DNS** turns a name into an address. Your domain `aimanjamal.com` is managed by Cloudflare. The command
`cloudflared tunnel route dns pantun pantun.aimanjamal.com` added one record:

```
pantun.aimanjamal.com   CNAME   623e5a61-2911-418a-a382-7dd1bcef6aac.cfargotunnel.com   (proxied)
```

A **CNAME** says "this name is an alias of that name". The target is your tunnel's internal name, which only
Cloudflare can resolve. Your portfolio (`aimanjamal.com` itself) is a different record and is untouched.

### 2.5 HTTPS
Visitors talk to Cloudflare over **HTTPS** (encrypted; Cloudflare provides the certificate automatically). The
tunnel between Cloudflare and your PC is also encrypted. Inside your PC, `cloudflared` → Streamlit is plain HTTP
on `localhost`, which never leaves the machine.
> Note: Cloudflare decrypts traffic at its edge (that is how it can route it). For a student demo this is fine;
> it would not be fine for medical or banking data.

### 2.6 HTTP headers
Every web request carries **headers** (name: value lines). Cloudflare adds its own on the way in:

| Header | Meaning | Used for |
|---|---|---|
| `Cf-Ray` | ID of this request inside Cloudflare | Detect "came through the tunnel" |
| `Cf-Connecting-Ip` | The visitor's real public IP address | Device list, per-IP limits, blocking |
| `Cf-Ipcountry` | Two-letter country code (e.g. `MY`) | Device list |
| `User-Agent` | Browser and operating system text (sent by the browser) | "Chrome · Android" label |

---

## Part 3 · Streamlit concepts the gate relies on

| Concept | What it means | Where it matters |
|---|---|---|
| **Rerun** | Every click re-runs the whole Python script from the top | `gate()` runs before every page, every time |
| **Session** | Each browser tab is its own session with its own `st.session_state` | "Unlocked" is remembered per tab; each tab = one device |
| **`st.stop()`** | Ends this run immediately; nothing below is drawn | The gate shows the code screen then stops |
| **`st.context.headers`** | The request headers of this session | Detecting Cloudflare, reading IP/country/browser |
| **`st.context.cookies`** | Cookies the browser sent when the session started (read-only) | Reading the 2-hour pass |
| **`st.html(..., unsafe_allow_javascript=True)`** | Runs a small script in the page | Saving the pass cookie (Streamlit can't set cookies itself) |
| **Fragment with `run_every`** | A small part of the page that re-runs on a timer | Heartbeat (10 s), live code (1 s), device list (5 s) |
| **Module-level variables** | Python module state is shared by *all* sessions in one server | The device list (`_reg`) that the owner sees |
| **Lock** (`threading.RLock`) | Sessions run in parallel threads; a lock stops two from editing the list at once | Every change to `_reg` and the files |

---

## Part 4 · One-time passwords (TOTP): the theory

### 4.1 The idea
You and the app share a **secret** (a random 160-bit number). Both sides can compute a short code from
*secret + current time*. Anyone without the secret cannot compute it, and a code is useless 15–30 seconds later.
This is exactly how Google Authenticator works. The standards are **RFC 4226 (HOTP)** and **RFC 6238 (TOTP)**.

### 4.2 The algorithm, step by step
```
counter  = floor(unix_time / PERIOD)              # PERIOD = 15 s here (30 s in Google Authenticator)
message  = counter as 8 bytes, big-endian
digest   = HMAC-SHA1(secret, message)             # 20 bytes
offset   = last byte of digest & 0x0F             # a number 0..15 ("dynamic truncation")
chunk    = 4 bytes of digest starting at offset
number   = chunk as an integer & 0x7FFFFFFF       # drop the top bit (keeps it positive)
code     = number mod 10^6, padded to 6 digits
```

**HMAC** (Hash-based Message Authentication Code) mixes the secret into a hash so that the output can only be
produced by someone who knows the secret. **Dynamic truncation** picks 4 bytes from a position chosen by the hash
itself, so every part of the hash affects the code.

### 4.3 Worked example (the official RFC 6238 test value)
Secret = the ASCII text `12345678901234567890`, period 30 s, time = 59 s:

| Step | Value |
|---|---|
| counter = floor(59 / 30) | 1 |
| message (8 bytes) | `0000000000000001` |
| HMAC-SHA1 | `75a48a19d4cbe100644e8ac1397eea747a2d33ab` |
| last byte `0xab` & `0x0F` | offset = 11 |
| 4 bytes from offset 11 | `c1397eea` = 3,241,770,730 |
| & `0x7FFFFFFF` | 1,094,287,082 |
| mod 1,000,000 | **287082** ✔ (matches the RFC) |

Same secret with this app's 15-second period at time 1,763,251,200 → counter 117,550,080 → code **370113**.
`src/share.py` passes both RFC test values (`code_at()`).

### 4.4 Where the secret lives
`secrets.token_hex(20)` makes 20 random bytes (160 bits) from the operating system's secure random source,
stored in `results/share_state.json`. It never leaves your PC: you only ever say the *code* out loud.
If you think the file leaked, delete it; a new secret is made on the next start.

### 4.5 Comparing codes safely
`hmac.compare_digest(a, b)` compares in **constant time**. A normal `==` stops at the first wrong digit, and in
theory an attacker could measure response times to learn digits one by one. Constant-time comparison removes
that leak.

### 4.6 Why the previous code is also accepted (the "grace window")
Codes change every 15 seconds. If you read out a code at second 13, the visitor has 2 seconds to type it. So the
app also accepts the code from the *previous* 15-second step (`GRACE_STEPS = 1`). Authenticator apps do the
same, mainly for clocks that are slightly out of sync. Effect:

- Each code is usable for **15 to 30 seconds** instead of 0 to 15.
- At any moment **2** codes are valid, so a random guess succeeds with probability **2 in 1,000,000**
  instead of 1 in 1,000,000.

### 4.7 Is that dangerous? The numbers
Guessing is the only realistic attack (the secret can't be worked out from codes). What matters is **how many
guesses** an attacker gets, which is why the app limits wrong codes:

| Situation | Guesses an attacker gets | Chance of getting in (grace on) | (grace off) |
|---|---|---|---|
| No limits, a script trying 10 codes per second, 1 hour | 36,000 | **6.9 %** | 3.5 % |
| Old limits (20 wrong per minute overall), 8 hours | 9,600 | **1.9 %** | 0.96 % |
| **Current limits (30 wrong per hour overall), 8 hours** | 240 | **0.048 %** (1 in ~2,100) | 0.024 % |

(Formula: chance = 1 − (1 − p)^guesses, with p = 2/10⁶ or 1/10⁶.)

So the grace window doubles a small number; the rate limits are what keep it small. With the current limits,
an attacker would also show up on your Kongsi page as a growing "kod salah" count long before they had a real
chance. To be stricter, set `GRACE_STEPS = 0` in `src/share.py` and read codes out right after they change.

### 4.8 Why not use the Google Authenticator app itself?
Google Authenticator only shows 30-second codes. The app shows its own 15-second codes on the Kongsi page, so no
phone is needed. To use an authenticator app instead: set `PERIOD = 30` and add the secret to the app via an
`otpauth://totp/...?secret=<base32 secret>&period=30` QR code.

---

## Part 5 · The gate design (what `src/share.py` does)

### 5.1 Owner vs visitor
`is_visitor()` returns True when the request has a `Cf-Ray` or `Cf-Connecting-Ip` header.
- **You** open `http://localhost:8501` directly: no Cloudflare headers, so you are the owner and also see **Kongsi**.
- **Visitors** can only arrive through Cloudflare, which always adds these headers.

Can a visitor fake being the owner? To be treated as the owner, a request must have *no* Cloudflare headers, but
every request from the internet passes through Cloudflare, and the app itself only listens on `localhost`. So
no. (A visitor *adding* fake headers only makes them look more like a visitor.)

### 5.2 States: off, on, rounds
```
            Hidupkan (30 min–8 h)                  time runs out / Matikan
   OFF  ─────────────────────────────►  ON  ──────────────────────────────►  OFF
                                        │  ▲
                     Keluarkan semua    │  │ new round, same end time
                                        └──┘
```
- **OFF**: visitors see "Perkongsian ditutup"; `verify()` returns False for every code.
- **ON** has a random **round** ID. A visitor who types a valid code is unlocked *for that round only*
  (`st.session_state["share_ok"] = round`).
- Switching off, switching on again, or **Keluarkan semua** creates a new round, so every earlier unlock
  becomes worthless at once. This is a simple and reliable way to revoke everyone.
- **Auto-expiry**: `state()` checks the end time on every call and switches off by itself.

### 5.3 The visitor screen
`gate()` runs at the top of `app.py`, before navigation. For a visitor it shows the right screen and calls
`st.stop()`, so **none of the app's pages or data run** until they are unlocked:

| Situation | Screen |
|---|---|
| Sharing off | Perkongsian ditutup |
| IP blocked, or device blocked | Akses disekat |
| Device removed | Akses ditarik balik |
| Not yet unlocked | Name + code form |
| Unlocked this round, or has a valid 2-hour pass | The app (plus a hidden heartbeat) |

### 5.4 Heartbeat and instant lock-out
An unlocked visitor page contains a tiny fragment (`_watch`) that re-runs every 10 seconds. Each run:
1. marks the device as "last seen now" (this is how the owner sees **Dalam talian**, online), and
2. checks whether sharing is still on, the round is the same, and the device is still active and not blocked.
   If not, it clears the unlock and reruns the page, which then shows a closed screen.

So removal takes effect **within 10 seconds**, even if the visitor doesn't click anything.

### 5.5 "Remember this device for 2 hours" (the pass)
Without it, every refresh starts a new Streamlit session, and a new session has no unlock, so visitors had to
type a code again. Now, after a correct code (with **Ingat peranti ini selama 2 jam** ticked, the default), the
browser keeps a **signed pass** in a cookie named `cz_pass`:

```
pass = base64url( {"r": round, "d": device_id, "n": name, "e": expiry_time} ) + "." + HMAC-SHA256(key, that text)
key  = HMAC-SHA256(code secret, "cz-remember-pass")      # a separate key derived from the secret
```

When a new session starts, `gate()` reads the cookie and accepts it only if **all** of these hold:

| Check | Why |
|---|---|
| The signature matches | Only the app (which knows the secret) can make a pass; editing any letter breaks it |
| Expiry not passed (2 h, never past the end of sharing) | Passes die on their own |
| Same round as now | **Matikan**, **Keluarkan semua** or switching on again cancels every pass at once |
| The device isn't removed/blocked and its IP isn't blocked | **Keluarkan** / **Sekat IP** cancel that device's pass |

An open page also locks itself when its 2 hours are up (the heartbeat checks the expiry).

Cookie settings: `Max-Age` = time left, `Path=/`, `SameSite=Strict` (not sent by other websites), `Secure` on
HTTPS (never sent unencrypted). It can't be `HttpOnly`, because it is set from JavaScript; that means a script
running on the page could read it, but the app runs no third-party scripts.

**Why sign instead of just storing "unlocked=yes"?** Anyone can edit their own cookies. A signature is a stamp
only the app can make, so a visitor can't invent a pass, extend its time or change the round.

### 5.6 Phone menu
On screens narrower than 768 px Streamlit hides its top menu behind a small **»** button, so phone visitors
only saw the first view. `app.py` adds a row of links (Pelajar · Pensyarah · Penyelidik & Pakar) shown only
on narrow screens (CSS `@media (max-width: 767px)`).

---

## Part 6 · Monitoring and removing devices

### 6.1 What counts as a device
A **device** is one browser. It gets a random `device_id` when its owner types a correct code, and that ID is
inside its 2-hour pass, so refreshing or opening a new tab is the *same* device (the list shows a visit count).
If **Ingat peranti** was unticked, each new tab needs a code and becomes a new device. The app records:

| Field | Source |
|---|---|
| Name | Typed by the visitor (optional, so you know who it is) |
| Device | `User-Agent` → e.g. "Chrome · Android", "Safari · iPhone" |
| IP address | `Cf-Connecting-Ip` |
| Country | `Cf-Ipcountry` |
| Entered at / last seen | Clock; last seen is updated by the heartbeat |
| Status | aktif / dikeluarkan / disekat |

The list is kept in memory and saved to `results/share_devices.json`, so removed and blocked devices **stay out
even if the app restarts**. It is cleared when a new round starts. Every event is
also written to `results/share_log.csv` (download it from the Kongsi page).

### 6.2 Actions on the Kongsi page
- **Keluarkan** (remove): that tab is locked within 10 s. The person could reload and type a *new* code if you
  give them one.
- **Sekat IP** (block): removes the device **and** refuses every request from that IP address for the rest of
  the round, even with a correct code. **Buka sekatan** undoes it.
- **Keluarkan semua** (remove all): new round; everyone must type a new code. Sharing stays on.
- **Matikan perkongsian** (switch off): nobody can get in until you switch it on again.

### 6.3 Limits of IP addresses (important)
- Many people can share **one IP**: everyone on the same Wi-Fi, a campus network, or a mobile carrier (CGNAT).
  Blocking that IP blocks all of them.
- One person can **change IP**: switching from Wi-Fi to mobile data or using a VPN gives a new IP and gets
  around a block. If you need someone out completely, use **Keluarkan semua** and give the new code only to the
  people you want.
- Visitors can type any name. The name is a label, not proof of identity.

---

## Part 7 · Wrong-code limits

| Limit | Value | What happens |
|---|---|---|
| Per IP address | 5 wrong codes in 10 minutes | That IP must wait |
| Everyone together | 30 wrong codes in 1 hour | Code screen paused for all; a warning appears on Kongsi |

Restarting sharing (off then on) clears the counters. The limits are the main defence against guessing
(Part 4.7). They are in memory, so restarting the app also clears them.

---

## Part 8 · The Cloudflare Tunnel, command by command

Run these once (already done for this project):

```bash
winget install --id Cloudflare.cloudflared -e
```
```bash
cloudflared tunnel login
```
Opens Cloudflare in your browser; you pick the domain and press **Authorize**. Saves `cert.pem`, which lets this
PC create tunnels and DNS records for that domain.
```bash
cloudflared tunnel create pantun
```
Creates the tunnel and a credentials file `<tunnel-id>.json`. That file is the tunnel's password.
```bash
cloudflared tunnel route dns pantun pantun.aimanjamal.com
```
Adds the CNAME record from Part 2.4.

Then the config file `%USERPROFILE%\.cloudflared\pantun.yml`:
```yaml
tunnel: 623e5a61-2911-418a-a382-7dd1bcef6aac
credentials-file: C:\Users\Administrator\.cloudflared\623e5a61-2911-418a-a382-7dd1bcef6aac.json
ingress:
  - hostname: pantun.aimanjamal.com
    service: http://localhost:8501
  - service: http_status:404        # anything else: "not found"
```
**Ingress rules** are checked top to bottom; the last rule must catch everything.

Each time you share:
```bash
cloudflared tunnel --config "%USERPROFILE%\.cloudflared\pantun.yml" run pantun
```
(`Start Sharing.bat` does exactly this.)

To remove everything later:
```bash
cloudflared tunnel delete pantun
```
Then delete the `pantun` CNAME record in the Cloudflare dashboard (DNS → Records).

**Keep secret:** `cert.pem` and the tunnel `.json` file. Never commit them or send them to anyone.

### 8.1 Keeping `cert.pem` off the PC (USB method)

The two secret files are not equally powerful, and they are needed at different times:

| File | What someone could do with it | When you need it |
|---|---|---|
| `cert.pem` | Create, change or delete tunnels **and DNS records** for your whole domain (e.g. point `aimanjamal.com` somewhere else) | Only to create, route, rename or delete a tunnel |
| `<tunnel-id>.json` | Run *this one* tunnel (serve something at `pantun.aimanjamal.com`) | Every time you share |

So once the tunnel exists, `cert.pem` can leave the PC, while `Start Sharing.bat` keeps working with only the
`.json` file.

**Where to keep it**

| Location | Who can read it | Verdict |
|---|---|---|
| `C:\Users\Administrator\.cloudflared\` (default) | You, every program you run, any malware on the PC | Works, least safe |
| Another drive on the same PC (e.g. `D:\`) | Exactly the same: one PC, one user, all drives readable | **No real gain** |
| **USB drive, unplugged** | Nobody until you plug it in | **Recommended** |
| Password-protected 7-Zip archive (AES-256) or a password manager | Only someone with the password | **Recommended** (keep a copy on USB too) |
| Anything under `G:\My Drive` (Google Drive sync) | Uploaded to the cloud automatically | **Never** |
| Inside a project folder (e.g. `D:\CODES\pantun-coherence`) | Could be committed to GitHub by mistake | **Never** |

**Moving it**
1. Plug in the USB drive (say it appears as `E:`).
2. Move `C:\Users\Administrator\.cloudflared\cert.pem` to `E:\cloudflared\cert.pem` (cut and paste, so no copy
   is left on the PC; also empty the Recycle Bin if it went there).
3. Unplug the USB and store it somewhere safe.
4. Test: run `Start Sharing.bat`. It should still connect, because running only needs the `.json` file.

(Prefer copy-then-delete? Copy it to the USB, check the copy opens, then delete the original.)

**When you need it again** (to create, route or delete a tunnel), plug in the USB and point `cloudflared` at it
with `--origincert`, without copying it back:
```bash
cloudflared tunnel --origincert E:\cloudflared\cert.pem delete pantun
```
```bash
cloudflared tunnel --origincert E:\cloudflared\cert.pem route dns pantun pantun.aimanjamal.com
```

**If the USB is lost, or you think `cert.pem` leaked:** it can't be "reset" by deleting your copy. In the
Cloudflare dashboard go to **My Profile → API Tokens** and delete the token named after the tunnel login (it is
created by `cloudflared tunnel login`). Then run `cloudflared tunnel login` again to get a fresh `cert.pem`.
Also check **DNS → Records** for any record you don't recognise.

**If the `.json` file leaks:** someone could run your tunnel and serve their own page at
`pantun.aimanjamal.com`. Delete the tunnel (`cloudflared tunnel --origincert … delete pantun`) and create a new
one; the old credentials stop working at once.

**The `.json` file has to stay on the PC** for sharing to work. To keep it off the OS drive, move it (e.g. to
`D:\Secrets\cloudflared\`) and update the `credentials-file:` line in `pantun.yml` (and the `--config` path in
`Start Sharing.bat` if you move `pantun.yml` too). Never put it in Google Drive or a project folder.

---

## Part 9 · Recreate it yourself from zero

The recipe below builds a minimal version in a fresh folder: a Streamlit app with a TOTP gate behind a tunnel.

### Step 1: a tiny app
```bash
py -3.11 -m venv .venv
```
```bash
.venv\Scripts\pip install streamlit
```

### Step 2: `gate_demo.py` (about 60 lines, the core of `src/share.py`)
```python
import hashlib, hmac, json, os, secrets, struct, time
import streamlit as st

STATE = "share_state.json"
PERIOD, DIGITS = 15, 6

def load():
    if not os.path.exists(STATE):
        json.dump({"secret": secrets.token_hex(20), "on": False, "round": ""}, open(STATE, "w"))
    return json.load(open(STATE))

def save(s):
    json.dump(s, open(STATE, "w"))

def code_at(secret, t):
    counter = int(t // PERIOD)
    d = hmac.new(bytes.fromhex(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    o = d[-1] & 0x0F
    n = struct.unpack(">I", d[o:o + 4])[0] & 0x7FFFFFFF
    return str(n % 10 ** DIGITS).zfill(DIGITS)

def verify(s, code):
    now = time.time()
    return s["on"] and any(hmac.compare_digest(code, code_at(s["secret"], now - k * PERIOD)) for k in (0, 1))

is_visitor = bool(st.context.headers.get("Cf-Ray"))
s = load()

if is_visitor and st.session_state.get("ok") != s["round"]:
    st.title("Enter access code")
    if not s["on"]:
        st.info("Sharing is closed.")
        st.stop()
    code = st.text_input("Code", max_chars=6)
    if st.button("Enter") and verify(s, code):
        st.session_state["ok"] = s["round"]
        st.rerun()
    st.stop()

if not is_visitor:                                   # owner controls
    if st.toggle("Sharing on", value=s["on"]) != s["on"]:
        s.update(on=not s["on"], round=secrets.token_hex(8))
        save(s)
        st.rerun()
    if s["on"]:
        @st.fragment(run_every=1)
        def live():
            st.metric("Code", code_at(s["secret"], time.time()), help="changes every 15 s")
        live()

st.write("🎉 The protected app goes here.")
```

### Step 3: run and test locally
```bash
.venv\Scripts\streamlit run gate_demo.py --server.address localhost
```
Open `http://localhost:8501`: you see the owner toggle. To see the visitor screen locally, temporarily change
`is_visitor` to `True`.

### Step 4: put it online
Install `cloudflared`, then `tunnel login`, `tunnel create <name>`, `tunnel route dns <name> <sub.yourdomain>`,
write the config file and run it (Part 8).

### Step 5: harden it (what the full version adds)
1. Wrong-code limits per IP and overall (Part 7).
2. Auto-expiry of sharing.
3. Heartbeat fragment that locks removed visitors (Part 5.4).
4. A signed 2-hour pass in a cookie, checked against round, expiry and device status (Part 5.5).
4. Device list with remove/block (Part 6).
5. Access log CSV.
6. A lock around shared state, and atomic file writes (write to `.tmp`, then `os.replace`).

---

## Part 10 · What this protects, and what it doesn't

**Protects against**
- Strangers finding the address: they see only the code screen, or "sharing closed".
- Guessing codes: limited to about 30 guesses an hour (≈0.05 % chance over a full 8-hour share).
- Old codes being reused later: they expire after 15–30 seconds.
- Forgetting to switch off: sharing ends by itself.
- An unwanted person who is already in: remove or block them, or remove everyone.

**Does not protect against**
- Someone you let in copying what they see (screenshots, saved CSV/PDF exports).
- Someone who copies a visitor's `cz_pass` cookie to another browser, for up to 2 hours. **Keluarkan** on that
  device, or **Keluarkan semua**, cancels it.
- A person you removed who gets a new code from someone else, or changes IP to dodge a block.
- Your PC being off or asleep (the site goes down).
- Cloudflare itself being able to see the traffic (Part 2.5).

**Stronger options if you ever need them**
- `GRACE_STEPS = 0` (current code only).
- Shorter sharing times.
- **Cloudflare Access** (Zero Trust, free for up to 50 users): visitors must prove their email address with a
  one-time code from Cloudflare *before* reaching your PC at all. It can be combined with this gate.

---

## Part 11 · Day-to-day checklist

1. Double-click `Start Demo.bat` (wait 1–2 minutes for the models to load).
2. Double-click `Start Sharing.bat` and keep its window open.
3. Open **Kongsi** → choose how long → **Hidupkan perkongsian**.
4. Read the code to your visitor; watch them appear under **Peranti yang disambung**.
5. When finished: **Matikan perkongsian sekarang**, then close the `Start Sharing.bat` window.

## Part 12 · Troubleshooting

| Problem | Cause and fix |
|---|---|
| Visitors see a Cloudflare "Error 1033" page | `Start Sharing.bat` isn't running. Start it. |
| Visitors see "Bad gateway" (502) | The tunnel is up but the app isn't. Start `Start Demo.bat`. |
| Tunnel log says "port 7844 blocked" | The network blocks the tunnel's port. Try another network, or add `--protocol http2` to the run command. (On this PC one Cloudflare region was blocked but the other worked.) |
| "Kod tidak sah" with the right code | The code expired (over 30 s old) or sharing is off. Give the newest code. |
| Code screen says "dijeda" (paused) | 30 wrong codes in the last hour. Switch sharing off and on again. |
| A visitor's device isn't listed as online | Their tab is closed, asleep or in the background; the heartbeat runs every 10 s. |

## Part 13 · Glossary

| Term | Meaning |
|---|---|
| CNAME | DNS record that makes one name an alias of another |
| CGNAT | Carrier-grade NAT: many customers share one public IP |
| Constant-time compare | Comparing secrets without leaking timing information |
| Dynamic truncation | TOTP step that picks 4 bytes of the hash at a position given by the hash |
| Fragment | Part of a Streamlit page that can re-run on its own (e.g. every second) |
| Heartbeat | Regular "I'm still here" check-in from a visitor's page |
| HMAC | Hash-based message authentication code: a keyed hash |
| Ingress rule | Tunnel rule mapping a hostname to a local service |
| NAT | Router feature that lets many devices share one public IP |
| Round | One sharing period; a new round invalidates every earlier unlock |
| TOTP / HOTP | Time-based / counter-based one-time password (RFC 6238 / RFC 4226) |

## Part 14 · References
- RFC 4226, *HOTP: An HMAC-Based One-Time Password Algorithm*: https://www.rfc-editor.org/rfc/rfc4226
- RFC 6238, *TOTP: Time-Based One-Time Password Algorithm*: https://www.rfc-editor.org/rfc/rfc6238
- RFC 2104, *HMAC*: https://www.rfc-editor.org/rfc/rfc2104
- Cloudflare Tunnel documentation: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/
- Cloudflare HTTP request headers: https://developers.cloudflare.com/fundamentals/reference/http-headers/
- Streamlit: `st.context`, `st.fragment`, session state: https://docs.streamlit.io
