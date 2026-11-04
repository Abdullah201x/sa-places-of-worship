import { describe, expect, it } from 'vitest';
import schema from 'virtual:id-tagging-schema';
import {
  BUILDING_YES_RULE, FIELDS, MOSQUE_PRESET, describeUpgrade, fieldLabel, fieldOptions,
  normalizeValue, optionLabel, outdatedRules, tagsFromValues, upgradeChanges, upgradeTags,
  validateValue, validateValues,
} from '../src/presets.js';

describe('id-tagging-schema subset', () => {
  it('keeps only the mosque preset and the fields Manara uses', () => {
    expect(Object.keys(schema.presets)).toEqual(['amenity/place_of_worship/muslim']);
    expect(JSON.stringify(schema).length).toBeLessThan(20000);
  });

  it('drops upgrade rules that cannot apply to a mosque', () => {
    expect(schema.deprecated.some(r => 'amenity' in r.old)).toBe(false);
    expect(schema.deprecated.length).toBeGreaterThan(0);
  });
});

describe('mosque preset', () => {
  it('adds the iD preset tags', () => {
    expect(MOSQUE_PRESET.addTags).toEqual({ amenity: 'place_of_worship', religion: 'muslim' });
  });

  it('every preset field is defined', () => {
    [...MOSQUE_PRESET.fields, ...MOSQUE_PRESET.moreFields].forEach(id => expect(FIELDS[id]).toBeDefined());
  });

  it('takes labels and options from iD, with Manara overrides', () => {
    expect(fieldOptions('wheelchair')).toEqual(['designated', 'yes', 'limited', 'no']);
    expect(fieldOptions('denomination')).toEqual(['sunni', 'shia', 'ibadi']);
    expect(fieldLabel('capacity', 'en')).toBe('Capacity');
    expect(fieldLabel('capacity', 'ar')).toBe('السعة');
    expect(fieldLabel('name:en', 'en')).toBe('English name');
    expect(optionLabel('wheelchair', 'limited', 'en')).toBe('Limited');
    expect(optionLabel('denomination', 'sunni', 'en')).toBeNull();
  });
});

describe('tagsFromValues', () => {
  it('builds a node from the form values', () => {
    expect(tagsFromValues(MOSQUE_PRESET, {
      'name:ar': '  جامع   النور ',
      'name:en': 'Al-Noor Mosque',
      denomination: 'sunni',
      'female:prayer_room': true,
      building: false,
      wheelchair: '',
      wikidata: 'https://www.wikidata.org/wiki/q123',
      capacity: '300',
      opening_hours: '',
    })).toEqual({
      amenity: 'place_of_worship',
      religion: 'muslim',
      name: 'جامع النور',
      'name:ar': 'جامع النور',
      'name:en': 'Al-Noor Mosque',
      denomination: 'sunni',
      'female:prayer_room': 'yes',
      wikidata: 'Q123',
      capacity: '300',
    });
  });

  it('falls back to name:en for name, and leaves name out when both are empty', () => {
    expect(tagsFromValues(MOSQUE_PRESET, { 'name:en': 'Masjid' }).name).toBe('Masjid');
    expect(tagsFromValues(MOSQUE_PRESET, {})).toEqual({ amenity: 'place_of_worship', religion: 'muslim' });
  });

  it('writes the check value of a checked check field', () => {
    expect(normalizeValue('building', true)).toBe('mosque');
    expect(normalizeValue('building', false)).toBe('');
  });
});

describe('validateValue', () => {
  it('accepts empty values', () => {
    expect(validateValues(MOSQUE_PRESET, {})).toEqual([]);
  });

  it('rejects bad numbers, options, formats and long values', () => {
    expect(validateValue('capacity', 'about 300')).toBe('notNumber');
    expect(validateValue('capacity', '-5')).toBe('notNumber');
    expect(validateValue('capacity', '300')).toBeNull();
    expect(validateValue('denomination', 'sunnite')).toBe('badOption');
    expect(validateValue('wikidata', 'X12')).toBe('badFormat');
    expect(validateValue('name:ar', 'م'.repeat(256))).toBe('tooLong');
    expect(validateValue('name:ar', 'م'.repeat(255))).toBeNull();
  });

  it('reports every invalid field', () => {
    expect(validateValues(MOSQUE_PRESET, { capacity: 'x', wikidata: 'nope' }).map(e => e.fieldId))
      .toEqual(['wikidata', 'capacity']);
  });
});

describe('upgradeTags', () => {
  it('normalizes denominations seen in the Saudi data', () => {
    expect(upgradeTags({ religion: 'muslim', denomination: 'سني' }).tags).toEqual({ religion: 'muslim', denomination: 'sunni' });
    expect(upgradeTags({ religion: 'muslim', denomination: 'السنية' }).tags.denomination).toBe('sunni');
    expect(upgradeTags({ religion: 'muslim', denomination: 'muslim' }).tags).toEqual({ religion: 'muslim' });
  });

  it('applies iD deprecated rules and Manara rules together', () => {
    const { tags, applied } = upgradeTags({ religion: 'islam', building: 'home' });
    expect(tags).toEqual({ religion: 'muslim', building: 'house' });
    expect(applied).toHaveLength(2);
  });

  it('upgrades amenity=mosque', () => {
    expect(upgradeTags({ amenity: 'mosque', name: 'x' }).tags)
      .toEqual({ amenity: 'place_of_worship', religion: 'muslim', name: 'x' });
  });

  it('leaves current tags alone', () => {
    const tags = { amenity: 'place_of_worship', religion: 'muslim', denomination: 'sunni', building: 'yes' };
    expect(upgradeTags(tags)).toEqual({ tags, applied: [] });
  });

  it('upgrades building=yes only with the preset rule', () => {
    expect(upgradeTags({ building: 'yes' }, [BUILDING_YES_RULE]).tags).toEqual({ building: 'mosque' });
  });

  it('a rule that no longer matches changes nothing', () => {
    expect(upgradeTags({ denomination: 'sunni' }, [{ old: { denomination: 'سني' }, replace: { denomination: 'sunni' } }]).applied).toEqual([]);
  });
});

describe('outdated tags on published places', () => {
  it('reads the flattened properties', () => {
    const props = { amenity: 'place_of_worship', religion: 'muslim', denomination: 'muslim', building: 'yes;mosque' };
    expect(outdatedRules(props)).toHaveLength(2);
    expect(describeUpgrade(props)).toEqual(['denomination=muslim → ∅', 'building=yes;mosque → mosque']);
  });

  it("treats denomination=unknown as missing, not outdated", () => {
    expect(outdatedRules({ religion: 'muslim', denomination: 'unknown', building: '' })).toEqual([]);
  });

  it('lists additions, changes and removals', () => {
    expect(upgradeChanges({ amenity: 'mosque' })).toEqual([
      { key: 'amenity', from: 'mosque', to: 'place_of_worship' },
      { key: 'religion', from: undefined, to: 'muslim' },
    ]);
  });
});

describe('geometry-aware fields', () => {
  it('never puts building=* on a point', () => {
    const values = { 'name:ar': 'مسجد', building: true };
    expect(tagsFromValues(MOSQUE_PRESET, values, 'point').building).toBeUndefined();
    expect(tagsFromValues(MOSQUE_PRESET, values, 'area').building).toBe('mosque');
  });
});
