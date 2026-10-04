// Bilingual UI (Arabic default, English toggle), modelled on the osm x wikidata
// project's translations.js / setLanguage().
//
// Static text lives in index.html in Arabic and is marked with data-i18n
// (innerHTML), data-i18n-placeholder, data-i18n-title or data-i18n-aria. When
// switching to English the Arabic original is kept on the element and the
// English string from TRANSLATIONS.en is shown; switching back restores it.
// Strings built in JavaScript use t(key, vars), which needs both languages.

const TRANSLATIONS = { ar: {}, en: {} };

// Registers strings: addTranslations({ key: ['عربي', 'English'], ... }).
function addTranslations(entries) {
  Object.entries(entries).forEach(([key, [ar, en]]) => {
    TRANSLATIONS.ar[key] = ar;
    TRANSLATIONS.en[key] = en;
  });
}

let currentLang = (() => {
  const fromUrl = new URLSearchParams(window.location.hash.slice(1)).get('lang');
  if (fromUrl === 'ar' || fromUrl === 'en') return fromUrl;
  try {
    return localStorage.getItem('gcc_lang') === 'en' ? 'en' : 'ar';
  } catch (e) {
    return 'ar';
  }
})();

// t('key', { n: 5 }) -> string with {n} replaced. Falls back to Arabic, then the key.
function t(key, vars) {
  let s = TRANSLATIONS[currentLang][key];
  if (s === undefined) s = TRANSLATIONS.ar[key];
  if (s === undefined) return key;
  if (vars) {
    s = s.replace(/\{(\w+)\}/g, (m, name) => (vars[name] !== undefined ? vars[name] : m));
  }
  return s;
}

function fmtNum(n) {
  return Number(n).toLocaleString(currentLang === 'ar' ? 'ar-SA' : 'en-US');
}

function fmtDate(value, withTime = false) {
  const d = new Date(value);
  const locale = currentLang === 'ar' ? 'ar-SA' : 'en-GB';
  return withTime ? d.toLocaleString(locale) : d.toLocaleDateString(locale);
}

const languageListeners = [];
function onLanguageChange(fn) {
  languageListeners.push(fn);
}

function applyStaticTranslations() {
  const en = currentLang === 'en';
  const swap = (el, attr, key, setter) => {
    const store = `i18nAr${attr}`;
    if (el.dataset[store] === undefined) el.dataset[store] = attr === 'Html' ? el.innerHTML : (el.getAttribute(setter) || '');
    const value = en && TRANSLATIONS.en[key] !== undefined ? TRANSLATIONS.en[key] : el.dataset[store];
    if (attr === 'Html') el.innerHTML = value;
    else el.setAttribute(setter, value);
  };
  document.querySelectorAll('[data-i18n]').forEach(el => swap(el, 'Html', el.dataset.i18n));
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => swap(el, 'Placeholder', el.dataset.i18nPlaceholder, 'placeholder'));
  document.querySelectorAll('[data-i18n-title]').forEach(el => swap(el, 'Title', el.dataset.i18nTitle, 'title'));
  document.querySelectorAll('[data-i18n-aria]').forEach(el => swap(el, 'Aria', el.dataset.i18nAria, 'aria-label'));
}

function setLanguage(lang) {
  currentLang = lang === 'en' ? 'en' : 'ar';
  try {
    localStorage.setItem('gcc_lang', currentLang);
  } catch (e) {
    // Ignore storage errors in private browsing
  }
  document.documentElement.lang = currentLang;
  document.documentElement.dir = currentLang === 'ar' ? 'rtl' : 'ltr';
  document.title = t('docTitle');
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
