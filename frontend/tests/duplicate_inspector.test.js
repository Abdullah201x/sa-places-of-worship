import { describe, it, expect, vi, beforeEach } from 'vitest';
import {
  fetchLiveOsmElement,
  fetchLiveNodeRelations,
  analyzeDuplicatePair,
  renderDuplicateInspector
} from '../src/duplicate_inspector.js';

describe('Live Duplicate POI Inspector (OSM API 0.6)', () => {
  let mockStorage;

  beforeEach(() => {
    vi.restoreAllMocks();
    mockStorage = {};
    vi.stubGlobal('sessionStorage', {
      getItem: (k) => mockStorage[k] ?? null,
      setItem: (k, v) => { mockStorage[k] = String(v); },
      removeItem: (k) => { delete mockStorage[k]; },
      clear: () => { mockStorage = {}; },
    });
  });

  describe('fetchLiveOsmElement', () => {
    it('fetches element and caches in sessionStorage', async () => {
      const mockElement = { id: 123, type: 'node', version: 2, tags: { name: 'مسجد' } };
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ elements: [mockElement] }),
      });
      vi.stubGlobal('fetch', fetchMock);

      const res1 = await fetchLiveOsmElement('node', 123, 'https://api.test');
      expect(res1).toEqual(mockElement);
      expect(fetchMock).toHaveBeenCalledTimes(1);

      // Second call hits cache
      const res2 = await fetchLiveOsmElement('node', 123, 'https://api.test');
      expect(res2).toEqual(mockElement);
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });

    it('handles 410 Gone / 404 cleanly', async () => {
      const fetchMock = vi.fn().mockResolvedValue({
        ok: false,
        status: 410,
      });
      vi.stubGlobal('fetch', fetchMock);

      const res = await fetchLiveOsmElement('node', 999, 'https://api.test');
      expect(res.gone).toBe(true);
      expect(res.status).toBe(410);
    });
  });

  describe('fetchLiveNodeRelations', () => {
    it('fetches relations array and caches result', async () => {
      const mockRels = [{ id: 888, type: 'relation', tags: { type: 'route' } }];
      const fetchMock = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => ({ elements: mockRels }),
      });
      vi.stubGlobal('fetch', fetchMock);

      const res1 = await fetchLiveNodeRelations(123, 'https://api.test');
      expect(res1).toEqual(mockRels);
      expect(fetchMock).toHaveBeenCalledTimes(1);

      const res2 = await fetchLiveNodeRelations(123, 'https://api.test');
      expect(res2).toEqual(mockRels);
      expect(fetchMock).toHaveBeenCalledTimes(1);
    });
  });

  describe('analyzeDuplicatePair', () => {
    it('classifies as resolved when node is gone', () => {
      const wayEl = { id: 1, tags: { amenity: 'place_of_worship' } };
      const nodeEl = { gone: true };
      const result = analyzeDuplicatePair(wayEl, nodeEl, []);

      expect(result.status).toBe('resolved');
      expect(result.isNodeGone).toBe(true);
    });

    it('classifies as relation_hazard when node belongs to relations', () => {
      const wayEl = { id: 1, tags: { amenity: 'place_of_worship' } };
      const nodeEl = { id: 2, tags: { amenity: 'place_of_worship' } };
      const rels = [{ id: 777, tags: { type: 'site' } }];

      const result = analyzeDuplicatePair(wayEl, nodeEl, rels);
      expect(result.status).toBe('relation_hazard');
      expect(result.relations.length).toBe(1);
    });

    it('classifies as distinct_poi when node represents a female prayer room / musalla', () => {
      const wayEl = { id: 1, tags: { amenity: 'place_of_worship', name: 'جامع الكبير' } };
      const nodeEl = { id: 2, tags: { amenity: 'place_of_worship', 'female:prayer_room': 'yes', name: 'مصلى النساء' } };

      const result = analyzeDuplicatePair(wayEl, nodeEl, []);
      expect(result.status).toBe('distinct_poi');
    });

    it('classifies as true_duplicate and generates tag diff when elements match', () => {
      const wayEl = {
        id: 10,
        tags: {
          amenity: 'place_of_worship',
          building: 'mosque',
          name: 'مسجد النور',
          religion: 'muslim',
        }
      };
      const nodeEl = {
        id: 20,
        tags: {
          amenity: 'place_of_worship',
          name: 'مسجد النور',
          religion: 'muslim',
          denomination: 'sunni',
          'name:en': 'Al Noor Mosque',
        }
      };

      const result = analyzeDuplicatePair(wayEl, nodeEl, []);
      expect(result.status).toBe('true_duplicate');
      expect(result.matchingCount).toBe(3); // amenity, name, religion
      expect(result.nodeOnlyCount).toBe(2); // denomination, name:en
      expect(result.conflictsCount).toBe(0);
    });

    it('detects conflicts when tags have different values', () => {
      const wayEl = { id: 1, tags: { amenity: 'place_of_worship', name: 'مسجد أ' } };
      const nodeEl = { id: 2, tags: { amenity: 'place_of_worship', name: 'مسجد ب' } };

      const result = analyzeDuplicatePair(wayEl, nodeEl, []);
      expect(result.conflictsCount).toBe(1);
    });
  });

  describe('renderDuplicateInspector', () => {
    it('hides container if props has no poi_node_id', async () => {
      const container = { style: { display: 'block' }, innerHTML: '' };
      await renderDuplicateInspector(container, { osm_id: 123 }, 24.5, 46.5);
      expect(container.style.display).toBe('none');
    });
  });
});
