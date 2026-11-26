"""
Saudi Geographic Naming Standards Transliteration & NLP Engine
Compliant with UNGEGN / GASGI (General Authority for Survey and Geospatial Information)
principles for Arabic-to-English romanization of Islamic places of worship in Saudi Arabia.
Loaded from canonical content/transliteration_rules.json.
"""

import json
import os
from pathlib import Path
import re
import unicodedata


def _find_rules_path() -> Path:
    env_dir = os.environ.get("MANARA_CONTENT_DIR")
    if env_dir:
        p = Path(env_dir) / "transliteration_rules.json"
        if p.exists():
            return p
    repo_root = Path(__file__).resolve().parent.parent.parent
    p = repo_root / "content" / "transliteration_rules.json"
    if p.exists():
        return p
    p = Path("content/transliteration_rules.json").resolve()
    if p.exists():
        return p
    return p


_RULES_FILE = _find_rules_path()
if _RULES_FILE.exists():
    with open(_RULES_FILE, "r", encoding="utf-8") as _f:
        _RULES = json.load(_f)
else:
    _RULES = {}

# ---------------------------------------------------------------------------
# Core Rule Dictionaries (Canonical from content/transliteration_rules.json)
# ---------------------------------------------------------------------------
TITLE_MAP = _RULES.get("titles", {})
HONORIFICS_MAP = _RULES.get("honorifics", {})
PATRONYMICS = _RULES.get("patronymics", {})
DIVINE_NAMES = _RULES.get("divine_names", {})
ABD_SPECIAL = _RULES.get("abd_special", {})
KNOWN_VOCABULARY = _RULES.get("known_vocabulary", {})
CHAR_MAP = _RULES.get("char_map", {})
WAW_ROOT_STARTS = tuple(_RULES.get("waw_root_starts", []))
NON_RELIGIOUS_TERMS = set(_RULES.get("non_religious", []))
EULOGY_PHRASES = _RULES.get("eulogies", [])

# Dynamic Abdul- forms for Divine Names
ABD_MAP = {}
for ar_name, en_trans in DIVINE_NAMES.items():
    if ar_name == "الله":
        ABD_MAP["الله"] = "Abdullah"
        ABD_MAP["لله"] = "Abdullah"
        continue
    core = en_trans.replace("Al-", "").replace("'", "")
    ABD_MAP[ar_name] = f"Abdul{core.lower()}"
    stem_ar = ar_name[2:] if ar_name.startswith("ال") else ar_name
    ABD_MAP[stem_ar] = f"Abdul{core.lower()}"

# ---------------------------------------------------------------------------
# Regex Sanitizers
# ---------------------------------------------------------------------------
_RE_TASHKEEL = re.compile(r"[ً-ٰٟ]")
_RE_TATWEEL = re.compile(r"ـ")

_EULOGY_ALTS = "|".join(re.escape(phrase).replace(r"\ ", r"\s+") for phrase in EULOGY_PHRASES)

# Handles parenthesized eulogies like "(رضي الله عنه)", "（رحمه الله）", etc.
_RE_PAREN_EULOGIES = re.compile(
    rf"\s*[(\uFF08]\s*(?:{_EULOGY_ALTS})\s*[)\uFF09]\s*",
    re.UNICODE
)

# Handles bare eulogies with word/punctuation boundaries
_RE_BARE_EULOGIES = [
    re.compile(rf"(?:^|[\s,.\-؛،(（]){re.escape(phrase).replace(r'\ ', r'\s+')}(?=[\s,.\-؛،)）]|$)", re.UNICODE)
    for phrase in EULOGY_PHRASES
]

_RE_EMPTY_PARENS = re.compile(r"\s*[(\uFF08]\s*[)\uFF09]\s*")


