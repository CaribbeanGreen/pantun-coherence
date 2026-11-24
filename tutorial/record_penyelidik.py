"""Record a real walkthrough video of the Penyelidik & Pakar page, from the login screen to "Log keluar".

It follows docs/demo_walkthrough.md, Part 4 (segments P4-1 ... P4-8). Unlike tutorial/render.py (animated pages),
this drives the real app: a private copy started here on this computer (same code as the live site, its own
throwaway accounts folder, the login screen switched on), with a demo expert account made for the recording.

    videnv\\Scripts\\python tutorial\\record_penyelidik.py

Output in recordings/ (not in git):
    penyelidik_raw.mp4        the screen, 1920x1080, 30 fps
    penyelidik_segments.json  when each segment P4-n starts and ends in the video (used to sync a voice-over)
Then tutorial/compose_video.py adds the face frame (and, later, the voice-over).

The two app logs a walkthrough writes to (results/expert_ratings.csv, results/instructor_decisions.csv) are copied
before and put back afterwards, so the recording leaves no trace in them.
"""

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "recordings"
PORT = 8510
URL = f"http://localhost:{PORT}"
FPS = 30
# The demo expert account (only exists in the throwaway folder of this recording)
EXPERT = {"username": "pakar.demo", "name": os.environ.get("REC_NAME", "Pakar Cenderawasih"),
          "password": "pakar-demo-2026"}
TOUCHED = [ROOT / "results" / "expert_ratings.csv", ROOT / "results" / "instructor_decisions.csv"]

# Visible mouse pointer and click ripple (an automated browser shows no pointer of its own)
CURSOR_JS = r"""
(() => {
  try { localStorage.setItem("cz_tour_done_penyelidik", "1"); localStorage.setItem("cz_tour_done_pelajar", "1"); }
  catch (e) {}
  const add = () => {
    if (document.getElementById("rec-cursor")) return;
    const c = document.createElement("div");
    c.id = "rec-cursor";
    c.innerHTML = '<svg width="30" height="30" viewBox="0 0 24 24"><path d="M4 2l15 9-6.5 1.5L16 20l-3 1.4-3.4-7.5L4 18z" '
      + 'fill="#fff" stroke="#17324D" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    Object.assign(c.style, { position: "fixed", left: "640px", top: "380px", zIndex: 2147483647, pointerEvents: "none",
      transition: "left .7s cubic-bezier(.3,.7,.3,1), top .7s cubic-bezier(.3,.7,.3,1)",
      filter: "drop-shadow(0 2px 3px rgba(0,0,0,.35))" });
    document.body.appendChild(c);
    const st = document.createElement("style");
    st.textContent = `.rec-ripple { position: fixed; width: 44px; height: 44px; margin: -22px 0 0 -22px; border-radius: 50%;
      border: 3px solid #DEB251; background: rgba(222,178,81,.25); pointer-events: none; z-index: 2147483646;
      animation: rec-r .6s ease-out forwards; } @keyframes rec-r { from { transform: scale(.3); opacity: 1 }
      to { transform: scale(1.4); opacity: 0 } }`;
    document.head.appendChild(st);
  };
  window.__recMove = (x, y, ms) => { add(); const c = document.getElementById("rec-cursor");
    c.style.transitionDuration = (ms / 1000) + "s"; c.style.left = (x - 4) + "px"; c.style.top = (y - 2) + "px"; };
  window.__recRipple = (x, y) => { const r = document.createElement("div"); r.className = "rec-ripple";
    r.style.left = x + "px"; r.style.top = y + "px"; document.body.appendChild(r); setTimeout(() => r.remove(), 700); };
  if (document.body) add(); else document.addEventListener("DOMContentLoaded", add);
})();
"""


