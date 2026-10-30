// MapLibre GL map kit (opt-in with ?map=gl). Implements the same factories as
// kit_leaflet.js, so app.js runs unchanged on either backend.
//
// Differences to know about:
// - Zoom numbers are Leaflet's (256 px tiles). MapLibre's zoom is one lower for
//   the same view, so the facade converts at its edges and permalinks, the
//   cluster threshold and every flyTo keep their meaning.
// - No text layers: cluster counts are DOM markers (same HTML and CSS as the
//   Leaflet clusters), which avoids a glyph server and the Arabic RTL text
//   plugin. Popups are DOM too, so Arabic renders natively.
import * as maplibregl from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url';
import 'maplibre-gl/dist/maplibre-gl.css';
import { interpolateGapScore, gapPixel, invertedMask } from './gap_field.js';

// The default worker URL is derived from the bundle's own location, which does
// not hold the worker file after bundling; point at the emitted asset instead.
maplibregl.setWorkerUrl(workerUrl);

const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services';
const ESRI_ATTR = 'Tiles &copy; Esri';
const ESRI_IMAGERY_ATTR = 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community';
const ESRI_STREETS_ATTR = 'Tiles &copy; Esri &mdash; Source: Esri, DeLorme, NAVTEQ, USGS, Intermap, iPC, NRCAN, Esri Japan, METI, Esri China (Hong Kong), Esri (Thailand), TomTom, 2012';
const CARTO_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>';
const BG = '#0a0b10';

// Draw order, bottom to top. Each slot is an invisible background layer that
// real layers are inserted in front of, so basemap swaps keep the overlays on top.
const SLOTS = ['basemap', 'field', 'places', 'top'];
const toGlZoom = z => z - 1;
const toLeafletZoom = z => z + 1;

let uid = 0;
const nextId = prefix => `${prefix}-${++uid}`;

class GlMap {
  constructor(containerId, { center, zoom }) {
    this.gl = new maplibregl.Map({
      container: containerId,
      style: {
        version: 8,
        sources: {},
        layers: SLOTS.map(s => ({ id: `slot-${s}`, type: 'background', paint: { 'background-color': BG, 'background-opacity': s === 'basemap' ? 1 : 0 } })),
      },
      center: [center[1], center[0]],
      zoom: toGlZoom(zoom),
      maxZoom: toGlZoom(20),
      dragRotate: false,
      pitchWithRotate: false,
      attributionControl: false,
    });
    this.gl.touchZoomRotate.disableRotation();
    this.gl.keyboard.disableRotation();
    // Zoom buttons bottom-left, away from the sidebar (RTL layout); no compass: rotation is off.
    this.gl.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-left');

    this._attribution = [];
    this._attrControl = null;
    this.attributionControl = { addAttribution: html => this._addAttribution(html) };
    this._ready = false;
    this._queue = [];
    this._layers = new Set();
    this._popups = new Set();
    this._interactive = [];
    this.gl.once('load', () => {
      this._ready = true;
      this._queue.splice(0).forEach(fn => fn());
    });
  }

  _addAttribution(html) {
    this._attribution.push(html);
    if (this._attrControl) this.gl.removeControl(this._attrControl);
    this._attrControl = new maplibregl.AttributionControl({ compact: false, customAttribution: this._attribution });
    this.gl.addControl(this._attrControl, 'bottom-right');
  }

  // Runs fn once the style is loaded; calls made earlier run in order.
  whenReady(fn) {
    if (this._ready) fn();
    else this._queue.push(fn);
  }

  // Adds a style layer in front of its slot's anchor, i.e. behind every later slot.
  addStyleLayer(spec, slot) {
    const next = SLOTS[SLOTS.indexOf(slot) + 1];
    this.gl.addLayer(spec, next ? `slot-${next}` : undefined);
  }

  addLayer(layer) {
    if (this._layers.has(layer)) return this;
    this._layers.add(layer);
    this.whenReady(() => { if (this._layers.has(layer)) layer._mount(this); });
    return this;
  }