def clean_arabic(text: str) -> str:
    """Removes diacritics, tatweel, pious eulogies (parenthesized and bare), and normalizes spacing."""
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", str(text).strip())
    s = _RE_TASHKEEL.sub("", s)
    s = _RE_TATWEEL.sub("", s)

    # Normalize medial alef maqsura (Persian/Urdu keyboard typo) to yaa
    s = re.sub(r"ى(?=[ء-ي])", "ي", s)

    # 1. Clean parenthesized eulogies first (including parentheses)
    s = _RE_PAREN_EULOGIES.sub(" ", s)

    # 2. Clean bare eulogies
    for eulogy_re in _RE_BARE_EULOGIES:
        s = eulogy_re.sub(" ", s)

    # 3. Clean any leftover empty parentheses
    s = _RE_EMPTY_PARENS.sub(" ", s)

    return re.sub(r"\s+", " ", s).strip()


def reconstruct_arabic_morphology(stem: str) -> str:
    """
    Applies Arabic morphological pattern rules (علم الصرف) to correctly
    vowelize trilateral / quadrilateral patterns for Out-Of-Vocabulary words.
    """
    n = len(stem)
    if n < 3:
        return "".join(CHAR_MAP.get(c, c) for c in stem).capitalize()

    # 1. Pattern تَفْعِيل (Taf'eel / Taf'il): e.g. توفيق (Tawfiq), تيسير (Tayseer), تحسين (Tahseen)
    if n == 5 and stem.startswith("ت") and stem[3] == "ي":
        c1 = CHAR_MAP.get(stem[1], stem[1])
        c2 = CHAR_MAP.get(stem[2], stem[2])
        if stem[1] == "و":
            return f"Taw{c2}iq" if stem[4] == "ق" else f"Taw{c2}id"
        return f"Ta{c1}{c2}in" if stem[4] == "ن" else f"Ta{c1}{c2}eer"

    # 2. Pattern مَفْعُول (Maf'oul): e.g. محمود (Mahmoud), منصور (Mansour), مسرور (Masrour)
    if n == 5 and stem.startswith("م") and stem[3] == "و":
        c1 = CHAR_MAP.get(stem[1], stem[1])
        c2 = CHAR_MAP.get(stem[2], stem[2])
        c3 = CHAR_MAP.get(stem[4], stem[4])
        return f"Ma{c1}{c2}ou{c3}".capitalize()

    # 3. Pattern فَعِيل (Fa'eel / Fa'il): e.g. كريم (Karim), خليل (Khalil), لطيف (Latif), جميل (Jamil), سعيد (Saeed), حكيم (Hakeem), عظيم (Azeem), شهيد (Shaheed)
    if n == 4 and stem[2] == "ي":
        c1 = CHAR_MAP.get(stem[0], stem[0])
        c2 = CHAR_MAP.get(stem[1], stem[1])
        c3 = CHAR_MAP.get(stem[3], stem[3])
        return f"{c1}a{c2}i{c3}".capitalize()

    # 4. Pattern فَعُول (Fa'oul): e.g. صبور (Sabour), شكور (Shakour), غفور (Ghafour)
    if n == 4 and stem[2] == "و":
        c1 = CHAR_MAP.get(stem[0], stem[0])
        c2 = CHAR_MAP.get(stem[1], stem[1])
        c3 = CHAR_MAP.get(stem[3], stem[3])
        return f"{c1}a{c2}ou{c3}".capitalize()

    # 5. Pattern فَاعِل (Fa'il): e.g. صالح (Salih), طارق (Tariq), ناصر (Nasir), ماجد (Majid), ثابت (Thabit), سالم (Salim)
    if n == 4 and stem[1] == "ا":
        c1 = CHAR_MAP.get(stem[0], stem[0])
        c2 = CHAR_MAP.get(stem[2], stem[2])
        c3 = CHAR_MAP.get(stem[3], stem[3])
        return f"{c1}a{c2}i{c3}".capitalize()

    # 6. Pattern فَعْلَان (Fa'lan): e.g. عمران (Imran), عدنان (Adnan), حمدان (Hamdan), رضوان (Ridwan)
    if n >= 5 and stem.endswith("ان"):
        prefix = stem[:-2]
        if len(prefix) == 3:
            c1 = CHAR_MAP.get(prefix[0], prefix[0])
            c2 = CHAR_MAP.get(prefix[1], prefix[1])
            c3 = CHAR_MAP.get(prefix[2], prefix[2])
            return f"{c1}a{c2}{c3}an".capitalize()

    # 7. Pattern فَعِيلَة (Fa'eelah / Taybah): e.g. طيبة (Taybah), جميلة (Jameelah), كريمة (Karimah)
    if n == 5 and stem[2] == "ي" and stem.endswith(("ة", "ه")):
        c1 = CHAR_MAP.get(stem[0], stem[0])
        c2 = CHAR_MAP.get(stem[1], stem[1])
        return f"{c1}a{c2}bah" if stem[3] == "ب" else f"{c1}a{c2}ee{CHAR_MAP.get(stem[3], stem[3])}ah".capitalize()

    # 8. Pattern فَعْل (Fa'l / Triliteral Root): e.g. بدر (Badr), فهد (Fahd), سعد (Saad), حمد (Hamad), نصر (Nasr)
    if n == 3:
        if stem in ("أحد", "احد"):
            return "Uhud"
        c1 = CHAR_MAP.get(stem[0], stem[0])
        c2 = CHAR_MAP.get(stem[1], stem[1])
        c3 = CHAR_MAP.get(stem[2], stem[2])
        if stem[1] in ("ا", "و", "ي"):
            vowel = "a" if stem[1] == "ا" else ("ou" if stem[1] == "و" else "i")
            return f"{c1}{vowel}{c3}".capitalize()
        return f"{c1}a{c2}{c3}".capitalize()

    # Fallback letter-by-letter with vowel awareness
    out = []
    i = 0
    while i < n:
        c = stem[i]
        if c == "و" and 0 < i < n - 1 and stem[i-1] not in ("ا", "و", "ي") and stem[i+1] not in ("ا", "و", "ي"):
            out.append("ou")
        elif c == "ي" and 0 < i < n - 1 and stem[i-1] not in ("ا", "و", "ي") and stem[i+1] not in ("ا", "و", "ي"):
            out.append("i")
        elif c == "ي" and i == n - 1:
            out.append("i")
        elif c in CHAR_MAP:
            out.append(CHAR_MAP[c])
        else:
            out.append(c)
        i += 1

    return "".join(out).capitalize()


