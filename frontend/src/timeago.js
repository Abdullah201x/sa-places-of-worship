// Compact "how old is this" labels in the style of Osmose's "20h", plus the
// ok / warn / stale level that colours them. Pure functions; the caller
// passes in the current time, corrected for the browser's clock skew.

const MINUTE = 60 * 1000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

const UNITS = {
  ar: { now: 'الآن', m: 'د', h: 'س', d: 'ي' },
  en: { now: 'now', m: 'm', h: 'h', d: 'd' },
};

// formatAge(ms, 'en') -> "now" | "5m" | "20h" | "3d"; Arabic uses "5 د",
// "20 س", "3 ي". fmt formats the number (defaults to String).
export function formatAge(ms, lang, fmt = String) {
  const u = UNITS[lang] || UNITS.en;
  const sep = lang === 'ar' ? ' ' : '';
  const age = Math.max(0, ms);
  if (age < MINUTE) return u.now;
  if (age < HOUR) return `${fmt(Math.floor(age / MINUTE))}${sep}${u.m}`;
  if (age < 2 * DAY) return `${fmt(Math.floor(age / HOUR))}${sep}${u.h}`;
  return `${fmt(Math.floor(age / DAY))}${sep}${u.d}`;
}

// 'ok' below okMs, 'warn' below warnMs, 'stale' from there on.
export function ageLevel(ms, okMs, warnMs) {
  if (ms < okMs) return 'ok';
  if (ms < warnMs) return 'warn';
  return 'stale';
}

// The age of the published OSM data: fine for a day and a half (the
// pipeline runs daily), stale from 72 h, matching the server's
// MANARA_MAX_DATASET_AGE_HOURS default.
export const DATA_AGE_OK_MS = 36 * HOUR;
export const DATA_AGE_WARN_MS = 72 * HOUR;

// Milliseconds to add to Date.now() to get the server's time, from a
// response's Date header (second resolution is plenty here).
export function clockOffset(dateHeader, localNow) {
  const server = Date.parse(dateHeader || '');
  return Number.isFinite(server) ? server - localNow : 0;
}