  removeLayer(layer) {
    if (!this._layers.delete(layer)) return this;
    this.whenReady(() => layer._unmount(this));
    return this;
  }

  hasLayer(layer) {
    return this._layers.has(layer);
  }

  // Layer ids that swallow map clicks (a click on a marker is not a map click, as in Leaflet).
  registerInteractive(ids) {
    this._interactive.push(...ids);
  }

  openPopup(lngLat, { html, node, className, closeButton = false, offset = 8 }) {
    const popup = new maplibregl.Popup({ className, closeButton, offset, maxWidth: '320px' }).setLngLat(lngLat);
    if (node) popup.setDOMContent(node);
    else popup.setHTML(html);
    popup.addTo(this.gl);
    this._popups.add(popup);
    popup.on('close', () => this._popups.delete(popup));
    return popup;
  }

  closePopup(popup) {
    if (popup) popup.remove();
    else [...this._popups].forEach(p => p.remove());
  }

  getCenter() {
    const c = this.gl.getCenter();
    return { lat: c.lat, lng: c.lng };
  }

  getZoom() {
    return toLeafletZoom(this.gl.getZoom());
  }

  getBounds() {
    const b = this.gl.getBounds();
    const [w, s, e, n] = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()];
    return {
      contains: ([lat, lon]) => lon >= w && lon <= e && lat >= s && lat <= n,
      getWest: () => w, getEast: () => e, getSouth: () => s, getNorth: () => n,
    };
  }

  setView([lat, lon], zoom, { animate = true } = {}) {
    const opts = { center: [lon, lat], zoom: toGlZoom(zoom) };
    if (animate && this._ready) this.gl.easeTo(opts);
    else this.gl.jumpTo(opts);
    return this;
  }

  flyTo([lat, lon], zoom, { duration } = {}) {
    this.gl.flyTo({ center: [lon, lat], zoom: toGlZoom(zoom), ...(duration ? { duration: duration * 1000 } : {}) });
    return this;
  }

  setMaxZoom(zoom) {
    this.gl.setMaxZoom(toGlZoom(zoom));
    return this;
  }

  on(type, fn) {
    if (type === 'click' || type === 'contextmenu') {
      let lastFired = 0;
      const emit = (point, lngLat, originalEvent) => {
        if (this._interactive.length && this._hitsInteractive(point)) return;
        // A long press can arrive both as the browser's contextmenu event and from the
        // touch handler below; deliver it once.
        if (type === 'contextmenu') {
          if (Date.now() - lastFired < 1000) return;
          lastFired = Date.now();
        }
        fn({ latlng: { lat: lngLat.lat, lng: lngLat.lng }, originalEvent });
      };
      this.gl.on(type, e => emit(e.point, e.lngLat, e.originalEvent));
      if (type === 'contextmenu') this._onLongPress(emit);
    } else {
      this.gl.on(type, fn);
    }
    return this;
  }

  // iOS Safari never fires contextmenu on a long press (Leaflet synthesises it there),
  // so the "add a mosque / note here" menu would be unreachable on iPhones.
  _onLongPress(emit) {
    const el = this.gl.getCanvasContainer();
    let timer = null;
    let start = null;
    const cancel = () => { clearTimeout(timer); timer = null; };
    el.addEventListener('touchstart', e => {
      cancel();
      if (e.touches.length !== 1) return;
      const t = e.touches[0];
      start = { x: t.clientX, y: t.clientY };
      timer = setTimeout(() => {
        const r = el.getBoundingClientRect();
        const point = { x: start.x - r.left, y: start.y - r.top };
        emit(point, this.gl.unproject([point.x, point.y]), e);
      }, 600);
    }, { passive: true });
    el.addEventListener('touchmove', e => {
      const t = e.touches[0];
      if (timer && Math.hypot(t.clientX - start.x, t.clientY - start.y) > 10) cancel();
    }, { passive: true });
    el.addEventListener('touchend', cancel, { passive: true });
    el.addEventListener('touchcancel', cancel, { passive: true });
  }

  _hitsInteractive(point) {
    const layers = this._interactive.filter(id => this.gl.getLayer(id));
    return layers.length > 0 && this.gl.queryRenderedFeatures(point, { layers }).length > 0;
  }
}

