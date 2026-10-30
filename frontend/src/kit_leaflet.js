// Leaflet map kit: the default backend. app.js builds every map object through
// this interface and never calls Leaflet itself, so kit_gl.js can supply the same
// factories on MapLibre.
//
// The map object each kit returns offers: getCenter() -> {lat, lng}, getZoom(),
// getBounds() -> {contains([lat, lon]), getWest/East/North/South()},
// setView([lat, lon], zoom, {animate}), flyTo([lat, lon], zoom, {duration}),
// on(event, fn) for move/moveend/zoomend/click/contextmenu (events carry
// latlng {lat, lng}), setMaxZoom(z), addLayer/removeLayer/hasLayer(layer),
// closePopup(popup?) and attributionControl.addAttribution(html).
//
// Layers are the objects the factories below return. Collections accept
// markers made by the matching createXMarker factory: clearLayers(),
// addLayers([..]), addLayer(m), removeLayer(m), hasLayer(m).
import './leaflet-bundle.js';
import { interpolateGapScore, gapPixel } from './gap_field.js';

const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services';
const ESRI_ATTR = 'Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ';
const ESRI_IMAGERY_ATTR = 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community';
const ESRI_STREETS_ATTR = 'Tiles &copy; Esri &mdash; Source: Esri, DeLorme, NAVTEQ, USGS, Intermap, iPC, NRCAN, Esri Japan, METI, Esri China (Hong Kong), Esri (Thailand), TomTom, 2012';
const CARTO_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>';

function createMap(containerId, { center, zoom }) {
  const map = L.map(containerId, {
    zoomControl: false // Custom styled zoom controls
  }).setView(center, zoom);

  // The overlays are OSM data whatever the basemap, so the ODbL attribution
  // stays on even over the Esri tiles.
  map.attributionControl.addAttribution('Data &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors (ODbL)');

  // Position Zoom Control on the bottom-left to avoid sidebar overlap on the right (RTL layout)
  L.control.zoom({ position: 'bottomleft' }).addTo(map);
  return map;
}

// { dark, satellite, light, streets }: layers with options.maxZoom (and
// options.maxNativeZoom + redraw() for satellite), added with map.addLayer.
// With a CARTO key the dark/light basemaps are CARTO's, otherwise keyless Esri.
function createBasemaps({ cartoKey }) {
  const cartoParam = cartoKey ? `?key=${encodeURIComponent(cartoKey)}` : '';

  let darkLayer;
  let lightLayer;

  if (cartoKey) {
    darkLayer = L.tileLayer(`https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png${cartoParam}`, {
      attribution: CARTO_ATTR, subdomains: 'abcd', maxZoom: 20
    });
    lightLayer = L.tileLayer(`https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png${cartoParam}`, {
      attribution: CARTO_ATTR, subdomains: 'abcd', maxZoom: 20
    });
  } else {
    darkLayer = L.layerGroup([
      L.tileLayer(`${ESRI}/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}`, { attribution: ESRI_ATTR, maxZoom: 20, maxNativeZoom: 19 }),
      L.tileLayer(`${ESRI}/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}`, { attribution: '', maxZoom: 20, maxNativeZoom: 19 })
    ]);
    darkLayer.options = { maxZoom: 20 };

    lightLayer = L.layerGroup([
      L.tileLayer(`${ESRI}/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}`, { attribution: ESRI_ATTR, maxZoom: 20, maxNativeZoom: 19 }),
      L.tileLayer(`${ESRI}/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}`, { attribution: '', maxZoom: 20, maxNativeZoom: 19 })
    ]);
    lightLayer.options = { maxZoom: 20 };
  }

  const satelliteLayer = L.tileLayer(`${ESRI}/World_Imagery/MapServer/tile/{z}/{y}/{x}`, {
    attribution: ESRI_IMAGERY_ATTR, maxZoom: 20, maxNativeZoom: 19
  });
  const streetsLayer = L.tileLayer(`${ESRI}/World_Street_Map/MapServer/tile/{z}/{y}/{x}`, {
    attribution: ESRI_STREETS_ATTR, maxZoom: 20
  });

  return { dark: darkLayer, satellite: satelliteLayer, light: lightLayer, streets: streetsLayer };
}