class Recorder:
    """Screen frames from Chrome DevTools (only sent when the screen changes), with segment marks."""

    def __init__(self, page, folder):
        self.page, self.folder, self.frames, self.marks = page, folder, [], []
        self.cdp = page.context.new_cdp_session(page)
        self.cdp.on("Page.screencastFrame", self._frame)

    def _frame(self, ev):
        path = self.folder / f"f{len(self.frames):06d}.jpg"
        path.write_bytes(base64.b64decode(ev["data"]))
        self.frames.append((ev["metadata"]["timestamp"], path))
        try:
            self.cdp.send("Page.screencastFrameAck", {"sessionId": ev["sessionId"]})
        except Exception:
            pass

    def start(self):
        self.t0 = time.time()
        self.cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 90, "maxWidth": 1920, "maxHeight": 1080,
                                               "everyNthFrame": 1})

    def mark(self, name):
        self.marks.append((name, time.time()))
        print(f"  {name} at {time.time() - self.t0:5.1f}s", flush=True)

    def stop(self):
        self.page.wait_for_timeout(300)
        self.end = time.time()
        self.cdp.send("Page.stopScreencast")

    def write(self, mp4, seg_json):
        """Constant 30 fps video: each frame is held until the next one arrived."""
        # the very first screencast frame can be a stale loading screen: start half a second in
        self.frames = [f for f in self.frames if f[0] >= self.t0 + 0.5] or self.frames
        times = [t for t, _ in self.frames]
        lines = []
        for i, (t, path) in enumerate(self.frames):
            nxt = times[i + 1] if i + 1 < len(times) else self.end
            # exact on-screen time (frames can come faster than 30 a second; the fps filter below evens them out)
            lines.append(f"file '{path.as_posix()}'\nduration {max(nxt - t, 0.001):.4f}")
        lines.append(f"file '{self.frames[-1][1].as_posix()}'")
        listing = self.folder / "frames.txt"
        listing.write_text("\n".join(lines), encoding="utf-8")
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
                        "-i", str(listing), "-vf", f"fps={FPS},scale=1920:1080:flags=lanczos,format=yuv420p",
                        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-movflags", "+faststart", str(mp4)],
                       check=True)
        start = times[0]
        segs = []
        for k, (name, t) in enumerate(self.marks[:-1]):
            segs.append({"segment": name, "start": round(max(0.0, t - start), 3),
                         "end": round(self.marks[k + 1][1] - start, 3)})
        seg_json.write_text(json.dumps({"fps": FPS, "duration": round(self.end - start, 3), "segments": segs},
                                       indent=2), encoding="utf-8")
        return segs


class Actor:
    """Slow, visible actions: the pointer glides to an element, a ripple shows the click."""

    def __init__(self, page):
        self.page = page

    def wait(self, s):
        self.page.wait_for_timeout(int(s * 1000))

    def point(self, loc, ms=750):
        loc.scroll_into_view_if_needed()
        self.wait(0.25)
        b = loc.bounding_box()
        x, y = b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
        self.page.evaluate(f"__recMove({x}, {y}, {ms})")
        self.page.mouse.move(x, y, steps=12)
        self.wait(ms / 1000 + 0.1)
        return x, y

    def click(self, loc, after=0.8):
        x, y = self.point(loc)
        self.page.evaluate(f"__recRipple({x}, {y})")
        loc.click()
        self.wait(after)

    def type(self, loc, text):
        self.click(loc, after=0.3)
        loc.press_sequentially(text, delay=110)
        self.wait(0.4)

    def scroll(self, px, steps=1, pause=1.2):
        for _ in range(steps):
            self.page.evaluate(f"document.querySelector('[data-testid=stMain]').scrollBy({{top: {px}, behavior: 'smooth'}})")
            self.wait(pause)

    def top(self):
        self.page.evaluate("document.querySelector('[data-testid=stMain]').scrollTo({top: 0, behavior: 'smooth'})")
        self.wait(0.8)


# ---- Setting up the private copy ---------------------------------------------------------------------

