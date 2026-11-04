// Arabic name helpers and Saudi Geographic Naming Standards (UNGEGN/GASGI) transliteration engine.
// Powered by canonical rules defined in content/transliteration_rules.json.

import rules from '../../content/transliteration_rules.json' with { type: 'json' };

const TITLE_MAP = rules.titles;
const HONORIFICS_MAP = rules.honorifics;
const PATRONYMICS = rules.patronymics;
const DIVINE_NAMES = rules.divine_names;
const ABD_SPECIAL = rules.abd_special;
const KNOWN_VOCABULARY = rules.known_vocabulary;
const CHAR_MAP = rules.char_map;
const WAW_ROOT_STARTS = rules.waw_root_starts;
const NON_RELIGIOUS_TERMS = new Set(rules.non_religious || []);
const EULOGY_PHRASES = rules.eulogies || [];

const ABD_MAP = {};
for (const [arName, enTrans] of Object.entries(DIVINE_NAMES)) {
  if (arName === 'الله') {
    ABD_MAP['الله'] = 'Abdullah';
    ABD_MAP['لله'] = 'Abdullah';
    continue;
  }
  const core = enTrans.replace('Al-', '').replace("'", '');
  const comp = `Abdul${core.toLowerCase()}`;
  ABD_MAP[arName] = comp;
  const stem = arName.startsWith('ال') ? arName.slice(2) : arName;
  ABD_MAP[stem] = comp;
}

const eulogyAlt = EULOGY_PHRASES.map(p => p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\s+/g, '\\s+')).join('|');
const RE_PAREN_EULOGIES = new RegExp(`\\s*[(\\uFF08]\\s*(?:${eulogyAlt})\\s*[)\\uFF09]\\s*`, 'gu');
const RE_EMPTY_PARENS = /\s*[(\uFF08]\s*[)\uFF09]\s*/gu;
const BARE_EULOGY_RES = EULOGY_PHRASES.map(p => {
  const esc = p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\s+/g, '\\s+');
  return new RegExp(`(?:^|[\\s,.\\-؛،(（])${esc}(?=[\\s,.\\-؛،)）]|$)`, 'gu');
});

export function cleanArabic(text) {
  if (!text) return '';
  let s = String(text).normalize('NFKC').trim()
    .replace(/[ً-ٰٟ]/g, '')
    .replace(/ـ/g, '')
    .replace(/ى(?=[ء-ي])/g, 'ي');

  // 1. Remove parenthesized eulogies first (including parentheses)
  s = s.replace(RE_PAREN_EULOGIES, ' ');

  // 2. Remove bare eulogies
  for (const re of BARE_EULOGY_RES) {
    s = s.replace(re, ' ');
  }

  // 3. Clean empty parens
  s = s.replace(RE_EMPTY_PARENS, ' ');

  return s.replace(/\s+/g, ' ').trim();
}

export function classifyMosqueType(name) {
  const cleaned = cleanArabic(name);
  const words = cleaned.split(/\s+/).filter(Boolean);
  if (!words.length) return 'mosque';

  if (words.some(w => NON_RELIGIOUS_TERMS.has(w))) {
    return 'non_religious';
  }

  const first = words[0];
  if (first === 'جامع' || words.includes('الجامع')) {
    return 'jamea';
  }
  if (['مصلى', 'مصلّى', 'المصلى'].includes(first) || words.includes('مصلى')) {
    return 'musalla';
  }
  return 'mosque';
}

