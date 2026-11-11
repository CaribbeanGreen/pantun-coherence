"""Render a tutorial page (tutorial/<name>.html) to an MP4 video, frame by frame.

Needs a separate tools environment (not the app's .venv):
    py -3.11 -m venv videnv
    videnv\\Scripts\\pip install playwright imageio-ffmpeg
    videnv\\Scripts\\python tutorial\\render.py pelajar pensyarah penyelidik

Uses Microsoft Edge (already on Windows), so no browser download is needed.
Each page calls start(seconds) and exposes window.seek(t); this script seeks to every frame,
takes a screenshot and pipes it to ffmpeg. Output: assets/tutorial/<name>.mp4 (+ a poster .jpg).
"""

import subprocess
import sys
import time
from pathlib import Path

import imageio_ffmpeg
from playwright.sync_api import sync_playwright

HERE = Path(__file__).parent
OUT = HERE.parent / "assets" / "tutorial"
FPS = 30
SCALE = 1.5          # 1280x720 page -> 1920x1080 video


def render(page, name):
    page.goto((HERE / f"{name}.html").as_uri() + "?render")
    page.wait_for_function("window.READY === true", timeout=60_000)
    page.wait_for_timeout(500)
    duration = page.evaluate("window.DURATION")
    frames = int(duration * FPS)
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{name}.mp4"
    ffmpeg = subprocess.Popen(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS),
         "-c:v", "mjpeg", "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "22",
         "-movflags", "+faststart", str(out)],
        stdin=subprocess.PIPE)
    start = time.perf_counter()
    for i in range(frames):
        page.evaluate(f"seek({i / FPS})")
        ffmpeg.stdin.write(page.screenshot(type="jpeg", quality=92))
        if i % (FPS * 5) == 0:
            print(f"  {name}: {i / FPS:4.0f}s / {duration}s", flush=True)
    ffmpeg.stdin.close()
    ffmpeg.wait()
    # Poster image for the video player
    page.evaluate(f"seek({duration * 0.5})")
    page.screenshot(path=str(OUT / f"{name}.jpg"), type="jpeg", quality=85)
    print(f"{out.name}: {frames} frames, {out.stat().st_size / 1e6:.1f} MB, {time.perf_counter() - start:.0f} s")


def main(names):
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge")
        page = browser.new_page(viewport={"width": 1280, "height": 720}, device_scale_factor=SCALE)
        for name in names:
            render(page, name)
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1:] or ["pelajar", "pensyarah", "penyelidik"])
