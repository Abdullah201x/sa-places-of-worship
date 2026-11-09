import { describe, expect, it } from 'vitest';
import { RULE_IDS, evaluateRules } from '../src/validator.js';

const NOW = Date.parse('2026-10-30T00:00:00Z');
const CTX = { sizeMinM2: 20, sizeMaxM2: 15000, qiblaDevThreshold: 20, now: NOW };

// A well-tagged mosque outline with no issues.
const GOOD = {
  geom_type: 'Polygon',
  amenity: 'place_of_worship',
  building: 'mosque',
  religion: 'muslim',
  denomination: 'sunni',
  name_original: 'جامع الملك فهد',
  'name:en': 'King Fahd Mosque',
  version: 4,
  edited_at: '2025-01-01T00:00:00Z',
  size_area_m2: 900,
  ml_anomaly: { is_anomaly: false, qibla_dev: 3, qibla_az: 240, bldg_az: 243 },
};

const ids = (props, ctx = CTX) => evaluateRules({ ...GOOD, ...props }, ctx).map(i => i.id);

describe('validator rules', () => {
  it('keeps the rule ids that filters, permalinks and exports rely on', () => {
    expect(RULE_IDS).toEqual([
      'missing_amenity', 'missing_name', 'missing_name_en', 'missing_denom',
      'size_too_small', 'size_too_large', 'stale_data', 'building_yes', 'mapped_as_node',
      'ml_geometry_anomaly', 'duplicate_poi', 'outdated_tags', 'qibla_deviation',
    ]);
  });

  it('reports nothing for a well-tagged mosque', () => {
    expect(ids({})).toEqual([]);
  });

  it('flags building=mosque without amenity', () => {
    expect(ids({ amenity: undefined })).toEqual(['missing_amenity']);
  });

  it('flags generic names but not missing_name_en for them', () => {
    expect(ids({ name_original: 'مسجد', 'name:en': undefined })).toEqual(['missing_name']);
  });

  it('flags a missing or copied English name', () => {
    expect(ids({ 'name:en': undefined })).toEqual(['missing_name_en']);
    expect(ids({ 'name:en': 'جامع الملك فهد' })).toEqual(['missing_name_en']);
  });

  it('flags a missing denomination only for Muslim places', () => {
    expect(ids({ denomination: 'unknown' })).toEqual(['missing_denom']);
    expect(ids({ religion: 'christian', denomination: undefined, building: 'church' })).toEqual([]);
  });

  it('judges size against the thresholds in ctx', () => {
    expect(ids({ size_area_m2: 10 })).toEqual(['size_too_small']);
    expect(ids({ size_area_m2: 20000 })).toEqual(['size_too_large']);
    expect(ids({ size_area_m2: 900 }, { ...CTX, sizeMaxM2: 500 })).toEqual(['size_too_large']);
    // Below the minimum wins even if the maximum is set lower.
    expect(ids({ size_area_m2: 10 }, { ...CTX, sizeMinM2: 50, sizeMaxM2: 5 })).toEqual(['size_too_small']);
  });

  it('flags version-1 places older than five years, using ctx.now', () => {
    expect(ids({ version: 1, edited_at: '2020-01-01T00:00:00Z' })).toEqual(['stale_data']);
    expect(ids({ version: 1, edited_at: '2024-01-01T00:00:00Z' })).toEqual([]);
  });

  it('flags building=yes and nodes', () => {
    expect(ids({ building: 'yes' })).toContain('building_yes');
    expect(ids({ geom_type: 'Point', size_area_m2: undefined, ml_anomaly: undefined })).toEqual(['mapped_as_node']);
  });

  it('reports ML anomalies and duplicates', () => {
    expect(ids({ ml_anomaly: { ...GOOD.ml_anomaly, is_anomaly: true, diagnosis: 'x' } })).toEqual(['ml_geometry_anomaly']);
    expect(ids({ duplicate_poi: true })).toEqual(['duplicate_poi']);
  });

  it('reports outdated values with the change in the title', () => {
    const issues = evaluateRules({ ...GOOD, denomination: 'سني' }, CTX);
    expect(issues.map(i => i.id)).toEqual(['outdated_tags']);
    expect(issues[0].title_en).toContain('sunni');
  });

  it('applies the Qibla threshold from ctx', () => {
    expect(ids({ ml_anomaly: { ...GOOD.ml_anomaly, qibla_dev: 25 } })).toEqual(['qibla_deviation']);
    expect(ids({ ml_anomaly: { ...GOOD.ml_anomaly, qibla_dev: 25 } }, { ...CTX, qiblaDevThreshold: 30 })).toEqual([]);
  });

  it('lists issues in rule order', () => {
    expect(ids({ amenity: undefined, 'name:en': undefined, ml_anomaly: { ...GOOD.ml_anomaly, qibla_dev: 40 } }))
      .toEqual(['missing_amenity', 'missing_name_en', 'qibla_deviation']);
  });
});
