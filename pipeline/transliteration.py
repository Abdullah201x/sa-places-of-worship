"""
Saudi Geographic Naming Standards Transliteration & NLP Engine
Compliant with UNGEGN / GASGI (General Authority for Survey and Geospatial Information)
principles for Arabic-to-English romanization of Islamic places of worship in Saudi Arabia.
"""

import re
import unicodedata

# ---------------------------------------------------------------------------
# Dictionaries & Vocabulary
# ---------------------------------------------------------------------------

# Mosque title / category prefixes
TITLE_MAP = {
    "جامع": "Grand Mosque",
    "مسجد": "Mosque",
    "مصلى": "Musalla",
    "مصلّى": "Musalla",
    "روضة": "Rawdah",
}

# Honorifics & titles
HONORIFICS_MAP = {
    "الملك": "King",
    "الأمير": "Prince",
    "الامير": "Prince",
    "الإمام": "Imam",
    "الامام": "Imam",
    "الشيخ": "Sheikh",
    "الشهيد": "Martyr",
    "السلطان": "Sultan",
    "الخليفة": "Caliph",
    "الصديق": "Al-Siddiq",
    "الفاروق": "Al-Farooq",
    "ذو النورين": "Dhu Al-Nurayn",
}

# Patronymics & connectives
PATRONYMICS = {
    "بن": "bin",
    "ابن": "Ibn",
    "بنت": "bint",
    "أبو": "Abu",
    "ابو": "Abu",
    "أبي": "Abi",
    "ابي": "Abi",
    "أم": "Umm",
    "ام": "Umm",
    "آل": "Al",
    "ذو": "Dhu",
    "ذي": "Dhi",
}

# Well-known historical, prophetic, royal and companion names
KNOWN_NAMES = {
    # Prophets & Companions
    "محمد": "Muhammad",
    "إبراهيم": "Ibrahim",
    "ابراهيم": "Ibrahim",
    "موسى": "Musa",
    "عيسى": "Isa",
    "يوسف": "Yusuf",
    "يونس": "Yunus",
    "أيوب": "Ayyub",
    "يعقوب": "Yaqub",
    "إسماعيل": "Ismail",
    "اسماعيل": "Ismail",
    "إسحاق": "Ishaq",
    "اسحاق": "Ishaq",
    "داود": "Dawud",
    "داوود": "Dawud",
    "سليمان": "Sulaiman",
    "نوح": "Nuh",
    "هارون": "Harun",
    "يحيى": "Yahya",
    "زكريا": "Zakariya",
    "علي": "Ali",
    "عمر": "Omar",
    "عثمان": "Othman",
    "خالد": "Khalid",
    "بلال": "Bilal",
    "حمزة": "Hamza",
    "سعد": "Saad",
    "سعيد": "Saeed",
    "طلحة": "Talha",
    "الزبير": "Al-Zubair",
    "معاذ": "Muadh",
    "حذيفة": "Hudhaifah",
    "عمار": "Ammar",
    "ياسر": "Yasser",
    "سلمان": "Salman",
    "صهيب": "Suhaib",
    "أسامة": "Osama",
    "اسامة": "Osama",
    "أنس": "Anas",
    "انس": "Anas",
    "أبي بن كعب": "Ubayy bin Kaab",
    "حسان": "Hassan",
    "جعفر": "Jafar",
    "الحسن": "Al-Hassan",
    "الحسين": "Al-Hussein",
    "عائشة": "Aisha",
    "خديجة": "Khadijah",
    "فاطمة": "Fatima",
    "مريم": "Maryam",
    "آسية": "Asiya",
    "زينب": "Zainab",
    "رقية": "Ruqayyah",
    "حفصة": "Hafsah",

    # Saudi Royal Family & State Figures
    "عبد العزيز": "Abdulaziz",
    "عبدالعزيز": "Abdulaziz",
    "عبد الله": "Abdullah",
    "عبدالله": "Abdullah",
    "عبد الرحمن": "Abdulrahman",
    "عبدالرحمن": "Abdulrahman",
    "عبد الملك": "Abdulmalik",
    "سعود": "Saud",
    "فيصل": "Faisal",
    "فهد": "Fahd",
    "سلطان": "Sultan",
    "نايف": "Nayef",
    "تركي": "Turki",
    "بندر": "Bandar",
    "مشعل": "Mishaal",
    "مقرن": "Muqrin",
    "طلال": "Talal",
    "نواف": "Nawaf",
    "منصور": "Mansour",
    "مساعد": "Musaed",
    "أحمد": "Ahmad",
    "احمد": "Ahmad",
    "وليد": "Waleed",
    "الوليد": "Al-Waleed",
    "الراجحي": "Al-Rajhi",
    "الشربتلي": "Al-Sharbatly",
    "بن باز": "bin Baz",
    "ابن باز": "Ibn Baz",
    "ابن عثيمين": "Ibn Uthaymeen",

    # Names of Allah & Islamic Concepts
    "الرحمن": "Al-Rahman",
    "الرحيم": "Al-Raheem",
    "السلام": "Al-Salam",
    "القدوس": "Al-Quddus",
    "المؤمن": "Al-Mu'min",
    "العزيز": "Al-Aziz",
    "الخالق": "Al-Khaliq",
    "الغفار": "Al-Ghaffar",
    "الرزاق": "Al-Razzaq",
    "الفتاح": "Al-Fattah",
    "العليم": "Al-Aleem",
    "النور": "Al-Noor",
    "الهدى": "Al-Huda",
    "التقوى": "Al-Taqwa",
    "الفتح": "Al-Fath",
    "الإخلاص": "Al-Ikhlas",
    "الاخلاص": "Al-Ikhlas",
    "الفردوس": "Al-Firdaws",
    "الكوثر": "Al-Kawthar",
    "الريان": "Al-Rayyan",
    "التوحيد": "Al-Tawhid",
    "البركة": "Al-Barakah",
    "الفرقان": "Al-Furqan",
    "الإيمان": "Al-Iman",
    "الايمان": "Al-Iman",
    "الإحسان": "Al-Ihsan",
    "الاحسان": "Al-Ihsan",
    "القبلتين": "Al-Qiblatain",
    "قباء": "Quba",
    "الجمعة": "Al-Jummah",
    "العيد": "Al-Eid",
}

