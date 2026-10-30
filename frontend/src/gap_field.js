// The coverage-gap colour ramp and the bilinear interpolation over the analysis
// grid. Shared by both map backends so Leaflet and MapLibre draw the same field.

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
