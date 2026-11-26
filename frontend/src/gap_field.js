// Pure map maths shared by both backends (and testable without a map library):
// the coverage-gap colour ramp, the bilinear interpolation over the analysis grid,
// Web Mercator pixels, and the mask that clips the satellite imagery.

export const GAP_GRADIENT_STOPS = [
  { stop: 0.0, color: [63, 43, 150] },   // Deep Indigo
  { stop: 0.5, color: [168, 192, 255] }, // Soft Lilac
  { stop: 0.8, color: [236, 0, 140] },   // Neon Magenta
  { stop: 1.0, color: [252, 103, 103] }  // Flame Orange/Red
];

export function gapScoreToColor(t) {
  t = Math.max(0, Math.min(1, t));
  for (let i = 1; i < GAP_GRADIENT_STOPS.length; i++) {
    const a = GAP_GRADIENT_STOPS[i - 1];
    const b = GAP_GRADIENT_STOPS[i];
    if (t <= b.stop) {
      const localT = (t - a.stop) / (b.stop - a.stop || 1);
      return [
        a.color[0] + (b.color[0] - a.color[0]) * localT,
        a.color[1] + (b.color[1] - a.color[1]) * localT,
        a.color[2] + (b.color[2] - a.color[2]) * localT
      ];
    }
  }
  return GAP_GRADIENT_STOPS[GAP_GRADIENT_STOPS.length - 1].color;
}

// Bilinear interpolation between the 4 grid cells surrounding (lon, lat), so
// colour is continuous across the real analysis grid at any zoom. Cell (gx, gy)
// spans [gx*G, (gx+1)*G) (calculate_gaps.py uses int(lon/G)), so its value sits
// at the cell centre: shift by half a cell before interpolating, otherwise the
// whole field is offset ~220 m south-west.
export function interpolateGapScore(scoreByCell, gridSize, lon, lat) {
  const cell = (gx, gy) => scoreByCell.get(gx + ',' + gy) || 0;
  const fx = lon / gridSize - 0.5;
  const fy = lat / gridSize - 0.5;
  const x0 = Math.floor(fx), y0 = Math.floor(fy);
  const tx = fx - x0, ty = fy - y0;

  const s00 = cell(x0, y0);
  const s10 = cell(x0 + 1, y0);
  const s01 = cell(x0, y0 + 1);
  const s11 = cell(x0 + 1, y0 + 1);

  const top = s00 + (s10 - s00) * tx;
  const bottom = s01 + (s11 - s01) * tx;
  return top + (bottom - top) * ty;
}

// RGBA for one sample, or null where the score is too small to draw.
export function gapPixel(score, maxScore) {
  if (score <= 0.001) return null;
  const t = Math.min(score / maxScore, 1);
  const [r, g, b] = gapScoreToColor(t);
  const alpha = 0.15 + t * 0.65; // keep low scores subtle, peak gaps vivid
  return [r | 0, g | 0, b | 0, alpha];
}

// Web Mercator pixel position of a point at a zoom (256 px tiles), the same
// numbers Leaflet's map.project() returned. Independent of any map instance.
export function worldPixel(lat, lon, zoom) {
  const scale = 256 * 2 ** zoom;
  const x = (lon + 180) / 360 * scale;
  const sin = Math.sin(lat * Math.PI / 180);
  const y = (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * scale;
  return { x, y };
}

// World rectangle with the boundary's outer rings cut out.
export function invertedMask(geometry) {
  const polygons = geometry.type === 'MultiPolygon' ? geometry.coordinates : [geometry.coordinates];
  const world = [[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]];
  return {
    type: 'Feature',
    properties: {},
    geometry: { type: 'Polygon', coordinates: [world, ...polygons.map(p => p[0])] },
  };
}

// One worship_gaps_sa.json row [gx, gy, road_length_m, gap_score, urgency_score, rx, ry]
// as a cell object. rx/ry (0-99) place the road-weighted point the pipeline measures
// from inside the cell; files without them fall back to the cell centre.
export function parseGapCell(cell, g) {
  const [gx, gy, roadLength, score, urgency, rx, ry] = cell;
  const hasRep = rx !== undefined && ry !== undefined;
  return {
    gx, gy,
    lat: (gy + 0.5) * g,
    lon: (gx + 0.5) * g,
    rep_lat: (gy + (hasRep ? ry / 99 : 0.5)) * g,
    rep_lon: (gx + (hasRep ? rx / 99 : 0.5)) * g,
    road_length_m: roadLength,
    gap_score: score,
    urgency_score: urgency !== undefined ? urgency : score
  };
}

// A cell with a mosque closer than this is not a gap (calculate_gaps.py MIN_GAP_DISTANCE_M).
export const GAP_COVERAGE_RADIUS_M = 750;
const M_PER_DEG_LAT = 110574; // pipeline/common.py
const M_PER_DEG_LON_EQ = 111320;

// Cells (as built by parseGapGrid: gx, gy, rep_lat, rep_lon) not within `radiusM` of
// any of `points` ({lon, lat}). Distance is the pipeline's own: each point is
// projected with its own cos(lat) (calculate_gaps.py), measured from the cell's
// road-weighted point, so it matches what the daily build will decide. Returns a new
// array; `cells` is not modified.
export function filterCoveredGaps(cells, points, radiusM = GAP_COVERAGE_RADIUS_M, gridSize = 0.004) {
  if (!points || !points.length) return cells.slice();
  const index = new Map();
  cells.forEach((c, i) => index.set(c.gx + ',' + c.gy, i));
  const r2 = radiusM * radiusM;
  const covered = new Set();
  for (const p of points) {
    const px = p.lon * (M_PER_DEG_LON_EQ * Math.cos(p.lat * Math.PI / 180));
    const py = p.lat * M_PER_DEG_LAT;
    // 750 m is ~1.9 cells; +1 for the point's offset inside its cell and the
    // pipeline's lon skew (<= ~800 m reach) gives +-3.
    const gx = Math.floor(p.lon / gridSize);
    const gy = Math.floor(p.lat / gridSize);
    for (let dx = -3; dx <= 3; dx++) {
      for (let dy = -3; dy <= 3; dy++) {
        const i = index.get((gx + dx) + ',' + (gy + dy));
        if (i === undefined || covered.has(i)) continue;
        const c = cells[i];
        const cx = c.rep_lon * (M_PER_DEG_LON_EQ * Math.cos(c.rep_lat * Math.PI / 180));
        const cy = c.rep_lat * M_PER_DEG_LAT;
        const ddx = cx - px, ddy = cy - py;
        if (ddx * ddx + ddy * ddy < r2) covered.add(i);
      }
    }
  }
  return cells.filter((_, i) => !covered.has(i));
}
