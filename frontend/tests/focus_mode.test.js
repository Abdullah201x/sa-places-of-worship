import { describe, it, expect, beforeEach } from 'vitest';

// Provide localStorage & DOM shims for Node testing environment
if (typeof globalThis.localStorage === 'undefined') {
  let store = {};
  globalThis.localStorage = {
    getItem: (k) => store[k] ?? null,
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: (k) => { delete store[k]; },
    clear: () => { store = {}; },
  };
}

if (typeof globalThis.document === 'undefined') {
  globalThis.document = {
    getElementById: () => null,
    createElement: () => ({
      classList: { add: () => {}, remove: () => {} },
      setAttribute: () => {},
      appendChild: () => {},
    }),
    body: { appendChild: () => {} },
    addEventListener: () => {},
  };
}

import {
  findNearestSimilarIssue,
  getChangesetSizeReminder,
  formatDistance,
  CHANGESET_LIMITS,
  FocusMode,
} from '../src/focus_mode.js';
import { EditBatch, createBatchEditItem } from '../src/editing.js';
import { ReviewMarks } from '../src/review.js';

describe('Focus Mode & Fast QA Triage', () => {
  beforeEach(() => {
    localStorage.clear();
    ReviewMarks._marks = {};
    EditBatch.replace([]);
    FocusMode.exit();
  });

  describe('formatDistance', () => {
    it('formats meters when distance is under 1 km', () => {
      expect(formatDistance(0.35, 'ar')).toBe('350 م');
      expect(formatDistance(0.35, 'en')).toBe('350 m');
      expect(formatDistance(0.05, 'ar')).toBe('50 م');
    });

    it('formats kilometers when distance is 1 km or more', () => {
      expect(formatDistance(1.24, 'ar')).toBe('1.2 كم');
      expect(formatDistance(1.24, 'en')).toBe('1.2 km');
      expect(formatDistance(15.8, 'en')).toBe('15.8 km');
    });

    it('handles null and invalid values gracefully', () => {
      expect(formatDistance(null)).toBe('–');
      expect(formatDistance(undefined)).toBe('–');
      expect(formatDistance(NaN)).toBe('–');
    });
  });

  describe('Changeset Size Reminders', () => {
    it('provides no warning for small batches under tip threshold', () => {
      const res = getChangesetSizeReminder(5, 'ar');
      expect(res.level).toBe('ok');
      expect(res.shouldWarn).toBe(false);
    });

    it('provides helpful tip when reaching tip threshold (15-24)', () => {
      const resAr = getChangesetSizeReminder(18, 'ar');
      expect(resAr.level).toBe('tip');
      expect(resAr.shouldWarn).toBe(false);
      expect(resAr.text).toContain('18');
      expect(resAr.text).toContain('20-30');

      const resEn = getChangesetSizeReminder(18, 'en');
      expect(resEn.level).toBe('tip');
      expect(resEn.text).toContain('20–30');
    });

    it('provides warning reminder when reaching recommended limit (25-49)', () => {
      const res = getChangesetSizeReminder(CHANGESET_LIMITS.WARN_THRESHOLD, 'ar');
      expect(res.level).toBe('warn');
      expect(res.shouldWarn).toBe(true);
      expect(res.text).toContain('25');
      expect(res.text).toContain('يُنصح برفع مجموعة التغييرات');

      const resEn = getChangesetSizeReminder(25, 'en');
      expect(resEn.level).toBe('warn');
      expect(resEn.shouldWarn).toBe(true);
      expect(resEn.text).toContain('moderate');
    });

    it('provides strong alert when reaching maximum recommended size (50+)', () => {
      const res = getChangesetSizeReminder(CHANGESET_LIMITS.MAX_RECOMMENDED, 'ar');
      expect(res.level).toBe('alert');
      expect(res.shouldWarn).toBe(true);
      expect(res.text).toContain('50');
      expect(res.text).toContain('الحد الأقصى');

      const resEn = getChangesetSizeReminder(50, 'en');
      expect(resEn.level).toBe('alert');
      expect(resEn.shouldWarn).toBe(true);
    });
  });

  describe('findNearestSimilarIssue', () => {
    const mockPlaces = [
      {
        id: 101,
        properties: { osm_id: 101, osm_type: 'way', name: 'جامع الهدى', religion: 'muslim', building: 'yes' },
        geometry: { type: 'Point', coordinates: [46.67, 24.71] } // ~Riyadh center
      },
      {
        id: 102,
        properties: { osm_id: 102, osm_type: 'way', name: 'مسجد النور', religion: 'muslim', building: 'yes' },
        geometry: { type: 'Point', coordinates: [46.68, 24.72] } // ~1.5 km from 101
      },
      {
        id: 103,
        properties: { osm_id: 103, osm_type: 'way', name: 'مسجد التقوى', religion: 'muslim', building: 'yes' },
        geometry: { type: 'Point', coordinates: [46.75, 24.78] } // ~10 km from 101
      },
      {
        id: 104,
        properties: { osm_id: 104, osm_type: 'way', name: 'مسجد بلال', religion: 'muslim', building: 'mosque' }, // already building=mosque (no building_yes issue)
        geometry: { type: 'Point', coordinates: [46.671, 24.711] }
      },
      {
        id: 105,
        properties: { osm_id: 105, osm_type: 'way', name: 'مسجد قباء', religion: 'muslim', building: 'yes' },
        geometry: { type: 'Point', coordinates: [39.85, 21.38] } // ~800 km away in Makkah
      }
    ];

    it('finds the nearest similar place matching building_yes', () => {
      const current = mockPlaces[0]; // 101
      const res = findNearestSimilarIssue(current, 'building_yes', mockPlaces);

      expect(res.nearest).not.toBeNull();
      expect(res.nearest.properties.osm_id).toBe(102); // 102 is nearest
      expect(res.distanceKm).toBeGreaterThan(1);
      expect(res.distanceKm).toBeLessThan(3);
      expect(res.remainingCount).toBe(3); // 102, 103, 105
    });

    it('excludes places already marked as fixed in ReviewMarks', () => {
      const current = mockPlaces[0];
      // Mark 102 as fixed
      ReviewMarks.set(mockPlaces[1].properties, 'fixed');

      const res = findNearestSimilarIssue(current, 'building_yes', mockPlaces);

      expect(res.nearest.properties.osm_id).toBe(103); // 102 is skipped, next nearest is 103
      expect(res.remainingCount).toBe(2); // 103, 105
    });

    it('excludes places already marked as skipped in ReviewMarks', () => {
      const current = mockPlaces[0];
      // Mark 102 as skipped
      ReviewMarks.set(mockPlaces[1].properties, 'skipped');

      const res = findNearestSimilarIssue(current, 'building_yes', mockPlaces);

      expect(res.nearest.properties.osm_id).toBe(103);
      expect(res.remainingCount).toBe(2);
    });

    it('excludes places already queued in EditBatch', () => {
      const current = mockPlaces[0];
      // Queue 102 in EditBatch
      const item = createBatchEditItem(mockPlaces[1].properties, 'building_yes');
      EditBatch.add(item);

      expect(EditBatch.isQueued(mockPlaces[1].properties, 'building_yes')).toBe(true);

      const res = findNearestSimilarIssue(current, 'building_yes', mockPlaces);
      expect(res.nearest.properties.osm_id).toBe(103);
      expect(res.remainingCount).toBe(2);
    });

    it('returns empty result when no similar candidates remain', () => {
      ReviewMarks.set(mockPlaces[1].properties, 'fixed');
      ReviewMarks.set(mockPlaces[2].properties, 'fixed');
      ReviewMarks.set(mockPlaces[4].properties, 'fixed');

      const res = findNearestSimilarIssue(mockPlaces[0], 'building_yes', mockPlaces);
      expect(res.nearest).toBeNull();
      expect(res.distanceKm).toBeNull();
      expect(res.remainingCount).toBe(0);
    });
  });

  describe('createBatchEditItem', () => {
    it('creates correct upgrade edit for building_yes', () => {
      const props = { osm_id: 999, osm_type: 'way', religion: 'muslim', building: 'yes', name: 'جامع تجريبي' };
      const item = createBatchEditItem(props, 'building_yes');

      expect(item).not.toBeNull();
      expect(item.id).toBe(999);
      expect(item.type).toBe('way');
      expect(item.fixId).toBe('building_yes');
      expect(item.edits.upgrade).toBeDefined();
      expect(item.edits.upgrade[0].old.building).toBe('yes');
      expect(item.edits.upgrade[0].replace.building).toBe('mosque');
    });
  });

  describe('FocusMode controller navigation', () => {
    it('manages active state and history navigation', () => {
      const navigated = [];
      FocusMode.setup({
        getPlaces: () => [
          { properties: { osm_id: 1, osm_type: 'way', religion: 'muslim', building: 'yes' }, geometry: { coordinates: [46.6, 24.7] } },
          { properties: { osm_id: 2, osm_type: 'way', religion: 'muslim', building: 'yes' }, geometry: { coordinates: [46.61, 24.71] } },
          { properties: { osm_id: 3, osm_type: 'way', religion: 'muslim', building: 'yes' }, geometry: { coordinates: [46.62, 24.72] } },
        ],
        onNavigateToPlace: (place, lat, lon) => {
          navigated.push({ id: place.properties.osm_id, lat, lon });
        }
      });

      const initial = { properties: { osm_id: 1, osm_type: 'way', religion: 'muslim', building: 'yes' }, geometry: { coordinates: [46.6, 24.7] } };
      FocusMode.enter({ ruleId: 'building_yes', place: initial });

      expect(FocusMode.isActive()).toBe(true);
      expect(FocusMode.getActiveRule()).toBe('building_yes');

      // Go to nearest
      FocusMode.goToNearestSimilarIssue();
      expect(navigated.length).toBe(1);
      expect(navigated[0].id).toBe(2);

      // Go to nearest again
      FocusMode.goToNearestSimilarIssue();
      expect(navigated.length).toBe(2);
      expect(navigated[1].id).toBe(3);

      // Go to previous
      FocusMode.goToPrevious();
      expect(navigated.length).toBe(3);
      expect(navigated[2].id).toBe(2);

      // Exit
      FocusMode.exit();
      expect(FocusMode.isActive()).toBe(false);
    });
  });
});
