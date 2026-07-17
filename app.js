let map;
let heatmapLayer = null;
let markerClusterLayer = null;
let basemaps = {};
let currentBasemap = null;

// OSM OAuth 2.0 State Variables
let OSM_ENVIRONMENT = localStorage.getItem('osm_oauth_environment') || 'production';
let OSM_CLIENT_ID = localStorage.getItem('osm_oauth_client_id') || '';
// Automatically resolve Redirect URI based on the current window location (without parameters)
const OSM_REDIRECT_URI = window.location.origin + window.location.pathname;
let isOsmAnonymized = sessionStorage.getItem('osm_auth_skipped') === 'true';

let OSM_AUTH_URL = '';
let OSM_TOKEN_URL = '';
let OSM_USER_DETAILS_URL = '';
let OSM_API_BASE = '';

function updateOsmUrls() {
  const isDev = OSM_ENVIRONMENT === 'dev';
  const base = isDev ? 'https://master.apis.dev.openstreetmap.org' : 'https://www.openstreetmap.org';
  const apiBase = isDev ? 'https://master.apis.dev.openstreetmap.org' : 'https://api.openstreetmap.org';
  OSM_AUTH_URL = `${base}/oauth2/authorize`;
  OSM_TOKEN_URL = `${base}/oauth2/token`;
  OSM_USER_DETAILS_URL = `${apiBase}/api/0.6/user/details.json`;
  OSM_API_BASE = apiBase;
}
updateOsmUrls();

// OSM Notes State
let addNoteMode = false;
let noteMarkersLayer = null;
let pendingNoteLatLng = null;
let activeNotePreset = 'freetext';

// Appended to every submitted note (preset or free text) so mappers processing
// it know which site it came from - the same convention StreetComplete/MAPS.ME
// use ("via StreetComplete", "#mapsme"), which also promotes the site itself.
const NOTE_SIGNATURE = 'via خارطة أماكن العبادة (https://abdullah201x.github.io/sa-places-of-worship) #sa-worship-map';

// Temporary storage for loaded data if auth is pending
let pendingPoiData = null;
let pendingGapData = null;
let pendingBoundaryData = null;
let pendingSizeData = null;

// Datasets
let allPlaces = [];
let filteredPlaces = [];
let allGaps = [];
let filteredGaps = [];

// Filter States
let currentMode = 'poi'; // 'poi', 'gap', or 'improve'
let currentReligionFilter = 'all';
let currentImprovementFilter = 'all';
let currentSearchQuery = '';
let currentDateFrom = null; // day-index (see dayIndex()), set once data loads
let currentDateTo = null;
let DATA_MIN_DAY = 0;
let DATA_MAX_DAY = 1;

// Size-outlier thresholds (m²), user-adjustable in Improve Mode. Defaults match
// calculate_mosque_sizes.py's DEFAULT_MIN/MAX_AREA_M2.
const SIZE_MIN_AREA_DEFAULT = 20;
const SIZE_MAX_AREA_DEFAULT = 15000;
let currentSizeMinM2 = SIZE_MIN_AREA_DEFAULT;
let currentSizeMaxM2 = SIZE_MAX_AREA_DEFAULT;

// Map configuration
const MAP_INITIAL_CENTER = [24.0, 45.0]; // Centered on Saudi Arabia
const MAP_INITIAL_ZOOM = 6;
const CLUSTER_MIN_ZOOM = 11; // Zoom level at which individual markers/clusters appear
const KAABA_COORDS = { lat: 21.42252, lng: 39.82618 };

// Color configuration for POIs
const RELIGION_COLORS = {
  'muslim': '#00ff87', // Neon Green
  'christian': '#4facfe', // Electric Blue
  'unknown': '#ffb03a', // Gold/Amber
  'other': '#ffd700'
};

// Arabic translations for metadata
const RELIGION_TRANSLATIONS = {
  'muslim': 'مسلم (مسجد)',
  'christian': 'مسيحي',
  'unknown': 'غير محدد',
  'other': 'ديانات أخرى'
};

const DENOM_TRANSLATIONS = {
  'sunni': 'أهل السنة والجماعة (سني)',
  'shia': 'شيعي',
  'unknown': 'غير معروف / غير محدد',
  'ahmadia': 'أحمدية',
  'ismailia': 'إسماعيلية'
};

// Small utility: delay invoking fn until `ms` after the last call.
// Keeps search/pan/zoom smooth by avoiding per-keystroke/per-frame recomputes.
function debounce(fn, ms) {
  let timer = null;
  return function (...args) {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), ms);
  };
}

// Esri's World_Imagery is a mosaic: real capture resolution varies by location, so a single
// global maxZoom either blurs out well-covered areas or shows Esri's "Map data not yet
// available" placeholder tile where it doesn't. Esri exposes a lightweight "tilemap" endpoint
// (same technique used by the iD/RapiD OSM editors) that reports tile availability without
// downloading imagery, so we can discover the true max zoom for the current view and overzoom
// up to it instead of guessing a fixed cap.
const ESRI_TILEMAP_URL = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tilemap';
const ESRI_ASSUMED_MIN_ZOOM = 13; // always-available global mosaic level; skip probing below this
const ESRI_MAX_PROBE_ZOOM = 21;   // Esri rarely publishes real imagery deeper than this

// Cache for max zoom levels. Keys are zoom-13 tile coordinates (approx. 4.4km x 4.4km grid cells).
const esriMaxZoomCache = new Map();

async function esriTilesAvailable(zoom, centerLatLng) {
  const point = map.project(centerLatLng, zoom);
  const tileSize = 256;
  const x = Math.floor(point.x / tileSize);
  const y = Math.floor(point.y / tileSize);
  try {
    // Request a 1x1 grid instead of 4x4 for the exact tile containing the center point.
    // This is more accurate, less strict on boundary edges, and fetches less data.
    const res = await fetch(`${ESRI_TILEMAP_URL}/${zoom}/${y}/${x}/1/1`);
    if (!res.ok) return false;
    const json = await res.json();
    return Array.isArray(json.data) && json.data[0] === 1;
  } catch (e) {
    return false;
  }
}

// Binary search between the always-available floor and the probe ceiling for the deepest
// zoom with real imagery at the given point.
async function findEsriMaxZoom(centerLatLng) {
  // Determine regional cache key at zoom level 13 to avoid redundant checks when panning locally
  const point13 = map.project(centerLatLng, 13);
  const x13 = Math.floor(point13.x / 256);
  const y13 = Math.floor(point13.y / 256);
  const cacheKey = `${x13}_${y13}`;

  if (esriMaxZoomCache.has(cacheKey)) {
    return esriMaxZoomCache.get(cacheKey);
  }

  let lo = ESRI_ASSUMED_MIN_ZOOM;
  let hi = ESRI_MAX_PROBE_ZOOM;
  let best = lo;
  while (lo <= hi) {
    const mid = Math.floor((lo + hi) / 2);
    const available = await esriTilesAvailable(mid, centerLatLng);
    if (available) {
      best = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }

  esriMaxZoomCache.set(cacheKey, best);
  return best;
}

// Re-probes real imagery availability for the current view and raises/lowers the satellite
// layer's zoom ceiling to match, so users can overzoom exactly as far as real data allows.
async function updateSatelliteZoomCap() {
  if (currentBasemap !== basemaps['satellite']) return;
  const layer = basemaps['satellite'];
  const maxFound = await findEsriMaxZoom(map.getCenter());
  if (currentBasemap !== basemaps['satellite']) return; // basemap may have changed while awaiting
  
  // Only update and redraw if the zoom capability has actually changed
  if (layer.options.maxNativeZoom !== maxFound) {
    const oldMax = layer.options.maxNativeZoom;
    layer.options.maxNativeZoom = maxFound;
    map.setMaxZoom(maxFound + 1); // small CSS-upscale buffer past the last confirmed real tile
    
    // Only redraw if we are currently at a zoom level that relies on tile scaling
    if (map.hasLayer(layer) && map.getZoom() >= Math.min(oldMax, maxFound)) {
      layer.redraw();
    }
  }
}

const debouncedUpdateSatelliteZoomCap = debounce(updateSatelliteZoomCap, 400);

// Convert an ISO edited_at timestamp to a whole-day index for slider bounds/comparison.
function dayIndex(isoString) {
  return Math.floor(new Date(isoString).getTime() / 86400000);
}

// Render a day-index back to a localized short date for slider labels.
function formatDay(day) {
  return new Date(day * 86400000).toLocaleDateString('ar-SA', { year: 'numeric', month: 'short', day: 'numeric' });
}

// Escape user-supplied text (OSM names) before injecting into popup HTML.
function escapeHtml(str) {
  return String(str ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  }[ch]));
}