function createMap(containerId, opts) {
  const map = new GlMap(containerId, opts);
  // The overlays are OSM data whatever the basemap.
  map.attributionControl.addAttribution('Data &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors (ODbL)');
  return map;
}

// ---------------------------------------------------------------- basemaps

// parts: [{ tiles: [url..], attribution }] drawn bottom to top.
class GlBasemap {
  constructor(parts, { maxZoom, maxNativeZoom }) {
    this.parts = parts;
    this._ids = [];
    this._map = null;
    // A source's maxzoom cannot be edited in place, so changing maxNativeZoom
    // (the satellite zoom cap) re-mounts the layer.
    let native = maxNativeZoom;
    this.options = { maxZoom };
    Object.defineProperty(this.options, 'maxNativeZoom', {
      enumerable: true,
      get: () => native,
      set: v => {
        if (v === native) return;
        native = v;
        this.redraw();
      },
    });
  }

  addTo(map) {
    map.addLayer(this);
    return this;
  }

  _mount(map) {
    this._map = map;
    this.parts.forEach(part => {
      const id = nextId('basemap');
      map.gl.addSource(id, {
        type: 'raster',
        tiles: part.tiles,
        tileSize: 256,
        maxzoom: this.options.maxNativeZoom ?? this.options.maxZoom,
        attribution: part.attribution || '',
      });
      map.addStyleLayer({ id, type: 'raster', source: id }, 'basemap');
      this._ids.push(id);
    });
  }

  _unmount(map) {
    this._ids.forEach(id => {
      if (map.gl.getLayer(id)) map.gl.removeLayer(id);
      if (map.gl.getSource(id)) map.gl.removeSource(id);
    });
    this._ids = [];
    this._map = null;
  }

  // Called after options.maxNativeZoom changed (the source's maxzoom cannot be edited in place).
  redraw() {
    const map = this._map;
    if (!map) return;
    this._unmount(map);
    this._mount(map);
  }
}

// Imagery drawn only inside the boundary: an "everything except Saudi Arabia"
// polygon in the page background colour sits on top of the raster.
class GlClippedSatellite extends GlBasemap {
  constructor(boundaryGeometry) {
    super([{ tiles: [`${ESRI}/World_Imagery/MapServer/tile/{z}/{y}/{x}`], attribution: ESRI_IMAGERY_ATTR }], { maxZoom: 20, maxNativeZoom: 19 });
    this._mask = invertedMask(boundaryGeometry);
  }

  _mount(map) {
    super._mount(map);
    const id = nextId('basemap-mask');
    map.gl.addSource(id, { type: 'geojson', data: this._mask });
    map.addStyleLayer({ id, type: 'fill', source: id, paint: { 'fill-color': BG, 'fill-antialias': true } }, 'basemap');
    this._ids.push(id);
  }
}

function carto(style, cartoKey) {
  const key = `?key=${encodeURIComponent(cartoKey)}`;
  return ['a', 'b', 'c', 'd'].map(s => `https://${s}.basemaps.cartocdn.com/${style}/{z}/{x}/{y}.png${key}`);
}

