import { currentLang, t, fmtNum, fmtDate, onLanguageChange, setLanguage } from './i18n.js';
import { ArabicText } from './arabic.js';
import { ReviewMarks, hideReviewedPlaces, setHideReviewedPlaces, isHiddenByReview, markCurrentPlace, clearCurrentMark, renderReviewActions, rebuildReviewQueue, navigateReview, updateReviewNavUI, Permalink, updatePermalinkSoon, setupKeyboardShortcuts } from './review.js';
import { Exporters } from './exporters.js';
import { OsmApi } from './osm_api.js';
import { renderQuickFixes, setupEditing } from './editing.js';
import { trackEvent } from './analytics.js';
export let map;
export let heatmapLayer = null;
export let markerClusterLayer = null;
export let basemaps = {};
export let currentBasemap = null;
export let currentBasemapKey = 'dark';

// Login, OAuth and API editing live in js/osm_api.js (OsmApi).
export let isOsmAnonymized = true;

// OSM Notes State
export let addNoteMode = false;
export let noteMarkersLayer = null;
export let pendingNoteLatLng = null;
export let activeNotePreset = 'freetext';

// Appended to every submitted note (preset or free text) so mappers processing
// it know which site it came from - the same convention StreetComplete/MAPS.ME
// use ("via StreetComplete", "#mapsme"), which also promotes the site itself.
export const NOTE_SIGNATURE = 'via خارطة أماكن العبادة (https://manara.saudiosm.org) #sa-worship-map';

// Temporary storage for loaded data if auth is pending
export let pendingPoiData = null;
export let pendingGapData = null;
export let pendingBoundaryData = null;
export let pendingSizeData = null;
export let pendingAnomalyData = null;

// Datasets
export let allPlaces = [];
export let filteredPlaces = [];
export let allGaps = [];
export let filteredGaps = [];

// Filter States
export let currentMode = 'poi'; // 'poi', 'gap', or 'improve'
export let currentReligionFilter = 'all';
export let currentImprovementFilter = 'all';
export let currentGapUrgencyFilter = 'all'; // 'all' or 'high_urgency'
export let currentSearchQuery = '';
export function setCurrentSearchQuery(q) {
  currentSearchQuery = q;
}
export let currentDateFrom = null; // day-index (see dayIndex()), set once data loads
export let currentDateTo = null;
export let DATA_MIN_DAY = 0;
export let DATA_MAX_DAY = 1;

// Size-outlier thresholds (m²), user-adjustable in Improve Mode. Defaults match
// calculate_mosque_sizes.py's DEFAULT_MIN/MAX_AREA_M2.
export const SIZE_MIN_AREA_DEFAULT = 20;
export const SIZE_MAX_AREA_DEFAULT = 15000;
export let currentSizeMinM2 = SIZE_MIN_AREA_DEFAULT;
export let currentSizeMaxM2 = SIZE_MAX_AREA_DEFAULT;

// Qibla-outlier threshold (degrees), user-adjustable in Improve Mode. Default is 20 deg (top ~10% outliers).
export const QIBLA_DEV_DEFAULT = 20.0;
export let currentQiblaDevThreshold = QIBLA_DEV_DEFAULT;
export let currentQiblaSort = 'least_accurate'; // 'least_accurate' or 'most_accurate'
export let selectedPlace = null; // { properties, lat, lon } of the place in the details panel
export let viewportCountsOnly = false;

// Map configuration
export const MAP_INITIAL_CENTER = [24.0, 45.0]; // Centered on Saudi Arabia
export const MAP_INITIAL_ZOOM = 6;
export const CLUSTER_MIN_ZOOM = 11; // Zoom level at which individual markers/clusters appear
export const KAABA_COORDS = { lat: 21.42252, lng: 39.82618 };

// Color configuration for POIs
export const RELIGION_COLORS = {
  'muslim': '#00ff87', // Neon Green
  'christian': '#4facfe', // Electric Blue
  'unknown': '#ffb03a', // Gold/Amber
  'other': '#ffd700'
};

// Localized labels for religion=* / denomination=* values (js/translations.js);
// unknown values are shown as tagged.
export function religionLabel(value) {
  const label = t(`rel_${value}`);
  return label === `rel_${value}` ? value : label;
}

export function denomLabel(value) {
  const label = t(`denom_${value}`);
  return label === `denom_${value}` ? value : label;
}