// Detect mapping issues for a feature based on its tags
function getQualityIssues(props) {
  const issues = [];
  
  // 1. building=mosque without amenity=place_of_worship
  if (props.building === 'mosque' && props.amenity !== 'place_of_worship') {
    issues.push({
      id: 'missing_amenity',
      title_ar: 'مبنى مسجد بدون تصنيف (amenity=place_of_worship)',
      title_en: 'Building marked as mosque but missing amenity=place_of_worship'
    });
  }
  
  // 2. Missing specific name (empty or placeholder like "Mosque", "Place of Worship", "مسجد")
  const cleanName = (props.name_original || '').trim();
  if (!cleanName || cleanName === 'Mosque' || cleanName === 'Place of Worship' || cleanName === 'مسجد') {
    issues.push({
      id: 'missing_name',
      title_ar: 'اسم المسجد مفقود أو افتراضي (مثال: "مسجد")',
      title_en: 'Mosque name is missing or set to a generic default'
    });
  }
  
  // 3. Missing English name translation (missing name:en or identical to Arabic name)
  const cleanNameAr = (props.name_original || '').trim();
  const cleanNameEn = (props.name_en_original || '').trim();
  if (!cleanNameEn || (cleanNameAr && cleanNameAr === cleanNameEn)) {
    issues.push({
      id: 'missing_name_en',
      title_ar: 'الاسم بالإنجليزية مفقود أو مطابق للاسم العربي',
      title_en: 'English name translation (name:en) is missing or identical to the Arabic name'
    });
  }
  
  // 4. Muslim mosque with missing denomination
  if (props.religion === 'muslim' && (!props.denomination || props.denomination === 'unknown')) {
    issues.push({
      id: 'missing_denom',
      title_ar: 'المذهب غير محدد (سني/شيعي)',
      title_en: 'Denomination is unknown or unspecified'
    });
  }
  
  // 5. Building footprint size looks like an outlier (too small/too large),
  // judged against the user-adjustable currentSizeMinM2/currentSizeMaxM2 thresholds.
  if (typeof props.size_area_m2 === 'number') {
    if (props.size_area_m2 < currentSizeMinM2) {
      issues.push({
        id: 'size_too_small',
        title_ar: 'مبنى المسجد أصغر من المعتاد بشكل ملحوظ — تحقق من حدود المبنى',
        title_en: 'Mosque building footprint looks too small — verify the building outline'
      });
    } else if (props.size_area_m2 > currentSizeMaxM2) {
      issues.push({
        id: 'size_too_large',
        title_ar: 'مبنى المسجد أكبر من المعتاد بشكل ملحوظ — تحقق من حدود المبنى',
        title_en: 'Mosque building footprint looks too large — verify the building outline'
      });
    }
  }

  // 6. Never revisited since first mapped (still version 1, and old)
  const FIVE_YEARS_MS = 5 * 365 * 24 * 60 * 60 * 1000;
  if (props.version === 1 && props.edited_at && (Date.now() - new Date(props.edited_at).getTime()) > FIVE_YEARS_MS) {
    issues.push({
      id: 'stale_data',
      title_ar: 'لم يتم تعديل هذا العنصر منذ إضافته لأول مرة (بيانات قديمة)',
      title_en: 'This entry has never been revisited since it was first mapped'
    });
  }

  // 7. building=yes for a mosque (should be building=mosque)
  if (props.religion === 'muslim' && props.building === 'yes') {
    issues.push({
      id: 'building_yes',
      title_ar: 'مبنى مسجد مصنف كـ building=yes بدلاً من building=mosque',
      title_en: 'Mosque building tagged as building=yes instead of building=mosque'
    });
  }

  return issues;
}

// Send load_and_zoom request to JOSM Remote Control port (8111)
function editInJOSM(lat, lon, osmId, geomType) {
  const type = geomType === 'Point' ? 'node' : 'way';
  const delta = 0.0015;
  const url = `http://127.0.0.1:8111/load_and_zoom?left=${lon - delta}&right=${lon + delta}&top=${lat + delta}&bottom=${lat - delta}&select=${type}${osmId}`;

  fetch(url)
    .then(res => {
      if (res.ok) {
        showToast('تم إرسال الموقع ومعرّف المعلم إلى JOSM بنجاح!');
      } else {
        showToast('فشل JOSM في تحميل المعلم. تأكد من تفعيل Remote Control.', 'error');
      }
    })
    .catch(err => {
      showToast('تعذر الاتصال بـ JOSM. يرجى تشغيل JOSM وتفعيل التحكم عن بعد (Remote Control) في الإعدادات.', 'error');
    });
}

// Send the currently visible map viewport (used in Gap Mode after locating an
// underserved area via the heatmap + Qibla compass) to JOSM Remote Control so
// the user can survey the area and add a new mosque node with its own ID.
function openAreaInJOSM() {
  const bounds = map.getBounds();
  const url = `http://127.0.0.1:8111/load_and_zoom?left=${bounds.getWest()}&right=${bounds.getEast()}&top=${bounds.getNorth()}&bottom=${bounds.getSouth()}`;

  fetch(url)
    .then(res => {
      if (res.ok) {
        showToast('تم إرسال النطاق الحالي إلى JOSM. يمكنك الآن إضافة معلم المسجد.');
      } else {
        showToast('فشل JOSM في تحميل النطاق. تأكد من تفعيل Remote Control.', 'error');
      }
    })
    .catch(err => {
      showToast('تعذر الاتصال بـ JOSM. يرجى تشغيل JOSM وتفعيل التحكم عن بعد (Remote Control) في الإعدادات.', 'error');
    });
}

// Update the iD Editor link for the currently viewed map area so that the user
// can open the area in iD Editor and add a new mosque node.
function updateIdEditorAreaLink() {
  const idBtn = document.getElementById('btn-open-area-id');
  if (idBtn && map) {
    const isDev = OSM_ENVIRONMENT === 'dev';
    const base = isDev ? 'https://master.apis.dev.openstreetmap.org' : 'https://www.openstreetmap.org';
    const center = map.getCenter();
    const zoom = Math.max(16, Math.round(map.getZoom()));
    idBtn.href = `${base}/edit?editor=id#map=${zoom}/${center.lat.toFixed(5)}/${center.lng.toFixed(5)}`;
  }
}

// Show animated non-blocking toast notification
function showToast(message, type = 'success') {
  // Remove existing toast if any
  const existingToast = document.querySelector('.toast-notification');
  if (existingToast) {
    existingToast.remove();
  }
  
  const toast = document.createElement('div');
  toast.className = `toast-notification ${type}`;
  toast.innerHTML = `<span>${message}</span>`;
  document.body.appendChild(toast);
  
  // Trigger slide-out and removal
  setTimeout(() => {
    toast.style.animation = 'slide-out-left 0.35s cubic-bezier(0.16, 1, 0.3, 1) forwards';
    toast.addEventListener('animationend', () => {
      toast.remove();
    });
  }, 4500);
}

// Calculate Great Circle bearing between two lat/lon points
function calculateBearing(lat1, lon1, lat2, lon2) {
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const lat1Rad = lat1 * Math.PI / 180;
  const lat2Rad = lat2 * Math.PI / 180;
  
  const y = Math.sin(dLon) * Math.cos(lat2Rad);
  const x = Math.cos(lat1Rad) * Math.sin(lat2Rad) -
            Math.sin(lat1Rad) * Math.cos(lat2Rad) * Math.cos(dLon);
  
  let brng = Math.atan2(y, x) * 180 / Math.PI;
  return (brng + 360) % 360;
}

// Calculate Haversine distance in kilometers
function calculateDistance(lat1, lon1, lat2, lon2) {
  const R = 6371; // Radius of the Earth in km
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a = Math.sin(dLat/2) * Math.sin(dLat/2) +
            Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
            Math.sin(dLon/2) * Math.sin(dLon/2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));
  return R * c;
}

// Update the rotation of the Qibla Compass needle
function updateQiblaCompass() {
  const compassEl = document.getElementById('qibla-compass');
  if (!compassEl || compassEl.classList.contains('hidden')) return;

  const center = map.getCenter();
  const bearing = calculateBearing(center.lat, center.lng, KAABA_COORDS.lat, KAABA_COORDS.lng);

  // Rotate the needle container
  const needleContainer = compassEl.querySelector('.compass-needle-container');
  if (needleContainer) {
    needleContainer.style.transform = `rotate(${bearing}deg)`;
  }
}

// Applies persisted (or, on a first-ever mobile visit, defaulted-collapsed)
// sidebar state and wires the toggle button. The auth overlay is a fixed,
// higher-z-index full-viewport modal, so it already covers this button
// whenever it's shown - no extra guard needed there.
function initSidebarToggle() {
  const container = document.getElementById('app-container');
  const toggleBtn = document.getElementById('sidebar-toggle');
  if (!container || !toggleBtn) return;

  function setSidebarCollapsed(isCollapsed) {
    container.classList.toggle('sidebar-collapsed', isCollapsed);
    toggleBtn.setAttribute('aria-expanded', String(!isCollapsed));
    localStorage.setItem('sidebar_collapsed', String(isCollapsed));
  }

  const stored = localStorage.getItem('sidebar_collapsed');
  const initialCollapsed = stored !== null
    ? stored === 'true'
    : window.matchMedia('(max-width: 768px)').matches;
  setSidebarCollapsed(initialCollapsed);

  toggleBtn.addEventListener('click', () => {
    setSidebarCollapsed(!container.classList.contains('sidebar-collapsed'));
  });
}

document.addEventListener('DOMContentLoaded', () => {
  initMap();
  setupEventListeners();
  initSidebarToggle();
  // Handle OAuth callback first, then load the data
  handleOAuthCallback().then(() => {
    loadData();
  });
});