function createBasemaps({ cartoKey }) {
  const esri = (path, attribution, extra = {}) => ({ tiles: [`${ESRI}/${path}/MapServer/tile/{z}/{y}/{x}`], attribution, ...extra });
  const canvas = name => new GlBasemap([
    esri(`Canvas/World_${name}_Gray_Base`, ESRI_ATTR),
    esri(`Canvas/World_${name}_Gray_Reference`, ''),
  ], { maxZoom: 20, maxNativeZoom: 19 });

  return {
    dark: cartoKey ? new GlBasemap([{ tiles: carto('dark_all', cartoKey), attribution: CARTO_ATTR }], { maxZoom: 20 }) : canvas('Dark'),
    light: cartoKey ? new GlBasemap([{ tiles: carto('light_all', cartoKey), attribution: CARTO_ATTR }], { maxZoom: 20 }) : canvas('Light'),
    satellite: new GlBasemap([esri('World_Imagery', ESRI_IMAGERY_ATTR)], { maxZoom: 20, maxNativeZoom: 19 }),
    streets: new GlBasemap([esri('World_Street_Map', ESRI_STREETS_ATTR)], { maxZoom: 20 }),
  };
}

function createClippedSatellite(boundaryGeometry) {
  return new GlClippedSatellite(boundaryGeometry);
}

// ---------------------------------------------------------------- clustered points

const POINT_COLORS = {
  muslim: '#00ff87',
  christian: '#4facfe',
  improve: '#ffb03a',
  unknown: '#00f2fe',
};
let markerUid = 0;

// Points clustered by supercluster inside MapLibre. Clusters are DOM markers
// (so they reuse the Leaflet cluster CSS and need no glyphs), single points are
// circle layers. Markers are plain descriptors from the createXMarker factories.
class GlClusterLayer {
  constructor({ clusterRadius, clusterMaxZoom, clusterHtml, pointLayers, onPointClick }) {
    this.cfg = { clusterRadius, clusterMaxZoom, clusterHtml, pointLayers, onPointClick };
    this.markers = new Map();
    this._map = null;
    this._srcId = null;
    this._flushQueued = false;
    this._clusterMarkers = new Map();
    this._sync = null;
  }

  addTo(map) {
    map.addLayer(this);
    return this;
  }

  _key(m) {
    if (!m._mid) m._mid = ++markerUid;
    return m._mid;
  }

  addLayers(list) {
    list.forEach(m => this.markers.set(this._key(m), m));
    this._dirty();
  }

  addLayer(m) {
    this.markers.set(this._key(m), m);
    this._dirty();
  }

  removeLayer(m) {
    if (m._mid && this.markers.delete(m._mid)) this._dirty();
  }

  hasLayer(m) {
    return Boolean(m._mid) && this.markers.get(m._mid) === m;
  }

  clearLayers() {
    this.markers.clear();
    this._dirty();
  }

  _dirty() {
    if (!this._map || this._flushQueued) return;
    this._flushQueued = true;
    queueMicrotask(() => {
      this._flushQueued = false;
      const src = this._map && this._map.gl.getSource(this._srcId);
      if (src) src.setData(this._geojson());
    });
  }

  _geojson() {
    const features = [];
    this.markers.forEach((m, mid) => {
      features.push({
        type: 'Feature',
        id: mid,
        properties: { mid, cls: m.cls || 'unknown' },
        geometry: { type: 'Point', coordinates: [m.lon, m.lat] },
      });
    });
    return { type: 'FeatureCollection', features };
  }

  _mount(map) {
    this._map = map;
    const gl = map.gl;
    const id = this._srcId = nextId('cluster');
    gl.addSource(id, {
      type: 'geojson',
      data: this._geojson(),
      cluster: true,
      clusterRadius: this.cfg.clusterRadius,
      clusterMaxZoom: this.cfg.clusterMaxZoom,
    });
    this._layerIds = this.cfg.pointLayers(id).map(spec => {
      map.addStyleLayer({ ...spec, source: id, filter: ['!', ['has', 'point_count']] }, 'places');
      return spec.id;
    });
    const hit = this._layerIds[0]; // the largest circle is the click target
    map.registerInteractive([hit]);

    this._onClick = e => {
      const f = e.features && e.features[0];
      const m = f && this.markers.get(f.properties.mid);
      if (m) this.cfg.onPointClick(map, m);
    };
    this._onEnter = () => { gl.getCanvas().style.cursor = 'pointer'; };
    this._onLeave = () => { gl.getCanvas().style.cursor = ''; };
    gl.on('click', hit, this._onClick);
    gl.on('mouseenter', hit, this._onEnter);
    gl.on('mouseleave', hit, this._onLeave);
    this._hit = hit;

    this._sync = () => this._syncClusters();
    gl.on('idle', this._sync);
    gl.on('moveend', this._sync);
    this._syncClusters();
  }

