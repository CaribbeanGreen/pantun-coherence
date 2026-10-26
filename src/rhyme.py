"""Sound link between pembayang and maksud: end rhyme (rima akhir).

A pantun empat kerat normally rhymes a-b-a-b: line 1 with line 3 and line 2 with
line 4. These are exactly the two places where pembayang and maksud are tied
together by SOUND. Embedding models cannot see this, so we measure it directly.

For each pair of lines we compare the end sound of their last words:
    rime = the last vowel(s) of the word + any consonants after it
           e.g. belayar -> "ar", peti -> "i", tanjung -> "ung", pantai -> "ai"
    1.0  same rime                      (belayar / dibayar, peti / mati)
    0.5  same final consonant(s), different vowel
         (a near-rhyme, e.g. tanjung / pinang: "-ung" / "-ang")
    0.0  otherwise
Sound score (0-10) = 5 x (pair 1-3 + pair 2-4).

This is a simple spelling-based rule (Malay spelling is close to pronunciation),
not a phonetic model. It measures FORM, not whether the meaning connects:
a nonsense pantun that rhymes gets a high sound score.
"""

import re

VOWELS = "aeiou"


def last_word(line):
    words = re.findall(r"[a-z]+(?:-[a-z]+)*", line.lower())
    return words[-1].split("-")[-1] if words else ""


def rime(word):
    """'belayar' -> 'ar'; 'peti' -> 'i'; 'pantai' -> 'ai'; 'tanjung' -> 'ung'."""
    m = re.search(r"[aeiou]+[^aeiou]*$", word)
    return m.group(0) if m else word


def split_rime(r):
    """'ung' -> ('u', 'ng'); 'ai' -> ('ai', '')."""
    m = re.match(r"([aeiou]+)(.*)$", r)
    return (m.group(1), m.group(2)) if m else ("", r)


def pair_score(line_a, line_b):
    """1.0 full rhyme, 0.5 near-rhyme, 0.0 none, for two lines' last words."""
    ra, rb = rime(last_word(line_a)), rime(last_word(line_b))
    if not ra or not rb:
        return 0.0
    if ra == rb:
        return 1.0
    (va, ca), (vb, cb) = split_rime(ra), split_rime(rb)
    if ca and ca == cb:
        return 0.5
    return 0.0


def sound_score(lines):
    """0-10 sound link between pembayang (lines 1-2) and maksud (lines 3-4)."""
    return 5 * (pair_score(lines[0], lines[2]) + pair_score(lines[1], lines[3]))


def explain(lines):
    """For display: [(line no., line no., ending a, ending b, score), ...]."""
    out = []
    for a, b in [(0, 2), (1, 3)]:
        out.append((a + 1, b + 1, rime(last_word(lines[a])), rime(last_word(lines[b])),
                    pair_score(lines[a], lines[b])))
    return out
