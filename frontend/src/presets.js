// Declarative mosque preset and fields, in the style of iD's tagging schema
// (github.com/openstreetmap/id-tagging-schema). The add-mosque form and the
// quick fixes render and validate from these definitions instead of each
// building tags by hand.
//
// The preset tags, iD field definitions (types, options, limits), their
// Arabic/English labels and the upgrade rules from iD's deprecated.json come
// from the npm package at build time (id-schema-plugin.js). Manara adds the
// fields iD doesn't have and the upgrade rules seen in the Saudi data.
//
// Pure module: no DOM and no i18n import, so it runs under Vitest in Node.
// Callers pass the UI language ('ar' | 'en').
import schema from 'virtual:id-tagging-schema';

export const ID_SCHEMA_VERSION = schema.version;
export const MAX_TAG_LENGTH = 255; // OSM rejects longer tag values

const ID_PRESET_ID = 'amenity/place_of_worship/muslim';
const idPreset = schema.presets[ID_PRESET_ID];

// Field id -> definition. `idField` names the iD field that supplies the
// label, placeholder, options and limits; the keys here override it.
//   type: text | number | combo (select from options) | check (checkbox that
//   writes checkValue)
export const FIELDS = {
  'name:ar': {
    key: 'name:ar', type: 'text', dir: 'rtl',
    label: ['اسم المسجد (بالعربية)', 'Mosque name (Arabic)'],
    placeholder: ['مثال: جامع الإيمان / مسجد النور', 'e.g. جامع الإيمان'],
  },
  'name:en': {
    key: 'name:en', type: 'text', dir: 'ltr',
    label: ['الاسم بالإنجليزية', 'English name'],
    placeholder: ['e.g. Al-Iman Mosque', 'e.g. Al-Iman Mosque'],
  },
  // iD's denomination field takes its options from taginfo; these are the
  // values used for mosques in the region.
  denomination: { key: 'denomination', type: 'combo', idField: 'denomination', options: ['sunni', 'shia', 'ibadi'] },
  'female:prayer_room': {
    key: 'female:prayer_room', type: 'check', checkValue: 'yes',
    label: ['مصلى نساء', "Women's prayer room"],
  },
  building: {
    key: 'building', type: 'check', checkValue: 'mosque', idField: 'building_area_yes',
    label: ['المعلم يمثل مبنى مسجداً مستقلاً', 'This is a standalone mosque building'],
  },
  wheelchair: { key: 'wheelchair', type: 'combo', idField: 'wheelchair' },
  wikidata: {
    key: 'wikidata', type: 'text', dir: 'ltr', idField: 'wikidata',
    pattern: /^Q[1-9]\d*$/, placeholder: ['مثال: Q12345678', 'e.g. Q12345678'],
  },
  capacity: { key: 'capacity', type: 'number', dir: 'ltr', idField: 'capacity' },
  opening_hours: { key: 'opening_hours', type: 'text', dir: 'ltr', idField: 'opening_hours' },
};

export const MOSQUE_PRESET = {
  id: ID_PRESET_ID,
  tags: { ...idPreset.tags },
  addTags: { ...(idPreset.addTags || idPreset.tags) },
  fields: ['name:ar', 'name:en', 'denomination'],
  moreFields: ['female:prayer_room', 'building', 'wheelchair', 'wikidata', 'capacity', 'opening_hours'],
};

function idFieldOf(fieldId) {
  const f = FIELDS[fieldId];
  return (f.idField && schema.fields[f.idField]) || {};
}

function idStrings(fieldId, lang) {
  const f = FIELDS[fieldId];
  return (f.idField && schema.strings[lang]?.fields[f.idField]) || {};
}

const pick = (pair, lang) => (pair ? pair[lang === 'en' ? 1 : 0] : undefined);

export function fieldLabel(fieldId, lang) {
  return pick(FIELDS[fieldId].label, lang)
    || idStrings(fieldId, lang).label || idStrings(fieldId, 'en').label || FIELDS[fieldId].key;
}

export function fieldPlaceholder(fieldId, lang) {
  return pick(FIELDS[fieldId].placeholder, lang) || idStrings(fieldId, lang).placeholder || '';
}

export function fieldOptions(fieldId) {
  return FIELDS[fieldId].options || idFieldOf(fieldId).options || [];
}

// iD's label for a combo option, or null when iD has none in either language.
export function optionLabel(fieldId, value, lang) {
  return idStrings(fieldId, lang).options?.[value] || idStrings(fieldId, 'en').options?.[value] || null;
}

// A raw form value (string, or boolean for checks) -> the tag value to write,
// '' meaning "leave the tag out".
export function normalizeValue(fieldId, raw) {
  const f = FIELDS[fieldId];
  if (f.type === 'check') return raw === true || raw === f.checkValue ? f.checkValue : '';
  const value = String(raw ?? '').trim().replace(/\s+/g, ' ');
  if (fieldId === 'wikidata') {
    // Accept a pasted Wikidata URL or a lower-case q.
    const m = value.match(/\bQ[1-9]\d*\b/i);
    return m ? m[0].toUpperCase() : value;
  }
  return value;
}

