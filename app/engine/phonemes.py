"""
Phoneme inventory + English grapheme-to-phoneme for the AsukaRVC-SVC singer.

Everything here is dependency free (stdlib only) so the app can boot on a bare
Python install.  The acoustic table is tuned for 16 kHz signals (RVC input rate).
"""

from __future__ import annotations

import os
import re

# --------------------------------------------------------------------------- #
# Acoustic inventory
# --------------------------------------------------------------------------- #
# kind: vowel | diph | fric | stop | nasal | liquid | glide | silence
# entry: f1, f2, f3, bw1, bw2, bw3, voiced, noise, noise_f, noise_bw, dur, amp
# dur is the nominal articulation length in seconds (vowels use the remaining
# note time; consonants are scheduled first).

VOWELS = {
    "AA": (730, 1090, 2440, 90, 110, 150),
    "AE": (660, 1720, 2410, 90, 120, 160),
    "AH": (640, 1190, 2390, 90, 110, 150),
    "AO": (570, 840, 2410, 90, 100, 150),
    "EH": (530, 1840, 2480, 90, 120, 160),
    "ER": (490, 1350, 1690, 80, 110, 150),
    "IH": (390, 1990, 2550, 80, 130, 170),
    "IY": (270, 2290, 3010, 70, 140, 180),
    "UH": (440, 1020, 2240, 90, 110, 150),
    "UW": (300, 870, 2240, 80, 100, 150),
    "AX": (500, 1500, 2500, 110, 140, 180),  # reduced / schwa
}

DIPHTHONGS = {
    "AY": ((660, 1700, 2400), (400, 1900, 2550)),
    "EY": ((530, 1840, 2480), (350, 2200, 2900)),
    "OW": ((570, 840, 2410), (400, 900, 2300)),
    "OY": ((570, 840, 2410), (400, 1900, 2500)),
    "AW": ((660, 1700, 2400), (500, 900, 2300)),
}

CONSONANTS = {
    #        f1   f2   f3   bw1 bw2 bw3  voiced noise nf    nbw  kind    dur
    "P": (300, 900, 2200, 120, 200, 250, 0.0, 0.55, 1500, 1200, "stop", 0.075),
    "B": (300, 900, 2200, 120, 200, 250, 0.55, 0.35, 1200, 1000, "stop", 0.070),
    "T": (300, 1700, 2600, 120, 200, 250, 0.0, 0.60, 4200, 2000, "stop", 0.075),
    "D": (300, 1700, 2600, 120, 200, 250, 0.55, 0.35, 3200, 1800, "stop", 0.070),
    "K": (300, 1800, 2600, 120, 200, 250, 0.0, 0.60, 2600, 1600, "stop", 0.080),
    "G": (300, 1800, 2600, 120, 200, 250, 0.55, 0.35, 2200, 1500, "stop", 0.075),
    "F": (400, 1300, 2400, 140, 220, 300, 0.0, 0.75, 4800, 2200, "fric", 0.095),
    "V": (400, 1300, 2400, 140, 220, 300, 0.35, 0.55, 4200, 2000, "fric", 0.085),
    "TH": (400, 1600, 2600, 140, 220, 300, 0.0, 0.70, 5200, 2400, "fric", 0.090),
    "DH": (400, 1600, 2600, 140, 220, 300, 0.35, 0.50, 4800, 2200, "fric", 0.080),
    "S": (320, 4200, 6200, 140, 220, 300, 0.0, 0.85, 6600, 2400, "fric", 0.100),
    "Z": (320, 4200, 6200, 140, 220, 300, 0.30, 0.70, 6200, 2200, "fric", 0.090),
    "SH": (300, 2200, 3500, 140, 220, 300, 0.0, 0.85, 3600, 1800, "fric", 0.105),
    "ZH": (300, 2200, 3500, 140, 220, 300, 0.30, 0.70, 3400, 1700, "fric", 0.095),
    "HH": (500, 1500, 2500, 160, 240, 320, 0.0, 0.65, 1800, 2200, "fric", 0.075),
    "M": (280, 900, 2200, 90, 180, 240, 1.0, 0.0, 2500, 1500, "nasal", 0.075),
    "N": (280, 1700, 2600, 90, 180, 240, 1.0, 0.0, 2800, 1500, "nasal", 0.070),
    "NG": (280, 2000, 2600, 90, 180, 240, 1.0, 0.0, 3000, 1500, "nasal", 0.075),
    "L": (360, 1300, 2700, 90, 160, 220, 1.0, 0.0, 3000, 1500, "liquid", 0.065),
    "R": (420, 1200, 1600, 90, 160, 220, 1.0, 0.0, 2500, 1500, "liquid", 0.065),
    "W": (300, 700, 2200, 90, 160, 220, 1.0, 0.0, 2200, 1500, "glide", 0.055),
    "Y": (300, 2200, 3000, 90, 160, 220, 1.0, 0.0, 3000, 1500, "glide", 0.055),
}

