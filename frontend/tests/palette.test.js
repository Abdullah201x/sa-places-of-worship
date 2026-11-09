import { describe, it, expect } from 'vitest';
import { filterPaletteItems, REGIONS, QA_RULES, ACTIONS } from '../src/palette.js';

describe('Command Palette Item Filtering', () => {
  it('returns default actions, rules, and regions on empty query', () => {
    const items = filterPaletteItems('');
    expect(items.length).toBeGreaterThan(0);
    expect(items.some(i => i.type === 'action')).toBe(true);
    expect(items.some(i => i.type === 'region')).toBe(true);
    expect(items.some(i => i.type === 'rule')).toBe(true);
  });

  it('matches regions by Arabic name and normalized spelling', () => {
    const riyadh = filterPaletteItems('رياض');
    expect(riyadh.some(i => i.type === 'region' && i.id === 'SA-01')).toBe(true);

    const makkah = filterPaletteItems('مكه'); // With 'ه' instead of 'ة'
    expect(makkah.some(i => i.type === 'region' && i.id === 'SA-02')).toBe(true);
  });

  it('matches regions by English name', () => {
    const eastern = filterPaletteItems('Eastern');
    expect(eastern.some(i => i.type === 'region' && i.id === 'SA-04')).toBe(true);
  });

  it('matches QA rules by rule ID or Arabic description', () => {
    const englishName = filterPaletteItems('missing_name_en');
    expect(englishName.some(i => i.type === 'rule' && i.id === 'missing_name_en')).toBe(true);

    const qibla = filterPaletteItems('قبلة');
    expect(qibla.some(i => i.type === 'rule' && i.id === 'qibla_deviation')).toBe(true);
  });

  it('matches core actions and commands', () => {
    const csv = filterPaletteItems('csv');
    expect(csv.some(i => i.type === 'action' && i.id === 'export_csv')).toBe(true);

    const satellite = filterPaletteItems('أقمار');
    expect(satellite.some(i => i.type === 'action' && i.id === 'toggle_satellite')).toBe(true);
  });
});

describe('region codes', () => {
  it('uses the real ISO 3166-2:SA codes (SA-01..SA-12 and SA-14)', () => {
    expect(REGIONS.map(r => r.code)).toEqual(
      ['SA-01', 'SA-02', 'SA-03', 'SA-04', 'SA-05', 'SA-06', 'SA-07', 'SA-08', 'SA-09', 'SA-10', 'SA-11', 'SA-12', 'SA-14']);
    const byCode = Object.fromEntries(REGIONS.map(r => [r.code, r.name_en]));
    expect(byCode['SA-05']).toMatch(/Qassim/);
    expect(byCode['SA-06']).toMatch(/Ha'il/);
    expect(byCode['SA-14']).toMatch(/Asir/);
  });
});
