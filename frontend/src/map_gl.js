// MapLibre preview of the three PMTiles overlays (/mapgl). The Leaflet map at /
// stays the default until this reaches parity (REDESIGN.md §5 Phase 5).
//
// No text layers on purpose: labels would need a glyph server and the Arabic
// RTL text plugin (which wants 'wasm-unsafe-eval' in the CSP). Names appear in
// the click popup, which is plain DOM and renders Arabic natively.
import * as maplibregl from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url';
import 'maplibre-gl/dist/maplibre-gl.css';
import { Protocol } from 'pmtiles';
import './styles/fonts.css';
import './styles/page.css';
import './styles/mapgl.css';
import { currentLang, setLanguage, addTranslations, t } from './i18n.js';
import { shortcutKey } from './keys.js';
import { initAnalytics } from './analytics.js';
import {
  SA_CENTER, SA_ZOOM, OVERLAY_IDS, CLICK_LAYERS, LAYER_KEYS,
  buildStyle, basemapLayerIds, parseMapHash, formatMapHash, popupRows, popupLinks,
  suggestionsSource, SUGGESTIONS_LAYER,
} from './map_gl_view.js';
import { checkSuggestionsAccess } from './suggestions_access.js';

addTranslations({
  glTitle: ['الخريطة (MapLibre، تجريبية) | منارة', 'Map (MapLibre preview) | Manara'],
  glName: ['الاسم', 'Name'],
  glNameEn: ['الاسم بالإنجليزية', 'English name'],
  glReligion: ['الديانة', 'Religion'],
  glDenomination: ['المذهب', 'Denomination'],
  glBuilding: ['المبنى', 'Building'],
  glWikidata: ['ويكي بيانات', 'Wikidata'],
  glNearest: ['أقرب مسجد مرسوم', 'Nearest mapped mosque'],
  glUrgency: ['الأولوية', 'Urgency'],
  glScore: ['درجة الفجوة', 'Gap score'],
  glRoadLength: ['طول الطرق', 'Road length'],
  glViewOsm: ['عرض في OSM ↗', 'View on OSM ↗'],
  glViewWikidata: ['عرض في ويكي بيانات ↗', 'View on Wikidata ↗'],
  glEditId: ['تحرير في iD ↗', 'Edit in iD ↗'],
  glLoadError: ['تعذر تحميل بيانات الخريطة. حدّث الصفحة أو جرّب الخريطة الكاملة.', 'Could not load the map data. Reload, or use the full map.'],
});

const params = new URLSearchParams(window.location.search);
const initialBasemap = ['light', 'dark', 'satellite', 'streets'].includes(params.get('base'))
  ? params.get('base')
  : (window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');

const protocol = new Protocol();
maplibregl.addProtocol('pmtiles', protocol.tile);
// The default worker URL is derived from the bundle's own location, which does
// not hold the worker file after bundling; point at the emitted asset instead.
maplibregl.setWorkerUrl(workerUrl);

const start = parseMapHash(window.location.hash);
const map = new maplibregl.Map({
  container: 'map',
  // Suggestions are added below, once the backend confirms this viewer is allowed to see them.
  style: buildStyle({ origin: window.location.origin, basemap: initialBasemap, suggestions: false }),
  center: start ? [start.lon, start.lat] : SA_CENTER,
  zoom: start ? start.zoom : SA_ZOOM,
  maxZoom: 19,
  attributionControl: false,
});
map.addControl(new maplibregl.AttributionControl({ compact: false }), 'bottom-left');
map.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), 'top-left');
map.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-right');

const status = document.getElementById('mapgl-status');
map.on('error', e => {
  console.warn('map error', e.error || e);
  if (e.sourceId && OVERLAY_IDS.includes(e.sourceId)) status.textContent = t('glLoadError');
});
map.on('sourcedata', e => { if (e.sourceId && OVERLAY_IDS.includes(e.sourceId) && e.isSourceLoaded) status.textContent = ''; });

// Keep the view in the URL so a link reproduces it; replaceState so panning does not fill history.
map.on('moveend', () => {
  const c = map.getCenter();
  const hash = formatMapHash({ zoom: map.getZoom(), lat: c.lat, lon: c.lng }, window.location.hash);
  history.replaceState(null, '', hash);
});

