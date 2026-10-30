import { describe, it, expect } from 'vitest';
import {
  TILE_STATE_LABELS,
  formatTileStateBadge,
  generateIdEditorUrl,
  generateJosmRemoteUrl,
  findNextReadyTile,
  calculateSprintProgress,
} from '../src/tasks_view.js';

describe('Tasks & Sprints Workspace Helpers', () => {
  describe('TILE_STATE_LABELS and formatTileStateBadge', () => {
    const requiredStates = ['ready', 'mapping', 'mapped', 'validating', 'validated', 'invalidated', 'skipped'];

    it('defines Arabic and English labels for all expected states', () => {
      for (const state of requiredStates) {
        expect(TILE_STATE_LABELS[state]).toBeDefined();
        expect(typeof TILE_STATE_LABELS[state].ar).toBe('string');
        expect(TILE_STATE_LABELS[state].ar.length).toBeGreaterThan(0);
        expect(typeof TILE_STATE_LABELS[state].en).toBe('string');
        expect(TILE_STATE_LABELS[state].en.length).toBeGreaterThan(0);
      }
    });

    it('formats state badges with correct classes and glyphs in Arabic and English', () => {
      const readyAr = formatTileStateBadge('ready', 'ar');
      expect(readyAr.className).toBe('state-ready');
      expect(readyAr.label).toBe('جاهز للرسم');

      const mappingEn = formatTileStateBadge('mapping', 'en');
      expect(mappingEn.className).toBe('state-mapping');
      expect(mappingEn.label).toBe('Mapping');

      const validatedAr = formatTileStateBadge('validated', 'ar');
      expect(validatedAr.className).toBe('state-validated');
      expect(validatedAr.glyph).toBe('★');

      const invEn = formatTileStateBadge('invalidated', 'en');
      expect(invEn.className).toBe('state-invalidated');
      expect(invEn.label).toBe('Needs Work');
    });
  });

  describe('generateIdEditorUrl', () => {
    it('generates a valid iD editor URL with center coordinates and changeset tags', () => {
      const bbox = [46.60, 24.70, 46.62, 24.72];
      const url = generateIdEditorUrl(bbox, 'Riyadh Central Mosques Sprint', '#sa-worship-sprint');

      expect(url).toContain('https://www.openstreetmap.org/edit?editor=id#map=16/24.710000/46.610000');
      expect(url).toContain('comment=Riyadh%20Central%20Mosques%20Sprint');
      expect(url).toContain('hashtags=%23sa-worship-sprint');
    });

    it('applies fallback comment and hashtag when omitted', () => {
      const bbox = [46.60, 24.70, 46.62, 24.72];
      const url = generateIdEditorUrl(bbox, null, null);

      expect(url).toContain('comment=Mosque%20mapping%20sprint');
      expect(url).toContain('hashtags=%23sa-worship-map');
    });
  });

  describe('generateJosmRemoteUrl', () => {
    it('generates a valid JOSM remote control URL with bounding box and parameters', () => {
      const bbox = [46.60, 24.70, 46.62, 24.72];
      const url = generateJosmRemoteUrl(bbox, 'Jeddah Coastal Sprint', '#jeddah-mosques');

      expect(url.startsWith('http://127.0.0.1:8111/load_and_zoom?')).toBe(true);
      expect(url).toContain('left=46.6');
      expect(url).toContain('bottom=24.7');
      expect(url).toContain('right=46.62');
      expect(url).toContain('top=24.72');
      expect(url).toContain('changeset_comment=Jeddah%20Coastal%20Sprint');
      expect(url).toContain('changeset_hashtags=%23jeddah-mosques');
    });
  });

  describe('findNextReadyTile', () => {
    it('returns null if there are no tiles or none in ready state', () => {
      expect(findNextReadyTile([])).toBeNull();

      const busyTiles = [
        { tile_id: '1:1', state: 'mapping', workload: 10 },
        { tile_id: '1:2', state: 'mapped', workload: 15 },
        { tile_id: '1:3', state: 'validated', workload: 20 },
      ];
      expect(findNextReadyTile(busyTiles)).toBeNull();
    });

    it('selects the ready tile with the highest workload', () => {
      const tiles = [
        { tile_id: '1:1', state: 'mapping', workload: 50 },
        { tile_id: '1:2', state: 'ready', workload: 12 },
        { tile_id: '1:3', state: 'ready', workload: 34 },
        { tile_id: '1:4', state: 'ready', workload: 8 },
        { tile_id: '1:5', state: 'validated', workload: 99 },
      ];

      const next = findNextReadyTile(tiles);
      expect(next).toBeDefined();
      expect(next.tile_id).toBe('1:3');
      expect(next.workload).toBe(34);
    });

    it('handles tiles with missing workload gracefully', () => {
      const tiles = [
        { tile_id: '1:1', state: 'ready' },
        { tile_id: '1:2', state: 'ready', workload: 5 },
      ];
      const next = findNextReadyTile(tiles);
      expect(next.tile_id).toBe('1:2');
    });
  });

  describe('calculateSprintProgress', () => {
    it('calculates totals, validated count, percentage, and remaining workload', () => {
      const tiles = [
        { tile_id: '1:1', state: 'validated', workload: 10 },
        { tile_id: '1:2', state: 'validated', workload: 15 },
        { tile_id: '1:3', state: 'mapped', workload: 20 },
        { tile_id: '1:4', state: 'ready', workload: 25 },
      ];
      const progress = calculateSprintProgress(tiles);

      expect(progress.total).toBe(4);
      expect(progress.validated).toBe(2);
      expect(progress.mapped).toBe(1);
      expect(progress.pct).toBe(50);
      expect(progress.remainingWorkload).toBe(45); // 20 + 25
    });

    it('handles empty tiles array gracefully', () => {
      const progress = calculateSprintProgress([]);
      expect(progress.total).toBe(0);
      expect(progress.pct).toBe(0);
      expect(progress.remainingWorkload).toBe(0);
    });
  });
});