  _unmount(map) {
    const gl = map.gl;
    gl.off('idle', this._sync);
    gl.off('moveend', this._sync);
    gl.off('click', this._hit, this._onClick);
    gl.off('mouseenter', this._hit, this._onEnter);
    gl.off('mouseleave', this._hit, this._onLeave);
    this._clusterMarkers.forEach(c => c.marker.remove());
    this._clusterMarkers.clear();
    this._layerIds.forEach(lid => { if (gl.getLayer(lid)) gl.removeLayer(lid); });
    if (gl.getSource(this._srcId)) gl.removeSource(this._srcId);
    this._map = null;
  }

  _syncClusters() {
    const map = this._map;
    if (!map) return;
    const gl = map.gl;
    if (!gl.getSource(this._srcId) || !gl.isSourceLoaded(this._srcId)) return;
    const seen = new Set();
    const b = gl.getBounds();
    for (const f of gl.querySourceFeatures(this._srcId, { filter: ['has', 'point_count'] })) {
      const cid = f.properties.cluster_id;
      if (seen.has(cid)) continue;
      const [lon, lat] = f.geometry.coordinates;
      if (!b.contains([lon, lat])) continue;
      seen.add(cid);
      const count = f.properties.point_count;
      const existing = this._clusterMarkers.get(cid);
      if (existing && existing.count === count) continue;
      if (existing) existing.marker.remove();
      this._clusterMarkers.set(cid, { count, marker: this._clusterMarker(cid, count, [lon, lat]) });
    }
    for (const [cid, c] of this._clusterMarkers) {
      if (!seen.has(cid)) { c.marker.remove(); this._clusterMarkers.delete(cid); }
    }
  }

  _clusterMarker(cid, count, lngLat) {
    const { html, size, className } = this.cfg.clusterHtml(count);
    const el = document.createElement('div');
    el.className = className;
    el.style.width = el.style.height = `${size}px`;
    el.innerHTML = html;
    el.addEventListener('click', ev => {
      ev.stopPropagation();
      const gl = this._map.gl;
      gl.getSource(this._srcId).getClusterExpansionZoom(cid).then(zoom => gl.easeTo({ center: lngLat, zoom: zoom + 0.5 }));
    });
    return new maplibregl.Marker({ element: el }).setLngLat(lngLat).addTo(this._map.gl);
  }
}

// Match expression for the per-class circle colours.
const byClass = (colors, fallback) => ['match', ['get', 'cls'], ...Object.entries(colors).flat(), fallback];
const rgba = (hex, a) => `rgba(${parseInt(hex.slice(1, 3), 16)}, ${parseInt(hex.slice(3, 5), 16)}, ${parseInt(hex.slice(5, 7), 16)}, ${a})`;

