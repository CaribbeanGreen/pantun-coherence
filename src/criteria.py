"""Traditional criteria of a pantun empat kerat that can be checked by rule.

Sources (see docs/related_work.md, section 5):
  - Johari Yahaya (2015, USM MA thesis, p. 15): pantun have middle and end rhyme
    (rima tengah dan rima akhir) a-b-a-b; a high-quality pantun needs well-found end
    rhymes and well-chosen symbols and words (p. 12).
  - Daillie (1990), cited by Johari (2015) and Juffri (2009): the pembayang draws on
    nature and everyday life (land, garden, paddy field, river, sea, forest, trees,
    fruits, animals, birds, fish, simple everyday things).
  - School / literary guides on pantun form: 8-12 syllables per line (about 4-5 words).

These checks describe FORM and CONVENTION. They are not a judgement of quality, and the
link through symbol and metaphor (perlambangan, kiasan) cannot be checked by rule.
"""

import re

from src.rhyme import pair_score, rime

# ---------------------------------------------------------------------------
# 1. Syllables (suku kata)
# ---------------------------------------------------------------------------
# Malay spelling is close to pronunciation: roughly one syllable per vowel.
# Exception: the diphthongs ai / au / oi at the END of a word are one syllable
# (pan-tai, pu-lau, am-boi), while inside a word they are usually two (ba-ik, da-un).

def syllables_in_word(word):
    word = word.lower()
    count = len(re.findall(r"[aeiou]", word))
    if re.search(r"(ai|au|oi)$", word):
        count -= 1
    return max(count, 1) if re.search(r"[a-z]", word) else 0


def syllables_in_line(line):
    words = re.findall(r"[a-z]+", line.lower())   # hyphenated words count both parts
    return sum(syllables_in_word(w) for w in words)


# ---------------------------------------------------------------------------
# 2. Middle rhyme (rima tengah)
# ---------------------------------------------------------------------------
# A line of a pantun is spoken in two halves with a pause in the middle. The "middle"
# word is the last word before that pause, e.g. "Pisang EMAS / dibawa belayar",
# "Masak SEBIJI / di atas peti". We put the pause where the syllables are closest
# to half of the line.

def middle_word(line):
    words = re.findall(r"[a-z]+(?:-[a-z]+)*", line.lower())
    if len(words) < 2:
        return ""
    counts = [syllables_in_line(w) for w in words]
    half = sum(counts) / 2
    running, best, best_gap = 0, 0, float("inf")
    for i, c in enumerate(counts[:-1]):        # the pause cannot come after the last word
        running += c
        if abs(running - half) < best_gap:
            best, best_gap = i, abs(running - half)
    return words[best].split("-")[-1]


def middle_pair_score(line_a, line_b):
    """Same scoring as end rhyme (1 / 0.5 / 0), applied to the middle words."""
    return pair_score(middle_word(line_a), middle_word(line_b))


# ---------------------------------------------------------------------------
# 3. Imagery from nature and daily life in the pembayang (alam)
# ---------------------------------------------------------------------------
# Word list built from Daillie's description of what pembayang draw on. It is a
# heuristic: it can miss words and some words also appear in maksud. Phase 3
# checks whether it actually separates pembayang from maksud.
NATURE_AND_DAILY_LIFE = set("""
pisang padi pinang sirih bunga mawar melati melur cempaka kenanga kemboja teratai tanjung
kelapa nyiur pandan tebu rotan buluh nangka durian rambutan manggis cempedak limau asam
pauh selasih keladi labu lada halia kunyit serai kangkung rumput lalang kayu pohon pokok
daun akar ranting dahan buah biji putik kuntum benih pucuk batang tangkai kulit getah
sagu jagung ubi keledek bayam petola peria terung timun kacang bendi cili tomato betik
jambu mangga ciku duku langsat salak pulasan cermai kedondong belimbing petai jering
mengkudu kemunting senduduk beringin meranti cengal jati pulai merbau ara
burung merpati tekukur murai pipit helang gagak bangau enggang kenari jentayu belatuk
punai serindit ayam itik angsa ikan sepat haruan keli tenggiri belanak kembung todak
udang ketam siput kerang penyu buaya ular harimau gajah rusa kancil kera monyet beruk
lembu kerbau kambing kucing anjing tikus semut lebah rama-rama kupu-kupu kumbang belalang
cengkerik katak kodok lintah nyamuk lalat pelanduk tupai musang
laut pantai pulau sungai kuala muara tasik paya sawah bendang ladang kebun hutan rimba
gunung bukit lembah tanjung teluk selat ombak gelombang arus pasir batu tanah air
hujan angin ribut petir guruh awan langit bulan bintang matahari mentari embun kabus pelangi
pagi petang senja malam fajar subuh
perahu sampan kapal bahtera layar dayung kolek rakit jala pukat pancing kail bubu
rumah pondok dangau teratak tangga tingkap pintu atap lantai serambi anjung beranda
peti dulang talam pinggan mangkuk cawan periuk kuali tempayan buyung kendi labu
kain baju sarung selendang tudung songkok tikar bantal tilam kelambu
pisau parang kapak cangkul tajak sabit lembing keris tombak
pasar kedai pekan kampung desa negeri kota simpang jalan titi jambatan
""".split())


def has_nature_imagery(text):
    words = set(re.findall(r"[a-z]+(?:-[a-z]+)*", text.lower()))
    parts = {p for w in words for p in w.split("-")}
    return sorted((words | parts) & NATURE_AND_DAILY_LIFE)


# ---------------------------------------------------------------------------
# Checklist
# ---------------------------------------------------------------------------

def checklist(lines):
    """Rule-based checks for a cleaned 4-line pantun.

    Returns a list of dicts: name, simple (child-friendly name), passed (bool),
    detail (short text), source.
    """
    syl = [syllables_in_line(line) for line in lines]
    end = [pair_score(lines[0], lines[2]), pair_score(lines[1], lines[3])]
    mid = [middle_pair_score(lines[0], lines[2]), middle_pair_score(lines[1], lines[3])]
    images = has_nature_imagery(" ".join(lines[:2]))
    mids = [middle_word(line) for line in lines]
    return [
        {"name": "8–12 syllables per line", "simple": "Each line is not too short or too long",
         "passed": all(8 <= s <= 12 for s in syl),
         "detail": "syllables: " + ", ".join(str(s) for s in syl),
         "source": "Pantun form guides (8–12 suku kata)"},
        {"name": "End rhyme a-b-a-b (rima akhir)", "simple": "The line endings rhyme",
         "passed": min(end) >= 0.5,
         "detail": f"line 1–3: -{rime(lines[0].split()[-1].lower())} / -{rime(lines[2].split()[-1].lower())}; "
                   f"line 2–4: -{rime(lines[1].split()[-1].lower())} / -{rime(lines[3].split()[-1].lower())}",
         "source": "Johari Yahaya (2015), p. 15"},
        {"name": "Middle rhyme a-b-a-b (rima tengah)", "simple": "The middle words rhyme too",
         "passed": min(mid) >= 0.5,
         "detail": f"middle words: {mids[0]} / {mids[2]}, {mids[1]} / {mids[3]}",
         "source": "Johari Yahaya (2015), p. 15"},
        {"name": "Pembayang uses nature / daily-life images (alam)",
         "simple": "The picture part uses things from nature or daily life",
         "passed": bool(images),
         "detail": ("found: " + ", ".join(images)) if images else "no nature / daily-life words found",
         "source": "Daillie (1990), via Johari (2015)"},
    ]