// Initialize Leaflet Map
function initMap() {
  map = L.map('map', {
    zoomControl: false // Custom styled zoom controls
  }).setView(MAP_INITIAL_CENTER, MAP_INITIAL_ZOOM);

  // Position Zoom Control on the bottom-left to avoid sidebar overlap on the right (RTL layout)
  L.control.zoom({
    position: 'bottomleft'
  }).addTo(map);

  // Define available basemaps
  basemaps = {
    'dark': L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
      subdomains: 'abcd',
      maxZoom: 20
    }),
    'satellite': L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
      attribution: 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community',
      maxZoom: 20,
      maxNativeZoom: 19
    }),
    'light': L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
      subdomains: 'abcd',
      maxZoom: 20
    }),
    'streets': L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}', {
      attribution: 'Tiles &copy; Esri &mdash; Source: Esri, DeLorme, NAVTEQ, USGS, Intermap, iPC, NRCAN, Esri Japan, METI, Esri China (Hong Kong), Esri (Thailand), TomTom, 2012',
      maxZoom: 20
    })
  };

  // Add default (dark) basemap
  currentBasemap = basemaps['dark'];
  currentBasemap.addTo(map);

  // Initialize Marker Cluster Layer for POI/Improve mode
  markerClusterLayer = L.markerClusterGroup({
    showCoverageOnHover: false,
    maxClusterRadius: 50,
    iconCreateFunction: function (cluster) {
      const childCount = cluster.getChildCount();
      let colorPrimary = currentMode === 'improve' ? '#ffb03a' : 'var(--color-primary)';
      let c = currentMode === 'improve' ? 'rgba(255, 176, 58, ' : 'rgba(0, 242, 254, ';
      
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

  // Track map movements/zooming to update stats.
  // Stat recomputation loops over every feature, so debounce it to keep panning smooth.
  const debouncedUpdateStats = debounce(updateStats, 150);
  map.on('moveend', debouncedUpdateStats);
  map.on('moveend', debouncedUpdateSatelliteZoomCap);
  map.on('moveend', updateIdEditorAreaLink);
  map.on('zoomend', () => {
    debouncedUpdateStats();
    toggleLayersByZoom(); // layer swap must stay immediate
    updateIdEditorAreaLink();
  });

  // OSM Notes: layer for existing + newly-created note markers, click-to-place
  // handling in Add Note mode, and refetching nearby notes as the view moves.
  noteMarkersLayer = L.layerGroup().addTo(map);
  map.on('click', handleMapClickForNotes);
  const debouncedLoadNearbyNotes = debounce(loadNearbyNotes, 400);
  map.on('moveend', debouncedLoadNearbyNotes);

  // Update Qibla compass dynamically as the map moves
  map.on('move', updateQiblaCompass);
}

function loadData() {
  const cacheBuster = `?t=${Date.now()}`;
  Promise.all([
    fetch(`places_of_worship_sa.geojson${cacheBuster}`).then(r => {
      if (!r.ok) throw new Error('Failed to load places of worship');
      return r.json();
    }),
    fetch(`worship_gaps_sa.geojson${cacheBuster}`).then(r => {
      if (!r.ok) throw new Error('Failed to load coverage gaps');
      return r.json();
    }),
    fetch(`sa_boundary.geojson${cacheBuster}`).then(r => {
      if (!r.ok) throw new Error('Failed to load Saudi boundary');
      return r.json();
    }),
    // Best-effort: computed on its own schedule (e.g. weekly) by
    // calculate_mosque_sizes.py, may not exist yet or may be mid-refresh.
    fetch(`mosque_sizes.json${cacheBuster}`).then(r => r.ok ? r.json() : {}).catch(() => ({}))
  ])
  .then(([poiData, gapData, boundaryData, sizeData]) => {
    // Detect if this is an internal OSM extract containing contributor metadata
    const isInternalExtract = poiData.features.some(f => f.properties && (f.properties.last_edited_by || f.properties.user_id));
    
    if (isInternalExtract) {
      // Store data in pending variables in case we need to authenticate first
      pendingPoiData = poiData;
      pendingGapData = gapData;
      pendingBoundaryData = boundaryData;
      pendingSizeData = sizeData;

      checkAuthStatus().then(isAuthenticated => {
        if (isAuthenticated || isOsmAnonymized) {
          // User is authorized or skipped, initialize dashboard
          initializeDashboard(poiData, gapData, boundaryData, sizeData);
        } else {
          // User is not authorized, show login overlay
          hideLoadingOverlay();
          const authOverlay = document.getElementById('osm-auth-overlay');
          if (authOverlay) {
            authOverlay.classList.remove('hidden');
          }
        }
      });
    } else {
      // Standard/anonymized dataset, no authentication required
      initializeDashboard(poiData, gapData, boundaryData, sizeData);
    }
  })
  .catch(error => {
    console.error('Error loading GeoJSON datasets:', error);
    showLoadingError('فشل في تحميل بيانات الخريطة. يرجى التأكد من تشغيل خادم محلي (مثل: python -m http.server) وفتح الصفحة عبر http://');
  });
}

function initializeDashboard(poiData, gapData, boundaryData, sizeData) {
  allPlaces = poiData.features;
  // Merge in weekly-computed building footprint areas (calculate_mosque_sizes.py),
  // keyed by osm_id; features with no entry simply have no size data. The
  // too_small/too_large classification itself is computed dynamically in
  // getQualityIssues() against the user-adjustable currentSizeMinM2/MaxM2.
  if (sizeData) {
    allPlaces.forEach(f => {
      const sizeInfo = sizeData[f.properties.osm_id];
      if (sizeInfo) {
        f.properties.size_area_m2 = sizeInfo.area_m2;
      }
    });
  }
  filteredPlaces = [...allPlaces];

  allGaps = gapData.features;
  filteredGaps = [...allGaps];

  // Reconfigure Esri Satellite as a BoundaryCanvas layer restricted to the Saudi Arabia boundary
  if (boundaryData && boundaryData.geometry) {
    basemaps['satellite'] = L.TileLayer.boundaryCanvas('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
      boundary: boundaryData.geometry,
      attribution: 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community',
      maxZoom: 20,
      maxNativeZoom: 19,
      crossOrigin: true
    });
  }

  // Derive the date-slider bounds from the real edited_at range in the data.
  const days = allPlaces.map(f => dayIndex(f.properties.edited_at));
  DATA_MIN_DAY = Math.min(...days);
  DATA_MAX_DAY = Math.max(...days);
  currentDateFrom = DATA_MIN_DAY;
  currentDateTo = DATA_MAX_DAY;
  initDateSliders();

  // Initial display
  updateDashboardUI();
  hideLoadingOverlay();
  updateUserWidgetUI();
}

// Set the date-range slider bounds/values to the real data span and update their labels.
function initDateSliders() {
  const fromSlider = document.getElementById('slider-date-from');
  const toSlider = document.getElementById('slider-date-to');

  [fromSlider, toSlider].forEach(slider => {
    slider.min = DATA_MIN_DAY;
    slider.max = DATA_MAX_DAY;
  });
  fromSlider.value = DATA_MIN_DAY;
  toSlider.value = DATA_MAX_DAY;

  document.getElementById('date-from-val').innerText = formatDay(DATA_MIN_DAY);
  document.getElementById('date-to-val').innerText = formatDay(DATA_MAX_DAY);
}

// Hide the loading overlay once data has rendered.
function hideLoadingOverlay() {
  const overlay = document.getElementById('loading-overlay');
  if (overlay) overlay.classList.add('hidden');
}

// Keep the overlay visible and show an inline error instead of a blocking alert().
function showLoadingError(message) {
  const overlay = document.getElementById('loading-overlay');
  const text = document.getElementById('loading-text');
  if (overlay) overlay.classList.add('error');
  if (text) text.innerText = message;
}

// Switch display logic based on current zoom level
function toggleLayersByZoom() {
  const zoom = map.getZoom();
  
  // Individual markers are only displayed in POI/Improve Density mode at high zoom levels
  if ((currentMode === 'poi' || currentMode === 'improve') && zoom >= CLUSTER_MIN_ZOOM) {
    if (!map.hasLayer(markerClusterLayer)) {
      map.addLayer(markerClusterLayer);
    }
  } else {
    if (map.hasLayer(markerClusterLayer)) {
      map.removeLayer(markerClusterLayer);
    }
  }
}

// === Coverage Gap Gradient Layer ===
// Renders coverage-gap scores as a continuous, zoom-independent gradient by
// bilinearly interpolating gap_score across the underlying ~440m analysis
// grid (calculate_gaps.py's GRID_SIZE), instead of leaflet.heat's
// fixed-pixel-radius blobs. Those blobs stop overlapping - and read as
// scattered dots rather than a smooth field - once the grid spacing exceeds
// the blob radius on screen, which is exactly what happens when zoomed into
// dense cities to inspect detail.
const GAP_GRID_SIZE_DEG = 0.004;
const GAP_GRADIENT_STOPS = [
  { stop: 0.0, color: [63, 43, 150] },   // Deep Indigo
  { stop: 0.5, color: [168, 192, 255] }, // Soft Lilac
  { stop: 0.8, color: [236, 0, 140] },   // Neon Magenta
  { stop: 1.0, color: [252, 103, 103] }  // Flame Orange/Red
];

function gapScoreToColor(t) {
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

// Builds a sparse Map<"x,y", gap_score> from the gap grid's own cell
// coordinates (grid_id already encodes them), so interpolation always lines
// up with the real analysis grid regardless of zoom.
function buildGapScoreLookup(gapFeatures) {
  const scoreByCell = new Map();
  let maxScore = 0;
  gapFeatures.forEach(f => {
    const [gx, gy] = f.properties.grid_id.split('_').map(Number);
    const score = f.properties.gap_score;
    scoreByCell.set(gx + ',' + gy, score);
    if (score > maxScore) maxScore = score;
  });
  return { scoreByCell, maxScore };
}

// Dilates + box-averages the raw lookup over a (2r+1)x(2r+1) cell
// neighborhood, used to drive the "smoothing" slider. Computed once per
// filter/slider change rather than per pixel, so tile rendering stays fast.
// Returns its own max so color contrast doesn't wash out under heavy
// smoothing (averaging with many zero neighbors shrinks every score, so
// normalizing against the *pre-smoothing* max would make the whole layer
// fade to near-invisible).
function buildSmoothedLookup(rawMap, rawMaxScore, radiusCells) {
  if (radiusCells <= 0) return { scoreByCell: rawMap, maxScore: rawMaxScore };

  const offsets = [];
  for (let dx = -radiusCells; dx <= radiusCells; dx++) {
    for (let dy = -radiusCells; dy <= radiusCells; dy++) {
      offsets.push([dx, dy]);
    }
  }

  const visited = new Set();
  rawMap.forEach((_, key) => {
    const [gx, gy] = key.split(',').map(Number);
    offsets.forEach(([dx, dy]) => visited.add((gx + dx) + ',' + (gy + dy)));
  });

  const smoothed = new Map();
  let maxScore = 0;
  visited.forEach(key => {
    const [gx, gy] = key.split(',').map(Number);
    let sum = 0;
    offsets.forEach(([dx, dy]) => {
      sum += rawMap.get((gx + dx) + ',' + (gy + dy)) || 0;
    });
    const avg = sum / offsets.length;
    smoothed.set(key, avg);
    if (avg > maxScore) maxScore = avg;
  });
  return { scoreByCell: smoothed, maxScore };
}

const GapGradientLayer = L.GridLayer.extend({
  initialize: function (scoreByCell, maxScore, options) {
    L.GridLayer.prototype.initialize.call(this, options);
    this._scoreByCell = scoreByCell;
    this._maxScore = maxScore || 1;
  },

  _cellScore: function (gx, gy) {
    const v = this._scoreByCell.get(gx + ',' + gy);
    return v === undefined ? 0 : v;
  },

  // Bilinear interpolation between the 4 grid cells surrounding (lon, lat),
  // so color is continuous across the real analysis grid at any zoom.
  _interpolate: function (lon, lat) {
    const fx = lon / GAP_GRID_SIZE_DEG;
    const fy = lat / GAP_GRID_SIZE_DEG;
    const x0 = Math.floor(fx), y0 = Math.floor(fy);
    const tx = fx - x0, ty = fy - y0;

    const s00 = this._cellScore(x0, y0);
    const s10 = this._cellScore(x0 + 1, y0);
    const s01 = this._cellScore(x0, y0 + 1);
    const s11 = this._cellScore(x0 + 1, y0 + 1);

    const top = s00 + (s10 - s00) * tx;
    const bottom = s01 + (s11 - s01) * tx;
    return top + (bottom - top) * ty;
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
        const score = this._interpolate(latlng.lng, latlng.lat);

        if (score <= 0.001) continue;

        const t = Math.min(score / this._maxScore, 1);
        const [r, g, b] = gapScoreToColor(t);
        const alpha = 0.15 + t * 0.65; // keep low scores subtle, peak gaps vivid

        ctx.fillStyle = `rgba(${r | 0}, ${g | 0}, ${b | 0}, ${alpha})`;
        ctx.fillRect(px, py, step, step);
      }
    }

    return canvas;
  }
});

