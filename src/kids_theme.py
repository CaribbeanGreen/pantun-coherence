"""The site's look: bright, bouncy and friendly, like a children's TV show, with Irasutoya pictures as the icons.

CSS  styles every Streamlit widget (chunky buttons, sticker-like cards, sky background).
JS   turns Streamlit's built-in icons into Irasutoya pictures (it only adds a background image, so if a picture is
     missing the page still works).
"""

import json

# Streamlit icon name -> picture in static/i/
MATERIAL = {
    "menu_book": "book_open_yoko", "school": "backpack", "co_present": "job_senesi", "science": "microscope",
    "rate_review": "clipboard", "share": "globe", "search": "magnifier", "edit": "pencil", "help": "bulb",
    "group_add": "group", "history": "clock", "login": "door", "logout": "door", "check_circle": "ok_mark",
    "check": "ok_mark", "task_alt": "ok_mark", "rule": "clipboard", "save": "save", "error": "warning",
    "warning": "warning", "send": "plane", "download": "arrow_down", "upload": "arrow_up", "upload_file": "folder",
    "picture_as_pdf": "paper", "description": "paper", "add_circle": "gift", "add": "gift", "forum": "raise_hand",
    "bar_chart": "chart", "play_arrow": "play", "play_circle": "play", "movie": "video", "touch_app": "raise_hand",
    "flag": "megaphone", "inbox": "box_kara_hako", "key": "key", "password": "key", "person_remove": "trash",
    "group_remove": "trash", "delete": "trash", "tour": "map", "lock": "lock", "lock_open": "key",
    "person_add": "gift", "hourglass_top": "hourglass", "timer": "stopwatch", "block": "ng_mark", "close": "ng_mark",
    "pause_circle": "stopwatch", "swap_horiz": "swap", "badge": "student", "tune": "compass",
}

_JS = r"""<script>
(() => {
  if (window.__czIcons) return;
  window.__czIcons = 1;
  const map = __MAP__;
  const skip = "[data-testid=stElementToolbar],[data-testid=stDataFrame],[data-testid=stHeaderActionElements]";
  const run = () => document.querySelectorAll("[data-testid=stIconMaterial]").forEach((e) => {
    const pic = map[(e.textContent || "").trim()];
    if (pic && !e.closest(skip)) {
      if (e.dataset.czi !== pic) {
        e.dataset.czi = pic;
        e.classList.add("cz-mi");
        e.style.backgroundImage = "url(/app/static/i/" + pic + ".png)";
      }
    } else if (e.dataset.czi) {
      delete e.dataset.czi;
      e.classList.remove("cz-mi");
      e.style.backgroundImage = "";
    }
  });
  let timer;
  new MutationObserver(() => { clearTimeout(timer); timer = setTimeout(run, 30); })
    .observe(document.body, { subtree: true, childList: true, characterData: true });
  run();
})();
</script>"""
JS = _JS.replace("__MAP__", json.dumps(MATERIAL))

