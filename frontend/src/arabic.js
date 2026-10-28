// Arabic name helpers. Mirrors normalize_arabic() / is_generic_mosque_name()
// in common.py (ported from the osm x wikidata project); keep both in sync.
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

  // Saudi Geographic Naming Standards (UNGEGN/GASGI) transliteration engine
  suggestEnglishName(arabicName) {
    if (!arabicName || this.isGenericMosqueName(arabicName)) return '';
    const clean = String(arabicName).normalize('NFKC').trim()
      .replace(this._tashkeel, '')
      .replace(this._tatweel, '');
    const tokens = clean.split(/\s+/).filter(Boolean);
    if (!tokens.length) return '';

    const titleMap = {
      'جامع': 'Grand Mosque',
      'مسجد': 'Mosque',
      'مصلى': 'Musalla',
      'مصلّى': 'Musalla',
      'روضة': 'Rawdah'
    };
    const honorificsMap = {
      'الملك': 'King',
      'الأمير': 'Prince',
      'الامير': 'Prince',
      'الإمام': 'Imam',
      'الامام': 'Imam',
      'الشيخ': 'Sheikh',
      'الشهيد': 'Martyr',
      'السلطان': 'Sultan'
    };
    const patronymics = {
      'بن': 'bin',
      'ابن': 'Ibn',
      'بنت': 'bint',
      'أبو': 'Abu',
      'ابو': 'Abu',
      'أبي': 'Abi',
      'ابي': 'Abi',
      'أم': 'Umm',
      'ام': 'Umm',
      'آل': 'Al'
    };
    const knownNames = {
      'محمد': 'Muhammad', 'إبراهيم': 'Ibrahim', 'ابراهيم': 'Ibrahim', 'موسى': 'Musa', 'عيسى': 'Isa',
      'علي': 'Ali', 'عمر': 'Omar', 'عثمان': 'Othman', 'خالد': 'Khalid', 'بلال': 'Bilal', 'رباح': 'Rabah',
      'حمزة': 'Hamza', 'سعد': 'Saad', 'سعيد': 'Saeed', 'طلحة': 'Talha', 'الزبير': 'Al-Zubair',
      'عائشة': 'Aisha', 'خديجة': 'Khadijah', 'فاطمة': 'Fatima', 'الخطاب': 'Al-Khattab', 'عفان': 'Affan',
      'عبد العزيز': 'Abdulaziz', 'عبدالعزيز': 'Abdulaziz', 'عبد الله': 'Abdullah', 'عبدالله': 'Abdullah',
      'عبد الرحمن': 'Abdulrahman', 'عبدالرحمن': 'Abdulrahman', 'سعود': 'Saud', 'فيصل': 'Faisal',
      'فهد': 'Fahd', 'سلطان': 'Sultan', 'نايف': 'Nayef', 'تركي': 'Turki', 'سلمان': 'Salman',
      'الراجحي': 'Al-Rajhi', 'الشربتلي': 'Al-Sharbatly', 'الوليد': 'Al-Waleed', 'أحمد': 'Ahmad',
      'الرحمن': 'Al-Rahman', 'السلام': 'Al-Salam', 'القدوس': 'Al-Quddus', 'النور': 'Al-Noor',
      'الهدى': 'Al-Huda', 'التقوى': 'Al-Taqwa', 'الفتح': 'Al-Fath', 'الإخلاص': 'Al-Ikhlas',
      'الاخلاص': 'Al-Ikhlas', 'الفردوس': 'Al-Firdaws', 'الكوثر': 'Al-Kawthar', 'الريان': 'Al-Rayyan',
      'التوحيد': 'Al-Tawhid', 'البركة': 'Al-Barakah', 'الفرقان': 'Al-Furqan', 'القبلتين': 'Al-Qiblatain',
      'قباء': 'Quba', 'العيد': 'Al-Eid'
    };

    let suffix = 'Mosque';
    let nameTokens = tokens;
    if (titleMap[tokens[0]]) {
      suffix = titleMap[tokens[0]];
      nameTokens = tokens.slice(1);
    }
    if (!nameTokens.length) return suffix;

    const parts = [];
    let i = 0;
    while (i < nameTokens.length) {
      const cur = nameTokens[i];
      if (i + 1 < nameTokens.length) {
        const two = `${cur} ${nameTokens[i+1]}`;
        if (knownNames[two]) {
          parts.push(knownNames[two]);
          i += 2;
          continue;
        }
        if (honorificsMap[two]) {
          parts.push(honorificsMap[two]);
          i += 2;
          continue;
        }
      }
      if (cur === 'عبد' && i + 1 < nameTokens.length) {
        let nxt = nameTokens[i+1];
        if (nxt.startsWith('ال')) nxt = nxt.slice(2);
        const transCore = knownNames[nxt] || nxt;
        parts.push(`Abdul${transCore.toLowerCase()}`);
        i += 2;
        continue;
      }
      if (honorificsMap[cur]) {
        parts.push(honorificsMap[cur]);
      } else if (patronymics[cur]) {
        parts.push(patronymics[cur]);
      } else if (knownNames[cur]) {
        parts.push(knownNames[cur]);
      } else {
        let stem = cur;
        let hasAl = false;
        if (stem.startsWith('ال') && stem.length > 3) {
          hasAl = true;
          stem = stem.slice(2);
        }
        if (knownNames[stem]) {
          parts.push(hasAl ? `Al-${knownNames[stem]}` : knownNames[stem]);
        } else {
          const cap = stem.charAt(0).toUpperCase() + stem.slice(1);
          parts.push(hasAl ? `Al-${cap}` : cap);
        }
      }
      i++;
    }

    const core = parts.join(' ');
    if (core.toLowerCase().includes(suffix.toLowerCase())) {
      return core;
    }
    return `${core} ${suffix}`.trim();
  }
};