// Re-generate Heatmap and Marker Clusters based on selected mode
function updateMapLayers() {
  // 1. Remove previous heatmap & clusters
  if (heatmapLayer) {
    map.removeLayer(heatmapLayer);
  }
  markerClusterLayer.clearLayers();

  const radiusVal = parseInt(document.getElementById('slider-radius').value, 10);
  const blurVal = parseInt(document.getElementById('slider-blur').value, 10);

  if (currentMode === 'poi' || currentMode === 'improve') {
    // === POI Density or Quality Improvement Mode ===
    const heatPoints = [];
    const markers = [];

    filteredPlaces.forEach(f => {
      const coords = f.geometry.coordinates;
      const lon = coords[0];
      const lat = coords[1];
      const props = f.properties;
      
      // Standard heatmap coordinates (lat, lon, weight)
      heatPoints.push([lat, lon, 1.0]);

      // Custom marker icon creation
      let markerClass = 'unknown';
      if (currentMode === 'improve') {
        markerClass = 'improve';
      } else {
        if (props.religion === 'muslim') markerClass = 'muslim';
        if (props.religion === 'christian') markerClass = 'christian';
      }

      const customIcon = L.divIcon({
        html: '<div class="custom-marker-inner"></div>',
        className: `custom-marker ${markerClass}`,
        iconSize: [12, 12],
        iconAnchor: [6, 6]
      });

      const marker = L.marker([lat, lon], { icon: customIcon });
      
      let popupContent = '';
      if (currentMode === 'improve') {
        const issues = getQualityIssues(props);
        popupContent = `
          <div style="font-family: var(--font-body); text-align: right; padding: 2px;">
            <h4 style="margin: 0 0 5px 0; font-size: 13px; font-weight: 700; color: #111;">${escapeHtml(props.name)}</h4>
            <span style="font-size: 10px; padding: 2px 6px; border-radius: 10px; background: rgba(255, 59, 48, 0.1); font-weight: 600; color: #ff3b30; border: 1px solid rgba(255, 59, 48, 0.2); display: inline-block; margin-top: 4px;">
              ⚠️ لديه ${issues.length} مشكلة جودة
            </span>
          </div>
        `;
      } else {
        popupContent = `
          <div style="font-family: var(--font-body); text-align: right; padding: 2px;">
            <h4 style="margin: 0 0 5px 0; font-size: 13px; font-weight: 700; color: #111;">${escapeHtml(props.name)}</h4>
            <p style="margin: 0 0 5px 0; font-size: 11px; color: #666; direction: ltr; text-align: right;">${props.name_en !== props.name ? escapeHtml(props.name_en) : ''}</p>
            <span style="font-size: 10px; padding: 2px 6px; border-radius: 10px; background: #eee; font-weight: 600; color: #333;">
              ${RELIGION_TRANSLATIONS[props.religion] || props.religion}
            </span>
          </div>
        `;
      }
      marker.bindPopup(popupContent, { closeButton: false });

      marker.on('click', () => {
        showDetails(props, lat, lon);
      });

      markers.push(marker);
    });

    // Render heatmap (different gradients for POI vs Improve)
    const poiGradient = {
      0.2: '#00f2fe',  // Cyan
      0.4: '#4facfe',  // Sky Blue
      0.6: '#00ff87',  // Neon Green
      0.9: '#ffd700',  // Gold
      1.0: '#ff3b30'   // Hot Red
    };

    const improveGradient = {
      0.2: '#ffd700',  // Gold
      0.6: '#ff9500',  // Amber
      1.0: '#ff3b30'   // Red
    };

    heatmapLayer = L.heatLayer(heatPoints, {
      radius: radiusVal,
      blur: blurVal,
      maxZoom: 14,
      gradient: currentMode === 'improve' ? improveGradient : poiGradient
    }).addTo(map);

    markerClusterLayer.addLayers(markers);
    toggleLayersByZoom();

  } else {
    // === Coverage Gaps Mode (Continuous Gradient) ===
    // Interpolated directly from the analysis grid rather than fed through
    // leaflet.heat, so the field stays smooth at any zoom instead of
    // resolving into scattered dots once grid spacing exceeds a fixed pixel
    // blob radius (the issue in dense cities).
    const { scoreByCell, maxScore } = buildGapScoreLookup(filteredGaps);

    // Reuse the blur/"smoothing" slider (5-40) as a 0-3 grid-cell smoothing radius.
    const smoothingRadius = Math.round((blurVal - 5) / 35 * 3);
    const smoothed = buildSmoothedLookup(scoreByCell, maxScore, smoothingRadius);

    // Explicit zIndex keeps the heatmap above whichever basemap tile layer is active, since
    // GridLayer has no bringToFront/bringToBack (those only exist on L.Path) and basemap
    // swaps re-append a fresh tile container that would otherwise stack on top by DOM order.
    heatmapLayer = new GapGradientLayer(smoothed.scoreByCell, smoothed.maxScore, { maxZoom: 19, zIndex: 650 }).addTo(map);

    // Disable marker clusters in gap mode since points are virtual grid cells
    toggleLayersByZoom();
  }
}