CSS = """<style>
@import url('https://fonts.googleapis.com/css2?family=Baloo+2:wght@600;700;800&family=Nunito:wght@600;700;800;900&display=swap');
:root { --ink: #17324D; --coral: #FF6B5E; --sun: #FFC83D; --sky: #2AA7E0; --grass: #35B84B; --grape: #9B5DE5; --pink: #FF7EB6;
        --line: #BDE7FF; }
@keyframes ks-hop { 0%, 62%, 100% { transform: translateY(0) scale(1, 1); } 70% { transform: translateY(0) scale(1.08, .9); }
                    82% { transform: translateY(-15px) scale(.96, 1.06); } 92% { transform: translateY(0) scale(1.05, .95); } }
@keyframes ks-drift { from { transform: translateX(-16px); } to { transform: translateX(22px); } }
@keyframes ks-spin { to { transform: rotate(360deg); } }
@keyframes ks-wig { 0%, 100% { transform: rotate(0); } 25% { transform: rotate(-12deg) scale(1.15); } 70% { transform: rotate(10deg) scale(1.15); } }
@keyframes ks-in { from { opacity: 0; transform: translateY(16px) scale(.97); } to { opacity: 1; transform: none; } }

.stApp { color: var(--ink);
  background: radial-gradient(circle at 12px 12px, rgba(255, 200, 61, .42) 0 3px, transparent 4px) 0 0 / 74px 74px,
              radial-gradient(circle at 50px 46px, rgba(42, 167, 224, .22) 0 3px, transparent 4px) 0 0 / 74px 74px,
              linear-gradient(180deg, #D8F4FF 0, #F2FBFF 240px, #FFF9E6 620px, #FFF3CF 100%) !important;
  background-attachment: fixed !important; }
.stApp, .stApp p, .stApp label, .stApp input, .stApp textarea, .stApp button, .stApp li { font-family: 'Nunito', sans-serif; }
.stApp p, .stApp label { font-weight: 700; }
.stApp h1, .stApp h2, .stApp h3, .stApp h4 { font-family: 'Baloo 2', 'Nunito', sans-serif !important; color: var(--ink); font-weight: 800 !important; }
[data-testid="stHeader"] { background: rgba(255, 255, 255, .94) !important; border-bottom: 0 !important; }
[data-testid="stHeader"]::after { opacity: 1 !important; height: 6px !important; bottom: -6px !important;
  background: linear-gradient(90deg, var(--coral) 0 20%, var(--sun) 0 40%, var(--grass) 0 60%, var(--sky) 0 80%, var(--grape) 0) !important; }
[data-testid="stHeader"] a { font-weight: 800 !important; border-radius: 14px !important; }
[data-testid="stMainBlockContainer"] { max-width: 1240px; }

/* Irasutoya pictures used as icons: little stickers with a white edge */
img[src*="/static/i/"] { filter: drop-shadow(1.5px 0 #fff) drop-shadow(-1.5px 0 #fff) drop-shadow(0 1.5px #fff) drop-shadow(0 -1.5px #fff)
                                  drop-shadow(0 2px 1px rgba(23, 50, 77, .2)); }
[data-testid="stMarkdownContainer"] img[src*="/static/i/"], img.cz-i { display: inline-block !important; width: auto !important;
  height: 1.75em !important; min-width: 1.75em; max-height: none !important; max-width: 1.75em !important; object-fit: contain; vertical-align: -.5em; margin: 0 .3em 0 .05em; }
h1 img[src*="/static/i/"], h2 img[src*="/static/i/"], h3 img[src*="/static/i/"] { height: 1.25em !important; min-width: 1.25em; max-width: 1.25em !important; vertical-align: -.25em; }
section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p { color: #fff !important; }
.cz-mi { display: inline-block !important; width: 27px !important; height: 27px !important; font-size: 0 !important; color: transparent !important;
  overflow: hidden; flex: none; background: center / contain no-repeat;
  filter: drop-shadow(1px 0 #fff) drop-shadow(-1px 0 #fff) drop-shadow(0 1px #fff) drop-shadow(0 -1px #fff); }
button:hover img[src*="/static/i/"], button:hover .cz-mi, [role="tab"]:hover img[src*="/static/i/"] { animation: ks-wig .55s ease; }

/* Chunky game-like buttons */
.stButton button, .stDownloadButton button, .stFormSubmitButton button, .stPopover button, [data-testid="stPopoverButton"] {
  min-height: 46px; padding: 6px 18px !important; border-radius: 18px !important; border: 3px solid var(--line) !important; background: #fff !important;
  color: var(--ink) !important; font-weight: 900 !important; box-shadow: 0 5px 0 #A9DCF7 !important;
  transition: transform .09s ease, box-shadow .09s ease !important; }
.stButton button p, .stDownloadButton button p, .stFormSubmitButton button p, .stPopover button p { font-weight: 900 !important; }
.stButton button:hover, .stDownloadButton button:hover, .stFormSubmitButton button:hover, .stPopover button:hover {
  transform: translateY(-2px) !important; box-shadow: 0 7px 0 #A9DCF7 !important; background: #F1FBFF !important; }
.stButton button:active, .stDownloadButton button:active, .stFormSubmitButton button:active, .stPopover button:active {
  transform: translateY(4px) !important; box-shadow: 0 1px 0 #A9DCF7 !important; }
.stButton button[kind="primary"], .stFormSubmitButton button[kind*="rimary"], .stDownloadButton button[kind="primary"] {
  background: #1E9A50 !important; border-color: #1E9A50 !important; color: #fff !important; box-shadow: 0 5px 0 #127039 !important; }
.stButton button[kind="primary"] p, .stFormSubmitButton button[kind*="rimary"] p { color: #fff !important; }
.stButton button[kind="primary"]:hover, .stFormSubmitButton button[kind*="rimary"]:hover { background: #22AD5A !important; box-shadow: 0 7px 0 #127039 !important; }
.stButton button[kind="primary"]:active, .stFormSubmitButton button[kind*="rimary"]:active { box-shadow: 0 1px 0 #127039 !important; }
.stButton button[kind="tertiary"] { min-height: 36px; border: 0 !important; background: transparent !important; box-shadow: none !important; padding: 2px 8px !important; }
.stButton button[kind="tertiary"]:hover { background: #FFF1BD !important; box-shadow: none !important; transform: none !important; }

/* Tabs and choice buttons: big pills */
.stTabs [role="tablist"] { gap: 10px; padding: 6px 2px 12px; border: 0 !important; }
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] { display: none !important; }
.stTabs [role="tab"] { height: auto; padding: 7px 18px !important; border-radius: 99px; background: #fff; border: 3px solid var(--line);
  box-shadow: 0 4px 0 #A9DCF7; transition: transform .1s ease; }
.stTabs [role="tab"] p { font-size: 1.04rem !important; font-weight: 900 !important; color: var(--ink) !important; }
.stTabs [role="tab"]:hover { transform: translateY(-2px); }
.stTabs [role="tab"][aria-selected="true"] { background: var(--sun); border-color: #F2A900; box-shadow: 0 4px 0 #D99400; }
[data-testid="stButtonGroup"] button { border: 3px solid var(--line) !important; font-weight: 800 !important; background: #fff !important; }
[data-testid="stButtonGroup"] button[kind*="Active"] { background: var(--sun) !important; border-color: #F2A900 !important; color: var(--ink) !important; }
[data-testid="stButtonGroup"] button[kind*="Active"] p { color: var(--ink) !important; }

/* Cards, inputs and boxes: thick soft outlines */
[data-testid="stVerticalBlockBorderWrapper"], .stVerticalBlock[class*="st-key-"][data-testid] { border-radius: 24px; }
div[data-testid="stLayoutWrapper"] > [data-testid="stVerticalBlock"][style*="border"], [data-testid="stVerticalBlockBorderWrapper"] {
  background: rgba(255, 255, 255, .94) !important; border: 3px solid var(--line) !important; box-shadow: 0 6px 0 #CDEEFF; backdrop-filter: none !important; }
[data-testid="stForm"] { padding: 16px !important; border: 3px solid var(--line) !important; border-radius: 24px !important; background: rgba(255, 255, 255, .94); box-shadow: 0 6px 0 #CDEEFF; }
.stTextInput [data-baseweb="input"], .stTextArea [data-baseweb="textarea"], [data-baseweb="select"] > div {
  border: 3px solid var(--line) !important; border-radius: 16px !important; background: #fff !important; }
.stTextInput [data-baseweb="input"]:focus-within, .stTextArea [data-baseweb="textarea"]:focus-within { border-color: var(--sun) !important; box-shadow: 0 0 0 4px rgba(255, 200, 61, .3) !important; }
[data-testid="stExpander"] details { border: 3px solid var(--line) !important; border-radius: 20px !important; background: #fff; }
[data-testid="stExpander"] summary p { font-weight: 900 !important; }
[data-testid="stAlert"] > div { border-radius: 18px !important; font-weight: 800; }
[data-testid="stDataFrame"] { border: 3px solid var(--line); border-radius: 18px; overflow: hidden; background: #fff; }
[data-testid="stMetric"] { border: 3px solid var(--line) !important; border-radius: 22px !important; background: #fff !important; box-shadow: 0 5px 0 #CDEEFF; padding: 12px 16px !important; }
[data-testid="stMetricValue"] { font-family: 'Baloo 2', sans-serif !important; color: var(--sky) !important; }
[data-testid="stMetricLabel"] p { font-weight: 800 !important; }
[data-testid="stProgress"] [role="progressbar"] > div > div > div { background: linear-gradient(90deg, var(--coral), var(--sun), var(--grass)) !important; }
[data-testid="stDialog"] [role="dialog"] { border: 5px solid var(--sun) !important; border-radius: 28px !important; }
[data-testid="stCaptionContainer"] p { font-weight: 700; color: #47627A !important; }

/* Show-opening stage at the top of every section */
.ks-stage { --a: #63D2FF; --b: #DDF7FF; --h1: #79DB55; --h2: #58C13B; --edge: #2F8F26; position: relative; overflow: hidden; border: 5px solid #fff; border-radius: 30px;
  min-height: 230px; padding: 20px 28px 0; margin: 2px 0 10px; box-shadow: 0 8px 0 var(--edge), 0 16px 26px rgba(23, 50, 77, .14);
  background: radial-gradient(62% 86px at 18% 100%, var(--h1) 98%, transparent 100%), radial-gradient(70% 104px at 84% 100%, var(--h2) 98%, transparent 100%),
              linear-gradient(180deg, var(--a), var(--b)); animation: ks-in .45s cubic-bezier(.2, 1.3, .4, 1) both; }
.ks-stage.sunset { --a: #FFAA5E; --b: #FFEFB5; --h1: #A5DE4F; --h2: #7CCB42; --edge: #5C9D2C; }
.ks-stage.grape { --a: #B28DFF; --b: #F0E4FF; --h1: #7FE3B5; --h2: #55CC98; --edge: #2E9A6C; }
.ks-stage.mint { --a: #5FE0C5; --b: #DFFCF2; --h1: #FFD65C; --h2: #FFC02E; --edge: #D08C00; }
.ks-stage.pink { --a: #FF96C3; --b: #FFE7F2; --h1: #8EDC5A; --h2: #68C944; --edge: #438F2A; }
.ks-sun { position: absolute; right: 34px; top: -26px; width: 104px; height: 104px; border-radius: 50%; background: #FFD84D; box-shadow: 0 0 0 10px rgba(255, 216, 77, .35); }
.ks-sun::before { content: ""; position: absolute; inset: -24px; border-radius: 50%; animation: ks-spin 24s linear infinite;
  background: repeating-conic-gradient(rgba(255, 216, 77, .75) 0 12deg, transparent 12deg 30deg);
  -webkit-mask: radial-gradient(circle, transparent 62%, #000 63%); mask: radial-gradient(circle, transparent 62%, #000 63%); }
.ks-cloud { position: absolute; width: 74px; height: 22px; border-radius: 22px; background: #fff; opacity: .92; animation: ks-drift 7s ease-in-out infinite alternate; }
.ks-cloud::before, .ks-cloud::after { content: ""; position: absolute; border-radius: 50%; background: #fff; }
.ks-cloud::before { left: 12px; top: -14px; width: 28px; height: 28px; } .ks-cloud::after { left: 34px; top: -20px; width: 34px; height: 34px; }
.ks-cloud.c1 { left: 56%; top: 34px; } .ks-cloud.c2 { left: 73%; top: 76px; transform: scale(.8); animation-duration: 9s; } .ks-cloud.c3 { left: 42%; top: 18px; animation-duration: 11s; opacity: .7; }
.ks-copy { position: relative; z-index: 2; max-width: 74%; }
.ks-kick { display: inline-block; padding: 1px 13px; border-radius: 99px; background: #fff; color: var(--ink); font-weight: 900; font-size: .84rem; box-shadow: 0 3px 0 rgba(23, 50, 77, .18); }
.ks-title { margin: 3px 0 0; font: 800 clamp(2rem, 4.4vw, 3.2rem)/1.08 'Baloo 2', 'Nunito', sans-serif; color: #fff;
  -webkit-text-stroke: 7px var(--ink); paint-order: stroke fill; text-shadow: 0 5px 0 var(--ink); letter-spacing: .3px; }
.ks-sub { margin-top: 7px; color: var(--ink); font-size: 1.04rem; font-weight: 800; }
.ks-sub b { color: #C93A2E; }
.ks-pill { display: inline-block; margin-top: 6px; padding: 2px 11px; border-radius: 99px; background: rgba(255, 255, 255, .85); font-size: .8rem; font-weight: 800; }
.ks-cast { position: relative; z-index: 2; display: flex; align-items: flex-end; gap: 3px; height: 86px; margin-top: 10px; padding-bottom: 7px; }
.ks-cast img { flex: 1 1 0; min-width: 0; height: var(--s); object-fit: contain; object-position: bottom; transform-origin: 50% 100%; animation: ks-hop var(--t) ease-in-out var(--d) infinite; }

/* Pop-up heading used on results */
.ks-banner { display: flex; align-items: center; gap: 14px; padding: 12px 18px; border: 4px solid #fff; border-radius: 24px; background: linear-gradient(100deg, var(--coral), #FF9B4A);
  box-shadow: 0 6px 0 #C94A3F; animation: cz-popin .55s cubic-bezier(.2, 1.4, .4, 1) both; }
.ks-banner img { height: 66px !important; width: auto; animation: ks-hop 2.1s ease-in-out infinite; }
.ks-banner small { color: #fff; font-weight: 900; } .ks-banner div div { color: #fff; font: 800 1.9rem/1.1 'Baloo 2', sans-serif; text-shadow: 0 2px 0 rgba(120, 30, 20, .45); }

@media (max-width: 700px) {
  .ks-stage { padding: 15px 15px 0; min-height: 0; border-radius: 24px; }
  .ks-copy { max-width: 100%; } .ks-title { -webkit-text-stroke-width: 5px; } .ks-sun { width: 62px; height: 62px; right: 12px; top: -16px; }
  .ks-cloud { display: none; } .ks-cast { flex-wrap: wrap; height: auto; justify-content: center; }
  .ks-cast img { flex: 0 0 11.5%; width: 11.5%; height: 38px; }
}
@media (prefers-reduced-motion: reduce) { .ks-cast img, .ks-cloud, .ks-sun::before { animation: none !important; } }
</style>"""
