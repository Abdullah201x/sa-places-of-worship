let map;
let heatmapLayer = null;
let markerClusterLayer = null;
let basemaps = {};
let currentBasemap = null;

// OSM OAuth 2.0 State Variables
let OSM_CLIENT_ID = localStorage.getItem('osm_oauth_client_id') || '';
// Automatically resolve Redirect URI based on the current window location (without parameters)
const OSM_REDIRECT_URI = window.location.origin + window.location.pathname;
const OSM_AUTH_URL = 'https://www.openstreetmap.org/oauth2/authorize';
const OSM_TOKEN_URL = 'https://www.openstreetmap.org/oauth2/token';
const OSM_USER_DETAILS_URL = 'https://api.openstreetmap.org/api/0.6/user/details.json';

// Temporary storage for loaded data if auth is pending
let pendingPoiData = null;
let pendingGapData = null;
let pendingBoundaryData = null;

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
  
  // 5. Missing wheelchair accessibility tag
  if (!props.wheelchair || props.wheelchair === 'unknown') {
    issues.push({
      id: 'missing_wheelchair',
      title_ar: 'معلومات الوصول للكراسي المتحركة مفقودة (wheelchair=*)',
      title_en: 'Wheelchair accessibility info is missing'
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

document.addEventListener('DOMContentLoaded', () => {
  initMap();
  setupEventListeners();
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
      maxZoom: 19
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
  map.on('zoomend', () => {
    debouncedUpdateStats();
    toggleLayersByZoom(); // layer swap must stay immediate
  });

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
    })
  ])
  .then(([poiData, gapData, boundaryData]) => {
    // Detect if this is an internal OSM extract containing contributor metadata
    const isInternalExtract = poiData.features.some(f => f.properties && (f.properties.last_edited_by || f.properties.user_id));
    
    if (isInternalExtract) {
      // Store data in pending variables in case we need to authenticate first
      pendingPoiData = poiData;
      pendingGapData = gapData;
      pendingBoundaryData = boundaryData;
      
      checkAuthStatus().then(isAuthenticated => {
        if (isAuthenticated) {
          // User is authorized, initialize dashboard
          initializeDashboard(poiData, gapData, boundaryData);
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
      initializeDashboard(poiData, gapData, boundaryData);
    }
  })
  .catch(error => {
    console.error('Error loading GeoJSON datasets:', error);
    showLoadingError('فشل في تحميل بيانات الخريطة. يرجى التأكد من تشغيل خادم محلي (مثل: python -m http.server) وفتح الصفحة عبر http://');
  });
}

function initializeDashboard(poiData, gapData, boundaryData) {
  allPlaces = poiData.features;
  filteredPlaces = [...allPlaces];

  allGaps = gapData.features;
  filteredGaps = [...allGaps];

  // Reconfigure Esri Satellite as a BoundaryCanvas layer restricted to the Saudi Arabia boundary
  if (boundaryData && boundaryData.geometry) {
    basemaps['satellite'] = L.TileLayer.boundaryCanvas('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
      boundary: boundaryData.geometry,
      attribution: 'Tiles &copy; Esri &mdash; Source: Esri, i-cubed, USDA, USGS, AEX, GeoEye, Getmapping, Aerogrid, IGN, IGP, UPR-EGP, and the GIS User Community',
      maxZoom: 19,
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
    // === Coverage Gaps Mode (Negative Heatmap) ===
    const gapPoints = [];

    filteredGaps.forEach(f => {
      const coords = f.geometry.coordinates;
      const lon = coords[0];
      const lat = coords[1];
      const score = f.properties.gap_score;
      
      // Feed coordinates and the calculated gap score (intensity)
      // Dividing by 4.0 normalizes the intensity spread of log counts
      gapPoints.push([lat, lon, score / 4.0]);
    });

    // Render high-contrast negative heatmap (magenta-violet-orange-red warning colors)
    heatmapLayer = L.heatLayer(gapPoints, {
      radius: radiusVal + 5, // Slightly larger spread for gaps to reveal general underserved corridors
      blur: blurVal,
      maxZoom: 14,
      gradient: {
        0.2: '#3f2b96',  // Deep Indigo
        0.5: '#a8c0ff',  // Soft Lilac
        0.8: '#ec008c',  // Neon Magenta (High gap)
        1.0: '#fc6767'   // Flame Orange/Red (Extreme coverage gap)
      }
    }).addTo(map);

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
  userLink.innerText = props.last_edited_by || 'مجهول';
  userLink.href = props.last_edited_by ? `https://www.openstreetmap.org/user/${encodeURIComponent(props.last_edited_by)}` : '#';

  document.getElementById('details-uid').innerText = props.user_id ?? '-';

  const changesetLink = document.getElementById('details-changeset');
  changesetLink.innerText = props.changeset_id ?? '-';
  changesetLink.href = props.changeset_id ? `https://www.openstreetmap.org/changeset/${props.changeset_id}` : '#';

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
  
  document.getElementById('details-mapper-tools').style.display = 'block';
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

  if (currentMode === 'poi') {
    // Restore POI Mode controls
    totalCountLabel.innerText = "إجمالي الأماكن";
    visibleCountLabel.innerText = "في النطاق المرئي";
    searchSection.style.display = 'block';
    filterSection.style.display = 'block';
    improveFilterSection.style.display = 'none';
    dateFilterSection.style.display = 'block';
    gapInfoBox.style.display = 'none';
  } else if (currentMode === 'improve') {
    // Quality Improvement Mode controls
    totalCountLabel.innerText = "أماكن تحتاج تحسين";
    visibleCountLabel.innerText = "تحتاج تحسين بالنطاق";
    searchSection.style.display = 'block';
    filterSection.style.display = 'none';
    improveFilterSection.style.display = 'block';
    dateFilterSection.style.display = 'block';
    gapInfoBox.style.display = 'none';
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

  // 5. Heatmap Radius Control
  const radiusSlider = document.getElementById('slider-radius');
  const radiusVal = document.getElementById('radius-val');
  radiusSlider.addEventListener('input', (e) => {
    const val = e.target.value;
    radiusVal.innerText = `${val}px`;
    if (heatmapLayer) {
      heatmapLayer.setOptions({ radius: parseInt(val, 10) });
    }
  });

  // 6. Heatmap Blur Control
  const blurSlider = document.getElementById('slider-blur');
  const blurVal = document.getElementById('blur-val');
  blurSlider.addEventListener('input', (e) => {
    const val = e.target.value;
    blurVal.innerText = `${val}px`;
    if (heatmapLayer) {
      heatmapLayer.setOptions({ blur: parseInt(val, 10) });
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

  // 8. OSM OAuth 2.0 Auth Controls
  const loginBtn = document.getElementById('btn-osm-login');
  if (loginBtn) {
    loginBtn.addEventListener('click', redirectToOSM);
  }
  


  const logoutBtn = document.getElementById('btn-osm-logout');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', logoutOSM);
  }

  // Pre-fill the Client ID input if already saved
  const clientIdInput = document.getElementById('osm-client-id');
  if (clientIdInput && OSM_CLIENT_ID) {
    clientIdInput.value = OSM_CLIENT_ID;
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
  const clientIdInput = document.getElementById('osm-client-id').value.trim();
  if (!clientIdInput) {
    showToast('الرجاء إدخال معرّف العميل (Client ID) للاستمرار.', 'error');
    return;
  }
  
  OSM_CLIENT_ID = clientIdInput;
  localStorage.setItem('osm_oauth_client_id', OSM_CLIENT_ID);
  
  const codeVerifier = generateRandomString(64);
  sessionStorage.setItem('osm_oauth_code_verifier', codeVerifier);
  
  const codeChallenge = await generateChallenge(codeVerifier);
  const state = generateRandomString(16);
  sessionStorage.setItem('osm_oauth_state', state);
  
  const url = `${OSM_AUTH_URL}?response_type=code` +
              `&client_id=${OSM_CLIENT_ID}` +
              `&redirect_uri=${encodeURIComponent(OSM_REDIRECT_URI)}` +
              `&scope=read_prefs` +
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
    // Save saved client ID back to state in case page reloads
    OSM_CLIENT_ID = localStorage.getItem('osm_oauth_client_id') || '';
    
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
      const response = await fetch(OSM_TOKEN_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded'
        },
        body: new URLSearchParams({
          client_id: OSM_CLIENT_ID,
          grant_type: 'authorization_code',
          code: code,
          redirect_uri: OSM_REDIRECT_URI,
          code_verifier: codeVerifier
        })
      });
      
      if (!response.ok) {
        const errText = await response.text();
        throw new Error(`Token exchange failed: ${errText}`);
      }
      
      const data = await response.json();
      if (data.access_token) {
        localStorage.setItem('osm_access_token', data.access_token);
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
  
  const token = localStorage.getItem('osm_access_token');
  
  if (token) {
    const displayName = localStorage.getItem('osm_user_display_name') || 'مستخدم OSM';
    if (nameEl) nameEl.innerText = displayName;
    if (widget) widget.style.display = 'flex';
  } else {
    if (widget) widget.style.display = 'none';
  }
}

function logoutOSM() {
  localStorage.removeItem('osm_access_token');
  localStorage.removeItem('osm_user_display_name');
  showToast('تم تسجيل الخروج بنجاح.');
  window.location.reload();
}
