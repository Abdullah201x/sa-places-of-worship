import { describe, it, expect, beforeEach, vi } from 'vitest';

class MockStorage {
  constructor() { this._s = {}; }
  getItem(k) { return this._s[k] ?? null; }
  setItem(k, v) { this._s[k] = String(v); }
  clear() { this._s = {}; }
}
const mockLocal = new MockStorage();
vi.stubGlobal('localStorage', mockLocal);

const { tagsToPlaceProps, liveFeatureToPlace, mergeLivePlaces, livePoints, LocalAdds } =
  await import('../src/live_places.js');

const place = (osm_id, extra = {}, osm_type = 'way') => ({
  type: 'Feature',
  properties: { osm_id, osm_type, geom_type: osm_type === 'node' ? 'Point' : 'Polygon', ...extra },
  geometry: { type: 'Point', coordinates: [46.7, 24.7] },
});
const serverFeature = (osm_id, tags = { amenity: 'place_of_worship', religion: 'muslim', name: 'X' }) => ({
  type: 'Feature',
  properties: { osm_type: 'node', osm_id, version: 1, edited_at: '2026-11-26T10:00:00Z', region_code: 'SA-01', tags },
  geometry: { type: 'Point', coordinates: [46.71, 24.71] },
});

describe('tagsToPlaceProps', () => {
  it('maps OSM tags to the static place shape', () => {
    const p = tagsToPlaceProps({ amenity: 'place_of_worship', religion: 'muslim', 'name:ar': 'مسجد', 'name:en': 'Mosque', 'female:prayer_room': 'yes' });
    expect(p).toMatchObject({ name: 'مسجد', name_en: 'Mosque', name_ar: 'مسجد', religion: 'muslim', female: 'yes', amenity: 'place_of_worship' });
  });

  it('does not call a non-mosque muslim without a religion tag', () => {
    expect(tagsToPlaceProps({ amenity: 'place_of_worship' }).religion).toBe('unknown');
    expect(tagsToPlaceProps({ amenity: 'mosque' }).religion).toBe('muslim');
  });
});

describe('mergeLivePlaces', () => {
  it('adds new live features and flags them live', () => {
    const places = [place(1)];
    expect(mergeLivePlaces(places, { features: [liveFeatureToPlace(serverFeature(50))], removed: [] })).toBe(true);
    expect(places).toHaveLength(2);
    expect(places[1].properties._live).toBe(true);
  });

  it('skips a feature already in the snapshot (the static copy wins)', () => {
    const places = [place(50, { name: 'static' }, 'node')];
    expect(mergeLivePlaces(places, { features: [liveFeatureToPlace(serverFeature(50))], removed: [] })).toBe(false);
    expect(places[0].properties.name).toBe('static');
  });

  it('replaces an older live copy with the newer one', () => {
    const places = [liveFeatureToPlace(serverFeature(50))];
    const newer = liveFeatureToPlace(serverFeature(50, { amenity: 'mosque', name: 'Renamed' }));
    expect(mergeLivePlaces(places, { features: [newer], removed: [] })).toBe(true);
    expect(places).toHaveLength(1);
    expect(places[0].properties.name).toBe('Renamed');
  });

  it('removes tombstoned objects, including a snapshot place whose inner node was deleted', () => {
    const places = [place(1, {}, 'way'), place(2, { poi_node_id: 777 }, 'way'), place(3, {}, 'node')];
    const delta = { features: [], removed: [{ osm_type: 'way', osm_id: 1 }, { osm_type: 'node', osm_id: 777 }] };
    expect(mergeLivePlaces(places, delta)).toBe(true);
    expect(places.map(p => p.properties.osm_id)).toEqual([3]);
  });

  it('reports no change for an empty delta', () => {
    const places = [place(1)];
    expect(mergeLivePlaces(places, { features: [], removed: [] })).toBe(false);
    expect(mergeLivePlaces(places, null)).toBe(false);
  });
});

describe('livePoints', () => {
  it('returns only live and newly added mosques', () => {
    const places = [place(1), liveFeatureToPlace(serverFeature(50)), place(2, { _newlyAdded: true })];
    expect(livePoints(places)).toEqual([{ lon: 46.71, lat: 24.71 }, { lon: 46.7, lat: 24.7 }]);
  });
});

describe('LocalAdds', () => {
  beforeEach(() => mockLocal.clear());

  it('replays an add as a server-shaped delta', () => {
    LocalAdds.add(99, 24.7, 46.7, { amenity: 'place_of_worship', name: 'N' });
    const delta = LocalAdds.asDelta();
    expect(delta.features).toHaveLength(1);
    const f = liveFeatureToPlace(delta.features[0]);
    expect(f.properties).toMatchObject({ osm_id: 99, osm_type: 'node', name: 'N', _live: true });
    expect(f.geometry.coordinates).toEqual([46.7, 24.7]);
  });

  it('prunes adds older than the published dataset', () => {
    LocalAdds.add(99, 24.7, 46.7, {});
    LocalAdds.prune(Date.now() + 1000);
    expect(LocalAdds.asDelta().features).toHaveLength(0);
    LocalAdds.add(100, 24.7, 46.7, {});
    LocalAdds.prune(Date.now() - 60000);
    expect(LocalAdds.asDelta().features).toHaveLength(1);
  });
});