function createPlaceLayer({ getMode }) {
  return new GlClusterLayer({
    clusterRadius: 50,
    clusterMaxZoom: toGlZoom(18),
    clusterHtml: count => {
      const improve = getMode() === 'improve';
      const colorPrimary = improve ? '#ffb03a' : 'var(--color-primary)';
      let c = improve ? 'rgba(255, 176, 58, ' : 'rgba(0, 242, 254, ';
      let size = 30;
      if (count < 10) c += '0.2)';
      else if (count < 100) { c += '0.4)'; size = 40; } else { c += '0.6)'; size = 50; }
      return {
        className: 'marker-cluster-custom',
        size,
        html: `<div style="background-color: ${c}; width: ${size}px; height: ${size}px; border-radius: 50%; display: flex; align-items: center; justify-content: center; border: 1px solid ${colorPrimary}; box-shadow: 0 0 10px ${colorPrimary}; font-weight: bold; color: white;"><span>${count}</span></div>`,
      };
    },
    pointLayers: () => {
      const id = nextId('places');
      return [
        { id: `${id}-ring`, type: 'circle', paint: { 'circle-radius': 7, 'circle-color': byClass(Object.fromEntries(Object.entries(POINT_COLORS).map(([k, v]) => [k, rgba(v, 0.15)])), rgba(POINT_COLORS.unknown, 0.15)), 'circle-stroke-width': 1, 'circle-stroke-color': byClass(POINT_COLORS, POINT_COLORS.unknown), 'circle-blur': 0 } },
        { id: `${id}-dot`, type: 'circle', paint: { 'circle-radius': 3.5, 'circle-color': byClass(POINT_COLORS, POINT_COLORS.unknown) } },
      ];
    },
    onPointClick: (map, m) => {
      m.onClick();
      map.closePopup();
      map.openPopup([m.lon, m.lat], { html: m.popupHtml(), offset: 10 });
    },
  });
}

function createPlaceMarker({ lat, lon, markerClass, popupHtml, onClick }) {
  return { lat, lon, cls: markerClass, popupHtml, onClick };
}

function createSuggestionLayer({ formatCount }) {
  return new GlClusterLayer({
    clusterRadius: 50,
    clusterMaxZoom: toGlZoom(17) - 1, // Leaflet: no clustering from zoom 17
    clusterHtml: count => {
      const size = count < 10 ? 32 : count < 100 ? 42 : 52;
      return {
        className: 'marker-cluster-custom',
        size,
        html: `<div class="suggestion-cluster" style="width: ${size}px; height: ${size}px; font-size: ${size > 40 ? 12 : 11}px;"><span>${formatCount(count)}</span></div>`,
      };
    },
    pointLayers: () => {
      const id = nextId('sug');
      const fill = byClass({ unnamed: '#94a3b8' }, '#f59e0b');
      return [{
        id: `${id}-dot`,
        type: 'circle',
        paint: {
          'circle-radius': 6,
          'circle-color': fill,
          'circle-opacity': 0.85,
          'circle-stroke-width': 1.5,
          'circle-stroke-color': byClass({ unnamed: '#64748b' }, '#d97706'),
        },
      }];
    },
    onPointClick: (map, m) => {
      const content = m.popupContent();
      map.closePopup();
      map.openPopup([m.lon, m.lat], typeof content === 'string' ? { html: content } : { node: content });
    },
  });
}

function createSuggestionMarker({ lat, lon, unnamed, popupContent }) {
  return { lat, lon, cls: unnamed ? 'unnamed' : 'named', popupContent };
}

// ---------------------------------------------------------------- heat and gap field

// leaflet.heat scales each point's weight by 2^-(maxZoom - zoom); the same ramp here.
function heatIntensity(maxZoom) {
  const top = toGlZoom(maxZoom);
  // Densities add linearly here, while leaflet.heat composites alpha, so they saturate
  // sooner; scale down to keep Riyadh from turning solid red.
  const k = 0.6;
  return ['interpolate', ['exponential', 2], ['zoom'], 1, k * 2 ** -(top - 1), top, k];
}

class GlHeatLayer {
  constructor(points, { radius, blur, maxZoom, gradient }) {
    this.points = points;
    this.opts = { radius, blur, maxZoom, gradient };
    this._map = null;
    this._id = null;
  }

  addTo(map) {
    map.addLayer(this);
    return this;
  }

  _radius() {
    return this.opts.radius + this.opts.blur * 0.75;
  }

  setOptions(opts) {
    Object.assign(this.opts, opts);
    if (this._map && this._map.gl.getLayer(this._id)) this._map.gl.setPaintProperty(this._id, 'heatmap-radius', this._radius());
  }