def transliterate_word(word: str) -> str:
    """Transliterates a single Arabic word according to UNGEGN / GASGI standards."""
    if not word:
        return ""

    if word in KNOWN_VOCABULARY:
        return KNOWN_VOCABULARY[word]
    if word in DIVINE_NAMES:
        return DIVINE_NAMES[word]
    if word in ABD_SPECIAL:
        return ABD_SPECIAL[word]
    if word in HONORIFICS_MAP:
        return HONORIFICS_MAP[word]
    if word in PATRONYMICS:
        return PATRONYMICS[word]

    # Orthographic variants: taa marbuta / haa
    if word.endswith("ه") and (word[:-1] + "ة") in KNOWN_VOCABULARY:
        return KNOWN_VOCABULARY[word[:-1] + "ة"]
    if word.endswith("ة") and (word[:-1] + "ه") in KNOWN_VOCABULARY:
        return KNOWN_VOCABULARY[word[:-1] + "ه"]

    has_al = False
    stem = word
    if word.startswith("ال") and len(word) > 3:
        has_al = True
        stem = word[2:]

    if stem in KNOWN_VOCABULARY:
        res = KNOWN_VOCABULARY[stem]
        return f"Al-{res}" if has_al and not res.startswith("Al-") else res
    if stem in DIVINE_NAMES:
        res = DIVINE_NAMES[stem]
        return f"Al-{res}" if has_al and not res.startswith("Al-") else res

    # Check normalized alef variants
    norm_stem = stem.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    if norm_stem in KNOWN_VOCABULARY:
        res = KNOWN_VOCABULARY[norm_stem]
        return f"Al-{res}" if has_al and not res.startswith("Al-") else res

    # Check taa marbuta variants on stem
    if norm_stem.endswith("ه") and (norm_stem[:-1] + "ة") in KNOWN_VOCABULARY:
        res = KNOWN_VOCABULARY[norm_stem[:-1] + "ة"]
        return f"Al-{res}" if has_al and not res.startswith("Al-") else res

    reconstructed = reconstruct_arabic_morphology(stem)
    if has_al:
        return f"Al-{reconstructed}"
    return reconstructed