// Show detailed information about a single place of worship in the sidebar
function showDetails(props, lat, lon) {
  const panel = document.getElementById('details-panel');
  panel.style.display = 'block';

  document.getElementById('details-name-ar').innerText = props.name || 'غير مسمى';
  document.getElementById('details-name-en').innerText = props.name_en || 'Unnamed';
  
  const relSpan = document.getElementById('details-religion');
  const arReligion = RELIGION_TRANSLATIONS[props.religion] || props.religion;
  relSpan.innerText = arReligion.toUpperCase();
  relSpan.style.color = RELIGION_COLORS[props.religion] || RELIGION_COLORS.unknown;
  
  const arDenom = DENOM_TRANSLATIONS[props.denomination] || props.denomination;
  document.getElementById('details-denom').innerText = props.denomination !== 'unknown' ? arDenom : 'غير محدد';
  
  document.getElementById('details-city').innerText = props.addr_city !== '' ? props.addr_city : 'المملكة العربية السعودية';
  document.getElementById('details-coords').innerText = `${lat.toFixed(5)}, ${lon.toFixed(5)}`;
  document.getElementById('details-osm-id').innerText = props.osm_id;

  const userLink = document.getElementById('details-user');
  const changesetLink = document.getElementById('details-changeset');
  const mapperTools = document.getElementById('details-mapper-tools');
  const guestToolsNotice = document.getElementById('details-guest-tools-notice');

  if (isOsmAnonymized) {
    userLink.innerText = 'مساهم OSM (سجل دخولك)';
    userLink.href = '#';
    userLink.style.pointerEvents = 'none';
    userLink.style.opacity = '0.6';
    userLink.style.textDecoration = 'none';

    document.getElementById('details-uid').innerText = 'محجوب بموجب GDPR';

    changesetLink.innerText = 'محجوب بموجب GDPR';
    changesetLink.href = '#';
    changesetLink.style.pointerEvents = 'none';
    changesetLink.style.opacity = '0.6';
    changesetLink.style.textDecoration = 'none';

    if (mapperTools) mapperTools.style.display = 'none';
    if (guestToolsNotice) guestToolsNotice.style.display = 'flex';
  } else {
    userLink.innerText = props.last_edited_by || 'مجهول';
    userLink.href = props.last_edited_by ? `https://www.openstreetmap.org/user/${encodeURIComponent(props.last_edited_by)}` : '#';
    userLink.style.pointerEvents = 'auto';
    userLink.style.opacity = '1';
    userLink.style.textDecoration = '';

    document.getElementById('details-uid').innerText = props.user_id ?? '-';

    changesetLink.innerText = props.changeset_id ?? '-';
    changesetLink.href = props.changeset_id ? `https://www.openstreetmap.org/changeset/${props.changeset_id}` : '#';
    changesetLink.style.pointerEvents = 'auto';
    changesetLink.style.opacity = '1';
    changesetLink.style.textDecoration = '';

    if (mapperTools) mapperTools.style.display = 'block';
    if (guestToolsNotice) guestToolsNotice.style.display = 'none';

    // Update mapper editing tools
    const type = props.geom_type === 'Point' ? 'node' : 'way';
    document.getElementById('btn-view-osm').href = `https://www.openstreetmap.org/${type}/${props.osm_id}`;
    document.getElementById('btn-edit-osm').href = `https://www.openstreetmap.org/edit?editor=id&${type}=${props.osm_id}`;
    
    const josmBtn = document.getElementById('btn-edit-josm');
    const newJosmBtn = josmBtn.cloneNode(true);
    josmBtn.parentNode.replaceChild(newJosmBtn, josmBtn);
    newJosmBtn.addEventListener('click', () => {
      editInJOSM(lat, lon, props.osm_id, props.geom_type);
    });
  }

  // OSM Note shortcut: always available (signed in or guest), since Notes
  // are unrelated to the GDPR gate on contributor metadata above.
  const addNoteBtn = document.getElementById('btn-add-note-here');
  if (addNoteBtn) {
    const newAddNoteBtn = addNoteBtn.cloneNode(true);
    addNoteBtn.parentNode.replaceChild(newAddNoteBtn, addNoteBtn);
    newAddNoteBtn.addEventListener('click', () => {
      openNoteComposer(lat, lon);
    });
  }

  document.getElementById('details-edited-at').innerText = props.edited_at
    ? new Date(props.edited_at).toLocaleString('ar-SA')
    : '-';

  // Update quality issues warning box
  const issues = getQualityIssues(props);
  const issuesBox = document.getElementById('details-quality-issues');
  const issuesList = document.getElementById('details-issues-list');
  
  if (issues.length > 0) {
    issuesList.innerHTML = issues.map(i => `<li>${escapeHtml(i.title_ar)}</li>`).join('');
    issuesBox.style.display = 'block';
  } else {
    issuesBox.style.display = 'none';
  }
}

// Update UI panel labels and counts depending on selected Mode
function updateDashboardUI() {
  const totalCountLabel = document.getElementById('total-count-label');
  const visibleCountLabel = document.getElementById('visible-count-label');
  const searchSection = document.getElementById('search-section');
  const filterSection = document.getElementById('filter-section');
  const improveFilterSection = document.getElementById('improve-filter-section');
  const dateFilterSection = document.getElementById('date-filter-section');
  const detailsPanel = document.getElementById('details-panel');
  const gapInfoBox = document.getElementById('gap-info-box');
  const gapJosmBox = document.getElementById('gap-josm-box');
  const radiusSliderContainer = document.getElementById('radius-slider-container');

  // The gap gradient interpolates from the analysis grid directly and has
  // no blob radius, unlike the POI/Improve leaflet.heat layers.
  radiusSliderContainer.style.display = (currentMode === 'gap') ? 'none' : 'block';

  if (currentMode === 'poi') {
    // Restore POI Mode controls
    totalCountLabel.innerText = "إجمالي الأماكن";
    visibleCountLabel.innerText = "في النطاق المرئي";
    searchSection.style.display = 'block';
    filterSection.style.display = 'block';
    improveFilterSection.style.display = 'none';
    dateFilterSection.style.display = 'block';
    gapInfoBox.style.display = 'none';
    gapJosmBox.style.display = 'none';
  } else if (currentMode === 'improve') {
    // Quality Improvement Mode controls
    totalCountLabel.innerText = "أماكن تحتاج تحسين";
    visibleCountLabel.innerText = "تحتاج تحسين بالنطاق";
    searchSection.style.display = 'block';
    filterSection.style.display = 'none';
    improveFilterSection.style.display = 'block';
    dateFilterSection.style.display = 'block';
    gapInfoBox.style.display = 'none';
    gapJosmBox.style.display = 'none';
  } else {
    // Adjust layout for Gap Mode
    totalCountLabel.innerText = "الفجوات المكتشفة";
    visibleCountLabel.innerText = "الفجوات في النطاق";
    searchSection.style.display = 'none';
    filterSection.style.display = 'none';
    improveFilterSection.style.display = 'none';
    dateFilterSection.style.display = 'none'; // Gap grid cells have no edited_at metadata
    detailsPanel.style.display = 'none'; // Grid gaps do not have individual clickable POI cards
    gapInfoBox.style.display = 'flex';
    gapJosmBox.style.display = 'block';
    updateIdEditorAreaLink();
  }

  updateMapLayers();
  updateStats();
}

// Calculate and update metrics matching filters and map bounds
function updateStats() {
  const bounds = map.getBounds();
  let totalCount = 0;
  let visibleCount = 0;

  if (currentMode === 'poi' || currentMode === 'improve') {
    totalCount = filteredPlaces.length;
    filteredPlaces.forEach(f => {
      const coords = f.geometry.coordinates;
      const lat = coords[1];
      const lon = coords[0];
      if (bounds.contains([lat, lon])) {
        visibleCount++;
      }
    });
  } else {
    totalCount = filteredGaps.length;
    filteredGaps.forEach(f => {
      const coords = f.geometry.coordinates;
      const lat = coords[1];
      const lon = coords[0];
      if (bounds.contains([lat, lon])) {
        visibleCount++;
      }
    });
  }

  document.getElementById('total-count').innerText = totalCount.toLocaleString();
  document.getElementById('visible-count').innerText = visibleCount.toLocaleString();
}

// Combines search query and religion category filters (POI mode only)
function filterData() {
  if (currentMode === 'gap') return;

  const searchInput = currentSearchQuery.toLowerCase().trim();
  
  filteredPlaces = allPlaces.filter(f => {
    const props = f.properties;
    
    // 1. Check search box keyword
    let matchesSearch = true;
    if (searchInput) {
      const name = (props.name || '').toLowerCase();
      const nameEn = (props.name_en || '').toLowerCase();
      const city = (props.addr_city || '').toLowerCase();
      const id = String(props.osm_id);

      matchesSearch = name.includes(searchInput) ||
                      nameEn.includes(searchInput) ||
                      city.includes(searchInput) ||
                      id.includes(searchInput);
    }

    // 2. Check last-modified date range
    let matchesDate = true;
    if (currentDateFrom !== null && currentDateTo !== null) {
      const day = dayIndex(props.edited_at);
      matchesDate = day >= currentDateFrom && day <= currentDateTo;
    }

    // 3. Mode-specific filters
    if (currentMode === 'poi') {
      let matchesReligion = true;
      if (currentReligionFilter !== 'all') {
        const isMusalla = props.place_of_worship === 'musalla';
        if (currentReligionFilter === 'musalla') {
          matchesReligion = isMusalla;
        } else if (currentReligionFilter === 'muslim') {
          matchesReligion = props.religion === 'muslim' && !isMusalla;
        } else if (currentReligionFilter === 'other') {
          matchesReligion = !(props.religion === 'muslim' && !isMusalla) && !isMusalla;
        }
      }
      return matchesReligion && matchesSearch && matchesDate;
    } else if (currentMode === 'improve') {
      const issues = getQualityIssues(props);
      if (issues.length === 0) return false;

      let matchesImprovement = false;
      if (currentImprovementFilter === 'all') {
        matchesImprovement = true;
      } else {
        matchesImprovement = issues.some(issue => issue.id === currentImprovementFilter);
      }
      return matchesImprovement && matchesSearch && matchesDate;
    }

    return false;
  });

  updateMapLayers();
  updateStats();
}

