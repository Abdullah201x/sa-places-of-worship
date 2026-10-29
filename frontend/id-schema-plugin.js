// Build-time subset of iD's tagging schema (@openstreetmap/id-tagging-schema).
// The package is a dev dependency only: the full presets.json alone is ~1 MB,
// so src/presets.js imports `virtual:id-tagging-schema` instead and gets just
// the mosque preset, the iD fields Manara uses, the upgrade rules that can
// apply to a mosque's tags, and their Arabic/English labels (a few KB).
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';

const VIRTUAL_ID = 'virtual:id-tagging-schema';
const RESOLVED_ID = `\0${VIRTUAL_ID}`;

export const PRESET_IDS = ['amenity/place_of_worship/muslim'];
export const FIELD_IDS = ['name', 'denomination', 'wheelchair', 'capacity', 'opening_hours', 'wikidata', 'building_area_yes'];
export const LANGS = ['ar', 'en'];

// deprecated.json covers every feature type. Keep the rules that only look at
// tags a Manara place carries, minus amenity=* rules (a mosque is always
// amenity=place_of_worship, so they would never apply) and rules whose
// replacement copies an old value ("*" / "$1"), which Manara doesn't need.
const RULE_KEYS = new Set(['religion', 'denomination', 'building', 'wheelchair', 'capacity', 'opening_hours', 'wikidata']);

function keepRule(rule) {
  const oldKeys = Object.keys(rule.old);
  return oldKeys.every(k => RULE_KEYS.has(k))
    && !Object.values(rule.replace || {}).some(v => v === '*' || String(v).includes('$'));
}

export function buildSchemaSubset() {
  const require = createRequire(import.meta.url);
  const pkgPath = require.resolve('@openstreetmap/id-tagging-schema/package.json');
  const dist = path.join(path.dirname(pkgPath), 'dist');
  const read = name => JSON.parse(fs.readFileSync(path.join(dist, name), 'utf8'));

  const presets = read('presets.json');
  const fields = read('fields.json');
  const subset = {
    version: JSON.parse(fs.readFileSync(pkgPath, 'utf8')).version,
    presets: {},
    fields: {},
    deprecated: read('deprecated.json').filter(keepRule),
    strings: {},
  };
  PRESET_IDS.forEach(id => {
    if (!presets[id]) throw new Error(`id-tagging-schema: preset ${id} not found`);
    subset.presets[id] = presets[id];
  });
  FIELD_IDS.forEach(id => {
    if (!fields[id]) throw new Error(`id-tagging-schema: field ${id} not found`);
    subset.fields[id] = fields[id];
  });
  LANGS.forEach(lang => {
    const strings = read(`translations/${lang}.json`)[lang].presets;
    subset.strings[lang] = {
      presets: Object.fromEntries(PRESET_IDS.map(id => [id, strings.presets[id] || {}])),
      fields: Object.fromEntries(FIELD_IDS.map(id => [id, strings.fields[id] || {}])),
    };
  });
  return subset;
}

export default function idSchemaPlugin() {
  return {
    name: 'manara-id-schema',
    resolveId(id) {
      return id === VIRTUAL_ID ? RESOLVED_ID : null;
    },
    load(id) {
      if (id !== RESOLVED_ID) return null;
      return `export default ${JSON.stringify(buildSchemaSubset())};`;
    },
  };
}
