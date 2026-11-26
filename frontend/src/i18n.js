// Bilingual UI (Arabic default, English toggle), modelled on the osm x wikidata
// project's translations.js / setLanguage().
//
// Static text stays in Arabic in index.html. Its English lives in
// js/translations_static.js keyed by the Arabic text itself, and
// applyStaticTranslations() swaps text nodes and placeholder/title/aria-label
// attributes in place, so the markup needs no per-element keys. Strings built
// in JavaScript use t(key, vars), registered with both languages.

export const TRANSLATIONS = { ar: {}, en: {} };
export const STATIC_EN = {};

export function addStaticTranslations(entries) {
  Object.assign(STATIC_EN, entries);
}

// Registers strings: addTranslations({ key: ['عربي', 'English'], ... }).
export function addTranslations(entries) {
  Object.entries(entries).forEach(([key, [ar, en]]) => {
    TRANSLATIONS.ar[key] = ar;
    TRANSLATIONS.en[key] = en;
  });
}

export let currentLang = (() => {
  const fromUrl = typeof window !== 'undefined' ? new URLSearchParams(window.location.hash.slice(1)).get('lang') : null;
  if (fromUrl === 'ar' || fromUrl === 'en') return fromUrl;
  try {
    return typeof localStorage !== 'undefined' && localStorage.getItem('gcc_lang') === 'en' ? 'en' : 'ar';
  } catch (e) {
    return 'ar';
  }
})();

// t('key', { n: 5 }) -> string with {n} replaced. Falls back to Arabic, then the key.
export function t(key, vars) {
  let s = TRANSLATIONS[currentLang][key];
  if (s === undefined) s = TRANSLATIONS.ar[key];
  if (s === undefined) return key;
  if (vars) {
    s = s.replace(/\{(\w+)\}/g, (m, name) => (vars[name] !== undefined ? vars[name] : m));
  }
  return s;
}

export function fmtNum(n) {
  return Number(n).toLocaleString(currentLang === 'ar' ? 'ar-SA' : 'en-US');
}

export function fmtDate(value, withTime = false) {
  const d = new Date(value);
  const locale = currentLang === 'ar' ? 'ar-SA' : 'en-GB';
  return withTime ? d.toLocaleString(locale) : d.toLocaleDateString(locale);
}

export const languageListeners = [];
export function onLanguageChange(fn) {
  languageListeners.push(fn);
}

export const collapseSpace = str => str.replace(/\s+/g, ' ').trim();
export const TRANSLATED_ATTRS = ['placeholder', 'title', 'aria-label'];
// node -> { ar, en } and element -> { attr: { ar, en } }, remembered the first
// time an Arabic original is seen so switching back restores it exactly.
export const textOriginals = new WeakMap();
export const attrOriginals = new WeakMap();

// Returns { ar, en } for an Arabic string with a known translation (keeping
// the surrounding whitespace), or null.
export function staticPair(value) {
  const key = collapseSpace(value);
  const en = key && STATIC_EN[key];
  if (!en) return null;
  const lead = value.match(/^\s*/)[0];
  const trail = value.match(/\s*$/)[0];
  return { ar: value, en: lead + en + trail };
}

export function applyStaticTranslations(root = document.body) {
  const en = currentLang === 'en';
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: n => (n.parentElement && n.parentElement.closest('#map, script, style')
      ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT)
  });
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    let rec = textOriginals.get(node);
    // Text replaced by JavaScript since we last saw it: start over from the new value.
    if (rec && node.nodeValue !== rec.ar && node.nodeValue !== rec.en) rec = null;
    if (!rec) {
      rec = staticPair(node.nodeValue);
      if (!rec) continue;
      textOriginals.set(node, rec);
    }
    const value = en ? rec.en : rec.ar;
    if (node.nodeValue !== value) node.nodeValue = value;
  }

  root.querySelectorAll(TRANSLATED_ATTRS.map(a => `[${a}]`).join(',')).forEach(el => {
    if (el.parentElement && el.parentElement.closest('#map')) return; // Leaflet's own UI
    const recs = attrOriginals.get(el) || {};
    TRANSLATED_ATTRS.forEach(attr => {
      const current = el.getAttribute(attr);
      if (current === null) return;
      let rec = recs[attr];
      if (rec && current !== rec.ar && current !== rec.en) rec = null;
      if (!rec) {
        rec = staticPair(current);
        if (!rec) return;
        recs[attr] = rec;
      }
      el.setAttribute(attr, en ? rec.en : rec.ar);
    });
    attrOriginals.set(el, recs);
  });
}

export function setLanguage(lang) {
  currentLang = lang === 'en' ? 'en' : 'ar';
  try {
    localStorage.setItem('gcc_lang', currentLang);
  } catch (e) {
    // Ignore storage errors in private browsing
  }
  document.documentElement.lang = currentLang;
  document.documentElement.dir = currentLang === 'ar' ? 'rtl' : 'ltr';
  document.title = t(document.body.dataset.titleKey || 'docTitle');
  applyStaticTranslations();
  const btn = document.getElementById('btn-toggle-lang');
  if (btn) btn.textContent = currentLang === 'ar' ? 'English' : 'العربية';
  languageListeners.forEach(fn => {
    try {
      fn(currentLang);
    } catch (e) {
      console.error('Language listener failed:', e);
    }
  });
}

addTranslations({
  docTitle: ['خارطة الكثافة وفجوات التغطية لأماكن العبادة بالمملكة', 'Saudi Places of Worship: Density & Coverage Gaps'],
});