// Small utility: delay invoking fn until `ms` after the last call.
// Keeps search/pan/zoom smooth by avoiding per-keystroke/per-frame recomputes.
export function debounce(fn, ms) {
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
export const ESRI_TILEMAP_URL = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tilemap';
export const ESRI_ASSUMED_MIN_ZOOM = 13; // always-available global mosaic level; skip probing below this
export const ESRI_MAX_PROBE_ZOOM = 21;   // Esri rarely publishes real imagery deeper than this

// Cache for max zoom levels. Keys are zoom-13 tile coordinates (approx. 4.4km x 4.4km grid cells).
export const esriMaxZoomCache = new Map();

export async function esriTilesAvailable(zoom, centerLatLng) {
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
export async function findEsriMaxZoom(centerLatLng) {
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
export async function updateSatelliteZoomCap() {
  if (currentBasemapKey !== 'satellite') return;
  const layer = basemaps['satellite'];
  const maxFound = await findEsriMaxZoom(map.getCenter());
  if (currentBasemapKey !== 'satellite') return; // basemap may have changed while awaiting
  
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

export const debouncedUpdateSatelliteZoomCap = debounce(updateSatelliteZoomCap, 400);

// Convert an ISO edited_at timestamp to a whole-day index for slider bounds/comparison.
export function dayIndex(isoString) {
  return Math.floor(new Date(isoString).getTime() / 86400000);
}

// Render a day-index back to a localized short date for slider labels.
export function formatDay(day) {
  return new Date(day * 86400000).toLocaleDateString(currentLang === 'ar' ? 'ar-SA' : 'en-GB', { year: 'numeric', month: 'short', day: 'numeric' });
}

// Escape user-supplied text (OSM names) before injecting into popup HTML.
export function escapeHtml(str) {
  return String(str ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  }[ch]));
}

// Returns the URL only if it uses http(s); blocks javascript: and similar schemes.
export function safeUrl(url) {
  const s = String(url || '').trim();
  return /^https?:\/\//i.test(s) ? s : '';
}

// OSM element type ('node' | 'way' | 'relation') for a place's properties.
export function osmTypeOf(props) {
  if (props.geom_type === 'Point') return 'node';
  if (props.geom_type === 'Relation') return 'relation';
  return 'way';
}

// Detect mapping issues for a feature based on its tags
export function getQualityIssues(props) {
  const issues = [];
  
  // 1. building=mosque without amenity=place_of_worship
  if (props.building === 'mosque' && props.amenity !== 'place_of_worship') {
    issues.push({
      id: 'missing_amenity',
      title_ar: 'مبنى مسجد بدون تصنيف (amenity=place_of_worship)',
      title_en: 'Building marked as mosque but missing amenity=place_of_worship'
    });
  }
  
  // 2. Missing specific name (empty, or only generic words like "مسجد", "الجامع", "مصلى", "Mosque")
  if (ArabicText.isGenericMosqueName(props.name_original)) {
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

  // 8. Mapped as a single node instead of a building outline (area/way).
  // Ideally a mosque's footprint should be traced as an area so its true
  // size and shape show up on the map, rather than a single point.
  if (props.geom_type === 'Point') {
    issues.push({
      id: 'mapped_as_node',
      title_ar: 'مرسوم كنقطة وليس كمساحة (مبنى) — يفضّل رسم حدود المبنى',
      title_en: 'Mapped as a single node instead of an area — ideally traced as a building outline'
    });
  }

  // 9. Machine Learning Spatial Geometry Anomaly (Isolation Forest)
  if (props.ml_anomaly && props.ml_anomaly.is_anomaly) {
    issues.push({
      id: 'ml_geometry_anomaly',
      title_ar: `🤖 شذوذ هندسي (ذكاء اصطناعي): ${props.ml_anomaly.diagnosis}`,
      title_en: `🤖 ML Geometry Anomaly: ${props.ml_anomaly.diagnosis_en || props.ml_anomaly.diagnosis}`
    });
  }

  // 11. Mapped twice: the building outline and a point inside it both carry
  // amenity=place_of_worship (merged into one place by extract_places.py).
  if (props.duplicate_poi) {
    issues.push({
      id: 'duplicate_poi',
      title_ar: 'مكرر: المبنى ونقطة داخله كلاهما موسوم كدار عبادة — يُفضّل نقل الوسوم إلى المبنى وحذف النقطة',
      title_en: 'Mapped twice: both the building and a point inside it are tagged as the place of worship'
    });
  }

  // 10. Qibla Orientation Misalignment
  if (props.ml_anomaly && typeof props.ml_anomaly.qibla_dev === 'number') {
    if (props.ml_anomaly.qibla_dev >= currentQiblaDevThreshold) {
      issues.push({
        id: 'qibla_deviation',
        title_ar: `🕋 انحراف حاد عن القبلة (${props.ml_anomaly.qibla_dev}° — سمت القبلة ${props.ml_anomaly.qibla_az}° مقابل ${props.ml_anomaly.bldg_az}° لمحور المبنى)`,
        title_en: `🕋 Severe Qibla deviation (${props.ml_anomaly.qibla_dev}°: Qibla bearing ${props.ml_anomaly.qibla_az}° vs building axis ${props.ml_anomaly.bldg_az}°)`
      });
    }
  }

  return issues;
}

// getQualityIssues() depends on the size/Qibla thresholds; cache its result
// per place and bump issuesVersion whenever a threshold changes, so counts,
// filtering, popups and the details panel don't recompute it 14k times each.
export let issuesVersion = 0;
export function getIssues(props) {
  if (props._issuesVersion !== issuesVersion) {
    props._issues = getQualityIssues(props);
    props._issuesVersion = issuesVersion;
  }
  return props._issues;
}

export function invalidateIssues() {
  issuesVersion++;
}

// Calculate and update the dynamic counts badge for each quality issue filter
export function updateImprovementIssueCounts() {
  if (!allPlaces || allPlaces.length === 0) return;

  // One badge per filter button in index.html; counts start at zero so a
  // check with no hits shows 0 rather than a stale value.
  const counts = { all: 0 };
  document.querySelectorAll('[data-improve]').forEach(btn => {
    counts[btn.getAttribute('data-improve')] = 0;
  });

  // Optionally only count what's on screen; places already marked as
  // reviewed are left out while they're hidden, so counts show what remains.
  const bounds = viewportCountsOnly && map ? map.getBounds() : null;
  for (let i = 0; i < allPlaces.length; i++) {
    const f = allPlaces[i];
    if (bounds && !bounds.contains([f.geometry.coordinates[1], f.geometry.coordinates[0]])) continue;
    if (hideReviewedPlaces && ReviewMarks.get(f.properties)) continue;
    const issues = getIssues(f.properties);
    if (issues.length > 0) {
      counts.all++;
      for (let j = 0; j < issues.length; j++) {
        const id = issues[j].id;
        if (counts[id] !== undefined) {
          counts[id]++;
        }
      }
    }
  }

  // Populate counts in badges
  Object.keys(counts).forEach(key => {
    const el = document.getElementById(`count-improve-${key}`);
    if (el) {
      el.textContent = fmtNum(counts[key]);
    }
  });

  const totalBadge = document.getElementById('quality-total-issues-badge');
  if (totalBadge) {
    totalBadge.textContent = t('issuesNeedReview', { n: fmtNum(counts.all) });
  }
}

// Send load_and_zoom request to JOSM Remote Control port (8111)
export function editInJOSM(lat, lon, props) {
  // Merged places select both the building and the POI node inside it.
  const select = [`${osmTypeOf(props)}${props.osm_id}`];
  if (props.poi_node_id) select.push(`node${props.poi_node_id}`);
  const delta = 0.0015;
  const url = `http://127.0.0.1:8111/load_and_zoom?left=${lon - delta}&right=${lon + delta}&top=${lat + delta}&bottom=${lat - delta}&select=${select.join(',')}`;

  fetch(url)
    .then(res => {
      if (res.ok) {
        showToast(t('josmSent'));
      } else {
        showToast(t('josmLoadFailed'), 'error');
      }
    })
    .catch(err => {
      showToast(t('josmUnreachable'), 'error');
    });
}

// Send the currently visible map viewport (used in Gap Mode after locating an
// underserved area via the heatmap + Qibla compass) to JOSM Remote Control so
// the user can survey the area and add a new mosque node with its own ID.
export function openAreaInJOSM() {
  const bounds = map.getBounds();
  const url = `http://127.0.0.1:8111/load_and_zoom?left=${bounds.getWest()}&right=${bounds.getEast()}&top=${bounds.getNorth()}&bottom=${bounds.getSouth()}`;

  fetch(url)
    .then(res => {
      if (res.ok) {
        showToast(t('josmAreaSent'));
      } else {
        showToast(t('josmAreaFailed'), 'error');
      }
    })
    .catch(err => {
      showToast(t('josmUnreachable'), 'error');
    });
}

// Update the iD Editor link for the currently viewed map area so that the user
// can open the area in iD Editor and add a new mosque node.
export function updateIdEditorAreaLink() {
  const idBtn = document.getElementById('btn-open-area-id');
  if (idBtn && map) {
    const isDev = OsmApi.environment() === 'dev';
    const base = isDev ? 'https://master.apis.dev.openstreetmap.org' : 'https://www.openstreetmap.org';
    const center = map.getCenter();
    const zoom = Math.max(16, Math.round(map.getZoom()));
    idBtn.href = `${base}/edit?editor=id#map=${zoom}/${center.lat.toFixed(5)}/${center.lng.toFixed(5)}`;
  }
}

// === Wikidata Suggested Mosques Layer ===
export let suggestionsLayer = null;
export let suggestionsLoading = false;
export let suggestionsAllFeatures = [];
export let suggestionsMarkers = [];
export const suggestionsByQid = {};
export let currentSuggestionFilter = 'all'; // 'all' | 'named' | 'unnamed'

export function setSuggestionsVisible(visible) {
  const toggle = document.getElementById('suggestions-toggle');
  const subcontrols = document.getElementById('suggestions-subcontrols');
  const badge = document.getElementById('suggestions-badge');

  if (!visible) {
    if (suggestionsLayer && map.hasLayer(suggestionsLayer)) {
      map.removeLayer(suggestionsLayer);
    }
    if (subcontrols) subcontrols.style.display = 'none';
    return;
  }

  if (subcontrols) subcontrols.style.display = 'flex';

  if (suggestionsLayer) {
    if (!map.hasLayer(suggestionsLayer)) {
      map.addLayer(suggestionsLayer);
    }
    updateSuggestionsViewportCount();
    return;
  }

  if (suggestionsLoading) return;
  suggestionsLoading = true;

  const label = document.getElementById('suggestions-switch-label');
  const originalLabel = label ? label.innerText : '';
  if (label) label.innerText = t('sugLoading');

  fetchJson('suggested_mosques_sa.geojson')
    .then(data => {
      suggestionsAllFeatures = data.features || [];
      const meta = data.metadata || {};

      const countAll = meta.total_suggestions || suggestionsAllFeatures.length;
      const countNamed = meta.named_suggestions || suggestionsAllFeatures.filter(f => !f.properties.is_unnamed).length;
      const countUnnamed = meta.unnamed_suggestions || (countAll - countNamed);

      if (badge) {
        badge.innerText = t('sugBadge', { n: fmtNum(countAll) });
        badge.style.display = 'inline-block';
      }
      const elAll = document.getElementById('sug-count-all');
      const elNamed = document.getElementById('sug-count-named');
      const elUnnamed = document.getElementById('sug-count-unnamed');
      if (elAll) elAll.innerText = fmtNum(countAll);
      if (elNamed) elNamed.innerText = fmtNum(countNamed);
      if (elUnnamed) elUnnamed.innerText = fmtNum(countUnnamed);

      suggestionsLayer = L.markerClusterGroup({
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
            html: `<div class="suggestion-cluster" style="width: ${size}px; height: ${size}px; font-size: ${size > 40 ? 12 : 11}px;"><span>${fmtNum(childCount)}</span></div>`,
            className: 'marker-cluster-custom',
            iconSize: new L.Point(size, size)
          });
        }
      });

      suggestionsMarkers = [];
      suggestionsAllFeatures.forEach(f => {
        const [lon, lat] = f.geometry.coordinates;
        const props = f.properties;
        const isUnnamed = props.is_unnamed;
        suggestionsByQid[props.qid] = { ...props, lat, lon };

        const marker = L.circleMarker([lat, lon], {
          radius: 6,
          color: isUnnamed ? '#64748b' : '#d97706',
          fillColor: isUnnamed ? '#94a3b8' : '#f59e0b',
          fillOpacity: 0.85,
          weight: 1.5
        });

        marker._sugProperties = props;
        marker._sugCoords = [lat, lon];
        marker.bindPopup(() => buildSuggestionPopup(props, lat, lon));
        suggestionsMarkers.push(marker);
      });

      applySuggestionsFilter();

      const currentToggle = document.getElementById('suggestions-toggle');
      if (!currentToggle || currentToggle.checked) {
        map.addLayer(suggestionsLayer);
      }
      if (subcontrols) subcontrols.style.display = 'flex';

      showToast(t('sugLoaded', { n: fmtNum(countAll) }));
      updateSuggestionsViewportCount();
    })
    .catch(err => {
      console.error('Error loading suggestions:', err);
      showToast(t('sugLoadFailed'), 'error');
      if (toggle) toggle.checked = false;
      if (subcontrols) subcontrols.style.display = 'none';
    })
    .finally(() => {
      suggestionsLoading = false;
      if (label) label.innerText = originalLabel;
    });
}

export function applySuggestionsFilter() {
  if (!suggestionsLayer) return;
  suggestionsLayer.clearLayers();

  const searchQuery = ArabicText.normalize(currentSearchQuery, true);

  const filteredMarkers = suggestionsMarkers.filter(m => {
    const props = m._sugProperties;
    if (currentSuggestionFilter === 'named' && props.is_unnamed) return false;
    if (currentSuggestionFilter === 'unnamed' && !props.is_unnamed) return false;

    if (searchQuery) {
      if (props._searchKey === undefined) {
        props._searchKey = ArabicText.normalize(`${props.name_ar || ''} ${props.name_en || ''} ${props.qid || ''}`, true);
      }
      if (!props._searchKey.includes(searchQuery)) return false;
    }
    return true;
  });

  suggestionsLayer.addLayers(filteredMarkers);
  updateSuggestionsViewportCount();
}

export function updateSuggestionsViewportCount() {
  if (!map || !suggestionsLayer || !map.hasLayer(suggestionsLayer)) return;
  const countEl = document.getElementById('suggestions-viewport-count');
  if (!countEl) return;

  const bounds = map.getBounds();
  let inView = 0;
  for (let i = 0; i < suggestionsMarkers.length; i++) {
    const m = suggestionsMarkers[i];
    const props = m._sugProperties;
    if (currentSuggestionFilter === 'named' && props.is_unnamed) continue;
    if (currentSuggestionFilter === 'unnamed' && !props.is_unnamed) continue;

    const [lat, lon] = m._sugCoords;
    if (bounds.contains([lat, lon])) {
      inView++;
    }
  }
  countEl.innerText = fmtNum(inView);
}