  _mount(map) {
    this._map = map;
    const id = this._id = nextId('heat');
    map.gl.addSource(id, {
      type: 'geojson',
      data: { type: 'FeatureCollection', features: this.points.map(([lat, lon]) => ({ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [lon, lat] } })) },
    });
    // leaflet.heat keeps each pixel's alpha tied to its density, so faint areas fade out
    // instead of showing the first colour at full strength; stop alpha rises with the stop.
    const ramp = Object.entries(this.opts.gradient).sort((a, b) => a[0] - b[0])
      .flatMap(([stop, color]) => [Number(stop), rgba(color, 0.3 + 0.7 * Number(stop))]);
    map.addStyleLayer({
      id, type: 'heatmap', source: id,
      paint: {
        'heatmap-radius': this._radius(),
        'heatmap-intensity': heatIntensity(this.opts.maxZoom),
        'heatmap-color': ['interpolate', ['linear'], ['heatmap-density'], 0, 'rgba(0,0,0,0)', ...ramp],
        'heatmap-opacity': 1,
      },
    }, 'field');
  }

  _unmount(map) {
    if (map.gl.getLayer(this._id)) map.gl.removeLayer(this._id);
    if (map.gl.getSource(this._id)) map.gl.removeSource(this._id);
    this._map = null;
  }
}

function createHeatLayer(points, opts) {
  return new GlHeatLayer(points, opts);
}

// The gap field is drawn on a canvas covering the viewport plus a margin, one
// pixel per 4 CSS px sample, and stretched over it by the GPU with nearest-
// neighbour filtering: the same blocks Leaflet's 4 px tiles produced. It is
// redrawn after each move (the old image stays put while panning).
const GAP_STEP = 4;
const GAP_PAD = 0.2;

class GlGapLayer {
  constructor(scoreByCell, maxScore, { gridSize }) {
    this.scoreByCell = scoreByCell;
    this.maxScore = maxScore || 1;
    this.gridSize = gridSize;
    this._map = null;
  }

  addTo(map) {
    map.addLayer(this);
    return this;
  }

  _mount(map) {
    this._map = map;
    const id = this._id = nextId('gap');
    this._canvas = document.createElement('canvas');
    this._canvas.width = this._canvas.height = 1;
    const coords = this._draw();
    map.gl.addSource(id, { type: 'canvas', canvas: this._canvas, coordinates: coords, animate: false });
    map.addStyleLayer({ id, type: 'raster', source: id, paint: { 'raster-resampling': 'nearest', 'raster-fade-duration': 0 } }, 'field');
    this._refresh = () => this._redraw();
    map.gl.on('moveend', this._refresh);
    this._upload();
  }

  _unmount(map) {
    map.gl.off('moveend', this._refresh);
    if (map.gl.getLayer(this._id)) map.gl.removeLayer(this._id);
    if (map.gl.getSource(this._id)) map.gl.removeSource(this._id);
    this._map = null;
  }

  // The canvas is re-uploaded to the GPU once per redraw, not every frame.
  _upload() {
    const src = this._map.gl.getSource(this._id);
    if (!src || !src.play) return;
    src.play();
    this._map.gl.once('render', () => src.pause());
  }

  _redraw() {
    const gl = this._map.gl;
    const src = gl.getSource(this._id);
    if (!src) return;
    src.setCoordinates(this._draw());
    this._upload();
  }