// -- Layer and basemap controls -------------------------------------------
const toggles = [...document.querySelectorAll('input[data-layer]')];
function setLayerVisible(id, visible) {
  if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', visible ? 'visible' : 'none');
  const box = toggles.find(b => b.dataset.layer === id);
  if (box) box.checked = visible;
}
// Wikidata suggestions are private to allowlisted OSM users: the checkbox is hidden in the HTML
// and the source/layer only exist once the backend says yes, so nobody else requests the tiles.
const suggestionsToggle = toggles.find(b => b.dataset.layer === 'suggestions');
let mapLoaded = false;
map.once('load', () => { mapLoaded = true; });
checkSuggestionsAccess().then(ok => {
  if (!ok) return;
  const add = () => {
    if (map.getSource('suggestions')) return;
    map.addSource('suggestions', suggestionsSource(window.location.origin));
    map.addLayer(SUGGESTIONS_LAYER, 'places');
    if (suggestionsToggle) {
      suggestionsToggle.closest('label').hidden = false;
      setLayerVisible('suggestions', suggestionsToggle.checked);
    }
  };
  if (mapLoaded) add(); else map.once('load', add);
});

// The style starts with suggestions hidden; sync every checkbox to what the style says.
map.on('load', () => toggles.forEach(b => setLayerVisible(b.dataset.layer, b.checked)));
toggles.forEach(b => b.addEventListener('change', () => setLayerVisible(b.dataset.layer, b.checked)));

const basemapSelect = document.getElementById('basemap-select');
basemapSelect.value = initialBasemap;
basemapSelect.addEventListener('change', () => {
  for (const name of ['light', 'dark', 'satellite', 'streets']) {
    for (const id of basemapLayerIds(name)) {
      map.setLayoutProperty(id, 'visibility', name === basemapSelect.value ? 'visible' : 'none');
    }
  }
});

document.addEventListener('keydown', e => {
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if (/^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName) && e.target.type !== 'checkbox') return;
  const id = LAYER_KEYS[shortcutKey(e)];
  if (!id || !map.getLayer(id)) return;
  const box = toggles.find(b => b.dataset.layer === id);
  setLayerVisible(id, !box.checked);
});

// -- Click popup -----------------------------------------------------------
map.on('click', e => {
  const present = CLICK_LAYERS.filter(id => map.getLayer(id) && map.getLayoutProperty(id, 'visibility') !== 'none');
  // A few pixels of slack so small dots are easy to hit on touch screens.
  const r = 6;
  const hits = map.queryRenderedFeatures([[e.point.x - r, e.point.y - r], [e.point.x + r, e.point.y + r]], { layers: present });
  if (!hits.length) return;
  // Layers are listed topmost first; within a layer take the one nearest the click.
  const top = CLICK_LAYERS.find(id => hits.some(h => h.layer.id === id));
  const feature = hits.filter(h => h.layer.id === top).sort((a, b) => dist(a, e.lngLat) - dist(b, e.lngLat))[0];
  const coords = feature.geometry.coordinates;
  new maplibregl.Popup({ maxWidth: '280px' }).setLngLat(coords).setDOMContent(buildPopup(top, feature.properties, coords)).addTo(map);
});
const dist = (f, ll) => (f.geometry.coordinates[0] - ll.lng) ** 2 + (f.geometry.coordinates[1] - ll.lat) ** 2;

for (const id of CLICK_LAYERS) {
  map.on('mouseenter', id, () => { map.getCanvas().style.cursor = 'pointer'; });
  map.on('mouseleave', id, () => { map.getCanvas().style.cursor = ''; });
}

// Every value comes from OSM or Wikidata, so it goes in with textContent, never as HTML.
function buildPopup(layer, props, coords) {
  const root = document.createElement('div');
  root.className = 'mapgl-popup';
  const dl = document.createElement('dl');
  for (const [key, value] of popupRows(layer, props)) {
    const dt = document.createElement('dt');
    dt.textContent = t(key);
    const dd = document.createElement('dd');
    dd.textContent = value;
    dd.dir = 'auto';
    dl.append(dt, dd);
  }
  root.append(dl);
  const links = document.createElement('p');
  for (const l of popupLinks(layer, props, coords)) {
    const a = document.createElement('a');
    a.href = l.href;
    a.target = '_blank';
    a.rel = 'noopener';
    a.textContent = t(l.key);
    links.append(a);
  }
  root.append(links);
  return root;
}

document.getElementById('btn-toggle-lang').addEventListener('click', () => {
  setLanguage(currentLang === 'ar' ? 'en' : 'ar');
});
setLanguage(currentLang);
initAnalytics();