// Wire up events for buttons, chips, search inputs, and range sliders
function setupEventListeners() {
  // 1. Dashboard Mode Selector
  document.getElementById('mode-poi').addEventListener('click', (e) => {
    document.getElementById('mode-gap').classList.remove('active');
    document.getElementById('mode-improve').classList.remove('active');
    e.target.classList.add('active');
    currentMode = 'poi';
    filterData();
    updateDashboardUI();
  });

  document.getElementById('mode-gap').addEventListener('click', (e) => {
    document.getElementById('mode-poi').classList.remove('active');
    document.getElementById('mode-improve').classList.remove('active');
    e.target.classList.add('active');
    currentMode = 'gap';
    updateDashboardUI();
  });

  document.getElementById('mode-improve').addEventListener('click', (e) => {
    document.getElementById('mode-poi').classList.remove('active');
    document.getElementById('mode-gap').classList.remove('active');
    e.target.classList.add('active');
    currentMode = 'improve';
    filterData();
    updateDashboardUI();
  });

  // Gap Mode: open the currently viewed area in JOSM to survey/add a mosque
  document.getElementById('btn-open-area-josm').addEventListener('click', () => {
    openAreaInJOSM();
  });

  // Gap Mode: open the currently viewed area in iD Editor
  const btnOpenAreaId = document.getElementById('btn-open-area-id');
  if (btnOpenAreaId) {
    btnOpenAreaId.addEventListener('click', () => {
      updateIdEditorAreaLink();
    });
  }

  // Basemap Chips Selector
  const basemapChips = document.querySelectorAll('#basemap-filters .chip');
  basemapChips.forEach(chip => {
    chip.addEventListener('click', (e) => {
      basemapChips.forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      
      const selectedBasemap = chip.getAttribute('data-basemap');
      if (basemaps[selectedBasemap] && currentBasemap !== basemaps[selectedBasemap]) {
        map.removeLayer(currentBasemap);
        currentBasemap = basemaps[selectedBasemap];
        currentBasemap.addTo(map);
        if (selectedBasemap === 'satellite') {
          updateSatelliteZoomCap();
        } else {
          map.setMaxZoom(currentBasemap.options.maxZoom);
        }
      }

      // Automatic Qibla compass visibility triggers based on basemap
      const compassToggle = document.getElementById('qibla-compass-toggle');
      const compassEl = document.getElementById('qibla-compass');
      if (compassToggle && compassEl) {
        if (selectedBasemap === 'satellite') {
          if (!compassToggle.checked) {
            compassToggle.checked = true;
            compassEl.classList.remove('hidden');
            updateQiblaCompass();
          }
        } else {
          if (compassToggle.checked) {
            compassToggle.checked = false;
            compassEl.classList.add('hidden');
          }
        }
      }
    });
  });

  // 2. Religion Chips Selector (POI Mode Only)
  const chips = document.querySelectorAll('#religion-filters .chip');
  chips.forEach(chip => {
    chip.addEventListener('click', (e) => {
      chips.forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      
      currentReligionFilter = chip.getAttribute('data-religion');
      filterData();
    });
  });

  // Quality Improvement Chips Selector (Improvement Mode Only)
  const improveChips = document.querySelectorAll('#improve-filters .chip');
  improveChips.forEach(chip => {
    chip.addEventListener('click', (e) => {
      improveChips.forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      
      currentImprovementFilter = chip.getAttribute('data-improve');
      filterData();
    });
  });

  // Size Threshold Inputs (Improvement Mode Only) — user-adjustable too_small/too_large cutoffs
  const sizeMinInput = document.getElementById('size-min-input');
  const sizeMaxInput = document.getElementById('size-max-input');
  const resetSizeBtn = document.getElementById('btn-reset-size-thresholds');
  const debouncedSizeFilter = debounce(filterData, 250);

  function applySizeThresholdsFromInputs() {
    const minVal = parseFloat(sizeMinInput.value);
    const maxVal = parseFloat(sizeMaxInput.value);
    const validMin = !isNaN(minVal) && minVal >= 0;
    const validMax = !isNaN(maxVal) && maxVal >= 0;

    sizeMinInput.classList.toggle('invalid', !validMin);
    sizeMaxInput.classList.toggle('invalid', !validMax);

    if (validMin) currentSizeMinM2 = minVal;
    if (validMax) currentSizeMaxM2 = maxVal;

    debouncedSizeFilter();
  }

  sizeMinInput.addEventListener('input', applySizeThresholdsFromInputs);
  sizeMaxInput.addEventListener('input', applySizeThresholdsFromInputs);

  resetSizeBtn.addEventListener('click', () => {
    sizeMinInput.value = SIZE_MIN_AREA_DEFAULT;
    sizeMaxInput.value = SIZE_MAX_AREA_DEFAULT;
    sizeMinInput.classList.remove('invalid');
    sizeMaxInput.classList.remove('invalid');
    currentSizeMinM2 = SIZE_MIN_AREA_DEFAULT;
    currentSizeMaxM2 = SIZE_MAX_AREA_DEFAULT;
    filterData();
  });

  // 3. Search Box keypress (POI Mode Only)
  // filterData() rebuilds every marker, so debounce to avoid per-keystroke lag on large datasets.
  const searchBox = document.getElementById('search-input');
  const debouncedFilter = debounce(filterData, 250);
  searchBox.addEventListener('input', (e) => {
    currentSearchQuery = e.target.value;
    debouncedFilter();
  });

  // 4. Last-Modified Date Range Sliders (POI Mode Only)
  // filterData() rebuilds every marker, so debounce like the search box.
  const dateFromSlider = document.getElementById('slider-date-from');
  const dateToSlider = document.getElementById('slider-date-to');
  const dateFromVal = document.getElementById('date-from-val');
  const dateToVal = document.getElementById('date-to-val');
  const debouncedDateFilter = debounce(filterData, 250);

  dateFromSlider.addEventListener('input', (e) => {
    let val = parseInt(e.target.value, 10);
    if (val > currentDateTo) {
      val = currentDateTo;
      e.target.value = val;
    }
    currentDateFrom = val;
    dateFromVal.innerText = formatDay(val);
    debouncedDateFilter();
  });

  dateToSlider.addEventListener('input', (e) => {
    let val = parseInt(e.target.value, 10);
    if (val < currentDateFrom) {
      val = currentDateFrom;
      e.target.value = val;
    }
    currentDateTo = val;
    dateToVal.innerText = formatDay(val);
    debouncedDateFilter();
  });

  // 5. Heatmap Radius Control (POI/Improve modes only - the gap gradient
  // interpolates from the real analysis grid and has no blob radius)
  const radiusSlider = document.getElementById('slider-radius');
  const radiusVal = document.getElementById('radius-val');
  radiusSlider.addEventListener('input', (e) => {
    const val = e.target.value;
    radiusVal.innerText = `${val}px`;
    if (heatmapLayer && (currentMode === 'poi' || currentMode === 'improve')) {
      heatmapLayer.setOptions({ radius: parseInt(val, 10) });
    }
  });

  // 6. Heatmap Blur / Smoothing Control
  const blurSlider = document.getElementById('slider-blur');
  const blurVal = document.getElementById('blur-val');
  const debouncedGapRebuild = debounce(updateMapLayers, 120);
  blurSlider.addEventListener('input', (e) => {
    const val = e.target.value;
    blurVal.innerText = `${val}px`;
    if (currentMode === 'poi' || currentMode === 'improve') {
      if (heatmapLayer) heatmapLayer.setOptions({ blur: parseInt(val, 10) });
    } else {
      // Gap mode: rebuild the smoothed grid lookup at the new radius.
      debouncedGapRebuild();
    }
  });

  // 7. Qibla Compass Manual Toggle Control
  const compassToggle = document.getElementById('qibla-compass-toggle');
  const compassEl = document.getElementById('qibla-compass');
  if (compassToggle && compassEl) {
    compassToggle.addEventListener('change', (e) => {
      if (e.target.checked) {
        compassEl.classList.remove('hidden');
        updateQiblaCompass();
      } else {
        compassEl.classList.add('hidden');
      }
    });
  }

  // 7b. Add OSM Note Mode Toggle + Composer
  const addNoteToggle = document.getElementById('add-note-mode-toggle');
  if (addNoteToggle) {
    addNoteToggle.addEventListener('change', (e) => {
      setAddNoteMode(e.target.checked);
    });
  }

  const noteSubmitBtn = document.getElementById('btn-submit-note');
  if (noteSubmitBtn) {
    noteSubmitBtn.addEventListener('click', submitPendingOsmNote);
  }

  const noteCancelBtn = document.getElementById('btn-cancel-note');
  if (noteCancelBtn) {
    noteCancelBtn.addEventListener('click', closeNoteComposer);
  }

  document.querySelectorAll('#note-preset-chips .chip').forEach(chip => {
    chip.addEventListener('click', () => {
      setActiveNotePreset(chip.getAttribute('data-preset'));
    });
  });

  // 8. OSM OAuth 2.0 Auth Controls
  const loginBtn = document.getElementById('btn-osm-login');
  if (loginBtn) {
    loginBtn.addEventListener('click', redirectToOSM);
  }
  
  const logoutBtn = document.getElementById('btn-osm-logout');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', () => {
      const token = localStorage.getItem('osm_access_token');
      if (token) {
        logoutOSM();
      } else {
        const authOverlay = document.getElementById('osm-auth-overlay');
        if (authOverlay) {
          authOverlay.classList.remove('hidden');
        }
      }
    });
  }

  // Handle skip/guest mode login
  const skipBtn = document.getElementById('btn-osm-skip');
  if (skipBtn) {
    skipBtn.addEventListener('click', () => {
      isOsmAnonymized = true;
      sessionStorage.setItem('osm_auth_skipped', 'true');
      
      // Close overlay
      const authOverlay = document.getElementById('osm-auth-overlay');
      if (authOverlay) {
        authOverlay.classList.add('hidden');
      }
      
      // Initialize dashboard using pending data
      if (pendingPoiData && pendingGapData && pendingBoundaryData) {
        initializeDashboard(pendingPoiData, pendingGapData, pendingBoundaryData, pendingSizeData);
      } else {
        // Fallback: reload page to fetch correctly
        window.location.reload();
      }
    });
  }

  // Handle Redirect URI copy button
  const copyUriBtn = document.getElementById('btn-copy-redirect-uri');
  if (copyUriBtn) {
    copyUriBtn.addEventListener('click', () => {
      navigator.clipboard.writeText(OSM_REDIRECT_URI).then(() => {
        // Find text label and swap momentarily
        const btnText = copyUriBtn.querySelector('span');
        const originalText = btnText.innerText;
        btnText.innerText = 'تم النسخ!';
        showToast('تم نسخ عنوان العودة (Redirect URI) إلى الحافظة.');
        setTimeout(() => {
          btnText.innerText = originalText;
        }, 2000);
      }).catch(err => {
        console.error('Failed to copy Redirect URI:', err);
        showToast('فشل في نسخ عنوان العودة تلقائياً. يرجى نسخه يدوياً.', 'error');
      });
    });
  }

  // Handle Auth Card Tab Switching
  const tabBtns = document.querySelectorAll('.auth-tab-btn');
  tabBtns.forEach(btn => {
    btn.addEventListener('click', (e) => {
      // Remove active class from all buttons
      tabBtns.forEach(b => b.classList.remove('active'));
      // Add active class to clicked button
      btn.classList.add('active');
      
      // Hide all tab contents
      const tabContents = document.querySelectorAll('.tab-content');
      tabContents.forEach(content => content.classList.add('hidden'));
      
      // Show targeted tab content
      const targetId = btn.getAttribute('data-target');
      const targetContent = document.getElementById(targetId);
      if (targetContent) {
        targetContent.classList.remove('hidden');
      }
    });
  });

  // Pre-fill fields if saved
  const envSelect = document.getElementById('osm-environment');
  if (envSelect && OSM_ENVIRONMENT) {
    envSelect.value = OSM_ENVIRONMENT;
  }

  const clientIdInput = document.getElementById('osm-client-id');
  if (clientIdInput && OSM_CLIENT_ID) {
    clientIdInput.value = OSM_CLIENT_ID;
  }

  const redirectUriDisplay = document.getElementById('osm-redirect-uri-display');
  if (redirectUriDisplay) {
    redirectUriDisplay.innerText = OSM_REDIRECT_URI;
  }
}

