"""Finish a walkthrough recording: the face frame, and (later) the presenter's voice-over and face, in sync.

    videnv\\Scripts\\python tutorial\\compose_video.py penyelidik --name "Nama Anda"
        -> recordings/penyelidik_frame.mp4   the recording with an empty face frame (bottom-left, like the deck)

    videnv\\Scripts\\python tutorial\\compose_video.py penyelidik --name "Nama Anda" --voice my_take.mp4
        -> recordings/penyelidik_final.mp4   video timed to the voice-over, face inside the frame, voice as audio

How the sync works: the presenter reads docs/demo_walkthrough.md segment by segment (P4-1 ... P4-8) with a short
pause (about a second) between segments. The pauses are found in the audio (ffmpeg silencedetect); each recorded
segment (recordings/<name>_segments.json) is then sped up or slowed down a little to fit what is said, and held on
its last frame if the speaking runs longer. If the pauses cannot be found, give the start of each segment by hand:
--cuts 0,14.2,31,... (seconds in the voice-over).
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import imageio_ffmpeg

ROOT = Path(__file__).resolve().parent.parent
REC = ROOT / "recordings"
FF = imageio_ffmpeg.get_ffmpeg_exe()
W, H = 1920, 1080
# Face frame (Japanese variety-show "wipe"), placed like the frame on the deck's Pelajar slide: bottom-left corner
FRAME = {"x": 18, "y": 752, "w": 320, "h": 310, "border": 7, "radius": 22}

FRAME_HTML = """<!doctype html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Nunito:wght@800;900&display=swap" rel="stylesheet">
<style>
html, body { margin: 0; width: 1920px; height: 1080px; background: transparent; overflow: hidden; }
.wipe { position: absolute; left: __X__px; top: __Y__px; width: __W__px; height: __H__px; box-sizing: border-box;
  border: __B__px solid #2E62C8; border-radius: __R__px; box-shadow: 0 8px 0 #1D3F86, 0 14px 30px rgba(0,0,0,.28);
  background: __BG__; overflow: hidden; }