PHONES = {}
for _p, (_f1, _f2, _f3, _b1, _b2, _b3) in VOWELS.items():
    PHONES[_p] = dict(
        kind="vowel",
        f=(_f1, _f2, _f3),
        bw=(_b1, _b2, _b3),
        voiced=1.0,
        noise=0.0,
        noise_f=2000,
        noise_bw=1500,
        dur=1.0,
        amp=1.0,
        target=None,
    )
for _p, (_a, _b) in DIPHTHONGS.items():
    PHONES[_p] = dict(
        kind="diph",
        f=_a,
        bw=(90, 120, 160),
        voiced=1.0,
        noise=0.0,
        noise_f=2000,
        noise_bw=1500,
        dur=1.0,
        amp=1.0,
        target=_b,
    )
for _p, (_f1, _f2, _f3, _b1, _b2, _b3, _v, _n, _nf, _nb, _kind, _dur) in CONSONANTS.items():
    PHONES[_p] = dict(
        kind=_kind,
        f=(_f1, _f2, _f3),
        bw=(_b1, _b2, _b3),
        voiced=_v,
        noise=_n,
        noise_f=_nf,
        noise_bw=_nb,
        dur=_dur * 2.2,
        amp=1.0,
        target=None,
    )

# Affricates are modelled as a stop followed by a fricative at synthesis time.
AFFRICATES = {"CH": ("T", "SH"), "JH": ("D", "ZH")}

VOWEL_SET = set(VOWELS) | set(DIPHTHONGS)
SONORANT_SET = {"M", "N", "NG", "L", "R", "W", "Y"}

_LETTER_PHONES = {
    "a": "AE", "b": "B", "c": "K", "d": "D", "e": "EH", "f": "F", "g": "G",
    "h": "HH", "i": "IH", "j": "JH", "k": "K", "l": "L", "m": "M", "n": "N",
    "o": "AA", "p": "P", "q": "K", "r": "R", "s": "S", "t": "T", "u": "AH",
    "v": "V", "w": "W", "x": "K", "y": "IY", "z": "Z",
}

# A tiny lexicon for sung syllables that dictionaries often miss.
SING_LEXICON = {
    "la": ["L", "AA1"], "laa": ["L", "AA1"], "na": ["N", "AA1"], "da": ["D", "AA1"],
    "ba": ["B", "AA1"], "pa": ["P", "AA1"], "ma": ["M", "AA1"], "ra": ["R", "AA1"],
    "ta": ["T", "AA1"], "ka": ["K", "AA1"], "sa": ["S", "AA1"], "fa": ["F", "AA1"],
    "ha": ["HH", "AA1"], "ya": ["Y", "AA1"], "wa": ["W", "AA1"],
    "ah": ["AA1"], "aah": ["AA1"], "oh": ["OW1"], "ooh": ["UW1"], "oo": ["UW1"],
    "uh": ["AH1"], "eh": ["EH1"], "ih": ["IH1"], "mm": ["M"], "mmm": ["M"],
    "hmm": ["HH", "M"], "sh": ["SH"], "shh": ["SH"], "tsk": ["T", "S", "K"],
    "hey": ["HH", "EY1"], "yeah": ["Y", "AE1"], "woah": ["W", "OW1"],
    "whoa": ["W", "OW1"], "doo": ["D", "UW1"], "dum": ["D", "AH1", "M"],
    "boom": ["B", "UW1", "M"], "nanana": ["N", "AA1", "N", "AA1", "N", "AA1"],
    "lalala": ["L", "AA1", "L", "AA1", "L", "AA1"],
    "hello": ["HH", "AH0", "L", "OW1"], "goodbye": ["G", "UH1", "D", "B", "AY1"],
    "fire": ["F", "AY1", "ER0"], "higher": ["HH", "AY1", "ER0"],
    "world": ["W", "ER1", "L", "D"], "voice": ["V", "OY1", "S"],
    "dream": ["D", "R", "IY1", "M"], "sing": ["S", "IH1", "NG"],
    "song": ["S", "AO1", "NG"], "sky": ["S", "K", "AY1"],
}