// ==========================================
// OpenStreetMap Notes (create + view nearby)
// ==========================================

// Enables/disables click-to-place Add Note mode: toggles the map cursor and
// (re)loads existing nearby notes so users can see what's already reported
// before filing a duplicate.
function setAddNoteMode(enabled) {
  addNoteMode = enabled;
  const mapEl = document.getElementById('map');
  if (mapEl) mapEl.classList.toggle('note-mode-active', enabled);

  if (enabled) {
    loadNearbyNotes();
  } else if (noteMarkersLayer) {
    noteMarkersLayer.clearLayers();
  }
}

function handleMapClickForNotes(e) {
  if (!addNoteMode) return;
  openNoteComposer(e.latlng.lat, e.latlng.lng);
}

// Switches which preset's field group is shown in the composer and updates
// the chip selector's active state to match.
function setActiveNotePreset(preset) {
  activeNotePreset = preset;

  document.querySelectorAll('#note-preset-chips .chip').forEach(chip => {
    chip.classList.toggle('active', chip.getAttribute('data-preset') === preset);
  });

  const groups = {
    freetext: document.getElementById('note-preset-freetext'),
    worship: document.getElementById('note-preset-worship'),
    fixme: document.getElementById('note-preset-fixme'),
    gone: document.getElementById('note-preset-gone')
  };
  Object.entries(groups).forEach(([key, el]) => {
    if (el) el.classList.toggle('hidden', key !== preset);
  });
}

// Opens the note composer overlay pre-filled with the given coordinates.
// Used both by map-click placement (Add Note mode) and the "report an issue
// here" shortcut on a POI's detail panel.
function openNoteComposer(lat, lon) {
  const overlay = document.getElementById('note-composer-overlay');
  const coordsEl = document.getElementById('note-composer-coords');
  const attributionEl = document.getElementById('note-composer-attribution');
  const textInput = document.getElementById('note-text-input');
  if (!overlay || !textInput) return;

  pendingNoteLatLng = { lat, lon };
  coordsEl.innerText = `${lat.toFixed(5)}, ${lon.toFixed(5)}`;

  // Reset every preset's fields and revert to free text each time the
  // composer opens, so leftover input from a previous note isn't resubmitted.
  textInput.value = '';
  document.getElementById('note-worship-name').value = '';
  document.getElementById('note-worship-religion').value = '';
  document.getElementById('note-fixme-text').value = '';
  document.getElementById('note-gone-name').value = '';
  document.getElementById('note-gone-types').value = '';
  setActiveNotePreset('freetext');

  const token = localStorage.getItem('osm_access_token');
  const displayName = localStorage.getItem('osm_user_display_name');
  attributionEl.innerText = (token && displayName)
    ? `سيتم نشر الملاحظة باسم: ${displayName}`
    : 'سيتم نشر الملاحظة كزائر مجهول (بدون تسجيل دخول).';

  overlay.classList.remove('hidden');
  textInput.focus();
}

function closeNoteComposer() {
  const overlay = document.getElementById('note-composer-overlay');
  if (overlay) overlay.classList.add('hidden');
  pendingNoteLatLng = null;
}

// Assembles the final note body for whichever preset is active (or the free
// text box), then appends the site's signature footer to every submission -
// preset or free text alike - the same convention StreetComplete/MAPS.ME use.
// Returns null (after showing a toast) if a required field for the active
// preset is missing.
function buildNoteText() {
  let body = '';

  if (activeNotePreset === 'worship') {
    const name = document.getElementById('note-worship-name').value.trim();
    const religion = document.getElementById('note-worship-religion').value.trim();
    const lines = ['يوجد هنا مكان عبادة غير موجود على الخريطة.'];
    if (name) lines.push(`الاسم: ${name}`);
    if (religion) lines.push(`الديانة: ${religion}`);
    body = lines.join('\n');
  } else if (activeNotePreset === 'fixme') {
    const fixme = document.getElementById('note-fixme-text').value.trim();
    if (!fixme) {
      showToast('يرجى وصف المشكلة قبل الإرسال.', 'error');
      return null;
    }
    body = `fixme: ${fixme}`;
  } else if (activeNotePreset === 'gone') {
    const poiName = document.getElementById('note-gone-name').value.trim();
    const poiTypes = document.getElementById('note-gone-types').value.trim();
    if (!poiName) {
      showToast('يرجى إدخال اسم المعلم قبل الإرسال.', 'error');
      return null;
    }
    const lines = [
      'المعلم غير موجود على أرض الواقع رغم ظهوره على الخريطة (قد تكون البيانات قديمة).',
      `POI name: ${poiName}`
    ];
    if (poiTypes) lines.push(`POI types: ${poiTypes}`);
    lines.push(`OSM data version: ${new Date().toISOString()}`);
    body = lines.join('\n');
  } else {
    const textInput = document.getElementById('note-text-input');
    body = textInput ? textInput.value.trim() : '';
    if (!body) {
      showToast('يرجى كتابة نص الملاحظة قبل الإرسال.', 'error');
      return null;
    }
  }

  return `${body}\n\n${NOTE_SIGNATURE}`;
}

// Submits the pending note to the OSM Notes API. Anonymous submission needs
// no Authorization header at all (OSM Notes natively support anonymous
// reporters); an attributed note is only attempted if the stored token's
// granted scope actually includes write_notes, since tokens issued before
// this feature existed won't have it.
async function submitPendingOsmNote() {
  if (!pendingNoteLatLng) return;

  const text = buildNoteText();
  if (!text) return;

  const { lat, lon } = pendingNoteLatLng;
  const submitBtn = document.getElementById('btn-submit-note');
  if (submitBtn) submitBtn.disabled = true;

  try {
    const token = localStorage.getItem('osm_access_token');
    const grantedScope = localStorage.getItem('osm_granted_scope') || '';
    const headers = {};
    if (token && grantedScope.split(' ').includes('write_notes')) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const url = `${OSM_API_BASE}/api/0.6/notes.json?lat=${lat}&lon=${lon}&text=${encodeURIComponent(text)}`;
    const response = await fetch(url, { method: 'POST', headers });

    if (!response.ok) {
      const errText = await response.text();
      throw new Error(errText || `HTTP ${response.status}`);
    }

    const noteFeature = await response.json();
    renderNoteMarker(noteFeature);

    const noteId = noteFeature.properties ? noteFeature.properties.id : undefined;
    showToast(`تم إرسال الملاحظة بنجاح! <a href="https://www.openstreetmap.org/note/${noteId}" target="_blank" rel="noopener noreferrer" style="color: inherit; text-decoration: underline;">عرض الملاحظة</a>`);
    closeNoteComposer();
  } catch (err) {
    console.error('Failed to submit OSM note:', err);
    showToast('فشل في إرسال الملاحظة إلى OpenStreetMap: ' + err.message, 'error');
  } finally {
    if (submitBtn) submitBtn.disabled = false;
  }
}

