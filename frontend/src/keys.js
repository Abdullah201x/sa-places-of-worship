// Keyboard shortcut keys that work with any keyboard layout.
//
// e.key is the typed character, so with the Arabic layout active the N key
// gives "ى" and the Latin shortcuts never match. Latin letters, digits and "?"
// are used as typed, so AZERTY and other Latin layouts keep their own letters.
// Anything else (Arabic letters, Arabic-Indic digits, "؟") falls back to the
// physical key in e.code.

const ARABIC_INDIC_DIGITS = '٠١٢٣٤٥٦٧٨٩';
const PERSIAN_DIGITS = '۰۱۲۳۴۵۶۷۸۹';
// Named keys ("Escape", "ArrowDown", "F1") are returned unchanged.
const NAMED_KEY = /^[A-Z][A-Za-z0-9]+$/;

export function shortcutKey(e) {
  const key = e.key || '';
  if (NAMED_KEY.test(key)) return key;
  if (key === '?' || key === '؟') return '?';

  const lower = key.toLowerCase();
  if (/^[a-z0-9]$/.test(lower)) return lower;

  let digit = ARABIC_INDIC_DIGITS.indexOf(key);
  if (digit < 0) digit = PERSIAN_DIGITS.indexOf(key);
  if (key.length === 1 && digit >= 0) return String(digit);

  const code = e.code || '';
  const letter = code.match(/^Key([A-Z])$/);
  if (letter) return letter[1].toLowerCase();
  const number = code.match(/^(?:Digit|Numpad)(\d)$/);
  if (number) return number[1];
  if (code === 'Slash' && e.shiftKey) return '?';
  return lower;
}
