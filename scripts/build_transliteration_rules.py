import re
import json
import os
import sys

# Add root to sys.path
root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, root)

from backend.app.transliteration import (
    TITLE_MAP, HONORIFICS_MAP, PATRONYMICS, DIVINE_NAMES, ABD_SPECIAL, KNOWN_VOCABULARY, CHAR_MAP, WAW_ROOT_STARTS
)

js_path = os.path.join(root, "frontend", "src", "arabic.js")
with open(js_path, "r", encoding="utf-8") as f:
    js_text = f.read()

# Helper to extract object from JS
def extract_js_dict(var_name):
    pattern = rf"const {var_name} = \{{(.*?)\n\}};"
    m = re.search(pattern, js_text, re.DOTALL)
    if not m:
        return {}
    res = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        pairs = re.findall(r"['\"]([^'\"]+)['\"]\s*:\s*['\"]([^'\"]+)['\"]", line)
        for k, v in pairs:
            res[k] = v
    return res

js_vocab = extract_js_dict("KNOWN_VOCABULARY")
js_honors = extract_js_dict("HONORIFICS_MAP")
js_titles = extract_js_dict("TITLE_MAP")
js_patrons = extract_js_dict("PATRONYMICS")
js_divine = extract_js_dict("DIVINE_NAMES")
js_abd = extract_js_dict("ABD_SPECIAL")

# Merge dicts (prioritizing Python's authoritative standards, but keeping any missing from JS)
merged_vocab = dict(KNOWN_VOCABULARY)
for k, v in js_vocab.items():
    if k not in merged_vocab:
        merged_vocab[k] = v

merged_honors = dict(HONORIFICS_MAP)
for k, v in js_honors.items():
    if k not in merged_honors:
        merged_honors[k] = v

merged_titles = dict(TITLE_MAP)
for k, v in js_titles.items():
    if k not in merged_titles:
        merged_titles[k] = v

merged_patrons = dict(PATRONYMICS)
for k, v in js_patrons.items():
    if k not in merged_patrons:
        merged_patrons[k] = v

merged_divine = dict(DIVINE_NAMES)
for k, v in js_divine.items():
    if k not in merged_divine:
        merged_divine[k] = v

merged_abd = dict(ABD_SPECIAL)
for k, v in js_abd.items():
    if k not in merged_abd:
        merged_abd[k] = v

non_religious_terms = [
    "مدرسة", "جامعة", "كلية", "مستشفى", "مستوصف", "جمعية", "نادي", "مؤسسة", "مقبرة",
    "شارع", "طريق", "حديقة", "سوق", "محطة", "مواقف", "بئر"
]

eulogy_phrases = [
    "رضي الله عنه", "رضي الله عنها", "رضي الله عنهم", "رضي الله عنهما",
    "رضوان الله عليهم", "رضوان الله عليه",
    "صلى الله عليه وسلم",
    "عليه الصلاة والسلام", "عليه السلام",
    "عليهم الصلاة والسلام", "عليهم السلام",
    "رحمه الله", "رحمها الله", "رحمهم الله",
    "غفر الله له", "عفا الله عنه",
    "أسكنه فسيح جناته", "اسكنه فسيح جناته",
    "كرم الله وجهه",
    "حفظه الله", "وفقه الله", "أيده الله", "ايده الله",
    "قدس سره", "تبارك وتعالى", "عز وجل", "سبحانه وتعالى"
]

canonical_rules = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "version": "1.0.0",
    "description": "Canonical transliteration rules & lexicon for Saudi Arabic places of worship (GASGI / UNGEGN)",
    "titles": merged_titles,
    "honorifics": merged_honors,
    "patronymics": merged_patrons,
    "divine_names": merged_divine,
    "abd_special": merged_abd,
    "known_vocabulary": merged_vocab,
    "char_map": CHAR_MAP,
    "waw_root_starts": list(WAW_ROOT_STARTS),
    "non_religious": non_religious_terms,
    "eulogies": eulogy_phrases
}

out_path = os.path.join(root, "content", "transliteration_rules.json")
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(canonical_rules, f, ensure_ascii=False, indent=2)

print(f"Written canonical rules to {out_path}:")
print(f"  Titles: {len(merged_titles)}")
print(f"  Honorifics: {len(merged_honors)}")
print(f"  Patronymics: {len(merged_patrons)}")
print(f"  Divine Names: {len(merged_divine)}")
print(f"  Abd Special: {len(merged_abd)}")
print(f"  Known Vocabulary: {len(merged_vocab)}")
print(f"  Waw Root Starts: {len(WAW_ROOT_STARTS)}")
print(f"  Non-Religious: {len(non_religious_terms)}")
print(f"  Eulogies: {len(eulogy_phrases)}")