  // Paints the field for the current view and returns the canvas corners (lng/lat, tl tr br bl).
  _draw() {
    const gl = this._map.gl;
    const { clientWidth: w, clientHeight: h } = gl.getContainer();
    const x0 = -w * GAP_PAD, y0 = -h * GAP_PAD, x1 = w * (1 + GAP_PAD), y1 = h * (1 + GAP_PAD);
    const tl = gl.unproject([x0, y0]), br = gl.unproject([x1, y1]);
    const cw = Math.max(1, Math.round((x1 - x0) / GAP_STEP));
    const ch = Math.max(1, Math.round((y1 - y0) / GAP_STEP));
    const canvas = this._canvas;
    canvas.width = cw;
    canvas.height = ch;
    const ctx = canvas.getContext('2d');
    const img = ctx.createImageData(cw, ch);

    // The canvas is stretched linearly in Web Mercator, so sample on that grid.
    const mercY = lat => Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360));
    const latOf = y => (2 * Math.atan(Math.exp(y)) - Math.PI / 2) * 180 / Math.PI;
    const yTop = mercY(tl.lat), yBottom = mercY(br.lat);
    for (let j = 0; j < ch; j++) {
      const lat = latOf(yTop + (yBottom - yTop) * (j + 0.5) / ch);
      for (let i = 0; i < cw; i++) {
        const lon = tl.lng + (br.lng - tl.lng) * (i + 0.5) / cw;
        const px = gapPixel(interpolateGapScore(this.scoreByCell, this.gridSize, lon, lat), this.maxScore);
        if (!px) continue;
        const o = (j * cw + i) * 4;
        img.data[o] = px[0]; img.data[o + 1] = px[1]; img.data[o + 2] = px[2]; img.data[o + 3] = Math.round(px[3] * 255);
      }
    }
    ctx.putImageData(img, 0, 0);
    return [[tl.lng, tl.lat], [br.lng, tl.lat], [br.lng, br.lat], [tl.lng, br.lat]];
  }
}

function createGapLayer(scoreByCell, maxScore, opts) {
  return new GlGapLayer(scoreByCell, maxScore, opts);
}

// ---------------------------------------------------------------- notes, pending pin, popups

// Collection of DOM markers (notes). Items come from createNoteMarker.
class GlNoteLayer {
  constructor(map) {
    this._map = map;
    this._items = new Set();
    map.addLayer(this);
  }

  _mount() {}

  _unmount() {
    this.clearLayers();
  }

  addLayer(item) {
    const el = document.createElement('div');
    el.className = `note-marker ${item.closed ? 'closed' : ''}`;
    el.innerHTML = '<div class="note-marker-inner">📝</div>';
    const popup = new maplibregl.Popup({ closeButton: false, offset: 18 }).setHTML(item.popupHtml);
    item._marker = new maplibregl.Marker({ element: el, anchor: 'bottom' }).setLngLat([item.lon, item.lat]).setPopup(popup).addTo(this._map.gl);
    this._items.add(item);
  }

  clearLayers() {
    this._items.forEach(i => i._marker.remove());
    this._items.clear();
  }
}

function createNoteLayer(map) {
  return new GlNoteLayer(map);
}

function createNoteMarker({ lat, lon, closed, popupHtml }) {
  return { lat, lon, closed, popupHtml };
}

function createPendingMarker(map, { lat, lon, onDrag }) {
  const el = document.createElement('div');
  el.className = 'add-mosque-marker';
  el.innerHTML = '<div class="add-mosque-marker-pin"><span class="marker-pulse"></span><span class="marker-icon-inner">🕌</span></div>';
  const marker = new maplibregl.Marker({ element: el, anchor: 'bottom', draggable: true }).setLngLat([lon, lat]).addTo(map.gl);
  marker.on('drag', () => {
    const p = marker.getLngLat();
    onDrag(p.lat, p.lng);
  });
  return {
    setLatLng: ([la, lo]) => marker.setLngLat([lo, la]),
    remove: () => marker.remove(),
  };
}

function openPopup(map, latlng, content, { className } = {}) {
  return map.openPopup([latlng.lng, latlng.lat], { node: content, className, closeButton: true, offset: 8 });
}

export const kit = {
  name: 'gl',
  createMap,
  createBasemaps,
  createClippedSatellite,
  createPlaceLayer,
  createPlaceMarker,
  createSuggestionLayer,
  createSuggestionMarker,
  createHeatLayer,
  createGapLayer,
  createNoteLayer,
  createNoteMarker,
  createPendingMarker,
  openPopup,
};