# Digraphs and common endings, longest first.
_RULES = [
    ("tion", ["SH", "AH0", "N"]),
    ("sion", ["ZH", "AH0", "N"]),
    ("ough", ["AO1"]),
    ("augh", ["AO1"]),
    ("eigh", ["EY1"]),
    ("tch", ["CH"]),
    ("dge", ["JH"]),
    ("ing", ["IH1", "NG"]),
    ("ck", ["K"]),
    ("ph", ["F"]),
    ("sh", ["SH"]),
    ("ch", ["CH"]),
    ("th", ["TH"]),
    ("wh", ["W"]),
    ("ng", ["NG"]),
    ("qu", ["K", "W"]),
    ("ee", ["IY1"]),
    ("ea", ["IY1"]),
    ("oo", ["UW1"]),
    ("ou", ["AW1"]),
    ("ow", ["OW1"]),
    ("oa", ["OW1"]),
    ("oi", ["OY1"]),
    ("oy", ["OY1"]),
    ("ai", ["EY1"]),
    ("ay", ["EY1"]),
    ("au", ["AO1"]),
    ("aw", ["AO1"]),
    ("ie", ["IY1"]),
    ("ei", ["EY1"]),
    ("ue", ["UW1"]),
    ("ui", ["UW1"]),
    ("ar", ["AA1", "R"]),
    ("er", ["ER0"]),
    ("ir", ["ER0"]),
    ("or", ["AO1", "R"]),
    ("ur", ["ER0"]),
]

_LONG_VOWEL = {"a": "EY1", "e": "IY1", "i": "AY1", "o": "OW1", "u": "UW1"}
_SHORT_VOWEL = {"a": "AE1", "e": "EH1", "i": "IH1", "o": "AA1", "u": "AH1"}

_STRESS_RE = re.compile(r"[012]$")


def strip_stress(phone: str) -> str:
    return _STRESS_RE.sub("", phone)


def stress_of(phone: str) -> int:
    m = _STRESS_RE.search(phone)
    return int(m.group(0)) if m else 0


def _reduce(phone: str) -> str:
    """Turn a stressed vowel into its reduced form (used for very short notes)."""
    base = strip_stress(phone)
    if base in ("AH", "AE", "EH", "IH", "AA"):
        return "AX"
    return base


