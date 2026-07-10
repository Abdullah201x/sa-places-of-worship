let map;
let heatmapLayer = null;
let markerClusterLayer = null;

// Datasets
let allPlaces = [];
let filteredPlaces = [];
let allGaps = [];
let filteredGaps = [];

// Filter States
let currentMode = 'poi'; // 'poi' or 'gap'
let currentReligionFilter = 'all';
let currentSearchQuery = '';

// Map configuration
const MAP_INITIAL_CENTER = [24.0, 45.0]; // Centered on Saudi Arabia
const MAP_INITIAL_ZOOM = 6;
const CLUSTER_MIN_ZOOM = 11; // Zoom level at which individual markers/clusters appear

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

document.addEventListener('DOMContentLoaded', () => {
  initMap();
  setupEventListeners();
  loadData();
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

  // CartoDB Dark Matter Base Tiles - High Contrast Dark Theme
  L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
    subdomains: 'abcd',
    maxZoom: 20
  }).addTo(map);

  // Initialize Marker Cluster Layer for POI mode
  markerClusterLayer = L.markerClusterGroup({
    showCoverageOnHover: false,
    maxClusterRadius: 50,
    iconCreateFunction: function (cluster) {
      const childCount = cluster.getChildCount();
      let c = ' rgba(0, 242, 254, ';
      
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
        html: `<div style="background-color: ${c}; width: ${size}px; height: ${size}px; border-radius: 50%; display: flex; align-items: center; justify-content: center; border: 1px solid var(--color-primary); box-shadow: 0 0 10px var(--color-primary); font-weight: bold; color: white;"><span>${childCount}</span></div>`,
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
}

// Load both Places of Worship and Coverage Gaps datasets in parallel
function loadData() {
  Promise.all([
    fetch('places_of_worship_sa.geojson').then(r => {
      if (!r.ok) throw new Error('Failed to load places of worship');
      return r.json();
    }),
    fetch('worship_gaps_sa.geojson').then(r => {
      if (!r.ok) throw new Error('Failed to load coverage gaps');
      return r.json();
    })
  ])
  .then(([poiData, gapData]) => {
    allPlaces = poiData.features;
    filteredPlaces = [...allPlaces];

    allGaps = gapData.features;
    filteredGaps = [...allGaps];

    // Initial display
    updateDashboardUI();
    hideLoadingOverlay();
  })
  .catch(error => {
    console.error('Error loading GeoJSON datasets:', error);
    showLoadingError('فشل في تحميل بيانات الخريطة. يرجى التأكد من تشغيل خادم محلي (مثل: python -m http.server) وفتح الصفحة عبر http://');
  });
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
  
  // Individual markers are only displayed in POI Density mode at high zoom levels
  if (currentMode === 'poi' && zoom >= CLUSTER_MIN_ZOOM) {
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

  if (currentMode === 'poi') {
    // === POI Density Mode ===
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
      let relClass = 'unknown';
      if (props.religion === 'muslim') relClass = 'muslim';
      if (props.religion === 'christian') relClass = 'christian';

      const customIcon = L.divIcon({
        html: '<div class="custom-marker-inner"></div>',
        className: `custom-marker ${relClass}`,
        iconSize: [12, 12],
        iconAnchor: [6, 6]
      });

      const marker = L.marker([lat, lon], { icon: customIcon });
      
      const popupContent = `
        <div style="font-family: var(--font-body); text-align: right; padding: 2px;">
          <h4 style="margin: 0 0 5px 0; font-size: 13px; font-weight: 700; color: #111;">${escapeHtml(props.name)}</h4>
          <p style="margin: 0 0 5px 0; font-size: 11px; color: #666; direction: ltr; text-align: right;">${props.name_en !== props.name ? escapeHtml(props.name_en) : ''}</p>
          <span style="font-size: 10px; padding: 2px 6px; border-radius: 10px; background: #eee; font-weight: 600; color: #333;">
            ${RELIGION_TRANSLATIONS[props.religion] || props.religion}
          </span>
        </div>
      `;
      marker.bindPopup(popupContent, { closeButton: false });

      marker.on('click', () => {
        showDetails(props, lat, lon);
      });

      markers.push(marker);
    });

    // Render standard cyan-green-red gradient heatmap
    heatmapLayer = L.heatLayer(heatPoints, {
      radius: radiusVal,
      blur: blurVal,
      maxZoom: 14,
      gradient: {
        0.2: '#00f2fe',  // Cyan
        0.4: '#4facfe',  // Sky Blue
        0.6: '#00ff87',  // Neon Green
        0.9: '#ffd700',  // Gold
        1.0: '#ff3b30'   // Hot Red
      }
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
}

// Update UI panel labels and counts depending on selected Mode
function updateDashboardUI() {
  const totalCountLabel = document.getElementById('total-count-label');
  const visibleCountLabel = document.getElementById('visible-count-label');
  const searchSection = document.getElementById('search-section');
  const filterSection = document.getElementById('filter-section');
  const detailsPanel = document.getElementById('details-panel');
  const gapInfoBox = document.getElementById('gap-info-box');

  if (currentMode === 'poi') {
    // Restore POI Mode controls
    totalCountLabel.innerText = "إجمالي الأماكن";
    visibleCountLabel.innerText = "في النطاق المرئي";
    searchSection.style.display = 'block';
    filterSection.style.display = 'block';
    gapInfoBox.style.display = 'none';
  } else {
    // Adjust layout for Gap Mode
    totalCountLabel.innerText = "الفجوات المكتشفة";
    visibleCountLabel.innerText = "الفجوات في النطاق";
    searchSection.style.display = 'none';
    filterSection.style.display = 'none';
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

  if (currentMode === 'poi') {
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
  if (currentMode !== 'poi') return;

  const searchInput = currentSearchQuery.toLowerCase().trim();
  
  filteredPlaces = allPlaces.filter(f => {
    const props = f.properties;
    
    // 1. Check religion filter
    // 'musalla' is a place_of_worship=musalla sub-tag (small prayer room), kept
    // as its own bucket rather than lumped into the main 'muslim' (mosque) chip.
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

    // 2. Check search box keyword
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

    return matchesReligion && matchesSearch;
  });

  updateMapLayers();
  updateStats();
}

// Wire up events for buttons, chips, search inputs, and range sliders
function setupEventListeners() {
  // 1. Dashboard Mode Selector
  document.getElementById('mode-poi').addEventListener('click', (e) => {
    document.getElementById('mode-gap').classList.remove('active');
    e.target.classList.add('active');
    currentMode = 'poi';
    updateDashboardUI();
  });

  document.getElementById('mode-gap').addEventListener('click', (e) => {
    document.getElementById('mode-poi').classList.remove('active');
    e.target.classList.add('active');
    currentMode = 'gap';
    updateDashboardUI();
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

  // 3. Search Box keypress (POI Mode Only)
  // filterData() rebuilds every marker, so debounce to avoid per-keystroke lag on large datasets.
  const searchBox = document.getElementById('search-input');
  const debouncedFilter = debounce(filterData, 250);
  searchBox.addEventListener('input', (e) => {
    currentSearchQuery = e.target.value;
    debouncedFilter();
  });

  // 4. Heatmap Radius Control
  const radiusSlider = document.getElementById('slider-radius');
  const radiusVal = document.getElementById('radius-val');
  radiusSlider.addEventListener('input', (e) => {
    const val = e.target.value;
    radiusVal.innerText = `${val}px`;
    if (heatmapLayer) {
      heatmapLayer.setOptions({ radius: parseInt(val, 10) });
    }
  });

  // 5. Heatmap Blur Control
  const blurSlider = document.getElementById('slider-blur');
  const blurVal = document.getElementById('blur-val');
  blurSlider.addEventListener('input', (e) => {
    const val = e.target.value;
    blurVal.innerText = `${val}px`;
    if (heatmapLayer) {
      heatmapLayer.setOptions({ blur: parseInt(val, 10) });
    }
  });
}
