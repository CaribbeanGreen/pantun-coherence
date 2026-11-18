"""Small decorative illustrations from Irasutoya (いらすとや, https://www.irasutoya.com/).

The image files stay on this computer: Irasutoya's terms allow free use (non-commercial use has no limit on the number
of images) but not redistribution, and the GitHub repository is public. Originals are in assets/irasutoya/, small copies
in static/i/ (served by Streamlit), and `python tools/fetch_irasutoya.py` downloads them on a fresh clone.
Where each image came from is listed in assets/irasutoya/CREDITS.md.

If a file is missing, the helpers return "" and the page simply shows no picture.
"""

import base64
import io
import math

import streamlit as st

from src.data_loader import PROJECT_ROOT

ILLUS_DIR = PROJECT_ROOT / "assets" / "irasutoya"
SMALL_DIR = PROJECT_ROOT / "static" / "i"
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


def has(name):
    return (SMALL_DIR / f"{name}.png").exists()


def url(name):
    return f"/app/static/i/{name}.png"


def ic(name):
    """A picture for Markdown text and widget labels."""
    return f"![]({url(name)})" if has(name) else ""


def tag(name):
    """A small picture for st.html."""
    return f'<img class="cz-i" alt="" src="{url(name)}">' if has(name) else ""


def img(name, width=110, style="", anim=""):
    """An <img> tag for use inside st.html, or "" if the picture isn't available.
    anim: "pop", "cheer" (pop + bounce), "wiggle" or "float" (CSS animations in app_core.UX_CSS)."""
    cls = "cz-illus" + (f" cz-anim-{anim}" if anim else "")
    return f'<img class="{cls}" src="{url(name)}" alt="" style="width:{width}px;height:auto;{style}">' if has(name) else ""


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
    return SMALL_DIR.exists() and any(SMALL_DIR.glob("*.png"))


# ---- The show-opening stage at the top of each section: 15 different characters hopping on a hill --------
SCENES = {
    "semak": ("sky", "fruit_banana mango durian pineapple papaya coconut watermelon kotori butterfly monkey yashinoki norimono_yacht turtle hibiscus sun"),
    "belajar": ("mint", "book_open_yoko pencil notebook owl bulb magnifier globe music star rainbow compass map backpack job_senesi study_woman_normal"),
    "sejarah": ("sunset", "clock hourglass calendar stopwatch medal trophy mail folder clipboard lantern shell starfish crab fish sailboat"),
    "dash": ("sky", "school job_senesi owl raise_hand student group megaphone bell chart trophy medal thumbs_up cracker sparkle hibiscus"),
    "kelas": ("mint", "folder paper clipboard pencil notebook magnifier ok_mark ng_mark hourglass stopwatch printer computer tablet book backpack"),
    "kod": ("sunset", "key lock ticket school backpack student handshake gift phone mail plane door home map compass"),
    "semakan": ("pink", "speech raise_hand mail plane bulb think ok_mark thumbs_up heart pencil owl megaphone bell handshake job_senesi"),
    "laporan": ("grape", "chart target medal trophy printer paper save folder arrow_up arrow_down stopwatch calendar rocket star computer"),
    "analyse": ("grape", "microscope test_tube magnifier computer chart gear think bulb book notebook rocket target compass globe owl"),
    "findings": ("sky", "chart trophy medal target star sparkle rainbow rocket printer paper folder clipboard calendar globe bulb"),
    "queue": ("sunset", "megaphone mail plane hourglass stopwatch bell raise_hand speech clipboard folder box_kara_hako owl job_senesi ok_mark ng_mark"),
    "method": ("mint", "gear compass map book_open_yoko notebook pencil music speaker microscope test_tube computer tablet phone key bulb"),
    "login": ("sky", "key lock door ticket backpack student job_senesi kotori butterfly hibiscus yashinoki sun cloud rainbow sailboat"),
    "penguji": ("pink", "clipboard pencil magnifier test_tube bulb star thumbs_up ok_mark ng_mark warning stopwatch phone computer tablet trophy"),
    "ahli": ("sky", "group student job_senesi owl key lock door handshake calendar clock ok_mark ng_mark trash gift backpack"),
    "akses": ("mint", "globe ticket lock key door stopwatch hourglass phone computer tablet map compass plane island sailboat"),
    "ujian": ("pink", "test_tube microscope clipboard chart target compass gear mail speech star medal trophy thumbs_up raise_hand bulb"),
    "log": ("grape", "paper notebook clock calendar folder save magnifier computer phone globe map key lock hourglass printer"),
}


def stage_html(scene, title, sub="", kicker="", pill=""):
    """`title`, `sub`, `kicker` and `pill` must already be safe HTML."""
    tone, names = SCENES[scene]
    cast = "".join(f'<img alt="" src="{url(n)}" style="--s:{58 + (k * 7) % 22}px;--d:{(k * .37) % 2.6:.2f}s;--t:{2.2 + (k * 3 % 5) * .25:.2f}s">'
                   for k, n in enumerate(names.split()) if has(n))
    return (f'<div class="ks-stage {tone if tone != "sky" else ""}"><span class="ks-sun"></span><i class="ks-cloud c1"></i><i class="ks-cloud c2"></i>'
            f'<i class="ks-cloud c3"></i><div class="ks-copy">{f"<span class=ks-kick>{kicker}</span>" if kicker else ""}'
            f'<div class="ks-title">{title}</div>{f"<div class=ks-sub>{sub}</div>" if sub else ""}'
            f'{f"<div class=ks-pill>{pill}</div>" if pill else ""}</div><div class="ks-cast" aria-hidden="true">{cast}</div></div>')


def stage(scene, title, sub="", kicker="", pill=""):
    st.html(stage_html(scene, title, sub, kicker, pill))
