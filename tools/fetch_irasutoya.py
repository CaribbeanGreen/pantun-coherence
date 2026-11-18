"""Download the Irasutoya pictures this app uses (they are not stored on GitHub: the site's terms forbid redistribution).

    python tools/fetch_irasutoya.py            # fetch what is missing, using assets/irasutoya/catalog.json
    python tools/fetch_irasutoya.py --search   # also look up catalog entries that have no picture chosen yet

Originals go to assets/irasutoya/, small copies for the web page to static/i/. Each file is re-saved through Pillow,
so only real image data is kept. The script waits between requests to be polite to the site.
"""

import io
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
ORIGINALS = ROOT / "assets" / "irasutoya"
SMALL = ROOT / "static" / "i"
CATALOG = ORIGINALS / "catalog.json"
HOSTS = ("blogger.googleusercontent.com", "bp.blogspot.com", "1.bp.blogspot.com", "2.bp.blogspot.com",
         "3.bp.blogspot.com", "4.bp.blogspot.com")
AGENT = {"User-Agent": "Mozilla/5.0 (course project image fetch)"}
WAIT = 0.7


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=AGENT), timeout=30) as r:
        return r.read()


def search(query, n=15):
    """[(title, page, image url)] for a search on the site, using its public Blogger feed. Shortest title first:
    the plainest picture of a thing usually has the shortest name."""
    url = ("https://www.irasutoya.com/feeds/posts/default?alt=json&max-results=" + str(n) + "&q="
           + urllib.parse.quote(query))
    out = []
    for e in json.loads(get(url))["feed"].get("entry", []):
        body = e.get("content", {}).get("$t", "")
        imgs = re.findall(r'src="(https://[^"]+?\.(?:png|PNG))"', body)
        page = next((l["href"] for l in e["link"] if l["rel"] == "alternate"), "")
        if imgs:
            out.append((e["title"]["$t"], page, imgs[0]))
    return sorted(out, key=lambda x: len(x[0]))


def full_size(url):
    return re.sub(r"/s\d+(-[a-z0-9-]+)?/", "/s800/", url)


def save(name, url):
    if urllib.parse.urlparse(url).hostname not in HOSTS:
        raise ValueError(f"unexpected image host: {url}")
    im = Image.open(io.BytesIO(get(full_size(url))))
    im.load()
    im = im.convert("RGBA")
    ORIGINALS.mkdir(parents=True, exist_ok=True)
    im.save(ORIGINALS / f"{name}.png", optimize=True)


def make_small(name):
    SMALL.mkdir(parents=True, exist_ok=True)
    im = Image.open(ORIGINALS / f"{name}.png").convert("RGBA")
    box = im.getbbox()                    # trim empty margins so small icons look as large as possible
    if box:
        im = im.crop(box)
    im.thumbnail((220, 220))
    im.save(SMALL / f"{name}.png", optimize=True)


def main():
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    for name, item in catalog.items():
        if "from" in item:                 # made from another picture, e.g. the same arrow turned round
            continue
        if "--search" in sys.argv and not item.get("image"):
            hits = search(item["q"])
            pick = hits[min(item.get("pick", 0), len(hits) - 1)] if hits else None
            if not pick:
                print("no result:", name, item["q"])
                continue
            item.update(title=pick[0], page=pick[1], image=pick[2])
            CATALOG.write_text(json.dumps(catalog, ensure_ascii=False, indent=1), encoding="utf-8")
            time.sleep(WAIT)
        if not item.get("image"):
            continue
        if not (ORIGINALS / f"{name}.png").exists():
            try:
                save(name, item["image"])
                print("saved", name)
            except Exception as e:             # one bad picture should not stop the rest
                print("FAILED", name, e)
                continue
            time.sleep(WAIT)
        if not (SMALL / f"{name}.png").exists():
            make_small(name)
    for name, item in catalog.items():
        if "from" in item and (ORIGINALS / f"{item['from']}.png").exists():
            Image.open(ORIGINALS / f"{item['from']}.png").convert("RGBA").rotate(item["rotate"], expand=True).save(
                ORIGINALS / f"{name}.png", optimize=True)
            make_small(name)
    write_credits(catalog)


def write_credits(catalog):
    rows = "".join(f"| {n}.png | {i.get('title', '')} | {i.get('page', '')} |\n" for n, i in sorted(catalog.items()) if i.get("page"))
    (ORIGINALS / "CREDITS.md").write_text(
        "# Illustrations: いらすとや (Irasutoya)\n\n"
        "All images are by いらすとや (https://www.irasutoya.com/), used under its terms "
        "(https://www.irasutoya.com/p/terms.html): free to use, copyright kept by the author, no redistribution.\n"
        "This is a non-commercial course project (CSC575), so the limit of 20 images per work for commercial use does "
        "not apply. **If the project ever becomes a paid product, this many pictures would exceed that limit: re-check "
        "the terms first.**\n\nThe image files are in .gitignore and are **not** published on GitHub; run "
        "`python tools/fetch_irasutoya.py` to download them. The tutorial videos show some of them as part of the "
        "app's screens.\n\n| File | Illustration | Page |\n|---|---|---|\n" + rows, encoding="utf-8")


if __name__ == "__main__":
    main()