def prepare(share_dir):
    """Demo expert account and two cases that teachers sent to the experts (so the queue is not empty)."""
    code = f"""
import sys; sys.path.insert(0, r"{ROOT}")
from src import share
from src.app_core import save_decision, EXAMPLES
key = share.add_member("{EXPERT['username']}", "{EXPERT['name']}", 30, "rakaman video", "penyelidik")
share.change_password("{EXPERT['username']}", key, "{EXPERT['password']}", "{EXPERT['password']}")
save_decision("4 Bestari · Pantun Nasihat", "M07", "pakar", "Kiasan dalam pembayang, saya kurang pasti.",
              EXAMPLES["Pandai menyimpai"], None, "cikgu.demo")
save_decision("5 Cemerlang · Pantun Budi", "M12", "pakar", "Pembayang dan maksud nampak tidak berkait.",
              EXAMPLES["Bercampur (ujian)"], None, "cikgu.demo")
"""
    env = {**os.environ, "PANTUN_SHARE_DIR": str(share_dir)}
    subprocess.run([str(ROOT / ".venv" / "Scripts" / "python.exe"), "-c", code], env=env, check=True,
                   stderr=subprocess.DEVNULL)


def start_app(share_dir):
    env = {**os.environ, "PANTUN_SHARE_DIR": str(share_dir), "PANTUN_FORCE_GATE": "1"}
    app = subprocess.Popen([str(ROOT / ".venv" / "Scripts" / "streamlit.exe"), "run", str(ROOT / "app.py"),
                            "--server.headless", "true", "--server.port", str(PORT), "--server.address", "localhost",
                            "--browser.gatherUsageStats", "false"], cwd=ROOT, env=env,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return app


def open_login(page):
    page.goto(URL + "/?lang=ms")
    page.get_by_role("tab", name="Log masuk").wait_for(timeout=120_000)
    page.wait_for_timeout(2500)                     # pictures and fonts finish loading before the video starts


def login(act, page):
    act.type(page.get_by_label("Nama pengguna").first, EXPERT["username"])
    act.type(page.get_by_label("Kata laluan atau kunci"), EXPERT["password"])
    act.click(page.locator("[data-testid=stForm]").get_by_role("button", name="Log masuk"), after=0.5)
    page.get_by_role("tab", name="Analisis pantun").wait_for(timeout=120_000)


def analyse(act, page):
    act.click(page.get_by_role("button", name="Pisang emas", exact=True), after=0.6)
    act.click(page.get_by_role("button", name="Analisis", exact=True), after=0.3)
    page.get_by_text("Keputusan setiap model").wait_for(timeout=180_000)


# ---- The walkthrough (one function per script segment) ------------------------------------------------

def walkthrough(act, page, rec):
    rec.mark("P4-1 Log masuk")
    act.wait(2.0)
    login(act, page)
    act.wait(1.5)
    act.point(page.locator(".st-key-cz_userbar .cz-chip"), ms=900)
    act.wait(4.5)

    rec.mark("P4-2 Analisis pantun")
    act.point(page.get_by_label("Pantun (4 baris, satu setiap baris)"))
    act.wait(2.0)
    analyse(act, page)
    act.wait(3.0)

    rec.mark("P4-3 Keputusan setiap model")
    act.point(page.get_by_text("Keseluruhan:", exact=False).first)
    act.wait(3.5)
    act.point(page.locator("[data-testid=stDataFrame]").first)
    act.wait(9.0)

    rec.mark("P4-4 Kedudukan pantun ini")
    chart = page.locator("[data-testid=stVegaLiteChart], [data-testid=stArrowVegaLiteChart]").first
    chart.scroll_into_view_if_needed()
    act.scroll(180, pause=1.0)                      # the model buttons and the whole chart on screen
    act.point(chart, ms=800)
    act.wait(2.0)
    group = page.locator("[data-testid=stButtonGroup]").filter(has_text="Kedudukan pantun ini")
    options = group.get_by_role("radio")
    act.click(options.nth(0), after=3.0)
    act.click(options.nth(min(3, options.count() - 1)), after=3.0)
    act.click(group.get_by_role("radio", name="LaBSE"), after=4.0)

    rec.mark("P4-5 Bentuk, bunyi dan penilaian pakar")
    act.point(page.get_by_text("BENTUK DAN BUNYI", exact=False).first)
    act.wait(4.0)
    form = page.locator("[data-testid=stForm]").filter(has_text="Sejauh mana pembayang")
    act.click(form.get_by_role("radio", name="4", exact=True), after=1.0)
    act.click(form.get_by_text("Gema bunyi", exact=True), after=0.8)
    act.click(form.get_by_text("Kiasan", exact=True), after=0.8)
    act.click(form.get_by_role("radio", name="Setuju", exact=True), after=1.0)
    act.click(form.get_by_role("button", name="Simpan penilaian"), after=3.5)

    rec.mark("P4-6 Barisan pakar")
    act.top()
    act.click(page.get_by_role("tab", name="Barisan pakar"), after=2.5)
    grid = page.locator("[role=tabpanel] [data-testid=stDataFrame]").first      # the open tab's table
    grid.scroll_into_view_if_needed()
    b = grid.bounding_box()
    x, y = b["x"] + 18, b["y"] + 35 + 17          # the first row's selection box
    page.evaluate(f"__recMove({x}, {y}, 800)")
    act.wait(1.0)
    page.evaluate(f"__recRipple({x}, {y})")
    page.mouse.click(x, y)
    act.wait(2.0)
    page.locator("[role=tabpanel]").get_by_text("Keputusan setiap model").wait_for(timeout=120_000)
    act.scroll(260, steps=2, pause=2.5)
    act.wait(3.0)

    rec.mark("P4-7 Dapatan")
    act.top()
    act.click(page.get_by_role("tab", name="Dapatan"), after=3.0)
    act.point(page.get_by_text("AUC peraturan rima").first)
    act.wait(2.5)
    act.point(page.get_by_text("AUC pembenaman terbaik").first)
    act.wait(3.0)
    act.scroll(320, steps=4, pause=2.2)
    act.wait(2.0)

    rec.mark("P4-8 Kaedah dan penutup")
    act.top()
    act.click(page.get_by_role("tab", name="Kaedah"), after=3.0)
    act.scroll(300, steps=2, pause=3.0)
    act.wait(6.0)
    act.top()
    act.click(page.get_by_role("button", name="Log keluar"), after=3.0)
    rec.mark("end")


def main():
    OUT.mkdir(exist_ok=True)
    backups = {p: p.read_bytes() if p.exists() else None for p in TOUCHED}
    share_dir = Path(tempfile.mkdtemp(prefix="pantun-rec-"))
    frames = OUT / "frames_penyelidik"
    shutil.rmtree(frames, ignore_errors=True)
    frames.mkdir()
    app = None
    try:
        prepare(share_dir)
        app = start_app(share_dir)
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="msedge")
            # Warm-up run (not recorded): loads the models so the recorded analysis answers in seconds
            print("warming up the app (loads the models, about a minute)...", flush=True)
            ctx = browser.new_context(viewport={"width": 1280, "height": 720}, device_scale_factor=1.5)
            ctx.add_init_script(CURSOR_JS)
            page = ctx.new_page()
            for _ in range(60):
                try:
                    page.goto(URL, timeout=5000)
                    break
                except Exception:
                    time.sleep(2)
            act = Actor(page)
            open_login(page)
            login(act, page)
            analyse(act, page)
            ctx.close()

            print("recording...", flush=True)
            ctx = browser.new_context(viewport={"width": 1280, "height": 720}, device_scale_factor=1.5)
            ctx.add_init_script(CURSOR_JS)
            page = ctx.new_page()
            open_login(page)                       # the video starts on a fully drawn login screen
            rec = Recorder(page, frames)
            rec.start()
            walkthrough(Actor(page), page, rec)
            rec.stop()
            ctx.close()
            browser.close()
        segs = rec.write(OUT / "penyelidik_raw.mp4", OUT / "penyelidik_segments.json")
        print(f"recordings/penyelidik_raw.mp4: {rec.end - rec.frames[0][0]:.1f}s, {len(rec.frames)} frames")
        for s in segs:
            print(f"  {s['segment']:<42} {s['start']:6.1f} - {s['end']:6.1f}")
    finally:
        if app:
            app.terminate()
        for path, data in backups.items():          # leave the app's logs exactly as they were
            if data is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(data)
        shutil.rmtree(share_dir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
