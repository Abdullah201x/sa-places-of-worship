import re
import unicodedata

_RE_TASHKEEL = re.compile(r"[ً-ٰٟ]")
_RE_TATWEEL = re.compile(r"ـ")
_RE_PUNCT = re.compile(r"[^\w\s؀-ۿ]", re.UNICODE)


def normalize_arabic(text: str, strip_al: bool = False) -> str:
    """
    Normalizes Arabic text for database search matching:
    removes diacritics, unifies alef/taa marbuta/alef maqsura,
    and maps 'جامع' and 'مسجد' to the same stem.
    """
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", str(text).strip())
    s = _RE_TASHKEEL.sub("", s)
    s = _RE_TATWEEL.sub("", s)
    s = re.sub(r"[أإآٱ]", "ا", s)
    s = s.replace("ة", "ه").replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي")

    words = []
    for w in s.split():
        w = _RE_PUNCT.sub("", w).lower()
        if not w:
            continue
        if strip_al and w.startswith("ال") and len(w) > 3:
            w = w[2:]
        if w in ("جامع", "مسجد"):
            w = "مسجد"
        words.append(w)
    return " ".join(words)