// Renders a single note (GeoJSON Feature from the notes API) as a read-only
// marker with a popup showing its first comment and a link to the note on OSM.
function renderNoteMarker(noteFeature) {
  if (!noteMarkersLayer || !noteFeature || !noteFeature.geometry) return;

  const [lon, lat] = noteFeature.geometry.coordinates;
  const props = noteFeature.properties || {};
  const isClosed = props.status === 'closed';
  const commentText = (props.comments && props.comments.length) ? props.comments[0].text : '';

  const icon = L.divIcon({
    html: '<div class="note-marker-inner">📝</div>',
    className: `note-marker ${isClosed ? 'closed' : ''}`,
    iconSize: [24, 24],
    iconAnchor: [12, 22]
  });

  const marker = L.marker([lat, lon], { icon });
  const noteUrl = `https://www.openstreetmap.org/note/${props.id}`;
  marker.bindPopup(`
    <div style="font-family: var(--font-body); text-align: right; padding: 2px; max-width: 220px;">
      <p style="margin: 0 0 6px 0; font-size: 12px; color: #333; white-space: pre-wrap;">${escapeHtml(commentText)}</p>
      <a href="${noteUrl}" target="_blank" rel="noopener noreferrer" style="font-size: 11px;">فتح الملاحظة على OSM</a>
    </div>
  `, { closeButton: false });

  noteMarkersLayer.addLayer(marker);
}

// Fetches open (and recently-closed) notes within the current map view while
// Add Note mode is active, so users can see what's already reported instead
// of filing duplicates.
async function loadNearbyNotes() {
  if (!addNoteMode || !map || !noteMarkersLayer) return;

  const bounds = map.getBounds();
  const bbox = `${bounds.getWest()},${bounds.getSouth()},${bounds.getEast()},${bounds.getNorth()}`;

  try {
    const response = await fetch(`${OSM_API_BASE}/api/0.6/notes.json?bbox=${bbox}&limit=100&closed=7`);
    if (!response.ok) return;

    const data = await response.json();
    noteMarkersLayer.clearLayers();
    (data.features || []).forEach(renderNoteMarker);
  } catch (err) {
    console.error('Failed to load nearby OSM notes:', err);
  }
}

// ==========================================
// OpenStreetMap OAuth 2.0 PKCE Helper Code
// ==========================================

function generateRandomString(length) {
  const chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~';
  let result = '';
  const randomValues = new Uint32Array(length);
  crypto.getRandomValues(randomValues);
  for (let i = 0; i < length; i++) {
    result += chars.charAt(randomValues[i] % chars.length);
  }
  return result;
}

async function sha256(plain) {
  const encoder = new TextEncoder();
  const data = encoder.encode(plain);
  return crypto.subtle.digest('SHA-256', data);
}

function base64urlencode(a) {
  let str = "";
  const bytes = new Uint8Array(a);
  const len = bytes.byteLength;
  for (let i = 0; i < len; i++) {
    str += String.fromCharCode(bytes[i]);
  }
  return btoa(str)
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/, "");
}

async function generateChallenge(verifier) {
  const hashed = await sha256(verifier);
  return base64urlencode(hashed);
}

async function redirectToOSM() {
  const envSelect = document.getElementById('osm-environment');
  if (envSelect) {
    OSM_ENVIRONMENT = envSelect.value;
    localStorage.setItem('osm_oauth_environment', OSM_ENVIRONMENT);
  }

  const clientIdInput = document.getElementById('osm-client-id').value.trim();
  if (!clientIdInput) {
    showToast('الرجاء إدخال معرّف العميل (Client ID) للاستمرار.', 'error');
    return;
  }
  
  OSM_CLIENT_ID = clientIdInput;
  localStorage.setItem('osm_oauth_client_id', OSM_CLIENT_ID);

  updateOsmUrls();
  
  const codeVerifier = generateRandomString(64);
  sessionStorage.setItem('osm_oauth_code_verifier', codeVerifier);
  
  const codeChallenge = await generateChallenge(codeVerifier);
  const state = generateRandomString(16);
  sessionStorage.setItem('osm_oauth_state', state);
  
  const url = `${OSM_AUTH_URL}?response_type=code` +
              `&client_id=${OSM_CLIENT_ID}` +
              `&redirect_uri=${encodeURIComponent(OSM_REDIRECT_URI)}` +
              `&scope=${encodeURIComponent('read_prefs write_notes')}` +
              `&code_challenge=${codeChallenge}` +
              `&code_challenge_method=S256` +
              `&state=${state}`;
              
  window.location.href = url;
}

async function handleOAuthCallback() {
  const params = new URLSearchParams(window.location.search);
  const code = params.get('code');
  const state = params.get('state');
  
  if (code && state) {
    // Save saved settings back to state in case page reloads
    OSM_ENVIRONMENT = localStorage.getItem('osm_oauth_environment') || 'production';
    OSM_CLIENT_ID = localStorage.getItem('osm_oauth_client_id') || '';
    updateOsmUrls();
    
    const cleanUrl = window.location.origin + window.location.pathname;
    window.history.replaceState({}, document.title, cleanUrl);

    const savedState = sessionStorage.getItem('osm_oauth_state');
    if (state !== savedState) {
      showToast('خطأ في التحقق من حالة الطلب (State Mismatch). يرجى المحاولة مجدداً.', 'error');
      return;
    }
    
    const codeVerifier = sessionStorage.getItem('osm_oauth_code_verifier');
    if (!codeVerifier) {
      showToast('مفقود رمز التحقق (Code Verifier). يرجى المحاولة مجدداً.', 'error');
      return;
    }
    
    sessionStorage.removeItem('osm_oauth_state');
    sessionStorage.removeItem('osm_oauth_code_verifier');
    
    try {
      showLoadingText('جارٍ تأكيد الهوية وتبادل الرموز مع OSM...');
      
      const payload = {
        client_id: OSM_CLIENT_ID,
        grant_type: 'authorization_code',
        code: code,
        redirect_uri: OSM_REDIRECT_URI,
        code_verifier: codeVerifier
      };

      const response = await fetch(OSM_TOKEN_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded'
        },
        body: new URLSearchParams(payload)
      });
      
      if (!response.ok) {
        const errText = await response.text();
        throw new Error(`Token exchange failed: ${errText}`);
      }
      
      const data = await response.json();
      if (data.access_token) {
        localStorage.setItem('osm_access_token', data.access_token);
        if (data.scope) {
          localStorage.setItem('osm_granted_scope', data.scope);
        }
        showToast('تم تسجيل الدخول بنجاح عبر OpenStreetMap!');
      }
    } catch (err) {
      console.error(err);
      showToast('فشل في تسجيل الدخول عبر OpenStreetMap: ' + err.message, 'error');
    }
  }
}

function showLoadingText(message) {
  const overlay = document.getElementById('loading-overlay');
  const text = document.getElementById('loading-text');
  if (overlay) {
    overlay.classList.remove('hidden');
    overlay.classList.remove('error');
  }
  if (text) text.innerText = message;
}

async function checkAuthStatus() {
  const token = localStorage.getItem('osm_access_token');
  if (!token) return false;
  
  try {
    OSM_ENVIRONMENT = localStorage.getItem('osm_oauth_environment') || 'production';
    updateOsmUrls();
    
    const response = await fetch(OSM_USER_DETAILS_URL, {
      headers: {
        'Authorization': `Bearer ${token}`
      }
    });
    
    if (response.ok) {
      const data = await response.json();
      if (data.user && data.user.display_name) {
        localStorage.setItem('osm_user_display_name', data.user.display_name);
        return true;
      }
    } else {
      localStorage.removeItem('osm_access_token');
      localStorage.removeItem('osm_user_display_name');
    }
  } catch (err) {
    console.error('Error verifying OSM token:', err);
  }
  return false;
}

function updateUserWidgetUI() {
  const widget = document.getElementById('user-profile-widget');
  const nameEl = document.getElementById('user-display-name');
  const roleEl = widget ? widget.querySelector('.user-role-text') : null;
  const statusEl = widget ? widget.querySelector('.user-status-text') : null;
  const logoutBtn = document.getElementById('btn-osm-logout');
  
  const token = localStorage.getItem('osm_access_token');
  
  if (widget) {
    if (token) {
      const displayName = localStorage.getItem('osm_user_display_name') || 'مستخدم OSM';
      if (nameEl) nameEl.innerText = displayName;
      if (statusEl) statusEl.innerHTML = `مرحباً، <strong id="user-display-name">${escapeHtml(displayName)}</strong>`;
      if (roleEl) roleEl.innerText = 'مساهم في OpenStreetMap';
      if (logoutBtn) {
        logoutBtn.innerText = 'تسجيل خروج';
        logoutBtn.className = 'osm-logout-btn';
        logoutBtn.title = 'تسجيل الخروج';
      }
      widget.style.display = 'flex';
    } else if (isOsmAnonymized) {
      if (statusEl) statusEl.innerHTML = `<span style="color: var(--color-text-muted);">تصفح كـ <strong>زائر (بيانات مجهلة)</strong></span>`;
      if (roleEl) roleEl.innerText = 'سجل دخولك لعرض المطورين والتعديل';
      if (logoutBtn) {
        logoutBtn.innerText = 'تسجيل دخول';
        logoutBtn.className = 'osm-login-btn-small';
        logoutBtn.title = 'تسجيل الدخول باستخدام OSM';
      }
      widget.style.display = 'flex';
    } else {
      widget.style.display = 'none';
    }
  }
}

function logoutOSM() {
  localStorage.removeItem('osm_access_token');
  localStorage.removeItem('osm_user_display_name');
  localStorage.removeItem('osm_granted_scope');
  sessionStorage.removeItem('osm_auth_skipped');
  showToast('تم تسجيل الخروج بنجاح.');
  window.location.reload();
}
