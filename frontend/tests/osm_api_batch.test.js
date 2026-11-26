import { describe, it, expect, vi, beforeEach } from 'vitest';

vi.stubGlobal('localStorage', {
  _s: { osm_access_token: 't' },
  getItem(k) { return this._s[k] ?? null; },
  setItem(k, v) { this._s[k] = String(v); },
  removeItem(k) { delete this._s[k]; },
});
vi.stubGlobal('sessionStorage', { getItem: () => null, setItem() {}, removeItem() {} });
vi.stubGlobal('window', { location: { origin: 'https://manara.saudiosm.org', pathname: '/tasks/', search: '', hash: '', protocol: 'https:' } });
vi.stubGlobal('document', { title: '', querySelector: () => null, getElementById: () => null, dispatchEvent() {} });

const { OsmApi } = await import('../src/osm_api.js');

describe('OsmApi.redirectUri', () => {
  it('is always the site root, whichever page starts the login', () => {
    expect(OsmApi.redirectUri()).toBe('https://manara.saudiosm.org/');
  });
});

describe('OsmApi.mergeEdits', () => {
  it('merges set/del of several fixes for one element', () => {
    const merged = OsmApi.mergeEdits([
      { set: { 'name:en': 'A' } },
      { set: { denomination: 'sunni' }, del: ['x'] },
      { del: ['x', 'y'] },
    ]);
    expect(merged.set).toEqual({ 'name:en': 'A', denomination: 'sunni' });
    expect(merged.del.sort()).toEqual(['x', 'y']);
  });
});

describe('OsmApi.applyEdits', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('uploads two fixes on the same element as ONE PUT built from one GET', async () => {
    vi.spyOn(OsmApi, 'canEdit').mockReturnValue(true);
    const fetchElement = vi.spyOn(OsmApi, 'fetchElement').mockResolvedValue({ tags: { amenity: 'place_of_worship' }, version: 3 });
    vi.spyOn(OsmApi, 'openChangeset').mockResolvedValue(77);
    const upload = vi.spyOn(OsmApi, '_uploadElement').mockResolvedValue(4);
    const close = vi.spyOn(OsmApi, 'closeChangeset').mockResolvedValue();
    const report = vi.spyOn(OsmApi, 'reportEdit').mockResolvedValue();

    const { results } = await OsmApi.applyEdits([
      { type: 'node', id: 1, expectedVersion: 3, edits: { set: { 'name:en': 'Masjid' } }, summary: 'name' },
      { type: 'node', id: 1, expectedVersion: 3, edits: { set: { denomination: 'sunni' } }, summary: 'denom' },
    ], { comment: 'c', source: 's', deferReport: true });

    expect(fetchElement).toHaveBeenCalledTimes(1);
    expect(upload).toHaveBeenCalledTimes(1);
    expect(upload.mock.calls[0][3]).toBeDefined();
    expect(upload.mock.calls[0][4]).toMatchObject({ 'name:en': 'Masjid', denomination: 'sunni' });
    expect(results.map(r => r.status)).toEqual(['success', 'success']);
    expect(close).toHaveBeenCalledWith(77);
    expect(report).not.toHaveBeenCalled(); // deferred to the caller
  });

  it('classifies a mid-flight version mismatch as a conflict, not an error', async () => {
    vi.spyOn(OsmApi, 'canEdit').mockReturnValue(true);
    vi.spyOn(OsmApi, 'fetchElement').mockResolvedValue({ tags: {}, version: 1 });
    vi.spyOn(OsmApi, 'openChangeset').mockResolvedValue(5);
    vi.spyOn(OsmApi, '_uploadElement').mockRejectedValue(new Error('VERSION_CONFLICT PUT node/1'));
    vi.spyOn(OsmApi, 'closeChangeset').mockResolvedValue();
    vi.spyOn(OsmApi, 'reportEdit').mockResolvedValue();
    const { results } = await OsmApi.applyEdits([{ type: 'node', id: 1, edits: { set: { a: 'b' } } }], { deferReport: true });
    expect(results[0].status).toBe('conflict');
  });
});

describe('OsmApi.addNode', () => {
  it('reports the changeset only after closing it', async () => {
    vi.spyOn(OsmApi, 'canEdit').mockReturnValue(true);
    const order = [];
    vi.spyOn(OsmApi, 'openChangeset').mockResolvedValue(9);
    vi.spyOn(OsmApi, 'createNode').mockResolvedValue(100);
    vi.spyOn(OsmApi, 'closeChangeset').mockImplementation(async () => { order.push('close'); });
    vi.spyOn(OsmApi, 'reportEdit').mockImplementation(async () => { order.push('report'); });
    await OsmApi.addNode({ lat: 1, lon: 2, tags: { amenity: 'place_of_worship' }, comment: 'c', source: 's' });
    expect(order).toEqual(['close', 'report']);
  });
});