export function buildSuggestionPopup(props, lat, lon) {
  const isUnnamed = props.is_unnamed;
  const displayName = (currentLang === 'en' ? props.name_en || props.name_ar : props.name_ar || props.name_en) || t('sugUnnamed');
  const subtitle = currentLang === 'en' ? props.name_ar : props.name_en;
  const nearest = props.nearest_osm_m == null ? t('sugOverKm') : t('sugMetres', { n: fmtNum(props.nearest_osm_m) });
  const idUrl = `https://www.openstreetmap.org/edit?editor=id#map=19/${lat}/${lon}`;

  return `
    <div class="suggestion-popup" dir="${currentLang === 'ar' ? 'rtl' : 'ltr'}">
      <div class="suggestion-popup-header">
        <h3 class="suggestion-title">🕌 ${escapeHtml(displayName)}</h3>
        ${props.name_en && props.name_ar ? `<div class="suggestion-subtitle">${escapeHtml(subtitle)}</div>` : ''}
      </div>

      <div>
        ${isUnnamed 
          ? `<span class="badge-sug-generic">${t('sugGeneric')}</span>`
          : `<span class="badge-sug-verified">${t('sugVerified')}</span>`
        }
      </div>

      <div class="suggestion-meta-list">
        <div class="suggestion-meta-item">
          <span class="suggestion-meta-label">${t('sugQid')}</span>
          <span class="suggestion-meta-val"><a href="https://www.wikidata.org/wiki/${escapeHtml(props.qid)}" target="_blank" rel="noopener noreferrer">${escapeHtml(props.qid)} ↗</a></span>
        </div>
        <div class="suggestion-meta-item">
          <span class="suggestion-meta-label">${t('sugNearest')}</span>
          <span class="suggestion-meta-val">${nearest}</span>
        </div>
        <div class="suggestion-meta-item">
          <span class="suggestion-meta-label">${t('sugCoords')}</span>
          <span class="suggestion-meta-val" dir="ltr">${lat.toFixed(5)}, ${lon.toFixed(5)}</span>
        </div>
      </div>

      <div class="suggestion-actions">
        <button type="button" class="btn-sug-action btn-sug-satellite" data-sug-action="satellite" data-qid="${escapeHtml(props.qid)}" title="${t('sugSatelliteTitle')}">
          ${t('sugSatellite')}
        </button>
        <button type="button" class="btn-sug-action btn-sug-copy" data-sug-action="copy" data-qid="${escapeHtml(props.qid)}" title="${t('sugCopyTitle')}">
          ${t('sugCopy')}
        </button>
        <a href="${idUrl}" target="_blank" rel="noopener noreferrer" class="btn-sug-action btn-sug-id" title="${t('sugIdTitle')}">
          ${t('sugId')}
        </a>
        <button type="button" class="btn-sug-action btn-sug-josm" data-sug-action="josm" data-qid="${escapeHtml(props.qid)}" title="${t('sugJosmTitle')}">
          ${t('sugJosm')}
        </button>
      </div>
    </div>`;
}

// Popup buttons carry data-sug-action/data-qid instead of inline onclick
// strings, so popup HTML never has to embed values inside JavaScript.
document.addEventListener('click', (e) => {
  const btn = e.target.closest('[data-sug-action]');
  if (!btn) return;
  e.preventDefault();
  const qid = btn.getAttribute('data-qid');
  const action = btn.getAttribute('data-sug-action');
  if (action === 'copy') {
    copySuggestionTags(qid);
  } else if (action === 'josm') {
    addSuggestionInJOSM(qid);
  } else if (action === 'satellite') {
    const s = suggestionsByQid[qid];
    if (s) previewSuggestionSatellite(s.lat, s.lon);
  }
});

export function previewSuggestionSatellite(lat, lon) {
  if (!map) return;
  setBasemap('satellite');
  const satChip = document.querySelector('#basemap-filters .chip[data-basemap="satellite"]');
  if (satChip) {
    document.querySelectorAll('#basemap-filters .chip').forEach(c => c.classList.remove('active'));
    satChip.classList.add('active');
  }
  map.setView([lat, lon], 18, { animate: true });
  showToast(t('sugSatelliteToast'));
}

export function copySuggestionTags(qid) {
  const s = suggestionsByQid[qid];
  if (!s) return;
  const lines = [
    'amenity=place_of_worship',
    'religion=muslim',
  ];
  if (!s.is_unnamed) {
    if (s.name_ar) {
      lines.push(`name=${s.name_ar}`);
      lines.push(`name:ar=${s.name_ar}`);
    } else if (s.name_en) {
      lines.push(`name=${s.name_en}`);
    }
    if (s.name_en) {
      lines.push(`name:en=${s.name_en}`);
    }
  }
  lines.push(`wikidata=${qid}`);

  const text = lines.join('\n');
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text)
      .then(() => showToast(t('tagsCopied')))
      .catch(() => showToast(t('copyFailed'), 'error'));
  } else {
    showToast(t('copyUnsupported'), 'error');
  }
}

export function addSuggestionInJOSM(qid) {
  const s = suggestionsByQid[qid];
  if (!s) return;
  const { lat, lon } = s;
  const delta = 0.0015;
  const loadUrl = `http://127.0.0.1:8111/load_and_zoom?left=${lon - delta}&right=${lon + delta}&top=${lat + delta}&bottom=${lat - delta}`;
  
  let tags = `amenity=place_of_worship|religion=muslim|wikidata=${qid}`;
  if (!s.is_unnamed) {
    const clean = str => String(str).replace(/\|/g, ' ');
    if (s.name_ar) tags += `|name=${clean(s.name_ar)}|name:ar=${clean(s.name_ar)}`;
    else if (s.name_en) tags += `|name=${clean(s.name_en)}`;
    if (s.name_en) tags += `|name:en=${clean(s.name_en)}`;
  }
  const addUrl = `http://127.0.0.1:8111/add_node?lon=${lon}&lat=${lat}&addtags=${encodeURIComponent(tags)}`;

  showToast(t('sugJosmWorking'));
  fetch(loadUrl)
    .then(res => {
      if (!res.ok) throw new Error('Load failed');
      return new Promise(resolve => setTimeout(resolve, 700));
    })
    .then(() => fetch(addUrl))
    .then(res => {
      if (res.ok) {
        showToast(t('sugJosmAdded'));
      } else {
        showToast(t('sugJosmAddFailed'), 'error');
      }
    })
    .catch(() => {
      showToast(t('josmUnreachable'), 'error');
    });
}


// Show animated non-blocking toast notification. The message is plain text
// (it can contain server error text); pass { link: { href, text } } to append a link.
export function showToast(message, type = 'success', options = {}) {
  // Remove existing toast if any
  const existingToast = document.querySelector('.toast-notification');
  if (existingToast) {
    existingToast.remove();
  }

  const toast = document.createElement('div');
  toast.className = `toast-notification ${type}`;
  const span = document.createElement('span');
  span.textContent = message;
  const href = options.link && safeUrl(options.link.href);
  if (href) {
    const a = document.createElement('a');
    a.href = href;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    a.className = 'toast-link';
    a.textContent = options.link.text;
    span.append(' ', a);
  }
  toast.appendChild(span);
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
export function calculateBearing(lat1, lon1, lat2, lon2) {
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
export function calculateDistance(lat1, lon1, lat2, lon2) {
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
export function updateQiblaCompass() {
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

// Controls sidebar collapsed state and persists preference
export function setSidebarCollapsed(isCollapsed) {
  const container = document.getElementById('app-container');
  const toggleBtn = document.getElementById('sidebar-toggle');
  if (!container) return;

  container.classList.toggle('sidebar-collapsed', isCollapsed);
  if (toggleBtn) {
    toggleBtn.setAttribute('aria-expanded', String(!isCollapsed));
  }
  try {
    localStorage.setItem('sidebar_collapsed', String(isCollapsed));
  } catch (e) {
    // Ignore storage errors in private browsing
  }
}

// Applies persisted (or, on a first-ever mobile visit, defaulted-collapsed)
// sidebar state and wires the toggle button. The auth overlay is a fixed,
// higher-z-index full-viewport modal, so it already covers this button
// whenever it's shown - no extra guard needed there.
export function initSidebarToggle() {
  const container = document.getElementById('app-container');
  const toggleBtn = document.getElementById('sidebar-toggle');
  if (!container || !toggleBtn) return;

  let initialCollapsed = false;
  try {
    const stored = localStorage.getItem('sidebar_collapsed');
    initialCollapsed = stored !== null
      ? stored === 'true'
      : window.matchMedia('(max-width: 768px)').matches;
  } catch (e) {
    initialCollapsed = window.matchMedia('(max-width: 768px)').matches;
  }
  setSidebarCollapsed(initialCollapsed);

  toggleBtn.addEventListener('click', () => {
    setSidebarCollapsed(!container.classList.contains('sidebar-collapsed'));
  });
}

document.addEventListener('DOMContentLoaded', () => {
  onLanguageChange(refreshLanguageDependentUI);
  if (currentLang !== 'ar') setLanguage(currentLang);
  document.getElementById('btn-toggle-lang').addEventListener('click', () => {
    setLanguage(currentLang === 'ar' ? 'en' : 'ar');
  });
  initMap();
  setupEventListeners();
  setupKeyboardShortcuts();
  initSidebarToggle();
  // Handle OAuth callback first, then load the data
  setupEditing();
  OsmApi.handleCallback().then(() => {
    loadData();
  });
});

// Build basemap layers according to whether a CARTO API key is provided
export function createBasemapLayers() {
  const cartoKey = (localStorage.getItem('carto_api_key') || '').trim();
  const cartoParam = cartoKey ? `?key=${encodeURIComponent(cartoKey)}` : '';

  let darkLayer;
  let lightLayer;

  if (cartoKey) {
    // If CARTO API key is provided, use official CARTO Dark Matter & Positron without watermark
    darkLayer = L.tileLayer(`https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png${cartoParam}`, {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
      subdomains: 'abcd',
      maxZoom: 20
    });
    lightLayer = L.tileLayer(`https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png${cartoParam}`, {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
      subdomains: 'abcd',
      maxZoom: 20
    });
  } else {
    // Keyless, watermark-free Esri Canvas layers by default
    darkLayer = L.layerGroup([
      L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
        attribution: 'Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ',
        maxZoom: 20,
        maxNativeZoom: 19
      }),
      L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}', {
        attribution: '',
        maxZoom: 20,
        maxNativeZoom: 19
      })
    ]);
    darkLayer.options = { maxZoom: 20 };

    lightLayer = L.layerGroup([
      L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
        attribution: 'Tiles &copy; Esri &mdash; Esri, DeLorme, NAVTEQ',
        maxZoom: 20,
        maxNativeZoom: 19
      }),
      L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}', {
        attribution: '',
        maxZoom: 20,
        maxNativeZoom: 19
      })
    ]);
    lightLayer.options = { maxZoom: 20 };
  }

  const satelliteLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
    attribution: 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community',
    maxZoom: 20,
    maxNativeZoom: 19
  });

  const streetsLayer = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}', {
    attribution: 'Tiles &copy; Esri &mdash; Source: Esri, DeLorme, NAVTEQ, USGS, Intermap, iPC, NRCAN, Esri Japan, METI, Esri China (Hong Kong), Esri (Thailand), TomTom, 2012',
    maxZoom: 20
  });

  return {
    'dark': darkLayer,
    'satellite': satelliteLayer,
    'light': lightLayer,
    'streets': streetsLayer
  };
}