class G2P:
    """English G2P with an optional CMU dictionary and a rule based fallback."""

    def __init__(self, dict_path: str | None = None):
        self.lexicon: dict[str, list[list[str]]] = {}
        self.lexicon_size = 0
        if dict_path and os.path.isfile(dict_path):
            self._load_cmudict(dict_path)

    # -- dictionary -------------------------------------------------------- #
    def _load_cmudict(self, path: str) -> None:
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith(";;;"):
                        continue
                    if "#" in line:
                        line = line.split("#", 1)[0].strip()
                    parts = line.split()
                    if len(parts) < 2:
                        continue
                    word = parts[0].lower()
                    # The cmusphinx dump separates the word with a space, the
                    # classic file uses two spaces.  Either way the phones follow.
                    phones = [p.upper() for p in parts[1:] if re.match(r"^[A-Z]+[0-2]?$", p.upper())]
                    if not phones:
                        continue
                    # Drop alternate pronunciation markers: word(2)
                    word = re.sub(r"\(\d+\)$", "", word)
                    self.lexicon.setdefault(word, []).append(phones)
            self.lexicon_size = len(self.lexicon)
        except OSError:
            self.lexicon_size = 0

    # -- public ------------------------------------------------------------ #
    def word_to_phones(self, word: str) -> list[str]:
        """Return ARPAbet phones (with stress digits) for one word."""
        raw = word.strip()
        if not raw:
            return []
        # Explicit phoneme input:  [AH0 N S ER0]
        if raw.startswith("[") and raw.endswith("]"):
            out = []
            for token in raw[1:-1].split():
                token = token.upper()
                base = strip_stress(token)
                if base in PHONES or base in AFFRICATES:
                    out.append(token if stress_of(token) or base in PHONES else base + "0")
            return out

        clean = re.sub(r"[^a-z']", "", raw.lower()).replace("'", "")
        if not clean:
            return []
        candidates = self.lexicon.get(clean)
        if candidates:
            return list(candidates[0])
        if clean in SING_LEXICON:
            return list(SING_LEXICON[clean])
        return self._rule_g2p(clean)

    def text_to_phones(self, text: str) -> list[str]:
        out: list[str] = []
        for token in re.split(r"[\s,.;:!?]+", text):
            if token:
                out.extend(self.word_to_phones(token))
        return out

    def split_syllable(self, phones: list[str]) -> tuple[list[str], list[str], list[str]]:
        """Split a phone list into (onset, nucleus, coda)."""
        if not phones:
            return [], [], []
        first_v = next(
            (i for i, p in enumerate(phones) if strip_stress(p) in VOWEL_SET), None
        )
        if first_v is None:
            return phones, [], []
        last_v = first_v
        for i, p in enumerate(phones):
            if strip_stress(p) in VOWEL_SET:
                last_v = i
        onset = phones[:first_v]
        nucleus = phones[first_v : last_v + 1]
        coda = phones[last_v + 1 :]
        return onset, nucleus, coda

    # -- fallback rules ---------------------------------------------------- #
    def _rule_g2p(self, word: str) -> list[str]:
        # magic-e:  "name" -> EY1 M
        if (
            len(word) >= 3
            and word.endswith("e")
            and word[-2] not in "aeiouy"
            and word[-3] in "aeiou"
        ):
            word = word[:-1]
            magic = True
        else:
            magic = False

        phones: list[str] = []
        i = 0
        n = len(word)
        while i < n:
            matched = False
            for pattern, out in _RULES:
                if word.startswith(pattern, i):
                    phones.extend(out)
                    i += len(pattern)
                    matched = True
                    break
            if matched:
                continue

            ch = word[i]
            # collapse doubled consonants ("ll", "ss", ...)
            if i > 0 and ch == word[i - 1] and ch in "bcdfgklmnprstvz":
                i += 1
                continue
            if ch in "aeiouy":
                # collect the vowel cluster
                j = i
                while j < n and word[j] in "aeiouy" and j - i < 2:
                    j += 1
                cluster = word[i:j]
                if magic and j == n:
                    phones.append(_LONG_VOWEL.get(cluster[0], "IY1"))
                elif cluster in ("ee", "ea", "ie"):
                    phones.append("IY1")
                elif cluster == "oo":
                    phones.append("UW1")
                elif cluster == "ou":
                    phones.append("AW1")
                elif cluster == "ai" or cluster == "ay":
                    phones.append("EY1")
                elif cluster == "oi" or cluster == "oy":
                    phones.append("OY1")
                elif cluster == "au" or cluster == "aw":
                    phones.append("AO1")
                elif cluster == "ow":
                    phones.append("OW1")
                elif cluster == "oa":
                    phones.append("OW1")
                elif ch == "y" and i == n - 1:
                    phones.append("IY1")
                elif j == n and n > 2 and ch == "e":
                    pass  # silent final e
                elif j == n and n > 2 and ch in "aoiu":
                    phones.append({"a": "AA1", "o": "OW1", "i": "AY1", "u": "UW1"}[ch])
                else:
                    phones.append(_SHORT_VOWEL.get(ch, "AH1"))
                i = j
                continue

            if ch == "c":
                nxt = word[i + 1] if i + 1 < n else ""
                phones.append("S" if nxt in "eiy" else "K")
            elif ch == "g":
                nxt = word[i + 1] if i + 1 < n else ""
                phones.append("JH" if nxt in "eiy" else "G")
            elif ch == "s" and i == n - 1 and len(word) > 2 and word[-2] in "ptkf":
                phones.append("S")
            elif ch == "x":
                phones.extend(["K", "S"])
            elif ch in _LETTER_PHONES:
                phones.append(_LETTER_PHONES[ch])
            i += 1

        if not phones:
            phones = ["AH1"]
        # Guarantee at least one syllabic nucleus.
        if not any(strip_stress(p) in VOWEL_SET for p in phones):
            phones.insert(len(phones) // 2, "AH0")
        return phones


def phone_info(phone: str) -> dict:
    base = strip_stress(phone)
    if base in AFFRICATES:
        return PHONES[AFFRICATES[base][1]]
    return PHONES.get(base, PHONES["AX"])