// Esri imagery drawn only inside the Saudi Arabia boundary (GeoJSON geometry).
function createClippedSatellite(boundaryGeometry) {
  return L.TileLayer.boundaryCanvas(`${ESRI}/World_Imagery/MapServer/tile/{z}/{y}/{x}`, {
    boundary: boundaryGeometry,
    attribution: ESRI_IMAGERY_ATTR,
    maxZoom: 20,
    maxNativeZoom: 19,
    crossOrigin: true
  });
}

// One shared icon per marker class instead of a new divIcon per place.
const MARKER_ICONS = {};
function markerIcon(markerClass) {
  if (!MARKER_ICONS[markerClass]) {
    MARKER_ICONS[markerClass] = L.divIcon({
      html: '<div class="custom-marker-inner"></div>',
      className: `custom-marker ${markerClass}`,
      iconSize: [12, 12],
      iconAnchor: [6, 6]
    });
  }
  return MARKER_ICONS[markerClass];
}

// Clustered collection of place markers. getMode() -> 'improve' | other tints the clusters.
function createPlaceLayer({ getMode }) {
  return L.markerClusterGroup({
    showCoverageOnHover: false,
    maxClusterRadius: 50,
    iconCreateFunction: function (cluster) {
      const childCount = cluster.getChildCount();
      const improve = getMode() === 'improve';
      let colorPrimary = improve ? '#ffb03a' : 'var(--color-primary)';
      let c = improve ? 'rgba(255, 176, 58, ' : 'rgba(0, 242, 254, ';

      let size = 30;
      if (childCount < 10) {
        c += '0.2)';
        size = 30;
      } else if (childCount < 100) {
        c += '0.4)';
        size = 40;
      } else {
        c += '0.6)';
        size = 50;
      }

      return new L.DivIcon({
        html: `<div style="background-color: ${c}; width: ${size}px; height: ${size}px; border-radius: 50%; display: flex; align-items: center; justify-content: center; border: 1px solid ${colorPrimary}; box-shadow: 0 0 10px ${colorPrimary}; font-weight: bold; color: white;"><span>${childCount}</span></div>`,
        className: 'marker-cluster-custom',
        iconSize: new L.Point(size, size)
      });
    }
  });
}

// A place marker. popupHtml() is evaluated when the popup opens; onClick runs on click.
function createPlaceMarker({ lat, lon, markerClass, popupHtml, onClick }) {
  const marker = L.marker([lat, lon], { icon: markerIcon(markerClass) });
  marker.bindPopup(popupHtml, { closeButton: false });
  marker.on('click', onClick);
  return marker;
}

function createSuggestionLayer({ formatCount }) {
  return L.markerClusterGroup({
    showCoverageOnHover: false,
    chunkedLoading: true,
    chunkInterval: 100,
    chunkDelay: 20,
    maxClusterRadius: 50,
    disableClusteringAtZoom: 17,
    iconCreateFunction: function (cluster) {
      const childCount = cluster.getChildCount();
      let size = 32;
      if (childCount < 10) size = 32;
      else if (childCount < 100) size = 42;
      else size = 52;

      return L.divIcon({
        html: `<div class="suggestion-cluster" style="width: ${size}px; height: ${size}px; font-size: ${size > 40 ? 12 : 11}px;"><span>${formatCount(childCount)}</span></div>`,
        className: 'marker-cluster-custom',
        iconSize: new L.Point(size, size)
      });
    }
  });
}

