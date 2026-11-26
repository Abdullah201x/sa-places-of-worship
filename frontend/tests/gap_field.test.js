import { describe, it, expect } from 'vitest';
import { gapScoreToColor, interpolateGapScore, gapPixel, worldPixel, invertedMask, GAP_GRADIENT_STOPS } from '../src/gap_field.js';
import { wantsGl } from '../src/map_kit.js';

describe('gapScoreToColor', () => {
  it('hits the gradient stops and clamps outside 0..1', () => {
    expect(gapScoreToColor(0)).toEqual([63, 43, 150]);
    expect(gapScoreToColor(0.5)).toEqual([168, 192, 255]);
    expect(gapScoreToColor(1)).toEqual(GAP_GRADIENT_STOPS.at(-1).color);
    expect(gapScoreToColor(-3)).toEqual(gapScoreToColor(0));
    expect(gapScoreToColor(9)).toEqual(gapScoreToColor(1));
  });
});

describe('interpolateGapScore', () => {
  const g = 0.004;
  const cells = new Map([['10,20', 10], ['11,20', 20], ['10,21', 30], ['11,21', 40]]);
  // Cell (gx, gy) has its value at its centre: ((gx + 0.5) * g, (gy + 0.5) * g).
  const at = (gx, gy) => [(gx + 0.5) * g, (gy + 0.5) * g];

  it('returns the cell value at a cell centre', () => {
    const [lon, lat] = at(10, 20);
    expect(interpolateGapScore(cells, g, lon, lat)).toBeCloseTo(10);
  });

  it('blends the four surrounding cells in the middle', () => {
    const lon = (11 * g), lat = (21 * g); // corner shared by the four cells
    expect(interpolateGapScore(cells, g, lon, lat)).toBeCloseTo(25);
  });

  it('is zero away from any cell', () => {
    expect(interpolateGapScore(cells, g, 40, 20)).toBe(0);
  });
});

describe('gapPixel', () => {
  it('skips negligible scores', () => {
    expect(gapPixel(0, 10)).toBeNull();
    expect(gapPixel(0.0005, 10)).toBeNull();
  });

  it('is more opaque for higher scores and caps at the max', () => {
    const lo = gapPixel(1, 10), hi = gapPixel(10, 10), over = gapPixel(99, 10);
    expect(hi[3]).toBeGreaterThan(lo[3]);
    expect(hi[3]).toBeCloseTo(0.8);
    expect(over).toEqual(hi);
  });
});

describe('worldPixel', () => {
  it('matches Web Mercator at the origin and the corners', () => {
    const o = worldPixel(0, 0, 0);
    expect(o.x).toBeCloseTo(128);
    expect(o.y).toBeCloseTo(128);
    expect(worldPixel(0, -180, 0).x).toBeCloseTo(0);
    expect(worldPixel(85.0511287798, 180, 0)).toEqual({ x: expect.closeTo(256, 5), y: expect.closeTo(0, 5) });
  });

  it('doubles per zoom level', () => {
    const a = worldPixel(24.7, 46.7, 10), b = worldPixel(24.7, 46.7, 11);
    expect(b.x).toBeCloseTo(a.x * 2);
    expect(b.y).toBeCloseTo(a.y * 2);
  });
});

describe('invertedMask', () => {
  const ring = [[40, 20], [50, 20], [50, 30], [40, 30], [40, 20]];

  it('cuts one hole per polygon out of a world rectangle', () => {
    const single = invertedMask({ type: 'Polygon', coordinates: [ring] });
    expect(single.geometry.coordinates).toHaveLength(2);
    expect(single.geometry.coordinates[1]).toBe(ring);

    const multi = invertedMask({ type: 'MultiPolygon', coordinates: [[ring], [[[1, 1], [2, 1], [2, 2], [1, 1]]]] });
    expect(multi.geometry.coordinates).toHaveLength(3);
  });

  it('ignores a polygon\'s own holes (only outer rings are cut)', () => {
    const hole = [[44, 24], [46, 24], [46, 26], [44, 24]];
    expect(invertedMask({ type: 'Polygon', coordinates: [ring, hole] }).geometry.coordinates).toHaveLength(2);
  });
});

describe('wantsGl', () => {
  it('defaults to MapLibre and opts out with ?map=leaflet', () => {
    expect(wantsGl('')).toBe(true);
    expect(wantsGl('?map=gl')).toBe(true);
    expect(wantsGl('?foo=1&map=gl')).toBe(true);
    expect(wantsGl('?map=leaflet')).toBe(false);
    expect(wantsGl('?foo=1&map=leaflet')).toBe(false);
  });
});
