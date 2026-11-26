import { describe, it, expect, beforeEach, vi } from 'vitest';

class MockStorage {
  constructor() {
    this._s = {};
  }
  getItem(k) { return this._s[k] ?? null; }
  setItem(k, v) { this._s[k] = String(v); }
  removeItem(k) { delete this._s[k]; }
  clear() { this._s = {}; }
}

const mockLocal = new MockStorage();
const mockSession = new MockStorage();

vi.stubGlobal('localStorage', mockLocal);
vi.stubGlobal('sessionStorage', mockSession);

const { computeHaversineDistance, findNearbyPlaces, queueSurveyAnswer, SURVEY_QUESTIONS } = await import('../src/field_mode.js');
const { EditBatch } = await import('../src/editing.js');

describe('Manara Field: Surveyor Mode', () => {
  beforeEach(() => {
    mockLocal.clear();
    mockSession.clear();
  });

  it('computeHaversineDistance calculates accurate geodesic distances', () => {
    // Distance between Kaaba (21.4225, 39.8262) and nearby point
    const d = computeHaversineDistance(21.4225, 39.8262, 21.4230, 39.8262);
    expect(d).toBeGreaterThan(50);
    expect(d).toBeLessThan(65);
  });

  it('findNearbyPlaces filters places within maxDist and sorts by distance', () => {
    const places = [
      { properties: { osm_id: 1, name: 'Far Mosque' }, lat: 24.7200, lon: 46.6800 },
      { properties: { osm_id: 2, name: 'Close Mosque' }, lat: 24.7138, lon: 46.6755 },
      { properties: { osm_id: 3, name: 'Very Far Mosque' }, lat: 24.7500, lon: 46.7000 },
    ];

    const nearby = findNearbyPlaces(places, 24.7136, 46.6753, 300);
    expect(nearby.length).toBe(1);
    expect(nearby[0].properties.osm_id).toBe(2);
    expect(nearby[0].distanceMeters).toBeLessThan(100);
  });

  it('queueSurveyAnswer adds survey tags to EditBatch with check_date', () => {
    const place = {
      properties: {
        osm_id: 12345,
        osm_type: 'way',
        version: 3,
        name: 'مسجد الإيمان',
      }
    };

    const queued = queueSurveyAnswer(place, 'female_prayer_room', 'yes');
    expect(queued).toBe(true);

    const items = EditBatch.items();
    expect(items.length).toBe(1);
    expect(items[0].id).toBe(12345);
    expect(items[0].edits.set['female:prayer_room']).toBe('yes');
    expect(items[0].edits.set.check_date).toBeDefined();
    expect(items[0].source).toBe('survey');
  });

  it('SURVEY_QUESTIONS contains the three essential worshipper amenities', () => {
    const questionIds = SURVEY_QUESTIONS.map(q => q.id);
    expect(questionIds).toContain('female_prayer_room');
    expect(questionIds).toContain('wheelchair_access');
    expect(questionIds).toContain('place_of_worship_type');
  });
});