.wipe .hill { position: absolute; left: -10%; right: -10%; bottom: -46%; height: 70%; border-radius: 50%;
  background: radial-gradient(ellipse at 50% 20%, #9BCB3C, #5E9A1E); }
.tag { position: absolute; left: __TX__px; top: __TY__px; transform: translateX(-100%); display: flex; align-items: center;
  font: 900 22px 'Nunito', sans-serif; color: #fff; }
.tag .name { background: #1D3F86; padding: 7px 14px 7px 16px; border-radius: 12px 0 0 12px; letter-spacing: .3px;
  box-shadow: 0 4px 0 #122a5c; white-space: nowrap; }
.tag .ini { background: #2E62C8; padding: 7px 12px; border-radius: 0 12px 12px 0; box-shadow: 0 4px 0 #1D3F86; }
.spark { position: absolute; font-size: 30px; color: #FFC83D; text-shadow: 0 2px 0 #D99400; }
</style></head><body>
<div class="wipe">__INNER__</div>
<div class="tag"><span class="name">__NAME__</span><span class="ini">__INI__</span></div>
<div class="spark" style="left:__S1X__px;top:__S1Y__px">✦</div>
</body></html>"""


def run(args, **kw):
    return subprocess.run([FF, "-y", "-loglevel", "error", *args], check=True, **kw)


def frame_png(name, path, empty_inside):
    """Render the frame (transparent PNG, 1920x1080) with Edge. `empty_inside`: a see-through hole for the face video;
    otherwise the sky-and-grass placeholder as on the deck."""
    from playwright.sync_api import sync_playwright
    f = FRAME
    ini = "".join(w[0] for w in name.split()[:2]).upper() or "?"
    inner = "" if empty_inside else '<div class="hill"></div>'
    bg = "transparent" if empty_inside else "linear-gradient(#FFFFFF 0%, #D9F0FF 55%, #BFE6FF 100%)"
    page_html = (FRAME_HTML.replace("__X__", str(f["x"])).replace("__Y__", str(f["y"])).replace("__W__", str(f["w"]))
                 .replace("__H__", str(f["h"])).replace("__B__", str(f["border"])).replace("__R__", str(f["radius"]))
                 .replace("__BG__", bg).replace("__INNER__", inner).replace("__NAME__", name).replace("__INI__", ini)
                 .replace("__TX__", str(f["x"] + f["w"] - 6)).replace("__TY__", str(f["y"] - 24))
                 .replace("__S1X__", str(f["x"] + f["w"] - 4)).replace("__S1Y__", str(f["y"] - 40)))
    html_file = Path(tempfile.mkdtemp()) / "frame.html"
    html_file.write_text(page_html, encoding="utf-8")
    with sync_playwright() as p:
        b = p.chromium.launch(channel="msedge")
        pg = b.new_page(viewport={"width": W, "height": H})
        pg.goto(html_file.as_uri())
        pg.wait_for_timeout(1200)                       # web font
        pg.screenshot(path=str(path), omit_background=True)
        b.close()


def silences(audio, min_len=0.6, noise="-32dB"):
    out = subprocess.run([FF, "-hide_banner", "-i", str(audio), "-af", f"silencedetect=noise={noise}:d={min_len}",
                          "-f", "null", "-"], capture_output=True, text=True).stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", out)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", out)]
    return list(zip(starts, ends))


def duration(path):
    out = subprocess.run([FF, "-hide_banner", "-i", str(path)], capture_output=True, text=True).stderr
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", out).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def voice_cuts(voice, n):
    """Start times of the n spoken segments: the n-1 longest pauses inside the take split it."""
    total = duration(voice)
    gaps = [(e - s, (s + e) / 2) for s, e in silences(voice) if s > 0.5 and e < total - 0.5]
    if len(gaps) < n - 1:
        sys.exit(f"Found only {len(gaps)} pauses in the voice-over, need {n - 1}. Give them with --cuts.")
    mids = sorted(m for _, m in sorted(gaps, reverse=True)[:n - 1])
    return [0.0, *mids], total


def retime(raw, segs, cuts, total, out):
    """Each recorded segment fitted to its spoken length: sped up as much as needed (never cut), or slowed down up to
    1.4x and then held on its last frame."""
    parts, tmp = [], Path(tempfile.mkdtemp())
    ends = cuts[1:] + [total]
    for k, s in enumerate(segs):
        want = ends[k] - cuts[k]
        have = s["end"] - s["start"]
        factor = min(1.4, want / have)                      # >1 = slower, <1 = faster
        part = tmp / f"p{k}.mp4"
        hold = max(0.0, want - have * factor)
        run(["-ss", f"{s['start']:.3f}", "-to", f"{s['end']:.3f}", "-i", str(raw),
             "-vf", f"setpts={factor:.4f}*PTS,tpad=stop_mode=clone:stop_duration={hold:.3f},fps=30",
             "-t", f"{want:.3f}", "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(part)])
        parts.append(part)
        print(f"  {s['segment']:<42} video {have:5.1f}s -> voice {want:5.1f}s (x{factor:.2f}, hold {hold:.1f}s)")
    listing = tmp / "parts.txt"
    listing.write_text("\n".join(f"file '{p.as_posix()}'" for p in parts), encoding="utf-8")
    run(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(out)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name", help="recording name, e.g. penyelidik")
    ap.add_argument("--name", dest="person", default="Nama Anda", help="name on the face frame's tag")
    ap.add_argument("--voice", help="presenter's take (video with face and voice, or audio only)")
    ap.add_argument("--cuts", help="segment start times in the voice-over, comma-separated seconds")
    a = ap.parse_args()
    raw = REC / f"{a.name}_raw.mp4"
    meta = json.loads((REC / f"{a.name}_segments.json").read_text(encoding="utf-8"))
    tmp = Path(tempfile.mkdtemp())

    if not a.voice:
        png = tmp / "frame.png"
        frame_png(a.person, png, empty_inside=False)
        out = REC / f"{a.name}_frame.mp4"
        run(["-i", str(raw), "-i", str(png), "-filter_complex", "[0][1]overlay=0:0", "-c:v", "libx264",
             "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)])
        print(f"{out.relative_to(ROOT)} ({duration(out):.1f}s)")
        return

    voice = Path(a.voice)
    segs = meta["segments"]
    if a.cuts:
        cuts, total = [float(x) for x in a.cuts.split(",")], duration(voice)
    else:
        cuts, total = voice_cuts(voice, len(segs))
    print("segment starts in the voice-over:", ", ".join(f"{c:.1f}" for c in cuts))
    timed = tmp / "timed.mp4"
    retime(raw, segs, cuts, total, timed)
    png = tmp / "frame.png"
    frame_png(a.person, png, empty_inside=True)
    f, b = FRAME, FRAME["border"]
    iw, ih = f["w"] - 2 * b, f["h"] - 2 * b
    has_video = "Video:" in subprocess.run([FF, "-hide_banner", "-i", str(voice)], capture_output=True,
                                           text=True).stderr
    out = REC / f"{a.name}_final.mp4"
    if has_video:     # face: cropped to fill the frame's inside, under the frame's border
        graph = (f"[1:v]scale={iw}:{ih}:force_original_aspect_ratio=increase,crop={iw}:{ih}[face];"
                 f"[0:v][face]overlay={f['x'] + b}:{f['y'] + b}[v1];[v1][2:v]overlay=0:0[v]")
    else:
        graph = "[0:v][2:v]overlay=0:0[v]"
    run(["-i", str(timed), "-i", str(voice), "-i", str(png), "-filter_complex", graph, "-map", "[v]", "-map", "1:a",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
         "-shortest", "-movflags", "+faststart", str(out)])
    print(f"{out.relative_to(ROOT)} ({duration(out):.1f}s)")


if __name__ == "__main__":
    main()
