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
  }
};