// Switches the active basemap on the map
export function setBasemap(key) {
  if (basemaps[key] && (currentBasemap !== basemaps[key] || !map.hasLayer(basemaps[key]))) {
    if (currentBasemap) {
      map.removeLayer(currentBasemap);
    }
    currentBasemapKey = key;
    currentBasemap = basemaps[key];
    currentBasemap.addTo(map);

    if (key === 'satellite') {
      updateSatelliteZoomCap();
    } else {
      const maxZoom = currentBasemap.options?.maxZoom || 20;
      map.setMaxZoom(maxZoom);
    }
  }

  // Automatic Qibla compass visibility triggers based on basemap
  const compassToggle = document.getElementById('qibla-compass-toggle');
  const compassEl = document.getElementById('qibla-compass');
  if (compassToggle && compassEl) {
    if (key === 'satellite') {
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
}

// Rebuilds basemaps when CARTO API key is saved or cleared, without losing state
export function reloadBasemapLayers() {
  const activeKey = currentBasemapKey || 'dark';
  if (currentBasemap) {
    map.removeLayer(currentBasemap);
  }
  basemaps = createBasemapLayers();
  currentBasemap = basemaps[activeKey];
  currentBasemap.addTo(map);

  if (activeKey === 'satellite') {
    updateSatelliteZoomCap();
  } else {
    const maxZoom = currentBasemap.options?.maxZoom || 20;
    map.setMaxZoom(maxZoom);
  }
  updateCartoBadgeStatus();
}

// Updates UI badge and modal fields based on stored CARTO key
export function updateCartoBadgeStatus() {
  const cartoKey = (localStorage.getItem('carto_api_key') || '').trim();
  const btn = document.getElementById('btn-carto-config');
  const inputEl = document.getElementById('carto-api-key-input');
  const statusEl = document.getElementById('carto-key-status');
  const statusText = document.getElementById('carto-status-text');
  const clearBtn = document.getElementById('btn-clear-carto-key');
  const badgeText = document.getElementById('carto-badge-text');

  if (inputEl) {
    inputEl.value = cartoKey;
  }

  if (cartoKey) {
    if (btn) btn.classList.add('active-key');
    if (badgeText) badgeText.innerText = t('cartoBadgeOn');
    if (clearBtn) clearBtn.style.display = 'block';
    if (statusEl) {
      statusEl.className = 'carto-status-box active';
      const dot = statusEl.querySelector('.status-dot');
      if (dot) dot.className = 'status-dot green';
    }
    if (statusText) {
      statusText.innerText = t('cartoStatusOn');
    }
  } else {
    if (btn) btn.classList.remove('active-key');
    if (badgeText) badgeText.innerText = t('cartoBadgeOff');
    if (clearBtn) clearBtn.style.display = 'none';
    if (statusEl) {
      statusEl.className = 'carto-status-box default';
      const dot = statusEl.querySelector('.status-dot');
      if (dot) dot.className = 'status-dot neutral';
    }
    if (statusText) {
      statusText.innerText = t('cartoStatusOff');
    }
  }
}

// Sets up CARTO API Key modal event listeners
export function setupCartoModalEvents() {
  const configBtn = document.getElementById('btn-carto-config');
  const modal = document.getElementById('carto-settings-overlay');
  const closeBtn = document.getElementById('btn-close-carto-modal');
  const saveBtn = document.getElementById('btn-save-carto-key');
  const clearBtn = document.getElementById('btn-clear-carto-key');
  const inputEl = document.getElementById('carto-api-key-input');

  if (configBtn && modal) {
    configBtn.addEventListener('click', () => {
      updateCartoBadgeStatus();
      modal.classList.remove('hidden');
    });
  }

  if (closeBtn && modal) {
    closeBtn.addEventListener('click', () => {
      modal.classList.add('hidden');
    });
  }

  if (modal) {
    modal.addEventListener('click', (e) => {
      if (e.target === modal) {
        modal.classList.add('hidden');
      }
    });
  }

  if (saveBtn && inputEl && modal) {
    saveBtn.addEventListener('click', () => {
      const key = inputEl.value.trim();
      if (key) {
        localStorage.setItem('carto_api_key', key);
        reloadBasemapLayers();
        modal.classList.add('hidden');
        showToast(t('cartoEnabled'));
      } else {
        localStorage.removeItem('carto_api_key');
        reloadBasemapLayers();
        modal.classList.add('hidden');
        showToast(t('cartoDefault'));
      }
    });
  }

  if (clearBtn && modal) {
    clearBtn.addEventListener('click', () => {
      localStorage.removeItem('carto_api_key');
      if (inputEl) inputEl.value = '';
      reloadBasemapLayers();
      modal.classList.add('hidden');
      showToast(t('cartoRestored'));
    });
  }
}

// Initialize Leaflet Map
export function initMap() {
  map = L.map('map', {
    zoomControl: false // Custom styled zoom controls
  }).setView(MAP_INITIAL_CENTER, MAP_INITIAL_ZOOM);

  // The overlays are OSM data whatever the basemap, so the ODbL attribution
  // stays on even over the Esri tiles.
  map.attributionControl.addAttribution('Data &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors (ODbL)');

  // Position Zoom Control on the bottom-left to avoid sidebar overlap on the right (RTL layout)
  L.control.zoom({
    position: 'bottomleft'
  }).addTo(map);

  // Define available basemaps (uses keyless Esri Dark/Light by default, or CARTO if API key is provided)
  basemaps = createBasemapLayers();

  // Add default (dark) basemap
  currentBasemapKey = 'dark';
  currentBasemap = basemaps[currentBasemapKey];
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
  map.on('moveend', () => {
    if (suggestionsLayer && map.hasLayer(suggestionsLayer)) {
      updateSuggestionsViewportCount();
    }
  });
  map.on('moveend', updatePermalinkSoon);
  const debouncedViewportCounts = debounce(() => {
    if (viewportCountsOnly && currentMode === 'improve') updateImprovementIssueCounts();
  }, 250);
  map.on('moveend', debouncedViewportCounts);
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

// summary.json is tiny and always fetched fresh; its updated_at is then used
// as the version for the big data files, so browsers cache them until the
// pipeline publishes new data instead of re-downloading ~20 MB every visit.
// Published datasets live under /data/ (served by Caddy in production and by
// vite.config.js in development), never next to the app's own files.
const DATA_BASE = '/data/';
export let dataSummary = {};
export let dataVersion = String(Date.now());

export function fetchJson(path, required = true) {
  const req = fetch(`${DATA_BASE}${path}?v=${encodeURIComponent(dataVersion)}`).then(r => {
    if (!r.ok) throw new Error(`Failed to load ${path} (HTTP ${r.status})`);
    return r.json();
  });
  return required ? req : req.catch(() => ({}));
}

// Shows which OSM extract the published data was built from.
export function renderDataUpdatedLabel() {
  const el = document.getElementById('data-updated');
  if (!el) return;
  const date = dataSummary.pbf_date || (dataSummary.updated_at || '').slice(0, 10);
  el.textContent = date ? t('dataUpdated', { date }) : '';
  el.style.display = date ? '' : 'none';
}

export function loadData() {
  fetch(`${DATA_BASE}summary.json`, { cache: 'no-store' })
    .then(r => (r.ok ? r.json() : {}))
    .catch(() => ({}))
    .then(summary => {
      dataSummary = summary || {};
      if (dataSummary.updated_at) dataVersion = dataSummary.updated_at;
      renderDataUpdatedLabel();
      return Promise.all([
        fetchJson('places_of_worship_sa.geojson'),
        fetchJson('worship_gaps_sa.json'),
        fetchJson('sa_boundary.geojson'),
        // Best-effort: building footprint areas (calculate_mosque_sizes.py)
        fetchJson('mosque_sizes.json', false),
        // Best-effort: ML spatial anomaly detection (detect_geometry_anomalies.py)
        fetchJson('mosque_anomalies.json', false)
      ]);
    })
  .then(([poiData, gapData, boundaryData, sizeData, anomalyData]) => {
    // Store data in pending variables
    pendingPoiData = poiData;
    pendingGapData = gapData;
    pendingBoundaryData = boundaryData;
    pendingSizeData = sizeData;
    pendingAnomalyData = anomalyData;

    // Check if user is logged in via OSM OAuth; default directly to guest mode if not
    OsmApi.checkAuth().then(isAuthenticated => {
      isOsmAnonymized = !isAuthenticated;
      initializeDashboard(poiData, gapData, boundaryData, sizeData, anomalyData);
    });
  })
  .catch(error => {
    console.error('Error loading GeoJSON datasets:', error);
    showLoadingError(t('loadError'));
  });
}

export function initializeDashboard(poiData, gapData, boundaryData, sizeData, anomalyData) {
  allPlaces = poiData.features;
  // Merge in weekly-computed building footprint areas (calculate_mosque_sizes.py),
  // keyed by osm_id; features with no entry simply have no size data. The
  // too_small/too_large classification itself is computed dynamically in
  // getQualityIssues() against the user-adjustable currentSizeMinM2/MaxM2.
  // Both files are keyed by way id, so only ways may look them up (a relation
  // or node with the same numeric id is a different object).
  if (sizeData) {
    allPlaces.forEach(f => {
      if (f.properties.geom_type !== 'Polygon') return;
      const sizeInfo = sizeData[f.properties.osm_id];
      if (sizeInfo) {
        f.properties.size_area_m2 = sizeInfo.area_m2;
      }
    });
  }

  // Merge in ML geometry anomalies (Isolation Forest from detect_geometry_anomalies.py)
  if (anomalyData) {
    allPlaces.forEach(f => {
      if (f.properties.geom_type !== 'Polygon') return;
      const anomInfo = anomalyData[String(f.properties.osm_id)];
      if (anomInfo) {
        f.properties.ml_anomaly = anomInfo;
      }
    });
  }
  filteredPlaces = [...allPlaces];
  updateImprovementIssueCounts();

  allGaps = parseGapGrid(gapData);
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

  ReviewMarks.prune(allPlaces);
  ReviewMarks.sync().then(() => updateDashboardUI()).catch(() => {});

  // Initial display
  updateDashboardUI();
  hideLoadingOverlay();
  updateUserWidgetUI();
  Permalink.apply();
}

// Set the date-range slider bounds/values to the real data span and update their labels.
export function initDateSliders() {
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
export function hideLoadingOverlay() {
  const overlay = document.getElementById('loading-overlay');
  if (overlay) overlay.classList.add('hidden');
}

// Keep the overlay visible and show an inline error instead of a blocking alert().
export function showLoadingError(message) {
  const overlay = document.getElementById('loading-overlay');
  const text = document.getElementById('loading-text');
  if (overlay) overlay.classList.add('error');
  if (text) text.innerText = message;
}

// Switch display logic based on current zoom level
export function toggleLayersByZoom() {
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
export let GAP_GRID_SIZE_DEG = 0.004; // overridden by worship_gaps_sa.json's grid_size
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

// worship_gaps_sa.json stores one [gx, gy, road_length_m, gap_score] row per
// cell; a cell's position is implied by its grid index, so expand each row to
// a small object with the cell-centre coordinates used for viewport counts.
export function parseGapGrid(gapData) {
  if (gapData.grid_size) GAP_GRID_SIZE_DEG = gapData.grid_size;
  const g = GAP_GRID_SIZE_DEG;
  return (gapData.cells || []).map(cell => {
    const [gx, gy, roadLength, score, urgency] = cell;
    return {
      gx, gy,
      lat: (gy + 0.5) * g,
      lon: (gx + 0.5) * g,
      road_length_m: roadLength,
      gap_score: score,
      urgency_score: urgency !== undefined ? urgency : score
    };
  });
}

// Builds a sparse Map<"x,y", gap_score> from the gap grid's own cell
// coordinates, so interpolation always lines up with the real analysis grid
// regardless of zoom.
export function buildGapScoreLookup(gapCells) {
  const scoreByCell = new Map();
  let maxScore = 0;
  gapCells.forEach(c => {
    scoreByCell.set(c.gx + ',' + c.gy, c.gap_score);
    if (c.gap_score > maxScore) maxScore = c.gap_score;
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
export function buildSmoothedLookup(rawMap, rawMaxScore, radiusCells) {
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

export const GapGradientLayer = L.GridLayer.extend({
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
  // Cell (gx, gy) spans [gx*G, (gx+1)*G) (calculate_gaps.py uses int(lon/G)),
  // so its value sits at the cell centre: shift by half a cell before
  // interpolating, otherwise the whole field is offset ~220 m south-west.
  _interpolate: function (lon, lat) {
    const fx = lon / GAP_GRID_SIZE_DEG - 0.5;
    const fy = lat / GAP_GRID_SIZE_DEG - 0.5;
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

// One shared icon per marker class instead of a new divIcon per place.
export const MARKER_ICONS = {};
export function markerIcon(markerClass) {
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

// Display name in the UI language (the Arabic name when no name:en exists).
export function placeName(props) {
  return currentLang === 'en' ? props.name_en || props.name : props.name;
}

export function buildPlacePopup(props, mode) {
  if (mode === 'improve') {
    const issues = getIssues(props);
    return `
      <div style="font-family: var(--font-body); text-align: start; padding: 2px;">
        <h4 style="margin: 0 0 5px 0; font-size: 13px; font-weight: 700; color: #111;">${escapeHtml(placeName(props))}</h4>
        <span style="font-size: 10px; padding: 2px 6px; border-radius: 10px; background: rgba(255, 59, 48, 0.1); font-weight: 600; color: #ff3b30; border: 1px solid rgba(255, 59, 48, 0.2); display: inline-block; margin-top: 4px;">
          ${t('popupIssueCount', { n: fmtNum(issues.length) })}
        </span>
      </div>
    `;
  }
  return `
    <div style="font-family: var(--font-body); text-align: start; padding: 2px;">
      <h4 style="margin: 0 0 5px 0; font-size: 13px; font-weight: 700; color: #111;">${escapeHtml(placeName(props))}</h4>
      <p style="margin: 0 0 5px 0; font-size: 11px; color: #666;">${props.name_en !== props.name ? escapeHtml(currentLang === 'en' ? props.name : props.name_en) : ''}</p>
      <span style="font-size: 10px; padding: 2px 6px; border-radius: 10px; background: #eee; font-weight: 600; color: #333;">
        ${escapeHtml(religionLabel(props.religion))}
      </span>
    </div>
  `;
}

// Markers are built once per place and mode and then reused: filtering only
// changes which of them are handed to the cluster layer. Popup content is
// generated when opened, so issue counts always reflect current thresholds.
export function getPlaceMarker(f) {
  const mode = currentMode === 'improve' ? 'improve' : 'poi';
  f._markers = f._markers || {};
  if (f._markers[mode]) return f._markers[mode];

  const [lon, lat] = f.geometry.coordinates;
  const props = f.properties;
  let markerClass = 'unknown';
  if (mode === 'improve') {
    markerClass = 'improve';
  } else {
    if (props.religion === 'muslim') markerClass = 'muslim';
    if (props.religion === 'christian') markerClass = 'christian';
  }

  const marker = L.marker([lat, lon], { icon: markerIcon(markerClass) });
  marker.bindPopup(() => buildPlacePopup(props, mode), { closeButton: false });
  marker.on('click', () => {
    showDetails(props, lat, lon);
  });
  f._markers[mode] = marker;
  return marker;
}

// Re-generate Heatmap and Marker Clusters based on selected mode
export function updateMapLayers() {
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
      // Standard heatmap coordinates (lat, lon, weight)
      heatPoints.push([coords[1], coords[0], 1.0]);
      markers.push(getPlaceMarker(f));
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
export function showDetails(props, lat, lon) {
  selectedPlace = { properties: props, lat, lon };
  const panel = document.getElementById('details-panel');
  panel.style.display = 'block';
  renderReviewActions();
  renderQuickFixes(props);
  updatePermalinkSoon();

  // Ensure sidebar is expanded so user sees the details immediately
  setSidebarCollapsed(false);
  setTimeout(() => {
    panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }, 100);

  document.getElementById('details-name-ar').innerText = props.name || t('unnamed');
  document.getElementById('details-name-en').innerText = props.name_en || 'Unnamed';
  
  const relSpan = document.getElementById('details-religion');
  relSpan.innerText = religionLabel(props.religion);
  relSpan.style.color = RELIGION_COLORS[props.religion] || RELIGION_COLORS.unknown;
  
  document.getElementById('details-denom').innerText = props.denomination !== 'unknown' ? denomLabel(props.denomination) : t('unspecified');
  
  document.getElementById('details-city').innerText = props.addr_city || t('saudiArabia');
  const type = osmTypeOf(props);
  const isDev = OsmApi.environment() === 'dev';
  const osmBase = isDev ? 'https://master.apis.dev.openstreetmap.org' : 'https://www.openstreetmap.org';

  document.getElementById('details-coords').innerText = `${lat.toFixed(5)}, ${lon.toFixed(5)}`;
  // Merged places are a building outline plus the POI node inside it.
  document.getElementById('details-osm-id').innerText = `${type}/${props.osm_id}` +
    (props.poi_node_id ? ` + node/${props.poi_node_id}` : '');

  const userLink = document.getElementById('details-user');
  const changesetLink = document.getElementById('details-changeset');
  const mapperTools = document.getElementById('details-mapper-tools');
  const guestToolsNotice = document.getElementById('details-guest-tools-notice');

  if (isOsmAnonymized) {
    userLink.innerText = t('guestContributor');
    userLink.href = '#';
    userLink.style.pointerEvents = 'auto';
    userLink.style.opacity = '0.85';
    userLink.style.textDecoration = 'underline';
    userLink.style.cursor = 'pointer';
    userLink.onclick = (e) => {
      e.preventDefault();
      const authOverlay = document.getElementById('osm-auth-overlay');
      if (authOverlay) authOverlay.classList.remove('hidden');
    };

    document.getElementById('details-uid').innerText = t('hiddenGdpr');

    changesetLink.innerText = t('hiddenGdpr');
    changesetLink.href = '#';
    changesetLink.style.pointerEvents = 'none';
    changesetLink.style.opacity = '0.6';
    changesetLink.style.textDecoration = 'none';

    if (guestToolsNotice) guestToolsNotice.style.display = 'flex';
  } else {
    userLink.onclick = null;
    if (guestToolsNotice) guestToolsNotice.style.display = 'none';

    if (props.last_edited_by) {
      userLink.innerText = props.last_edited_by;
      userLink.href = `${osmBase}/user/${encodeURIComponent(props.last_edited_by)}`;
      userLink.style.pointerEvents = 'auto';
      userLink.style.opacity = '1';
      userLink.style.textDecoration = '';

      document.getElementById('details-uid').innerText = props.user_id ?? '-';

      changesetLink.innerText = props.changeset_id ?? '-';
      changesetLink.href = props.changeset_id ? `${osmBase}/changeset/${props.changeset_id}` : '#';
      changesetLink.style.pointerEvents = props.changeset_id ? 'auto' : 'none';
      changesetLink.style.opacity = '1';
      changesetLink.style.textDecoration = '';
    } else {
      userLink.innerText = '…';
      userLink.href = '#';
      userLink.style.pointerEvents = 'none';
      userLink.style.opacity = '0.6';
      userLink.style.textDecoration = 'none';

      document.getElementById('details-uid').innerText = '…';

      changesetLink.innerText = '…';
      changesetLink.href = '#';
      changesetLink.style.pointerEvents = 'none';
      changesetLink.style.opacity = '0.6';
      changesetLink.style.textDecoration = 'none';

      if (props.osm_id) {
        OsmApi.fetchLastEdit(type, props.osm_id, props.version).then(meta => {
          props.last_edited_by = meta.user;
          props.user_id = meta.uid;
          props.changeset_id = meta.changeset;
          // Guard: verify this place is still the currently selected one
          if (selectedPlace && selectedPlace.properties === props) {
            userLink.innerText = meta.user || t('anonymous');
            userLink.href = meta.user ? `${osmBase}/user/${encodeURIComponent(meta.user)}` : '#';
            userLink.style.pointerEvents = meta.user ? 'auto' : 'none';
            userLink.style.opacity = '1';
            userLink.style.textDecoration = '';

            document.getElementById('details-uid').innerText = meta.uid ?? '-';

            changesetLink.innerText = meta.changeset ?? '-';
            changesetLink.href = meta.changeset ? `${osmBase}/changeset/${meta.changeset}` : '#';
            changesetLink.style.pointerEvents = meta.changeset ? 'auto' : 'none';
            changesetLink.style.opacity = '1';
            changesetLink.style.textDecoration = '';
          }
        }).catch(() => {
          if (selectedPlace && selectedPlace.properties === props) {
            userLink.innerText = '-';
            document.getElementById('details-uid').innerText = '-';
            changesetLink.innerText = '-';
          }
        });
      } else {
        userLink.innerText = '-';
        document.getElementById('details-uid').innerText = '-';
        changesetLink.innerText = '-';
      }
    }
  }

  // Update mapper editing tools (always available in both guest and authenticated modes)
  if (mapperTools) mapperTools.style.display = 'block';

  const viewOsmBtn = document.getElementById('btn-view-osm');
  if (viewOsmBtn) {
    viewOsmBtn.href = props.osm_id
      ? `${osmBase}/${type}/${props.osm_id}`
      : `${osmBase}/#map=18/${lat.toFixed(5)}/${lon.toFixed(5)}`;
  }

  const editOsmBtn = document.getElementById('btn-edit-osm');
  if (editOsmBtn) {
    editOsmBtn.href = props.osm_id
      ? `${osmBase}/edit?editor=id&${type}=${props.osm_id}`
      : `${osmBase}/edit?editor=id#map=18/${lat.toFixed(5)}/${lon.toFixed(5)}`;
  }
  
  const josmBtn = document.getElementById('btn-edit-josm');
  if (josmBtn) {
    const newJosmBtn = josmBtn.cloneNode(true);
    josmBtn.parentNode.replaceChild(newJosmBtn, josmBtn);
    newJosmBtn.addEventListener('click', () => {
      editInJOSM(lat, lon, props);
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
    ? fmtDate(props.edited_at, true)
    : '-';

  // Update Qibla row in details table
  const qiblaRow = document.getElementById('row-details-qibla');
  const qiblaVal = document.getElementById('details-qibla');
  if (qiblaRow && qiblaVal) {
    if (props.ml_anomaly && typeof props.ml_anomaly.qibla_dev === 'number') {
      const dev = props.ml_anomaly.qibla_dev;
      const qAz = props.ml_anomaly.qibla_az;
      const bAz = props.ml_anomaly.bldg_az;
      let badgeColor = '#34c759';
      let badgeText = t('qiblaVeryAccurate');
      if (dev >= currentQiblaDevThreshold) {
        badgeColor = '#ff3b30';
        badgeText = t('qiblaSevere');
      } else if (dev > 10) {
        badgeColor = '#ff9500';
        badgeText = t('qiblaSlight');
      }
      qiblaVal.innerHTML = `
        <span style="display: inline-block; padding: 2px 7px; border-radius: 4px; font-weight: 700; font-size: 11px; background: ${badgeColor}20; color: ${badgeColor}; border: 1px solid ${badgeColor}40; margin-left: 6px;">
          ${dev}° (${badgeText})
        </span>
        <span style="font-size: 11px; color: #777;">${t('qiblaAxes', { q: qAz, b: bAz })}</span>
      `;
      qiblaRow.style.display = 'flex';
    } else {
      qiblaRow.style.display = 'none';
    }
  }

  // Update quality issues warning box
  const issues = getIssues(props);
  const issuesBox = document.getElementById('details-quality-issues');
  const issuesList = document.getElementById('details-issues-list');
  
  if (issues.length > 0) {
    issuesList.innerHTML = issues.map(i => `<li>${escapeHtml(currentLang === 'en' ? i.title_en : i.title_ar)}</li>`).join('');
    issuesBox.style.display = 'block';
  } else {
    issuesBox.style.display = 'none';
  }
}

// Update UI panel labels and counts depending on selected Mode
export function updateDashboardUI() {
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
  document.getElementById('export-section').style.display = currentMode === 'gap' ? 'none' : 'block';

  // The gap gradient interpolates from the analysis grid directly and has
  // no blob radius, unlike the POI/Improve leaflet.heat layers.
  radiusSliderContainer.style.display = (currentMode === 'gap') ? 'none' : 'block';

  if (currentMode === 'poi') {
    // Restore POI Mode controls
    totalCountLabel.innerText = t('labelTotalPlaces');
    visibleCountLabel.innerText = t('labelVisiblePlaces');
    searchSection.style.display = 'block';
    filterSection.style.display = 'block';
    improveFilterSection.style.display = 'none';
    dateFilterSection.style.display = 'block';
    gapInfoBox.style.display = 'none';
    gapJosmBox.style.display = 'none';
    const gapFilterBoxPoi = document.getElementById('gap-filter-box');
    if (gapFilterBoxPoi) gapFilterBoxPoi.style.display = 'none';
  } else if (currentMode === 'improve') {
    // Quality Improvement Mode controls
    totalCountLabel.innerText = t('labelTotalImprove');
    visibleCountLabel.innerText = t('labelVisibleImprove');
    searchSection.style.display = 'block';
    filterSection.style.display = 'none';
    improveFilterSection.style.display = 'block';
    dateFilterSection.style.display = 'block';
    gapInfoBox.style.display = 'none';
    gapJosmBox.style.display = 'none';
    const gapFilterBoxImp = document.getElementById('gap-filter-box');
    if (gapFilterBoxImp) gapFilterBoxImp.style.display = 'none';

    // Toggle sub-control visibility based on active improvement filter
    const sizeControls = document.getElementById('size-threshold-controls');
    const qiblaControls = document.getElementById('qibla-threshold-controls');
    if (sizeControls) {
      sizeControls.style.display = (currentImprovementFilter === 'size_too_small' || currentImprovementFilter === 'size_too_large' || currentImprovementFilter === 'all') ? 'block' : 'none';
    }
    if (qiblaControls) {
      qiblaControls.style.display = (currentImprovementFilter === 'qibla_deviation') ? 'block' : 'none';
    }
  } else {
    // Adjust layout for Gap Mode
    totalCountLabel.innerText = t('labelTotalGaps');
    visibleCountLabel.innerText = t('labelVisibleGaps');
    searchSection.style.display = 'none';
    filterSection.style.display = 'none';
    improveFilterSection.style.display = 'none';
    dateFilterSection.style.display = 'none'; // Gap grid cells have no edited_at metadata
    detailsPanel.style.display = 'none'; // Grid gaps do not have individual clickable POI cards
    gapInfoBox.style.display = 'flex';
    gapJosmBox.style.display = 'block';
    const gapFilterBox = document.getElementById('gap-filter-box');
    if (gapFilterBox) gapFilterBox.style.display = 'block';
    updateIdEditorAreaLink();
  }

  filterData();
}

// Calculate and update metrics matching filters and map bounds
export function updateStats() {
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
    filteredGaps.forEach(c => {
      if (bounds.contains([c.lat, c.lon])) {
        visibleCount++;
      }
    });
  }

  document.getElementById('total-count').innerText = fmtNum(totalCount);
  document.getElementById('visible-count').innerText = fmtNum(visibleCount);
}

// Combines search query and religion category filters (POI mode only)
// Rebuilds filteredPlaces and the map layers for the current mode (the single
// entry point for any change to filters, thresholds or mode).
export function filterData() {
  if (currentMode === 'gap') {
    if (currentGapUrgencyFilter === 'high_urgency') {
      filteredGaps = allGaps.filter(c => (c.urgency_score || 0) >= 50);
    } else {
      filteredGaps = [...allGaps];
    }
    updateMapLayers();
    updateStats();
    updateReviewNavUI();
    updatePermalinkSoon();
    return;
  }

  // Normalized so diacritics, alef/taa-marbuta variants and جامع/مسجد don't
  // matter ("الجامع الكبير" finds "المسجد الكبير").
  const searchInput = ArabicText.normalize(currentSearchQuery, true);

  filteredPlaces = allPlaces.filter(f => {
    const props = f.properties;

    // 1. Check search box keyword
    let matchesSearch = true;
    if (searchInput) {
      if (props._searchKey === undefined) {
        props._searchKey = ArabicText.normalize(
          [props.name, props.name_en, props.addr_city].filter(Boolean).join(' '), true
        ) + ' ' + props.osm_id + (props.poi_node_id ? ' ' + props.poi_node_id : '');
      }
      matchesSearch = props._searchKey.includes(searchInput);
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
      const issues = getIssues(props);
      if (issues.length === 0) return false;
      if (isHiddenByReview(props)) return false;

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

  // Sort filtered places if Qibla Deviation filter is active
  if (currentMode === 'improve' && currentImprovementFilter === 'qibla_deviation') {
    if (currentQiblaSort === 'least_accurate') {
      filteredPlaces.sort((a, b) => ((b.properties.ml_anomaly?.qibla_dev) || 0) - ((a.properties.ml_anomaly?.qibla_dev) || 0));
    } else if (currentQiblaSort === 'most_accurate') {
      filteredPlaces.sort((a, b) => ((a.properties.ml_anomaly?.qibla_dev) || 0) - ((b.properties.ml_anomaly?.qibla_dev) || 0));
    }
  }

  updateMapLayers();
  updateStats();
  rebuildReviewQueue();
  updatePermalinkSoon();
}

// Number of checks per category tab, derived from the issue buttons
// themselves so adding a check never leaves a stale hard-coded count.
export function updateCategoryTabCounts() {
  const improveItems = [...document.querySelectorAll('#improve-filters .improve-item')];
  document.querySelectorAll('.improve-category-tabs .category-tab').forEach(tab => {
    const category = tab.getAttribute('data-category');
    const n = category === 'all'
      ? improveItems.length
      : improveItems.filter(item => item.getAttribute('data-category') === category).length;
    const countEl = document.getElementById(`cat-count-${category}`);
    if (countEl) countEl.textContent = fmtNum(n);
  });
}

// Re-renders everything built in JavaScript after a language switch; static
// text is swapped by setLanguage() itself.
export function refreshLanguageDependentUI() {
  updateCategoryTabCounts();
  renderDataUpdatedLabel();
  updateUserWidgetUI();
  updateCartoBadgeStatus();
  if (!allPlaces.length) return; // data not loaded yet
  document.getElementById('date-from-val').innerText = formatDay(currentDateFrom);
  document.getElementById('date-to-val').innerText = formatDay(currentDateTo);
  updateImprovementIssueCounts();
  updateDashboardUI();
  if (selectedPlace) showDetails(selectedPlace.properties, selectedPlace.lat, selectedPlace.lon);
  if (suggestionsAllFeatures.length) {
    const named = suggestionsAllFeatures.filter(f => !f.properties.is_unnamed).length;
    const badge = document.getElementById('suggestions-badge');
    if (badge) badge.innerText = t('sugBadge', { n: fmtNum(suggestionsAllFeatures.length) });
    document.getElementById('sug-count-all').innerText = fmtNum(suggestionsAllFeatures.length);
    document.getElementById('sug-count-named').innerText = fmtNum(named);
    document.getElementById('sug-count-unnamed').innerText = fmtNum(suggestionsAllFeatures.length - named);
    updateSuggestionsViewportCount();
  }
}

// Wire up events for buttons, chips, search inputs, and range sliders
export function setupEventListeners() {
  // 1. Dashboard Mode Selector
  document.getElementById('mode-poi').addEventListener('click', (e) => {
    document.getElementById('mode-gap').classList.remove('active');
    document.getElementById('mode-improve').classList.remove('active');
    e.target.classList.add('active');
    currentMode = 'poi';
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
    updateImprovementIssueCounts();
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
      setBasemap(selectedBasemap);
    });
  });

  // Wire CARTO Basemap Key modal & status
  setupCartoModalEvents();
  updateCartoBadgeStatus();

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

  // Gap Urgency Filter Chips Selector
  const gapUrgencyChips = document.querySelectorAll('#gap-urgency-filters .chip');
  gapUrgencyChips.forEach(chip => {
    chip.addEventListener('click', () => {
      gapUrgencyChips.forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      currentGapUrgencyFilter = chip.getAttribute('data-gap-urgency');
      filterData();
    });
  });

  // Quality Improvement Filter Buttons Selector (Hero card + List Items)
  const allImproveButtons = document.querySelectorAll('[data-improve]');
  allImproveButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      allImproveButtons.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      
      currentImprovementFilter = btn.getAttribute('data-improve');
      filterData();

      // Toggle sub-control visibility based on active improvement filter
      const sizeControls = document.getElementById('size-threshold-controls');
      const qiblaControls = document.getElementById('qibla-threshold-controls');
      if (sizeControls) {
        sizeControls.style.display = (currentImprovementFilter === 'size_too_small' || currentImprovementFilter === 'size_too_large' || currentImprovementFilter === 'all') ? 'block' : 'none';
      }
      if (qiblaControls) {
        qiblaControls.style.display = (currentImprovementFilter === 'qibla_deviation') ? 'block' : 'none';
      }
    });
  });

  // Category Tabs filtering for Quality Issues
  const categoryTabs = document.querySelectorAll('.improve-category-tabs .category-tab');
  const improveItems = document.querySelectorAll('#improve-filters .improve-item');

  updateCategoryTabCounts();

  categoryTabs.forEach(tab => {
    tab.addEventListener('click', () => {
      categoryTabs.forEach(t => {
        t.classList.remove('active');
        t.setAttribute('aria-selected', 'false');
      });
      tab.classList.add('active');
      tab.setAttribute('aria-selected', 'true');

      const category = tab.getAttribute('data-category');
      improveItems.forEach(item => {
        if (category === 'all' || item.getAttribute('data-category') === category) {
          item.style.display = 'flex';
        } else {
          item.style.display = 'none';
        }
      });
    });
  });

  // Reset Improvement Filter Button (in header)
  const resetImproveBtn = document.getElementById('btn-reset-improve-filter');
  if (resetImproveBtn) {
    resetImproveBtn.addEventListener('click', () => {
      const heroBtn = document.getElementById('btn-improve-all');
      if (heroBtn) heroBtn.click();
      const allTab = document.querySelector('.improve-category-tabs .category-tab[data-category="all"]');
      if (allTab) allTab.click();
    });
  }

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
    invalidateIssues();

    updateImprovementIssueCounts();
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
    invalidateIssues();
    updateImprovementIssueCounts();
    filterData();
  });

  // Qibla Deviation Controls (Improvement Mode Only)
  const qiblaSlider = document.getElementById('qibla-dev-slider');
  const qiblaInput = document.getElementById('qibla-dev-input');
  const qiblaResetBtn = document.getElementById('btn-reset-qibla-threshold');
  const qiblaSortSelect = document.getElementById('qibla-sort-select');
  const debouncedQiblaFilter = debounce(filterData, 200);

  function applyQiblaThreshold(val) {
    const num = parseFloat(val);
    if (!isNaN(num) && num >= 1 && num <= 45) {
      currentQiblaDevThreshold = num;
      invalidateIssues();
      if (qiblaSlider) qiblaSlider.value = num;
      if (qiblaInput) qiblaInput.value = num;
      const label = document.getElementById('qibla-threshold-label');
      if (label) label.textContent = `≥ ${num}°`;
      updateImprovementIssueCounts();
      debouncedQiblaFilter();
    }
  }

  if (qiblaSlider) {
    qiblaSlider.addEventListener('input', (e) => applyQiblaThreshold(e.target.value));
  }
  if (qiblaInput) {
    qiblaInput.addEventListener('input', (e) => applyQiblaThreshold(e.target.value));
  }
  if (qiblaResetBtn) {
    qiblaResetBtn.addEventListener('click', () => {
      applyQiblaThreshold(QIBLA_DEV_DEFAULT);
    });
  }
  if (qiblaSortSelect) {
    qiblaSortSelect.addEventListener('change', (e) => {
      currentQiblaSort = e.target.value;
      filterData();
    });
  }

  // Review queue, marks and exports (js/review.js, js/exporters.js)
  document.getElementById('btn-review-prev').addEventListener('click', () => navigateReview(-1));
  document.getElementById('btn-review-next').addEventListener('click', () => navigateReview(1));
  document.getElementById('btn-review-fixed').addEventListener('click', () => markCurrentPlace('fixed'));
  document.getElementById('btn-review-skip').addEventListener('click', () => markCurrentPlace('skipped'));
  document.getElementById('btn-review-unmark').addEventListener('click', clearCurrentMark);
  document.getElementById('hide-reviewed-toggle').addEventListener('change', (e) => {
    setHideReviewedPlaces(e.target.checked);
    updateImprovementIssueCounts();
    filterData();
  });
  document.getElementById('viewport-counts-toggle').addEventListener('change', (e) => {
    viewportCountsOnly = e.target.checked;
    updateImprovementIssueCounts();
  });
  document.getElementById('btn-export-csv').addEventListener('click', () => Exporters.exportCsv());
  document.getElementById('btn-export-maproulette').addEventListener('click', () => Exporters.exportMapRoulette());
  document.getElementById('btn-export-josm').addEventListener('click', () => Exporters.loadVisibleInJosm());
  document.getElementById('btn-export-overpass').addEventListener('click', () => Exporters.openOverpassTurbo());

  const shortcutsOverlay = document.getElementById('shortcuts-overlay');
  document.getElementById('btn-shortcuts').addEventListener('click', () => shortcutsOverlay.classList.remove('hidden'));
  document.getElementById('btn-close-shortcuts').addEventListener('click', () => shortcutsOverlay.classList.add('hidden'));
  shortcutsOverlay.addEventListener('click', (e) => {
    if (e.target === shortcutsOverlay) shortcutsOverlay.classList.add('hidden');
  });

  // 3. Search Box keypress (POI Mode Only)
  // filterData() rebuilds every marker, so debounce to avoid per-keystroke lag on large datasets.
  const searchBox = document.getElementById('search-input');
  const debouncedFilter = debounce(() => {
    filterData();
    if (suggestionsLayer) {
      applySuggestionsFilter();
    }
  }, 250);
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
        OsmApi.logout();
      } else {
        const authOverlay = document.getElementById('osm-auth-overlay');
        if (authOverlay) {
          authOverlay.classList.remove('hidden');
        }
      }
    });
  }

  // Modal close handlers (close button, backdrop, Escape, guest notice link)
  const closeAuthModal = () => {
    const authOverlay = document.getElementById('osm-auth-overlay');
    if (authOverlay) {
      authOverlay.classList.add('hidden');
    }
  };

  const closeAuthBtn = document.getElementById('btn-close-auth-modal');
  if (closeAuthBtn) {
    closeAuthBtn.addEventListener('click', closeAuthModal);
  }

  const authOverlay = document.getElementById('osm-auth-overlay');
  if (authOverlay) {
    authOverlay.addEventListener('click', (e) => {
      if (e.target === authOverlay) {
        closeAuthModal();
      }
    });
  }

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      closeAuthModal();
      document.getElementById('shortcuts-overlay').classList.add('hidden');
    }
  });

  const guestLoginLink = document.getElementById('link-guest-login');
  if (guestLoginLink) {
    guestLoginLink.addEventListener('click', (e) => {
      e.preventDefault();
      const overlay = document.getElementById('osm-auth-overlay');
      if (overlay) {
        overlay.classList.remove('hidden');
      }
    });
  }

  // Handle skip/guest mode login button in modal
  const skipBtn = document.getElementById('btn-osm-skip');
  if (skipBtn) {
    skipBtn.addEventListener('click', () => {
      isOsmAnonymized = true;
      closeAuthModal();
      
      // Initialize dashboard if not yet loaded
      if (allPlaces.length === 0 && pendingPoiData && pendingGapData && pendingBoundaryData) {
        initializeDashboard(pendingPoiData, pendingGapData, pendingBoundaryData, pendingSizeData, pendingAnomalyData);
      }
    });
  }

  // Handle Redirect URI copy button
  const copyUriBtn = document.getElementById('btn-copy-redirect-uri');
  if (copyUriBtn) {
    copyUriBtn.addEventListener('click', () => {
      navigator.clipboard.writeText(OsmApi.redirectUri()).then(() => {
        // Find text label and swap momentarily
        const btnText = copyUriBtn.querySelector('span');
        const originalText = btnText.innerText;
        btnText.innerText = t('copied');
        showToast(t('redirectCopied'));
        setTimeout(() => {
          btnText.innerText = originalText;
        }, 2000);
      }).catch(err => {
        console.error('Failed to copy Redirect URI:', err);
        showToast(t('redirectCopyFailed'), 'error');
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
  if (envSelect) {
    envSelect.value = OsmApi.environment();
  }

  const clientIdInput = document.getElementById('osm-client-id');
  // Only a custom client ID is shown; empty means the built-in one.
  if (clientIdInput) {
    clientIdInput.value = localStorage.getItem('osm_oauth_client_id') || '';
  }

  const redirectUriDisplay = document.getElementById('osm-redirect-uri-display');
  if (redirectUriDisplay) {
    if (window.location.protocol === 'http:') {
      redirectUriDisplay.innerHTML = `${escapeHtml(OsmApi.redirectUri())} <span style="color:#ffb03a; font-size:11px; display:block; margin-top:3px;">⚠️ يتطلب OpenStreetMap بروتوكول HTTPS. شغّل: npm run dev</span>`;
    } else {
      redirectUriDisplay.innerText = OsmApi.redirectUri();
    }
  }

  // 7a. Suggested Additions (Wikidata mosques missing in OSM) Toggle & Chips
  const suggestionsToggle = document.getElementById('suggestions-toggle');
  if (suggestionsToggle) {
    suggestionsToggle.addEventListener('change', (e) => {
      setSuggestionsVisible(e.target.checked);
    });
  }

  const sugFilterChips = document.querySelectorAll('#suggestions-filter-chips .chip');
  sugFilterChips.forEach(chip => {
    chip.addEventListener('click', (e) => {
      sugFilterChips.forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      currentSuggestionFilter = chip.getAttribute('data-sug-filter') || 'all';
      applySuggestionsFilter();
    });
  });
}

// ==========================================
// OpenStreetMap Notes (create + view nearby)
// ==========================================

// Enables/disables click-to-place Add Note mode: toggles the map cursor and
// (re)loads existing nearby notes so users can see what's already reported
// before filing a duplicate.
export function setAddNoteMode(enabled) {
  addNoteMode = enabled;
  const mapEl = document.getElementById('map');
  if (mapEl) mapEl.classList.toggle('note-mode-active', enabled);

  if (enabled) {
    loadNearbyNotes();
  } else if (noteMarkersLayer) {
    noteMarkersLayer.clearLayers();
  }
}

export function handleMapClickForNotes(e) {
  if (!addNoteMode) return;
  openNoteComposer(e.latlng.lat, e.latlng.lng);
}

// Switches which preset's field group is shown in the composer and updates
// the chip selector's active state to match.
export function setActiveNotePreset(preset) {
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
export function openNoteComposer(lat, lon) {
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
    ? t('notePostedAs', { name: displayName })
    : t('notePostedAnon');

  overlay.classList.remove('hidden');
  textInput.focus();
}

export function closeNoteComposer() {
  const overlay = document.getElementById('note-composer-overlay');
  if (overlay) overlay.classList.add('hidden');
  pendingNoteLatLng = null;
}

// Assembles the final note body for whichever preset is active (or the free
// text box), then appends the site's signature footer to every submission -
// preset or free text alike - the same convention StreetComplete/MAPS.ME use.
// Returns null (after showing a toast) if a required field for the active
// preset is missing.
export function buildNoteText() {
  let body = '';

  if (activeNotePreset === 'worship') {
    const name = document.getElementById('note-worship-name').value.trim();
    const religion = document.getElementById('note-worship-religion').value.trim();
    const lines = [t('noteWorshipBody')];
    if (name) lines.push(t('noteNameLine', { v: name }));
    if (religion) lines.push(t('noteReligionLine', { v: religion }));
    body = lines.join('\n');
  } else if (activeNotePreset === 'fixme') {
    const fixme = document.getElementById('note-fixme-text').value.trim();
    if (!fixme) {
      showToast(t('noteFixmeRequired'), 'error');
      return null;
    }
    body = `fixme: ${fixme}`;
  } else if (activeNotePreset === 'gone') {
    const poiName = document.getElementById('note-gone-name').value.trim();
    const poiTypes = document.getElementById('note-gone-types').value.trim();
    if (!poiName) {
      showToast(t('noteGoneNameRequired'), 'error');
      return null;
    }
    const lines = [
      t('noteGoneBody'),
      `POI name: ${poiName}`
    ];
    if (poiTypes) lines.push(`POI types: ${poiTypes}`);
    lines.push(`OSM data version: ${new Date().toISOString()}`);
    body = lines.join('\n');
  } else {
    const textInput = document.getElementById('note-text-input');
    body = textInput ? textInput.value.trim() : '';
    if (!body) {
      showToast(t('noteTextRequired'), 'error');
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
export async function submitPendingOsmNote() {
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

    const url = `${OsmApi.urls().api}/api/0.6/notes.json?lat=${lat}&lon=${lon}&text=${encodeURIComponent(text)}`;
    const response = await fetch(url, { method: 'POST', headers });

    if (!response.ok) {
      const errText = await response.text();
      throw new Error(errText || `HTTP ${response.status}`);
    }

    const noteFeature = await response.json();
    renderNoteMarker(noteFeature);

    const noteId = noteFeature.properties ? noteFeature.properties.id : undefined;
    trackEvent('Note created', { signedIn: Boolean(headers['Authorization']) });
    showToast(t('noteSent'), 'success', {
      link: { href: `https://www.openstreetmap.org/note/${encodeURIComponent(noteId)}`, text: t('noteView') }
    });
    closeNoteComposer();
  } catch (err) {
    console.error('Failed to submit OSM note:', err);
    showToast(t('noteFailed', { msg: err.message }), 'error');
  } finally {
    if (submitBtn) submitBtn.disabled = false;
  }
}

// Renders a single note (GeoJSON Feature from the notes API) as a read-only
// marker with a popup showing its first comment and a link to the note on OSM.
export function renderNoteMarker(noteFeature) {
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
    <div style="font-family: var(--font-body); text-align: start; padding: 2px; max-width: 220px;">
      <p style="margin: 0 0 6px 0; font-size: 12px; color: #333; white-space: pre-wrap;">${escapeHtml(commentText)}</p>
      <a href="${noteUrl}" target="_blank" rel="noopener noreferrer" style="font-size: 11px;">${t('noteOpenOnOsm')}</a>
    </div>
  `, { closeButton: false });

  noteMarkersLayer.addLayer(marker);
}

// Fetches open (and recently-closed) notes within the current map view while
// Add Note mode is active, so users can see what's already reported instead
// of filing duplicates.
export async function loadNearbyNotes() {
  if (!addNoteMode || !map || !noteMarkersLayer) return;

  const bounds = map.getBounds();
  const bbox = `${bounds.getWest()},${bounds.getSouth()},${bounds.getEast()},${bounds.getNorth()}`;

  try {
    const response = await fetch(`${OsmApi.urls().api}/api/0.6/notes.json?bbox=${bbox}&limit=100&closed=7`);
    if (!response.ok) return;

    const data = await response.json();
    noteMarkersLayer.clearLayers();
    (data.features || []).forEach(renderNoteMarker);
  } catch (err) {
    console.error('Failed to load nearby OSM notes:', err);
  }
}

// ==========================================
// OpenStreetMap login (flow in js/osm_api.js)
// ==========================================

// Saves the advanced settings from the login dialog, then starts the PKCE flow.
export function redirectToOSM() {
  const envSelect = document.getElementById('osm-environment');
  if (envSelect) localStorage.setItem('osm_oauth_environment', envSelect.value);
  const clientId = document.getElementById('osm-client-id').value.trim();
  if (clientId) {
    localStorage.setItem('osm_oauth_client_id', clientId);
  } else {
    localStorage.removeItem('osm_oauth_client_id');
  }
  OsmApi.startLogin().then(started => {
    if (!started) document.querySelector('#osm-auth-overlay .auth-advanced')?.setAttribute('open', '');
  });
}

export function showLoadingText(message) {
  const overlay = document.getElementById('loading-overlay');
  const text = document.getElementById('loading-text');
  if (overlay) {
    overlay.classList.remove('hidden');
    overlay.classList.remove('error');
  }
  if (text) text.innerText = message;
}

export function updateUserWidgetUI() {
  const widget = document.getElementById('user-profile-widget');
  const nameEl = document.getElementById('user-display-name');
  const roleEl = widget ? widget.querySelector('.user-role-text') : null;
  const statusEl = widget ? widget.querySelector('.user-status-text') : null;
  const logoutBtn = document.getElementById('btn-osm-logout');
  
  const token = localStorage.getItem('osm_access_token');
  
  if (widget) {
    if (token) {
      const displayName = localStorage.getItem('osm_user_display_name') || t('osmUser');
      if (nameEl) nameEl.innerText = displayName;
      if (statusEl) statusEl.innerHTML = t('welcomeUser', { name: escapeHtml(displayName) });
      if (roleEl) roleEl.innerText = t('osmContributor');
      if (logoutBtn) {
        logoutBtn.innerText = t('logout');
        logoutBtn.className = 'osm-logout-btn';
        logoutBtn.title = t('logoutTitle');
      }
      widget.style.display = 'flex';
    } else if (isOsmAnonymized) {
      if (statusEl) statusEl.innerHTML = t('browsingAsGuest');
      if (roleEl) roleEl.innerText = t('guestRole');
      if (logoutBtn) {
        logoutBtn.innerText = t('login');
        logoutBtn.className = 'osm-login-btn-small';
        logoutBtn.title = t('loginTitle');
      }
      widget.style.display = 'flex';
    } else {
      widget.style.display = 'none';
    }
  }
}