function reconstructMorphology(stem) {
  const n = stem.length;
  if (n < 3) {
    let out = '';
    for (const c of stem) out += CHAR_MAP[c] || c;
    return out.charAt(0).toUpperCase() + out.slice(1);
  }

  // 1. Taf'eel: توفيق
  if (n === 5 && stem.startsWith('ت') && stem[3] === 'ي') {
    const c1 = CHAR_MAP[stem[1]] || stem[1];
    const c2 = CHAR_MAP[stem[2]] || stem[2];
    if (stem[1] === 'و') {
      return stem[4] === 'ق' ? `Taw${c2}iq` : `Taw${c2}id`;
    }
    return stem[4] === 'ن' ? `Ta${c1}${c2}in` : `Ta${c1}${c2}eer`;
  }

  // 2. Maf'oul: محمود, منصور
  if (n === 5 && stem.startsWith('م') && stem[3] === 'و') {
    const c1 = CHAR_MAP[stem[1]] || stem[1];
    const c2 = CHAR_MAP[stem[2]] || stem[2];
    const c3 = CHAR_MAP[stem[4]] || stem[4];
    const s = `Ma${c1}${c2}ou${c3}`;
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  // 3. Fa'il/Fa'eel: كريم, خليل
  if (n === 4 && stem[2] === 'ي') {
    const c1 = CHAR_MAP[stem[0]] || stem[0];
    const c2 = CHAR_MAP[stem[1]] || stem[1];
    const c3 = CHAR_MAP[stem[3]] || stem[3];
    const s = `${c1}a${c2}i${c3}`;
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  // 4. Fa'oul: صبور, شكور
  if (n === 4 && stem[2] === 'و') {
    const c1 = CHAR_MAP[stem[0]] || stem[0];
    const c2 = CHAR_MAP[stem[1]] || stem[1];
    const c3 = CHAR_MAP[stem[3]] || stem[3];
    const s = `${c1}a${c2}ou${c3}`;
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  // 5. Fa'il: صالح, طارق
  if (n === 4 && stem[1] === 'ا') {
    const c1 = CHAR_MAP[stem[0]] || stem[0];
    const c2 = CHAR_MAP[stem[2]] || stem[2];
    const c3 = CHAR_MAP[stem[3]] || stem[3];
    const s = `${c1}a${c2}i${c3}`;
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  // 6. Fa'lan: عمران, عدنان
  if (n >= 5 && stem.endsWith('ان')) {
    const pre = stem.slice(0, -2);
    if (pre.length === 3) {
      const c1 = CHAR_MAP[pre[0]] || pre[0];
      const c2 = CHAR_MAP[pre[1]] || pre[1];
      const c3 = CHAR_MAP[pre[2]] || pre[2];
      const s = `${c1}a${c2}${c3}an`;
      return s.charAt(0).toUpperCase() + s.slice(1);
    }
  }

  // 7. Fa'eelah: طيبة, جميلة
  if (n === 5 && stem[2] === 'ي' && (stem.endsWith('ة') || stem.endsWith('ه'))) {
    const c1 = CHAR_MAP[stem[0]] || stem[0];
    const c2 = CHAR_MAP[stem[1]] || stem[1];
    if (stem[3] === 'ب') return `${c1.toUpperCase()}a${c2}bah`;
    const c3 = CHAR_MAP[stem[3]] || stem[3];
    return `${c1.toUpperCase()}a${c2}ee${c3}ah`;
  }

  // 8. Triliteral: بدر, فهد, أحد
  if (n === 3) {
    if (stem === 'أحد' || stem === 'احد') return 'Uhud';
    const c1 = CHAR_MAP[stem[0]] || stem[0];
    const c2 = CHAR_MAP[stem[1]] || stem[1];
    const c3 = CHAR_MAP[stem[2]] || stem[2];
    if (['ا', 'و', 'ي'].includes(stem[1])) {
      const v = stem[1] === 'ا' ? 'a' : (stem[1] === 'و' ? 'ou' : 'i');
      return `${c1.toUpperCase()}${v}${c3}`;
    }
    return `${c1.toUpperCase()}a${c2}${c3}`;
  }

  // Fallback letter-by-letter
  let out = '';
  for (let i = 0; i < n; i++) {
    const c = stem[i];
    if (c === 'و' && i > 0 && i < n - 1 && !['ا', 'و', 'ي'].includes(stem[i-1]) && !['ا', 'و', 'ي'].includes(stem[i+1])) {
      out += 'ou';
    } else if (c === 'ي' && i > 0 && i < n - 1 && !['ا', 'و', 'ي'].includes(stem[i-1]) && !['ا', 'و', 'ي'].includes(stem[i+1])) {
      out += 'i';
    } else if (c === 'ي' && i === n - 1) {
      out += 'i';
    } else {
      out += CHAR_MAP[c] || c;
    }
  }
  return out.charAt(0).toUpperCase() + out.slice(1);
}

function transliterateWord(word) {
  if (!word) return '';
  if (KNOWN_VOCABULARY[word]) return KNOWN_VOCABULARY[word];
  if (DIVINE_NAMES[word]) return DIVINE_NAMES[word];
  if (ABD_SPECIAL[word]) return ABD_SPECIAL[word];
  if (HONORIFICS_MAP[word]) return HONORIFICS_MAP[word];
  if (PATRONYMICS[word]) return PATRONYMICS[word];

  if (word.endsWith('ه') && KNOWN_VOCABULARY[word.slice(0, -1) + 'ة']) {
    return KNOWN_VOCABULARY[word.slice(0, -1) + 'ة'];
  }
  if (word.endsWith('ة') && KNOWN_VOCABULARY[word.slice(0, -1) + 'ه']) {
    return KNOWN_VOCABULARY[word.slice(0, -1) + 'ه'];
  }

  let hasAl = false;
  let stem = word;
  if (word.startsWith('ال') && word.length > 3) {
    hasAl = true;
    stem = word.slice(2);
  }

  if (KNOWN_VOCABULARY[stem]) {
    const res = KNOWN_VOCABULARY[stem];
    return hasAl && !res.startsWith('Al-') ? `Al-${res}` : res;
  }
  if (DIVINE_NAMES[stem]) {
    const res = DIVINE_NAMES[stem];
    return hasAl && !res.startsWith('Al-') ? `Al-${res}` : res;
  }

  const normStem = stem.replace(/[أإآ]/g, 'ا');
  if (KNOWN_VOCABULARY[normStem]) {
    const res = KNOWN_VOCABULARY[normStem];
    return hasAl && !res.startsWith('Al-') ? `Al-${res}` : res;
  }
  if (normStem.endsWith('ه') && KNOWN_VOCABULARY[normStem.slice(0, -1) + 'ة']) {
    const res = KNOWN_VOCABULARY[normStem.slice(0, -1) + 'ة'];
    return hasAl && !res.startsWith('Al-') ? `Al-${res}` : res;
  }

  const morph = reconstructMorphology(stem);
  return hasAl ? `Al-${morph}` : morph;
}

export const ArabicText = {
  _tashkeel: /[ً-ٰٟ]/g,
  _tatweel: /ـ/g,
  _punct: /[^\w\s؀-ۿ]/g,

  // Removes tashkeel/tatweel, unifies alef/taa marbuta/alef maqsura/hamza
  // seats, lowercases Latin, and treats جامع and مسجد as synonyms.
  normalize(text, stripAl = false) {
    if (!text) return '';
    const s = String(text).normalize('NFKC').trim()
      .replace(this._tashkeel, '')
      .replace(this._tatweel, '')
      .replace(/[أإآٱ]/g, 'ا')
      .replace(/ة/g, 'ه')
      .replace(/ى/g, 'ي')
      .replace(/ؤ/g, 'و')
      .replace(/ئ/g, 'ي');

    const words = [];
    for (const raw of s.split(/\s+/)) {
      let w = raw.replace(this._punct, '').toLowerCase();
      if (!w) continue;
      if (stripAl && w.startsWith('ال') && w.length > 3) w = w.slice(2);
      if (w === 'جامع' || w === 'مسجد') w = 'مسجد';
      words.push(w);
    }
    return words.join(' ');
  },

  // Words that carry no identifying information in a mosque's name (normalized).
  GENERIC_NAME_WORDS: new Set([
    'مسجد', 'مصلي', 'محراب', 'جمعه', 'بدون', 'اسم', 'بلا',
    'mosque', 'masjid', 'musalla', 'jami', 'jame', 'prayer', 'room',
    'place', 'of', 'worship', 'unnamed', 'no', 'name'
  ]),

  // True for empty names and names made only of generic words/numbers
  // ("مسجد", "الجامع", "مسجد جامع", "مصلى", "Mosque", "مسجد 3").
  isGenericMosqueName(name) {
    const norm = this.normalize(name, true);
    if (!norm) return true;
    return norm.split(' ').every(w => this.GENERIC_NAME_WORDS.has(w) || /^[0-9٠-٩]+$/.test(w));
  },

  // Case/diacritic-insensitive "contains" used by the search box.
  matches(haystack, normalizedQuery) {
    return !!haystack && this.normalize(haystack).includes(normalizedQuery);
  },

  // Checks if text contains pious eulogies (e.g. رضي الله عنه, رحمه الله)
  hasEulogy(name) {
    if (!name) return false;
    const clean = String(name).normalize('NFKC')
      .replace(/[ً-ٰٟ]/g, '')
      .replace(/ـ/g, '');
    if (RE_PAREN_EULOGIES.test(clean)) return true;
    return BARE_EULOGY_RES.some(re => {
      re.lastIndex = 0;
      return re.test(clean);
    });
  },

  // Classifies mosque type (jamea, mosque, musalla, non_religious)
  classifyMosqueType(name) {
    return classifyMosqueType(name);
  },

  // Saudi Geographic Naming Standards (UNGEGN/GASGI) transliteration engine
  suggestEnglishName(arabicName) {
    if (!arabicName || this.isGenericMosqueName(arabicName)) return '';

    const mosqueType = classifyMosqueType(arabicName);
    if (mosqueType === 'non_religious') {
      return '';
    }

    const clean = cleanArabic(arabicName);
    const rawTokens = clean.split(/\s+/).filter(Boolean);
    if (!rawTokens.length) return '';

    let suffix = 'Mosque';
    let nameTokens = rawTokens;
    if (TITLE_MAP[rawTokens[0]]) {
      suffix = TITLE_MAP[rawTokens[0]];
      nameTokens = rawTokens.slice(1);
    } else if (['جامع', 'مسجد', 'مصلى', 'مصلّى', 'روضة'].includes(rawTokens[0])) {
      suffix = TITLE_MAP[rawTokens[0]] || 'Mosque';
      nameTokens = rawTokens.slice(1);
    } else {
      suffix = mosqueType === 'jamea' ? 'Grand Mosque' : 'Mosque';
      nameTokens = rawTokens;
    }
    if (!nameTokens.length) return suffix;

    // Split conjunction 'و' (excluding words starting with root 'و')
    const splitTokens = [];
    for (const t of nameTokens) {
      if (t.startsWith('و') && !WAW_ROOT_STARTS.some(p => t.startsWith(p))) {
        if (t.length > 3 && (t.startsWith('وال') || t.startsWith('وإ') || t.startsWith('وأ'))) {
          splitTokens.push('and');
          splitTokens.push(t.slice(1));
        } else if (t === 'و') {
          splitTokens.push('and');
        } else {
          splitTokens.push(t);
        }
      } else {
        splitTokens.push(t);
      }
    }

    const parts = [];
    let i = 0;
    while (i < splitTokens.length) {
      const cur = splitTokens[i];

      if (cur === 'and') {
        parts.push('and');
        i++;
        continue;
      }

      // 4-token phrases
      if (i + 3 < splitTokens.length) {
        const four = `${cur} ${splitTokens[i+1]} ${splitTokens[i+2]} ${splitTokens[i+3]}`;
        if (HONORIFICS_MAP[four]) {
          parts.push(HONORIFICS_MAP[four]);
          i += 4;
          continue;
        }
      }

      // 3-token phrases
      if (i + 2 < splitTokens.length) {
        const three = `${cur} ${splitTokens[i+1]} ${splitTokens[i+2]}`;
        if (HONORIFICS_MAP[three]) {
          parts.push(HONORIFICS_MAP[three]);
          i += 3;
          continue;
        }
        if (KNOWN_VOCABULARY[three]) {
          parts.push(KNOWN_VOCABULARY[three]);
          i += 3;
          continue;
        }
      }

      // 2-token compound
      if (i + 1 < splitTokens.length) {
        const two = `${cur} ${splitTokens[i+1]}`;
        if (ABD_SPECIAL[two]) {
          parts.push(ABD_SPECIAL[two]);
          i += 2;
          continue;
        }
        if (HONORIFICS_MAP[two]) {
          parts.push(HONORIFICS_MAP[two]);
          i += 2;
          continue;
        }
        if (KNOWN_VOCABULARY[two]) {
          parts.push(KNOWN_VOCABULARY[two]);
          i += 2;
          continue;
        }
      }

      // Compound "عبد"
      if ((cur === 'عبد' || cur === 'العبد') && i + 1 < splitTokens.length) {
        const nxt = splitTokens[i+1];
        if (ABD_MAP[nxt]) {
          parts.push(ABD_MAP[nxt]);
          i += 2;
          continue;
        }
        const core = nxt.startsWith('ال') ? nxt.slice(2) : nxt;
        const transCore = transliterateWord(core);
        parts.push(`Abdul${transCore.toLowerCase()}`);
        i += 2;
        continue;
      }

      // Single word lookups
      if (ABD_SPECIAL[cur]) {
        parts.push(ABD_SPECIAL[cur]);
      } else if (HONORIFICS_MAP[cur]) {
        parts.push(HONORIFICS_MAP[cur]);
      } else if (PATRONYMICS[cur]) {
        let p = PATRONYMICS[cur];
        if (p === 'bin' && !parts.length) p = 'Bin';
        parts.push(p);
      } else if (KNOWN_VOCABULARY[cur]) {
        parts.push(KNOWN_VOCABULARY[cur]);
      } else if (DIVINE_NAMES[cur]) {
        parts.push(DIVINE_NAMES[cur]);
      } else {
        parts.push(transliterateWord(cur));
      }

      i++;
    }

    const core = parts.join(' ').trim();

    if (suffix === 'Musalla') {
      if (core.includes('Men')) return core.replace('Men', "Men's Musalla").trim();
      if (core.includes('Women')) return core.replace('Women', "Women's Musalla").trim();
    }

    if (['Mosque', 'Grand Mosque', 'Musalla', 'Rawdah', 'Complex', 'Center'].some(s => core.toLowerCase().endsWith(s.toLowerCase()))) {
      return core;
    }
    if (core.toLowerCase().includes(suffix.toLowerCase())) {
      return core;
    }
    return `${core} ${suffix}`.trim();
  }
};