def classify_mosque_type(name: str) -> str:
    """
    Classifies mosque type from Arabic name:
    'jamea' (Grand Mosque / Friday prayers),
    'mosque' (Standard 5-time neighborhood mosque),
    'musalla' (Prayer room, seasonal or transit facility),
    'non_religious' (False positive entity like schools/hospitals).
    """
    cleaned = clean_arabic(name)
    words = cleaned.split()
    if not words:
        return "mosque"

    if any(w in NON_RELIGIOUS_TERMS for w in words):
        return "non_religious"

    first = words[0]
    if first == "جامع" or "الجامع" in words:
        return "jamea"
    if first in ("مصلى", "مصلّى", "المصلى") or "مصلى" in words:
        return "musalla"
    return "mosque"


def transliterate_mosque_name(arabic_name: str) -> dict:
    """
    Translates/transliterates an Arabic mosque name to English according to
    Saudi Geographic Naming Standards (UNGEGN/GASGI).

    Examples:
      - 'جامع الملك فهد' -> 'King Fahd Grand Mosque'
      - 'مسجد التقوى' -> 'Al-Taqwa Mosque'
      - 'جامع الشيخ عبد العزيز الراجحي' -> 'Sheikh Abdulaziz Al-Rajhi Grand Mosque'
      - 'مسجد بلال بن رباح' -> 'Bilal bin Rabah Mosque'
      - 'مصلى العيد' -> 'Al-Eid Musalla'
      - 'مسجد الهدى والتقوى' -> 'Al-Huda and Al-Taqwa Mosque'
      - 'مسجد عمر بن الخطاب (رضي الله عنه)' -> 'Omar bin Al-Khattab Mosque'

    Returns:
      {
        'name_ar': str,
        'name_en': str,
        'type': 'jamea' | 'mosque' | 'musalla' | 'non_religious',
        'confidence': float (0.0 to 1.0)
      }
    """
    cleaned = clean_arabic(arabic_name)
    if not cleaned:
        return {"name_ar": "", "name_en": "", "type": "mosque", "confidence": 0.0}

    mosque_type = classify_mosque_type(cleaned)
    if mosque_type == "non_religious":
        return {"name_ar": cleaned, "name_en": "", "type": "non_religious", "confidence": 0.0}

    tokens = cleaned.split()
    first_word = tokens[0]

    # Determine mosque title suffix
    suffix = "Mosque"
    if first_word in TITLE_MAP:
        suffix = TITLE_MAP[first_word]
        name_tokens = tokens[1:]
    elif tokens[0] in ("جامع", "مسجد", "مصلى", "مصلّى", "روضة"):
        suffix = TITLE_MAP.get(tokens[0], "Mosque")
        name_tokens = tokens[1:]
    else:
        suffix = "Grand Mosque" if mosque_type == "jamea" else "Mosque"
        name_tokens = tokens

    # If the name is solely 'مسجد' or 'جامع' with no further tokens
    if not name_tokens:
        return {"name_ar": cleaned, "name_en": suffix, "type": mosque_type, "confidence": 0.5}

    # Pre-process tokens: split conjunction 'و' attached to words (excluding words with root 'و')
    split_tokens = []
    for t in name_tokens:
        if t.startswith("و") and not any(t.startswith(p) for p in WAW_ROOT_STARTS):
            if len(t) > 3 and (t.startswith("وال") or t.startswith("وإ") or t.startswith("وأ")):
                split_tokens.append("and")
                split_tokens.append(t[1:])
            elif t == "و":
                split_tokens.append("and")
            else:
                split_tokens.append(t)
        else:
            split_tokens.append(t)

    name_tokens = split_tokens
    processed_parts = []
    i = 0
    num_known = 0
    total_tokens = len(name_tokens)

    while i < len(name_tokens):
        current = name_tokens[i]

        if current == "and":
            processed_parts.append("and")
            num_known += 1
            i += 1
            continue

        # Check 4-token phrases
        if i + 3 < len(name_tokens):
            four_word = f"{current} {name_tokens[i+1]} {name_tokens[i+2]} {name_tokens[i+3]}"
            if four_word in HONORIFICS_MAP:
                processed_parts.append(HONORIFICS_MAP[four_word])
                num_known += 4
                i += 4
                continue

        # Check 3-token phrases
        if i + 2 < len(name_tokens):
            three_word = f"{current} {name_tokens[i+1]} {name_tokens[i+2]}"
            if three_word in HONORIFICS_MAP:
                processed_parts.append(HONORIFICS_MAP[three_word])
                num_known += 3
                i += 3
                continue
            if three_word in KNOWN_VOCABULARY:
                processed_parts.append(KNOWN_VOCABULARY[three_word])
                num_known += 3
                i += 3
                continue

        # Check 2-token compound phrases
        if i + 1 < len(name_tokens):
            two_word = f"{current} {name_tokens[i+1]}"
            if two_word in ABD_SPECIAL:
                processed_parts.append(ABD_SPECIAL[two_word])
                num_known += 2
                i += 2
                continue
            if two_word in HONORIFICS_MAP:
                processed_parts.append(HONORIFICS_MAP[two_word])
                num_known += 2
                i += 2
                continue
            if two_word in KNOWN_VOCABULARY:
                processed_parts.append(KNOWN_VOCABULARY[two_word])
                num_known += 2
                i += 2
                continue

        # Check compound "عبد" + Name
        if current in ("عبد", "العبد") and i + 1 < len(name_tokens):
            next_word = name_tokens[i+1]
            if next_word in ABD_MAP:
                processed_parts.append(ABD_MAP[next_word])
                num_known += 2
                i += 2
                continue
            core = next_word[2:] if next_word.startswith("ال") else next_word
            trans_core = transliterate_word(core)
            processed_parts.append(f"Abdul{trans_core.lower()}")
            num_known += 2
            i += 2
            continue

        # Single word lookups
        if current in ABD_SPECIAL:
            processed_parts.append(ABD_SPECIAL[current])
            num_known += 1
        elif current in HONORIFICS_MAP:
            processed_parts.append(HONORIFICS_MAP[current])
            num_known += 1
        elif current in PATRONYMICS:
            patron = PATRONYMICS[current]
            if patron == "bin" and not processed_parts:
                patron = "Bin"
            processed_parts.append(patron)
            num_known += 1
        elif current in KNOWN_VOCABULARY:
            processed_parts.append(KNOWN_VOCABULARY[current])
            num_known += 1
        elif current in DIVINE_NAMES:
            processed_parts.append(DIVINE_NAMES[current])
            num_known += 1
        else:
            trans = transliterate_word(current)
            processed_parts.append(trans)
            if trans and not any(ord(c) > 127 for c in trans):
                num_known += 0.85

        i += 1

    core_name = " ".join(processed_parts).strip()

    # Special handling for musalla with men / women
    if suffix == "Musalla":
        if "Men" in core_name:
            full_name_en = core_name.replace("Men", "Men's Musalla").strip()
            return {"name_ar": cleaned, "name_en": full_name_en, "type": mosque_type, "confidence": 0.98}
        if "Women" in core_name:
            full_name_en = core_name.replace("Women", "Women's Musalla").strip()
            return {"name_ar": cleaned, "name_en": full_name_en, "type": mosque_type, "confidence": 0.98}

    if any(core_name.lower().endswith(s.lower()) for s in ("Mosque", "Grand Mosque", "Musalla", "Rawdah", "Complex", "Center")):
        full_name_en = core_name
    elif suffix.lower() not in core_name.lower():
        full_name_en = f"{core_name} {suffix}".strip()
    else:
        full_name_en = core_name.strip()

    ratio = num_known / max(total_tokens, 1)
    if ratio >= 0.95:
        confidence = 0.98
    elif ratio >= 0.80:
        confidence = 0.95
    elif ratio >= 0.60:
        confidence = 0.88
    else:
        confidence = max(0.60, round(ratio, 2))

    return {
        "name_ar": cleaned,
        "name_en": full_name_en,
        "type": mosque_type,
        "confidence": confidence,
    }
