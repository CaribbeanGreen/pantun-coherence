"""Small decorative illustrations from Irasutoya (いらすとや, https://www.irasutoya.com/).

The image files live in assets/irasutoya/ on this computer only: Irasutoya's terms allow free use (non-commercial
use has no limit on the number of images) but not redistribution, and the GitHub repository is public, so the folder
is in .gitignore. Where each image came from is listed in assets/irasutoya/CREDITS.md.

If the folder or a file is missing (e.g. a fresh clone), the helpers return "" and the page simply shows no picture.
"""

import base64
import io
import math

import streamlit as st

from src.data_loader import PROJECT_ROOT

ILLUS_DIR = PROJECT_ROOT / "assets" / "irasutoya"
CREDIT = "Ilustrasi: いらすとや (irasutoya.com)"


@st.cache_data(show_spinner=False)
def data_uri(name, px=240):
    """The picture shrunk to `px` pixels wide (small enough to send quickly), as a data: URI."""
    path = ILLUS_DIR / f"{name}.png"
    if not path.exists():
        return ""
    try:
        from PIL import Image
        im = Image.open(path).convert("RGBA")
        im.thumbnail((px, px))
        buf = io.BytesIO()
        im.save(buf, "PNG", optimize=True)
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    except OSError:
        return ""


def img(name, width=110, style="", anim=""):
    """An <img> tag for use inside st.html, or "" if the picture isn't available.
    anim: "pop", "cheer" (pop + bounce), "wiggle" or "float" (CSS animations in app_core.UX_CSS)."""
    uri = data_uri(name, px=max(120, width * 2))      # 2x for sharp screens
    cls = "cz-illus" + (f" cz-anim-{anim}" if anim else "")
    return f'<img class="{cls}" src="{uri}" alt="" style="width:{width}px;height:auto;{style}">' if uri else ""


def show(name, width=110, anim="", style=""):
    """Put one picture on the page (centred)."""
    tag = img(name, width, style, anim)
    if tag:
        st.html(f'<div style="text-align:center">{tag}</div>')


COLOURS = ["#DEB251", "#0C525C", "#1B6E78", "#2F7D4F", "#F3D58E", "#B4443C", "#E07AA0"]


def _popper(side):
    """A party popper drawn in CSS, with confetti and streamers that fly out of its mouth in a fan."""
    bits = []
    for k in range(18):
        angle = math.radians(-62 + k * (124 / 17))          # fan from -62° to +62° around "straight out"
        dist = 80 + (k * 37) % 70
        dx, dy = math.sin(angle) * dist, -math.cos(angle) * dist
        tag = "b" if k % 3 == 0 else "i"                      # every third piece is a long streamer
        bits.append(f'<{tag} style="background:{COLOURS[k % len(COLOURS)]};--dx:{dx:.0f}px;--dy:{dy:.0f}px;'
                    f'--rot:{(k * 97) % 540 - 270}deg;animation-delay:{0.75 + (k % 4) * 0.03:.2f}s"></{tag}>')
    return (f'<div class="cz-popper {side}" aria-hidden="true"><div class="cone"></div><div class="rim"></div>'
            f'<div class="burst">{"".join(bits)}</div></div>')


def celebrate(title, text, name="gutspose_man"):
    """Duolingo-style pop-up: the character jumps in, two party poppers go off beside it, confetti falls, and the
    whole thing fades away by itself after about 6 seconds (it never blocks clicks)."""
    char = img(name, 150, "margin:0 auto")
    if not char:
        return
    pieces = "".join(
        f'<i style="background:{COLOURS[i % len(COLOURS)]};--dx:{((i * 53) % 520) - 260}px;--rot:{360 + (i * 47) % 540}deg;'
        f'left:{((i * 29) % 80) - 40}px;animation-delay:{0.9 + (i % 6) * 0.05:.2f}s"></i>' for i in range(48))
    st.html(f"""
<div class="cz-celebrate" role="status" aria-live="polite">
  <div class="cz-confetti" aria-hidden="true">{pieces}</div>
  <div class="cz-cel-card">
    <div class="cz-cel-char">{_popper("l")}{char}{_popper("r")}</div>
    <h2>{title}</h2>
    <p>{text}</p>
  </div>
</div>""")


def available():
    return ILLUS_DIR.exists() and any(ILLUS_DIR.glob("*.png"))