// Error code for a normalized value, or null when it is fine (or empty).
export function validateValue(fieldId, value) {
  if (!value) return null;
  const f = FIELDS[fieldId];
  if ([...value].length > MAX_TAG_LENGTH) return 'tooLong';
  if (f.type === 'number') {
    const min = idFieldOf(fieldId).minValue ?? 0;
    if (!/^\d+$/.test(value) || Number(value) < min) return 'notNumber';
  }
  if (f.type === 'combo' && !fieldOptions(fieldId).includes(value)) return 'badOption';
  if (f.pattern && !f.pattern.test(value)) return 'badFormat';
  return null;
}

export function presetFieldIds(preset) {
  return [...preset.fields, ...preset.moreFields];
}

// values: { fieldId: raw } -> [{ fieldId, code }] for every invalid field.
export function validateValues(preset, values) {
  return presetFieldIds(preset)
    .map(fieldId => ({ fieldId, code: validateValue(fieldId, normalizeValue(fieldId, values[fieldId])) }))
    .filter(e => e.code);
}

// values: { fieldId: raw } -> the tags of a new feature with this preset.
// name follows name:ar (the local language), else name:en.
export function tagsFromValues(preset, values) {
  const tags = { ...preset.addTags };
  presetFieldIds(preset).forEach(fieldId => {
    const value = normalizeValue(fieldId, values[fieldId]);
    if (value) tags[FIELDS[fieldId].key] = value;
  });
  const name = tags['name:ar'] || tags['name:en'];
  if (name) tags.name = name;
  return tags;
}

// ---------------------------------------------------------------------------
// Upgrade rules (iD's deprecated.json format: { old, replace })
// ---------------------------------------------------------------------------

// Old and misspelled values found in or likely for Saudi mosque data, on top
// of iD's own rules.
const variants = (key, values, replacement) =>
  values.map(v => ({ old: { [key]: v }, replace: replacement }));

export const MANARA_DEPRECATED = [
  { old: { amenity: 'mosque' }, replace: { amenity: 'place_of_worship', religion: 'muslim' } },
  ...variants('religion', ['islam', 'Islam', 'Muslim', 'moslem', 'muslim;islam'], { religion: 'muslim' }),
  // The religion already says muslim; denomination=muslim adds nothing.
  ...variants('denomination', ['muslim', 'islam', 'Muslim', 'Islam'], {}),
  ...variants('denomination', ['Sunni', 'sunnah', 'sunna', 'sunnite', 'سني', 'سنى', 'السنية', 'السنة', 'أهل السنة'], { denomination: 'sunni' }),
  ...variants('denomination', ['Shia', 'shiite', "shi'a", 'shiah', 'shii', 'شيعي', 'شيعة', 'الشيعة'], { denomination: 'shia' }),
  { old: { building: 'yes;mosque' }, replace: { building: 'mosque' } },
];

export const UPGRADE_RULES = [...schema.deprecated, ...MANARA_DEPRECATED];

// building=yes is valid OSM in general, so this upgrade is specific to the
// mosque preset and has its own issue (building_yes) rather than being
// reported as an outdated tag.
export const BUILDING_YES_RULE = { old: { building: 'yes' }, replace: { building: 'mosque' } };

function ruleMatches(rule, tags) {
  return Object.entries(rule.old).every(([k, v]) => k in tags && (v === '*' || tags[k] === v));
}

// Applies every matching rule in order, as iD's actionUpgradeTags does: keys
// of `old` missing from `replace` are removed, `replace` is written.
export function upgradeTags(tags, rules = UPGRADE_RULES) {
  const result = { ...tags };
  const applied = [];
  rules.forEach(rule => {
    if (!ruleMatches(rule, result)) return;
    Object.keys(rule.old).forEach(k => {
      if (!(k in rule.replace)) delete result[k];
    });
    Object.assign(result, rule.replace);
    applied.push(rule);
  });
  return { tags: result, applied };
}

// [{ key, from, to }] for each tag the rules would change; from is undefined
// for an added tag, to for a removed one.
export function upgradeChanges(tags, rules = UPGRADE_RULES) {
  const after = upgradeTags(tags, rules).tags;
  return [...new Set([...Object.keys(tags), ...Object.keys(after)])]
    .filter(k => tags[k] !== after[k])
    .map(key => ({ key, from: tags[key], to: after[key] }));
}

// The OSM tags a place in the published dataset carries, as far as the
// flattened GeoJSON properties tell ('unknown' and '' mean missing).
export function tagsFromProps(props) {
  const tags = {};
  ['amenity', 'religion', 'denomination', 'building', 'wheelchair'].forEach(k => {
    const v = props[k];
    if (v && v !== 'unknown') tags[k] = String(v);
  });
  return tags;
}

// Rules that would upgrade a place's tags (building=yes excluded, see above).
export function outdatedRules(props) {
  return upgradeTags(tagsFromProps(props)).applied;
}

// "denomination=سني → sunni" lines for a place's outdated tags.
export function describeUpgrade(props, rules = outdatedRules(props)) {
  return upgradeChanges(tagsFromProps(props), rules).map(({ key, from, to }) =>
    (from === undefined ? `${key}=${to}` : `${key}=${from} → ${to === undefined ? '∅' : to}`));
}