// popupContent() is evaluated when the popup opens (HTML string or DOM node).
function createSuggestionMarker({ lat, lon, unnamed, popupContent }) {
  const marker = L.circleMarker([lat, lon], {
    radius: 6,
    color: unnamed ? '#64748b' : '#d97706',
    fillColor: unnamed ? '#94a3b8' : '#f59e0b',
    fillOpacity: 0.85,
    weight: 1.5
  });
  marker.bindPopup(popupContent);
  return marker;
}

// POI / improve density heatmap. points: [[lat, lon, weight]]; gradient: {stop: colour}.
function createHeatLayer(points, { radius, blur, maxZoom, gradient }) {
  return L.heatLayer(points, { radius, blur, maxZoom, gradient });
}

// Coverage-gap field: bilinear interpolation of the analysis grid at every
// 4 px sample, instead of heatmap blobs, so it stays smooth at any zoom.
const GapGradientLayer = L.GridLayer.extend({
  initialize: function (scoreByCell, maxScore, options) {
    L.GridLayer.prototype.initialize.call(this, options);
    this._scoreByCell = scoreByCell;
    this._maxScore = maxScore || 1;
    this._gridSize = options.gridSize;
  },

  createTile: function (coords) {
    const tileSize = this.getTileSize();
    const canvas = L.DomUtil.create('canvas', 'leaflet-tile');
    canvas.width = tileSize.x;
    canvas.height = tileSize.y;
    const ctx = canvas.getContext('2d');
    const step = 4; // sample every 4px and fill blocks, for performance

    for (let py = 0; py < tileSize.y; py += step) {
      for (let px = 0; px < tileSize.x; px += step) {
        const tilePoint = coords.scaleBy(tileSize).add([px, py]);
        const latlng = this._map.unproject(tilePoint, coords.z);
        const pixel = gapPixel(interpolateGapScore(this._scoreByCell, this._gridSize, latlng.lng, latlng.lat), this._maxScore);
        if (!pixel) continue;
        ctx.fillStyle = `rgba(${pixel[0]}, ${pixel[1]}, ${pixel[2]}, ${pixel[3]})`;
        ctx.fillRect(px, py, step, step);
      }
    }
    return canvas;
  }
});

// Explicit zIndex keeps the field above whichever basemap is active: GridLayer has
// no bringToFront, and basemap swaps re-append a fresh tile container.
function createGapLayer(scoreByCell, maxScore, { gridSize }) {
  return new GapGradientLayer(scoreByCell, maxScore, { gridSize, maxZoom: 19, zIndex: 650 });
}

// Layer for OSM note markers.
function createNoteLayer(map) {
  return L.layerGroup().addTo(map);
}

function createNoteMarker({ lat, lon, closed, popupHtml }) {
  const icon = L.divIcon({
    html: '<div class="note-marker-inner">📝</div>',
    className: `note-marker ${closed ? 'closed' : ''}`,
    iconSize: [24, 24],
    iconAnchor: [12, 22]
  });
  const marker = L.marker([lat, lon], { icon });
  marker.bindPopup(popupHtml, { closeButton: false });
  return marker;
}

// The draggable "new mosque" pin. onDrag(lat, lon) fires while it moves.
// Returns { setLatLng([lat, lon]), remove() }.
function createPendingMarker(map, { lat, lon, onDrag }) {
  const icon = L.divIcon({
    html: '<div class="add-mosque-marker-pin"><span class="marker-pulse"></span><span class="marker-icon-inner">🕌</span></div>',
    className: 'add-mosque-marker',
    iconSize: [36, 36],
    iconAnchor: [18, 36]
  });
  const marker = L.marker([lat, lon], { icon, draggable: true }).addTo(map);
  marker.on('drag', (e) => {
    const pos = e.target.getLatLng();
    onDrag(pos.lat, pos.lng);
  });
  return marker;
}

// Opens a popup at latlng with a DOM node; returns it (close with map.closePopup(popup)).
function openPopup(map, latlng, content, { className } = {}) {
  return L.popup({ className, closeButton: true })
    .setLatLng(latlng)
    .setContent(content)
    .openOn(map);
}

export const kit = {
  name: 'leaflet',
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
