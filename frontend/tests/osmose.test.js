import { describe, it, expect, vi, beforeEach } from 'vitest';
import { buildOsmoseApiUrl, buildOsmoseMapUrl, fetchNearbyOsmoseIssues, renderOsmoseResults } from '../src/osmose.js';

describe('Osmose QA Integration', () => {
  let mockStorage;

  beforeEach(() => {
    vi.restoreAllMocks();
    mockStorage = {};
    vi.stubGlobal('sessionStorage', {
      getItem: (k) => mockStorage[k] ?? null,
      setItem: (k, v) => { mockStorage[k] = String(v); },
      clear: () => { mockStorage = {}; },
    });
  });

  it('buildOsmoseApiUrl creates correct bounding box parameters', () => {
    const url = buildOsmoseApiUrl(24.7136, 46.6753, 0.01);
    expect(url).toContain('https://osmose.openstreetmap.fr/api/0.3/issues.json?bbox=');
    expect(url).toContain('46.6653,24.7036,46.6853,24.7236');
  });

  it('buildOsmoseMapUrl points to the Osmose web map view', () => {
    const url = buildOsmoseMapUrl(24.7136, 46.6753, 16);
    expect(url).toContain('https://osmose.openstreetmap.fr/');
    expect(url).toContain('lat=24.71360');
    expect(url).toContain('lon=46.67530');
  });

  it('fetchNearbyOsmoseIssues parses response and caches in sessionStorage', async () => {
    const mockIssues = [{ id: 12345, title: { auto: 'Missing tag' }, severity: 2 }];
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ issues: mockIssues }),
    });
    vi.stubGlobal('fetch', fetchMock);

    const res1 = await fetchNearbyOsmoseIssues(24.7136, 46.6753);
    expect(res1.issues).toEqual(mockIssues);
    expect(res1.cached).toBe(false);

    // Second call should hit cache without calling fetch
    const res2 = await fetchNearbyOsmoseIssues(24.7136, 46.6753);
    expect(res2.issues).toEqual(mockIssues);
    expect(res2.cached).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('renderOsmoseResults handles empty issues with success message', () => {
    const container = { style: {}, innerHTML: '' };
    renderOsmoseResults(container, { issues: [] }, 24.7136, 46.6753);
    expect(container.style.display).toBe('block');
    expect(container.innerHTML).toContain('لا توجد تنبيهات Osmose');
  });

  it('renderOsmoseResults handles issues list with alerts', () => {
    const container = { style: {}, innerHTML: '' };
    const issues = [{ id: 9999, title: { en: 'Wrong road tag' }, severity: 1 }];
    renderOsmoseResults(container, { issues }, 24.7136, 46.6753);
    expect(container.innerHTML).toContain('Wrong road tag');
    expect(container.innerHTML).toContain('#9999');
  });
});
