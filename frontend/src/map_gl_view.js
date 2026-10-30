// Pure helpers for the MapLibre map (/mapgl): style, hash permalink, popup rows
// and links. No DOM or maplibre import here, so Vitest can cover all of it.

export const SA_CENTER = [45.0, 24.0];
export const SA_ZOOM = 5;

const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services';
const ESRI_ATTR = 'Tiles &copy; Esri';
export const OSM_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors (ODbL)';

// Basemap id -> raster layers drawn bottom to top. Same keyless Esri tiles as
// the Leaflet map; CARTO is left out because the CSP's connect-src (which
// MapLibre's tile fetches fall under) does not list it.
export const BASEMAPS = {
  light: [`${ESRI}/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}`, `${ESRI}/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}`],
  dark: [`${ESRI}/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}`, `${ESRI}/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}`],
  satellite: [`${ESRI}/World_Imagery/MapServer/tile/{z}/{y}/{x}`],
  streets: [`${ESRI}/World_Street_Map/MapServer/tile/{z}/{y}/{x}`],
};

export const OVERLAY_IDS = ['gaps', 'suggestions', 'places'];

// Same gradient as the Leaflet gap layer (GAP_GRADIENT_STOPS in app.js), over urgency 0-100.
const GAP_COLOR = ['interpolate', ['linear'], ['coalesce', ['get', 'urgency'], 0],
  0, 'rgb(63,43,150)', 50, 'rgb(168,192,255)', 80, 'rgb(236,0,140)', 100, 'rgb(252,103,103)'];

const circleRadius = (...stops) => ['interpolate', ['linear'], ['zoom'], ...stops];

// origin is passed in so the helper stays testable; pmtiles:// needs an absolute URL.
export function buildStyle({ origin, basemap = 'light' }) {
  const sources = {};
  const layers = [];

  for (const [id, urls] of Object.entries(BASEMAPS)) {
    urls.forEach((url, i) => {
      const sid = `base-${id}-${i}`;
      sources[sid] = { type: 'raster', tiles: [url], tileSize: 256, maxzoom: 19, attribution: i === 0 ? ESRI_ATTR : '' };
      layers.push({ id: sid, type: 'raster', source: sid, layout: { visibility: id === basemap ? 'visible' : 'none' } });
    });
  }

  for (const id of OVERLAY_IDS) {
    sources[id] = {
      type: 'vector',
      url: `pmtiles://${origin}/data/${id}.pmtiles`,
      attribution: id === 'places' ? `${OSM_ATTR}, Manara` : '',
    };
  }

  layers.push(
    {
      id: 'gaps', type: 'circle', source: 'gaps', 'source-layer': 'gaps',
      paint: {
        'circle-color': GAP_COLOR,
        'circle-opacity': 0.55,
        'circle-radius': circleRadius(5, 1.5, 8, 3, 10, 5, 12, 9, 14, 18, 17, 60),
      },
    },
    {
      id: 'suggestions', type: 'circle', source: 'suggestions', 'source-layer': 'suggestions',
      layout: { visibility: 'none' },
      paint: {
        'circle-color': '#f59e0b',
        'circle-stroke-color': '#ffffff',
        'circle-stroke-width': 1,
        'circle-radius': circleRadius(5, 2, 10, 4, 14, 7),
      },
    },
    {
      id: 'places', type: 'circle', source: 'places', 'source-layer': 'places',
      paint: {
        'circle-color': '#10b981',
        'circle-stroke-color': '#ffffff',
        'circle-stroke-width': 1,
        'circle-radius': circleRadius(5, 2, 10, 4, 14, 7),
      },
    },
  );

  return { version: 8, sources, layers };
}

export function basemapLayerIds(basemap) {
  return (BASEMAPS[basemap] || []).map((_, i) => `base-${basemap}-${i}`);
}

// #map=zoom/lat/lon&lang=en, the same shape osm.org uses.
export function parseMapHash(hash) {
  const params = new URLSearchParams(String(hash || '').replace(/^#/, ''));
  const m = (params.get('map') || '').match(/^(-?\d+(?:\.\d+)?)\/(-?\d+(?:\.\d+)?)\/(-?\d+(?:\.\d+)?)$/);
  if (!m) return null;
  const [zoom, lat, lon] = [Number(m[1]), Number(m[2]), Number(m[3])];
  if (zoom < 0 || zoom > 22 || Math.abs(lat) > 85 || Math.abs(lon) > 180) return null;
  return { zoom, lat, lon };
}

export function formatMapHash({ zoom, lat, lon }, existingHash = '') {
  const params = new URLSearchParams(String(existingHash).replace(/^#/, ''));
  params.set('map', `${zoom.toFixed(2)}/${lat.toFixed(5)}/${lon.toFixed(5)}`);
  return `#${params.toString().replace(/%2F/g, '/')}`;
}

// Rows shown in the popup for a clicked feature: [label key, value] pairs.
// Values are plain strings; the caller must insert them with textContent.
export function popupRows(layer, props) {
  const p = props || {};
  const rows = [];
  const add = (key, value) => {
    if (value !== undefined && value !== null && value !== '') rows.push([key, String(value)]);
  };
  if (layer === 'places') {
    add('glName', p.name);
    add('glNameEn', p.name_en);
    add('glReligion', p.religion);
    add('glDenomination', p.denomination && p.denomination !== 'unknown' ? p.denomination : '');
    add('glBuilding', p.building);
  } else if (layer === 'suggestions') {
    add('glName', p.name_ar);
    add('glNameEn', p.name_en);
    add('glWikidata', p.qid);
    add('glNearest', p.nearest_osm_m !== undefined ? `${p.nearest_osm_m} m` : '');
  } else if (layer === 'gaps') {
    add('glUrgency', p.urgency);
    add('glScore', p.gap_score);
    add('glRoadLength', p.road_len !== undefined ? `${p.road_len} m` : '');
  }
  return rows;
}

// Links out of the popup. OSM objects open on osm.org; the edit link goes to iD.
export function popupLinks(layer, props, [lon, lat]) {
  const p = props || {};
  const at = `#map=18/${lat.toFixed(5)}/${lon.toFixed(5)}`;
  const links = [];
  if (layer === 'places' && p.osm_id) {
    const type = p.osm_type || 'node';
    links.push({ key: 'glViewOsm', href: `https://www.openstreetmap.org/${type}/${p.osm_id}` });
  }
  if (layer === 'suggestions' && /^Q\d+$/.test(p.qid || '')) {
    links.push({ key: 'glViewWikidata', href: `https://www.wikidata.org/wiki/${p.qid}` });
  }
  links.push({ key: 'glEditId', href: `https://www.openstreetmap.org/edit?editor=id${at}` });
  return links;
}

// Layers that react to clicks, topmost first.
export const CLICK_LAYERS = ['places', 'suggestions', 'gaps'];

// Number keys toggle overlays: 1 places, 2 suggestions, 3 gaps. Keys come from shortcutKey().
export const LAYER_KEYS = { 1: 'places', 2: 'suggestions', 3: 'gaps' };