# Compound Abdullah/Abdulrahman variations
ABD_PREFIXES = {
    "عبد": "Abdul",
}

# Arabic character transliteration table (UNGEGN / Saudi Standard)
CHAR_MAP = {
    "ء": "'", "أ": "A", "إ": "I", "آ": "Aa", "ٱ": "A",
    "ب": "b", "ت": "t", "ث": "th", "ج": "j", "ح": "h", "خ": "kh",
    "د": "d", "ذ": "dh", "ر": "r", "ز": "z", "س": "s", "ش": "sh",
    "ص": "s", "ض": "d", "ط": "t", "ظ": "dh", "ع": "a", "غ": "gh",
    "ف": "f", "ق": "q", "ك": "k", "ل": "l", "م": "m", "ن": "n",
    "ه": "h", "و": "w", "ي": "y", "ى": "a", "ة": "ah", "ؤ": "w", "ئ": "y"
}

_RE_TASHKEEL = re.compile(r"[ً-ٰٟ]")
_RE_TATWEEL = re.compile(r"ـ")


def clean_arabic(text: str) -> str:
    """Removes diacritics, tatweel, and normalizes spacing."""
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", str(text).strip())
    s = _RE_TASHKEEL.sub("", s)
    s = _RE_TATWEEL.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


def transliterate_word(word: str) -> str:
    """Phonetically transliterates an unrecognized Arabic word using GASGI standards."""
    if not word:
        return ""

    # Check known single words first
    if word in KNOWN_NAMES:
        return KNOWN_NAMES[word]
    if word in HONORIFICS_MAP:
        return HONORIFICS_MAP[word]
    if word in PATRONYMICS:
        return PATRONYMICS[word]

    # Handle definite article Al-
    has_al = False
    stem = word
    if word.startswith("ال") and len(word) > 3:
        has_al = True
        stem = word[2:]

    # Check stem in known names
    if stem in KNOWN_NAMES:
        result = KNOWN_NAMES[stem]
        return f"Al-{result}" if has_al and not result.startswith("Al-") else result

    # Transliterate characters
    out = []
    i = 0
    n = len(stem)
    while i < n:
        c = stem[i]
        # Handle long vowel patterns: 'ou', 'ee', 'aa'
        if c == "ا":
            out.append("a")
        elif c == "و" and i > 0 and i == n - 1:
            out.append("ou")
        elif c == "ي" and i > 0 and i == n - 1:
            out.append("i")
        elif c in CHAR_MAP:
            out.append(CHAR_MAP[c])
        else:
            out.append(c)
        i += 1

    transliterated = "".join(out).capitalize()
    if has_al:
        return f"Al-{transliterated}"
    return transliterated


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

    # False positive check
    non_religious_terms = {"مدرسة", "جامعة", "كلية", "مستشفى", "مستوصف", "جمعية", "نادي", "مؤسسة"}
    if any(w in non_religious_terms for w in words):
        return "non_religious"

    first = words[0]
    if first == "جامع" or "الجامع" in words:
        return "jamea"
    if first in ("مصلى", "مصلّى") or "مصلى" in words:
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
      - 'مصلى العيد' -> 'Eid Musalla'

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
    elif tokens[0] in ("جامع", "مسجد", "مصلى"):
        suffix = TITLE_MAP.get(tokens[0], "Mosque")
        name_tokens = tokens[1:]
    else:
        # Default suffix
        suffix = "Grand Mosque" if mosque_type == "jamea" else "Mosque"
        name_tokens = tokens

    # If the name is solely 'مسجد' or 'جامع' with no further tokens, it's generic
    if not name_tokens:
        return {"name_ar": cleaned, "name_en": suffix, "type": mosque_type, "confidence": 0.5}

    processed_parts = []
    i = 0
    num_known = 0
    total_tokens = len(name_tokens)

    while i < len(name_tokens):
        current = name_tokens[i]

        # Check two-token compound phrases first (e.g., 'عبد العزيز', 'الملك فهد', 'أبو بكر')
        if i + 1 < len(name_tokens):
            two_word = f"{current} {name_tokens[i+1]}"
            if two_word in KNOWN_NAMES:
                processed_parts.append(KNOWN_NAMES[two_word])
                num_known += 2
                i += 2
                continue
            if two_word in HONORIFICS_MAP:
                processed_parts.append(HONORIFICS_MAP[two_word])
                num_known += 2
                i += 2
                continue

        # Check compound "عبد" + Name
        if current in ABD_PREFIXES and i + 1 < len(name_tokens):
            next_word = name_tokens[i+1]
            # Strip 'الـ' from next word if present
            core = next_word[2:] if next_word.startswith("ال") else next_word
            trans_core = transliterate_word(core)
            processed_parts.append(f"Abdul{trans_core.lower()}")
            num_known += 2
            i += 2
            continue

        # Check individual token
        if current in HONORIFICS_MAP:
            processed_parts.append(HONORIFICS_MAP[current])
            num_known += 1
        elif current in PATRONYMICS:
            processed_parts.append(PATRONYMICS[current])
            num_known += 1
        elif current in KNOWN_NAMES:
            processed_parts.append(KNOWN_NAMES[current])
            num_known += 1
        else:
            # Fall back to phonetic transliteration
            trans = transliterate_word(current)
            processed_parts.append(trans)

        i += 1

    # Join the core name parts
    core_name = " ".join(processed_parts)

    # Position suffix appropriately:
    # In standard English geographic titles, 'Grand Mosque' / 'Mosque' / 'Musalla' goes at the end
    # Example: 'King Fahd Grand Mosque', 'Al-Taqwa Mosque'
    if suffix.lower() not in core_name.lower():
        full_name_en = f"{core_name} {suffix}".strip()
    else:
        full_name_en = core_name.strip()

    # Calculate confidence based on proportion of recognized vocabulary
    confidence = min(0.98, max(0.60, round(num_known / max(total_tokens, 1), 2)))
    if total_tokens > 0 and num_known >= total_tokens - 1:
        confidence = max(confidence, 0.92)

    return {
        "name_ar": cleaned,
        "name_en": full_name_en,
        "type": mosque_type,
        "confidence": confidence,
    }
