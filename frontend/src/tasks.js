// Task Tracker & Sprints Workspace (/tasks)
import './styles/fonts.css';
import './styles/page.css';
import './styles/tasks.css';
import './translations_static.js';
import { currentLang, setLanguage, addTranslations } from './i18n.js';
import { initAnalytics } from './analytics.js';
import { OsmApi } from './osm_api.js';
import { showToast } from './ui.js';
import { shortcutKey } from './keys.js';
import * as maplibregl from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?url';
import 'maplibre-gl/dist/maplibre-gl.css';
maplibregl.setWorkerUrl(workerUrl);
import {
  TILE_STATE_LABELS,
  generateIdEditorUrl,
  generateJosmRemoteUrl,
  findNextReadyTile,
  formatTileStateBadge,
  calculateSprintProgress,
} from './tasks_view.js';

// The demo sprint/tiles are a walkthrough aid only: never shown as if real data.
const DEMO_MODE = new URLSearchParams(window.location.search).get('demo') === '1';

export {
  TILE_STATE_LABELS,
  generateIdEditorUrl,
  generateJosmRemoteUrl,
  findNextReadyTile,
  formatTileStateBadge,
  calculateSprintProgress,
};

addTranslations({
  tasksTitle: ['حملات التخطيط والتحرير | منارة: خريطة بيوت الله', 'Mapping Sprints & Task Tracker | Manara'],
  heroTitle: ['حملات تحسين وتوثيق المساجد', 'Mosque Mapping Sprints & Task Tracker'],
  heroSubtitle: [
    'نسق جهود المجتمع الجغرافي عبر حملات مركزة ومقسمة إلى مربعات (Tiles)، مع إمكانية القفل، التحرير المباشر، والتحقق المتبادل.',
    'Coordinate community mapping via focused area sprints divided into tiles with locking, live editing, and peer validation.'
  ],
  btnNewSprint: ['+ إنشاء حملة جديدة (للمشرفين)', '+ New Sprint (Admin)'],
  activeSprintsHeading: ['الحملات الجارية والنشطة', 'Active Sprints'],
  noSprintsFound: ['لا توجد حملات نشطة حالياً. يمكنك للمشرفين إنشاء حملة جديدة.', 'No active sprints found. Admins can create a new sprint.'],
  openBoardBtn: ['فتح لوحة الحملة ←', 'Open Sprint Board ←'],
  backToSprints: ['← العودة إلى قائمة الحملات', '← Back to Sprints'],
  exportMapRoulette: ['تصدير كـ MapRoulette', 'Export MapRoulette'],
  totalTiles: ['إجمالي المربعات:', 'Total Tiles:'],
  completedTiles: ['المعتمدة:', 'Validated:'],
  remainingWorkload: ['العمل المتبقي:', 'Workload Left:'],
  tileInspectorTitle: ['المربع المحدد:', 'Selected Tile:'],
  tileState: ['الحالة:', 'State:'],
  tileWorkload: ['المساجد والملاحظات:', 'Issues / Workload:'],
  tileLock: ['القفل الحالي:', 'Current Lock:'],
  tileMapper: ['رُسم بواسطة:', 'Mapped by:'],
  tileValidator: ['اعتُمد بواسطة:', 'Validated by:'],
  lockMappingBtn: ['🔒 قفل للرسم (L)', '🔒 Lock for Mapping (L)'],
  lockValidationBtn: ['🔍 قفل للتحقق (L)', '🔍 Lock for Validation (L)'],
  markDoneBtn: ['✓ تم الانتهاء (D)', '✓ Mark Done (D)'],
  approveBtn: ['★ اعتماد المربع (A)', '★ Approve Tile (A)'],
  invalidateBtn: ['✕ طلب تصحيح (X)', '✕ Invalidate (X)'],
  releaseLockBtn: ['إلغاء القفل', 'Release Lock'],
  skipTileBtn: ['تخطي المربع (S)', 'Skip Tile (S)'],
  openInId: ['فتح في iD', 'Open in iD'],
  openInJosm: ['فتح في JOSM', 'Open in JOSM'],
  invalidateModalTitle: ['طلب تصحيح المربع', 'Invalidate Tile'],
  invalidateReasonPrompt: ['اذكر سبب الرفض أو النواقص التي تتطلب تصحيحاً:', 'State the reason or missing items requiring correction:'],
  btnCancel: ['إلغاء', 'Cancel'],
  btnConfirmInvalidate: ['تأكيد الرفض', 'Confirm Invalidation'],
  readyToLock: ['متاح للقفل والعمل', 'Available to lock'],
  noTileSelected: ['اختر مربعاً من اللوحة للبدء، أو اضغط N للمربع التالي', 'Select a tile from the grid or press N for next ready tile'],
  authNeededToast: ['يرجى تسجيل الدخول بحساب OpenStreetMap للقيام بهذا الإجراء.', 'Please sign in with OpenStreetMap to perform this action.'],
  authExpiredToast: ['انتهت جلستك، يرجى تسجيل الدخول مجدداً عبر OSM.', 'Session expired. Please log in again via OpenStreetMap.'],
  notFoundToast: ['المربع أو الحملة غير موجودة على الخادم.', 'Tile or sprint not found on server.'],
  conflictToast: ['تم تعديل المربع من قبل مستخدم آخر، سيتم تحديث اللوحة.', 'Conflict: Tile was modified by another user. Reloading...'],
  actionSuccessToast: ['تم تحديث حالة المربع بنجاح.', 'Tile status updated successfully.'],
  demoSuccessToast: ['تم تحديث حالة المربع محلياً (وضع العرض التوضيحي).', 'Tile status updated locally (Demo Mode).'],
});

let currentSprint = null;
let currentTiles = [];
let selectedTileId = null;
let currentRevMax = 0;
let pollInterval = null;
let mapInstance = null;
let mapInitializedForSlug = null;

// Names and sprint text come from OSM / the API, so escape them before innerHTML.
function escapeHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

const STATE_COLORS = {
  ready: { stroke: '#00f2fe', fill: '#00f2fe', fillOpacity: 0.22 },
  mapping: { stroke: '#f59e0b', fill: '#f59e0b', fillOpacity: 0.4 },
  mapped: { stroke: '#a855f7', fill: '#a855f7', fillOpacity: 0.4 },
  validating: { stroke: '#38bdf8', fill: '#38bdf8', fillOpacity: 0.45 },
  validated: { stroke: '#10b981', fill: '#10b981', fillOpacity: 0.45 },
  invalidated: { stroke: '#f43f5e', fill: '#f43f5e', fillOpacity: 0.4 },
  skipped: { stroke: '#64748b', fill: '#64748b', fillOpacity: 0.15 },
};

// ==========================================
// Initialization & Routing
// ==========================================
export function renderAuthWidget() {
  const container = document.getElementById('user-auth-widget');
  if (!container) return;
  const isAr = currentLang === 'ar';
  const token = OsmApi.token();
  const userName = escapeHtml(OsmApi.userName());

  if (token && userName) {
    container.innerHTML = `
      <div class="auth-user-badge" title="${isAr ? 'مسجل الدخول كـ' : 'Signed in as'} ${userName}">
        <span class="auth-user-name">👤 ${userName}</span>
        <button type="button" id="btn-tasks-logout" class="auth-logout-btn" title="${isAr ? 'تسجيل الخروج' : 'Log out'}">
          ${isAr ? 'خروج' : 'Logout'}
        </button>
      </div>
    `;
    document.getElementById('btn-tasks-logout')?.addEventListener('click', () => {
      OsmApi.logout(true);
    });
  } else {
    container.innerHTML = `
      <button type="button" id="btn-tasks-login" class="auth-login-btn">
        <span>${isAr ? 'دخول عبر OSM' : 'Sign in with OSM'}</span>
      </button>
    `;
    document.getElementById('btn-tasks-login')?.addEventListener('click', () => {
      OsmApi.startLogin();
    });
  }
}

export async function initTasksWorkspace() {
  renderAuthWidget();
  if (OsmApi.token() && !localStorage.getItem('osm_uid')) {
    OsmApi.checkAuth().catch(() => {});
  }

  const params = new URLSearchParams(window.location.search);
  const sprintSlug = params.get('sprint');

  setupViewControls();

  if (sprintSlug) {
    await loadSprintBoard(sprintSlug);
  } else {
    await loadSprintsList();
  }

  setupGlobalShortcuts();
}

// ==========================================

// ==========================================
// Map Controls & Leaflet Rendering
// ==========================================
function setupViewControls() {
  const btnMap = document.getElementById('btn-view-map');
  const btnSplit = document.getElementById('btn-view-split');
  const btnGrid = document.getElementById('btn-view-grid');
  const layout = document.getElementById('board-layout-container');
  const mapView = document.getElementById('board-map-view');
  const gridView = document.getElementById('board-grid-view');

  function setViewMode(mode) {
    [btnMap, btnSplit, btnGrid].forEach(b => b?.classList.remove('active'));

    if (mode === 'map') {
      btnMap?.classList.add('active');
      if (layout) {
        layout.classList.remove('view-mode-split');
        layout.classList.add('view-mode-map');
      }
      if (mapView) mapView.style.display = 'block';
      if (gridView) gridView.style.display = 'none';
    } else if (mode === 'split') {
      btnSplit?.classList.add('active');
      if (layout) {
        layout.classList.remove('view-mode-map');
        layout.classList.add('view-mode-split');
      }
      if (mapView) mapView.style.display = 'block';
      if (gridView) gridView.style.display = 'block';
    } else if (mode === 'grid') {
      btnGrid?.classList.add('active');
      if (layout) {
        layout.classList.remove('view-mode-split');
        layout.classList.remove('view-mode-map');
      }
      if (mapView) mapView.style.display = 'none';
      if (gridView) gridView.style.display = 'block';
    }

    setTimeout(() => {
      mapInstance?.resize();
    }, 100);
  }

  btnMap?.addEventListener('click', () => setViewMode('map'));
  btnSplit?.addEventListener('click', () => setViewMode('split'));
  btnGrid?.addEventListener('click', () => setViewMode('grid'));
}

const ESRI_IMAGERY_TILES = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';
const CARTO_LABEL_TILES = 'https://a.basemaps.cartocdn.com/rastertiles/voyager_only_labels/{z}/{x}/{y}.png';
const MAP_ATTRIBUTION = 'Tiles &copy; Esri, Maxar &mdash; &copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions" target="_blank" rel="noopener">CARTO</a>';

function tilesToGeoJson(tiles, selectedId) {
  const features = [];
  tiles.forEach(t => {
    if (!t.bbox || t.bbox.length !== 4) return;
    const [minLon, minLat, maxLon, maxLat] = t.bbox;
    const isSelected = t.tile_id === selectedId;
    const style = STATE_COLORS[t.state] || STATE_COLORS.ready;
    features.push({
      type: 'Feature',
      id: t.tile_id,
      geometry: {
        type: 'Polygon',
        coordinates: [[
          [minLon, minLat],
          [maxLon, minLat],
          [maxLon, maxLat],
          [minLon, maxLat],
          [minLon, minLat],
        ]]
      },
      properties: {
        tile_id: t.tile_id,
        state: t.state,
        workload: t.workload || 0,
        isSelected: isSelected ? 1 : 0,
        fillColor: style.fill,
        fillOpacity: isSelected ? 0.65 : style.fillOpacity,
        strokeColor: isSelected ? '#ffffff' : style.stroke,
        strokeWidth: isSelected ? 3.5 : 1.5,
      }
    });
  });
  return { type: 'FeatureCollection', features };
}

let tileHoverPopup = null;

export function initOrUpdateSprintMap(tiles) {
  const mapContainer = document.getElementById('sprint-leaflet-map');
  if (!mapContainer || !tiles || !tiles.length) return;

  const geojson = tilesToGeoJson(tiles, selectedTileId);

  if (!mapInstance) {
    mapInstance = new maplibregl.Map({
      container: 'sprint-leaflet-map',
      style: {
        version: 8,
        sources: {
          satellite: {
            type: 'raster',
            tiles: [ESRI_IMAGERY_TILES],
            tileSize: 256,
            maxzoom: 19,
            attribution: MAP_ATTRIBUTION,
          },
          labels: {
            type: 'raster',
            tiles: [CARTO_LABEL_TILES],
            tileSize: 256,
            maxzoom: 19,
          },
          sprint_tiles: {
            type: 'geojson',
            data: geojson,
          }
        },
        layers: [
          { id: 'satellite-layer', type: 'raster', source: 'satellite' },
          { id: 'labels-layer', type: 'raster', source: 'labels' },
          {
            id: 'tiles-fill-layer',
            type: 'fill',
            source: 'sprint_tiles',
            paint: {
              'fill-color': ['get', 'fillColor'],
              'fill-opacity': ['get', 'fillOpacity'],
            }
          },
          {
            id: 'tiles-line-layer',
            type: 'line',
            source: 'sprint_tiles',
            paint: {
              'line-color': ['get', 'strokeColor'],
              'line-width': ['get', 'strokeWidth'],
            }
          }
        ]
      },
      center: [45.0, 24.0],
      zoom: 11,
      maxZoom: 19,
    });

    mapInstance.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-left');

    tileHoverPopup = new maplibregl.Popup({
      closeButton: false,
      closeOnClick: false,
      className: 'sprint-tile-tooltip'
    });

    mapInstance.on('mousemove', 'tiles-fill-layer', (e) => {
      const f = e.features && e.features[0];
      if (!f) return;
      mapInstance.getCanvas().style.cursor = 'pointer';
      const props = f.properties;
      const isAr = currentLang === 'ar';
      const stateLbl = isAr ? TILE_STATE_LABELS[props.state]?.ar : TILE_STATE_LABELS[props.state]?.en;
      tileHoverPopup
        .setLngLat(e.lngLat)
        .setHTML(`<strong>Tile: ${props.tile_id}</strong><br/>${isAr ? 'الحالة' : 'State'}: ${stateLbl}<br/>${isAr ? 'الأعمال' : 'Workload'}: ${props.workload || 0}`)
        .addTo(mapInstance);
    });

    mapInstance.on('mouseleave', 'tiles-fill-layer', () => {
      mapInstance.getCanvas().style.cursor = '';
      tileHoverPopup.remove();
    });

    mapInstance.on('click', 'tiles-fill-layer', (e) => {
      const f = e.features && e.features[0];
      if (!f) return;
      const tId = f.properties.tile_id;
      selectedTileId = tId;
      document.querySelectorAll('.tile-cell').forEach(c => {
        c.classList.toggle('selected', c.dataset.tileId === tId);
      });
      const t = currentTiles.find(x => x.tile_id === tId);
      if (t) renderInspector(t);
      highlightMapTile(tId);
    });
  } else {
    const src = mapInstance.getSource('sprint_tiles');
    if (src) src.setData(geojson);
  }

  // Fit bounds when loading a new sprint
  const minLons = tiles.map(t => t.bbox[0]);
  const minLats = tiles.map(t => t.bbox[1]);
  const maxLons = tiles.map(t => t.bbox[2]);
  const maxLats = tiles.map(t => t.bbox[3]);
  const minX = Math.min(...minLons);
  const minY = Math.min(...minLats);
  const maxX = Math.max(...maxLons);
  const maxY = Math.max(...maxLats);

  if (mapInitializedForSlug !== currentSprint?.slug) {
    mapInitializedForSlug = currentSprint?.slug;
    const fit = () => {
      mapInstance.fitBounds([[minX, minY], [maxX, maxY]], { padding: 30, maxZoom: 15 });
    };
    if (mapInstance.loaded()) fit();
    else mapInstance.once('load', fit);
  }

  setTimeout(() => {
    mapInstance?.resize();
  }, 120);
}

export function highlightMapTile(tileId) {
  if (!mapInstance || !currentTiles.length) return;
  const src = mapInstance.getSource('sprint_tiles');
  if (src) {
    src.setData(tilesToGeoJson(currentTiles, tileId));
  }
  const tile = currentTiles.find(t => t.tile_id === tileId);
  if (tile && tile.bbox) {
    const cLon = (tile.bbox[0] + tile.bbox[2]) / 2;
    const cLat = (tile.bbox[1] + tile.bbox[3]) / 2;
    mapInstance.easeTo({ center: [cLon, cLat], duration: 500 });
  }
}

// 1. Sprints List View
// ==========================================
async function loadSprintsList() {
  const container = document.getElementById('sprints-list-view');
  const boardContainer = document.getElementById('sprint-board-view');
  if (container) container.style.display = 'block';
  if (boardContainer) boardContainer.style.display = 'none';

  const grid = document.getElementById('sprints-grid');
  if (!grid) return;

  grid.innerHTML = `<p style="color: var(--color-text-muted);">Loading sprints...</p>`;

  let sprints = [];
  try {
    const res = await fetch('/api/v1/sprints?status=all');
    if (res.ok) {
      sprints = await res.json();
    }
  } catch (err) {
    console.warn('Failed to fetch sprints from API:', err);
  }

  // Demo sprint only with ?demo=1
  if (DEMO_MODE && (!sprints || sprints.length === 0)) {
    sprints = [
      {
        id: 1,
        slug: 'al-kharj-mosques-2026',
        _isDemo: true,
        title: { ar: 'حملة استكمال مساجد الخرج', en: 'Al-Kharj Mosques Mapping Sprint' },
        instructions: {
          ar: 'إضافة وتدقيق جميع المساجد والمصليات في محافظة الخرج مع الأسماء الإنجليزية ورسم حدود المباني.',
          en: 'Map and review all places of worship in Al-Kharj governorate with English transliteration and building outlines.'
        },
        hashtag: '#manara-kharj-2026',
        status: 'active',
        progress: {
          total: 120,
          by_state: { ready: 45, mapping: 5, mapped: 18, validating: 2, validated: 45, invalidated: 3, skipped: 2 },
          workload_remaining: 52,
          percent_complete: 37.5
        }
      }
    ];
  }

  renderSprintsGrid(sprints, grid);
}

function renderSprintsGrid(sprints, grid) {
  grid.innerHTML = '';
  const isAr = currentLang === 'ar';

  sprints.forEach(s => {
    const card = document.createElement('article');
    card.className = 'sprint-card';

    const title = isAr ? (s.title?.ar || s.title?.en) : (s.title?.en || s.title?.ar);
    const prog = s.progress || { total: 0, by_state: {}, percent_complete: 0, workload_remaining: 0 };
    const total = prog.total || 1;
    const validated = prog.by_state?.validated || 0;
    const mapped = prog.by_state?.mapped || 0;
    const mapping = prog.by_state?.mapping || 0;

    const valPct = ((validated / total) * 100).toFixed(1);
    const mapPct = ((mapped / total) * 100).toFixed(1);
    const inProgPct = ((mapping / total) * 100).toFixed(1);

    card.innerHTML = `
      <div>
        <div class="sprint-card-header">
          <span class="sprint-status-pill ${s.status}">${s.status}</span>
          <span class="sprint-hashtag">${escapeHtml(s.hashtag)}</span>
        </div>
        <h3 class="sprint-card-title">${escapeHtml(title)}</h3>
        <p style="color: var(--color-text-muted); font-size: 0.88rem; margin: 6px 0 14px;">
          ${escapeHtml(isAr ? (s.instructions?.ar || s.instructions?.en || '') : (s.instructions?.en || s.instructions?.ar || ''))}
        </p>

        <div class="sprint-progress-bar-wrap" title="${valPct}% validated">
          <div class="progress-segment validated" style="width: ${valPct}%;"></div>
          <div class="progress-segment mapped" style="width: ${mapPct}%;"></div>
          <div class="progress-segment mapping" style="width: ${inProgPct}%;"></div>
        </div>

        <div class="sprint-stats-summary">
          <span>${valPct}% ${isAr ? 'مكتمل' : 'Complete'}</span>
          <span>${prog.workload_remaining} ${isAr ? 'عمل متبقي' : 'work left'}</span>
          <span>${total} ${isAr ? 'مربع' : 'tiles'}</span>
        </div>
      </div>

      <a href="/tasks?sprint=${s.slug}" class="btn-open-sprint">
        ${isAr ? 'فتح لوحة الحملة ←' : 'Open Sprint Board ←'}
      </a>
    `;

    grid.appendChild(card);
  });
}

// ==========================================
// 2. Sprint Board View
// ==========================================
async function loadSprintBoard(slug) {
  const listView = document.getElementById('sprints-list-view');
  const boardView = document.getElementById('sprint-board-view');
  if (listView) listView.style.display = 'none';
  if (boardView) boardView.style.display = 'block';

  try {
    const res = await fetch(`/api/v1/sprints/${slug}`);
    if (res.ok) {
      currentSprint = await res.json();
    }
  } catch (err) {
    console.warn('Failed to load sprint details:', err);
  }

  if (!currentSprint && !DEMO_MODE) {
    showToast(currentLang === 'ar' ? 'تعذر تحميل الحملة.' : 'Could not load this sprint.', 'error');
    return;
  }
  // Demo sprint only with ?demo=1
  if (!currentSprint) {
    currentSprint = {
      id: 1,
      slug,
      _isDemo: true,
      title: { ar: 'حملة استكمال مساجد الخرج', en: 'Al-Kharj Mosques Mapping Sprint' },
      hashtag: `#manara-${slug}`,
      status: 'active'
    };
  }

  renderBoardHeader();
  await fetchBoardTiles(slug);
  startPolling(slug);
}

function renderBoardHeader() {
  const isAr = currentLang === 'ar';
  const titleEl = document.getElementById('board-sprint-title');
  const tagEl = document.getElementById('board-sprint-hashtag');
  const exportBtn = document.getElementById('btn-export-maproulette');
  const demoBanner = document.getElementById('demo-mode-banner');

  if (titleEl) titleEl.textContent = isAr ? (currentSprint.title?.ar || currentSprint.title?.en) : (currentSprint.title?.en || currentSprint.title?.ar);
  if (tagEl) tagEl.textContent = currentSprint.hashtag;

  if (demoBanner) {
    if (currentSprint?._isDemo) {
      demoBanner.style.display = 'flex';
      demoBanner.textContent = isAr
        ? 'ℹ️ وضع العرض التوضيحي: هذه الحملة تجريبية لاستكشاف النظام. التعديلات والقفل تجري محلياً في المتصفح.'
        : 'ℹ️ Demo Preview Mode: This sprint is for exploration. Locking and status transitions are simulated locally in your browser.';
    } else {
      demoBanner.style.display = 'none';
    }
  }

  if (exportBtn) {
    exportBtn.href = `/api/v1/sprints/${currentSprint.slug}/maproulette`;
  }
}

async function fetchBoardTiles(slug) {
  if (currentSprint?._isDemo) {
    currentTiles = generateDemoTiles();
    renderTileGrid(currentTiles);
    updateBoardProgressStats(currentTiles);
    initOrUpdateSprintMap(currentTiles);
    return;
  }
  try {
    const headers = {};
    if (currentRevMax) {
      headers['If-None-Match'] = `W/"${currentRevMax}"`;
    }

    const res = await fetch(`/api/v1/sprints/${slug}/tiles`, { headers });
    if (res.status === 304) {
      // Tiles unchanged
      return;
    }
    if (res.ok) {
      const data = await res.json();
      currentRevMax = data.rev_max;
      currentTiles = data.tiles || [];
      renderTileGrid(currentTiles);
      updateBoardProgressStats(currentTiles);
      initOrUpdateSprintMap(currentTiles);
      if (selectedTileId) {
        const found = currentTiles.find(t => t.tile_id === selectedTileId);
        if (found) renderInspector(found);
      }
    }
  } catch (err) {
    console.warn('Failed to fetch sprint tiles:', err);
  }

  // Demo tiles only with ?demo=1
  if (DEMO_MODE && (!currentTiles || currentTiles.length === 0)) {
    currentTiles = generateDemoTiles();
    renderTileGrid(currentTiles);
    updateBoardProgressStats(currentTiles);
    initOrUpdateSprintMap(currentTiles);
  }
}

function generateDemoTiles() {
  const demo = [];
  const states = ['ready', 'ready', 'mapping', 'mapped', 'validating', 'validated', 'validated', 'skipped'];
  for (let x = 0; x < 6; x++) {
    for (let y = 0; y < 5; y++) {
      const st = states[(x + y) % states.length];
      const tx = 2330 + x;
      const ty = 1225 + y;
      demo.push({
        tile_id: `${tx}:${ty}`,
        bbox: [round6(tx * 0.02), round6(ty * 0.02), round6((tx + 1) * 0.02), round6((ty + 1) * 0.02)],
        state: st,
        rev: 1,
        workload: st === 'validated' || st === 'skipped' ? 0 : ((x * 2 + y) % 7) + 1,
        mapped_by: st === 'mapped' || st === 'validated' ? 1001 : null,
        lock: st === 'mapping' ? { display_name: 'mapper_ali', expires_at: new Date(Date.now() + 3600000).toISOString() } : null
      });
    }
  }
  return demo;
}

function round6(val) {
  return Math.round(val * 1000000) / 1000000;
}

function updateBoardProgressStats(tiles) {
  const total = tiles.length;
  const validated = tiles.filter(t => t.state === 'validated').length;
  const workload = tiles.reduce((acc, t) => acc + (t.state !== 'validated' && t.state !== 'skipped' ? (t.workload || 0) : 0), 0);
  const pct = total > 0 ? ((validated / total) * 100).toFixed(1) : 0;

  const totalEl = document.getElementById('stat-total-tiles');
  const valEl = document.getElementById('stat-validated-tiles');
  const workEl = document.getElementById('stat-workload-tiles');
  const pctEl = document.getElementById('stat-pct-tiles');

  if (totalEl) totalEl.textContent = total.toString();
  if (valEl) valEl.textContent = validated.toString();
  if (workEl) workEl.textContent = workload.toString();
  if (pctEl) pctEl.textContent = `${pct}%`;
}

function renderTileGrid(tiles) {
  const container = document.getElementById('tile-grid-matrix');
  if (!container) return;

  container.innerHTML = '';
  tiles.forEach(t => {
    const isSelected = t.tile_id === selectedTileId;
    const cell = document.createElement('div');
    cell.className = `tile-cell ${t.state} ${isSelected ? 'selected' : ''}`;
    cell.dataset.tileId = t.tile_id;
    cell.setAttribute('role', 'button');
    cell.setAttribute('tabindex', '0');
    cell.setAttribute('aria-pressed', isSelected ? 'true' : 'false');
    cell.setAttribute('aria-label', `Tile ${t.tile_id}, state ${t.state}, workload ${t.workload || 0}`);
    cell.title = `Tile: ${t.tile_id} (${t.state})`;

    cell.innerHTML = `
      <span>${t.tile_id}</span>
      <span class="tile-workload-badge">${t.workload || 0}</span>
    `;

    const selectTile = () => {
      document.querySelectorAll('.tile-cell').forEach(c => {
        c.classList.remove('selected');
        c.setAttribute('aria-pressed', 'false');
      });
      cell.classList.add('selected');
      cell.setAttribute('aria-pressed', 'true');
      selectedTileId = t.tile_id;
      renderInspector(t);
      highlightMapTile(t.tile_id);
    };

    cell.addEventListener('click', selectTile);
    cell.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        selectTile();
      }
    });

    container.appendChild(cell);
  });
}

function renderInspector(tile) {
  const panel = document.getElementById('board-inspector-body');
  if (!panel) return;

  const isAr = currentLang === 'ar';
  const stateLabel = isAr ? TILE_STATE_LABELS[tile.state]?.ar : TILE_STATE_LABELS[tile.state]?.en;
  const currentUserUid = OsmApi.uid();
  const isOwnMapped = Boolean(currentUserUid && tile.mapped_by && currentUserUid === tile.mapped_by);

  let lockText = isAr ? 'متاح للقفل والعمل' : 'Available to lock';
  if (tile.lock) {
    lockText = `@${escapeHtml(tile.lock.display_name || 'user')}`;
  }

  let actionButtonsHtml = '';

  if (tile.state === 'ready' || tile.state === 'invalidated') {
    actionButtonsHtml = `
      <button type="button" class="tile-action-btn primary" id="btn-action-lock-mapping">
        ${isAr ? '🔒 قفل للرسم (L)' : '🔒 Lock for Mapping (L)'}
      </button>
    `;
  } else if (tile.state === 'mapping') {
    actionButtonsHtml = `
      <button type="button" class="tile-action-btn success" id="btn-action-done">
        ${isAr ? '✓ تم الانتهاء من الرسم (D)' : '✓ Mark Done (D)'}
      </button>
      <button type="button" class="tile-action-btn secondary" id="btn-action-release">
        ${isAr ? 'إلغاء القفل' : 'Release Lock'}
      </button>
    `;
  } else if (tile.state === 'mapped') {
    if (isOwnMapped) {
      actionButtonsHtml = `
        <div class="tile-notice" style="font-size: 0.82rem; color: var(--color-text-muted); padding: 8px; background: rgba(255,255,255,0.05); border-radius: 6px;">
          ${isAr ? '⚠️ لا يمكنك التحقق من مربع رسمته بنفسك. التحقق يتطلب مراجعاً آخر.' : '⚠️ You mapped this tile. Peer validation is required.'}
        </div>
      `;
    } else {
      actionButtonsHtml = `
        <button type="button" class="tile-action-btn primary" id="btn-action-lock-validation">
          ${isAr ? '🔍 قفل للتحقق (L)' : '🔍 Lock for Validation (L)'}
        </button>
        <button type="button" class="tile-action-btn success" id="btn-action-approve">
          ${isAr ? '★ اعتماد المربع (A)' : '★ Approve (A)'}
        </button>
        <button type="button" class="tile-action-btn danger" id="btn-action-invalidate">
          ${isAr ? '✕ طلب تصحيح (X)' : '✕ Invalidate (X)'}
        </button>
      `;
    }
  } else if (tile.state === 'validating') {
    actionButtonsHtml = `
      <button type="button" class="tile-action-btn success" id="btn-action-approve">
        ${isAr ? '★ اعتماد المربع (A)' : '★ Approve (A)'}
      </button>
      <button type="button" class="tile-action-btn danger" id="btn-action-invalidate">
        ${isAr ? '✕ طلب تصحيح (X)' : '✕ Invalidate (X)'}
      </button>
      <button type="button" class="tile-action-btn secondary" id="btn-action-release">
        ${isAr ? 'إلغاء القفل' : 'Release Lock'}
      </button>
    `;
  }

  // External Editor Links
  const idUrl = generateIdEditorUrl(tile.bbox, currentSprint.title?.en || currentSprint.title?.ar, currentSprint.hashtag);
  const josmUrl = generateJosmRemoteUrl(tile.bbox, currentSprint.title?.en || currentSprint.title?.ar, currentSprint.hashtag);

  panel.innerHTML = `
    <div class="inspector-header">
      <h3 class="inspector-title">M-${tile.tile_id}</h3>
      <span class="inspector-state-pill ${tile.state}">${stateLabel}</span>
    </div>

    <div class="inspector-details">
      <div class="detail-row">
        <span class="detail-lbl">${isAr ? 'الأعمال المطلوبة:' : 'Pending Work:'}</span>
        <span class="detail-val">${tile.workload || 0} ${isAr ? 'ملاحظة' : 'issues'}</span>
      </div>
      <div class="detail-row">
        <span class="detail-lbl">${isAr ? 'القفل:' : 'Lock:'}</span>
        <span class="detail-val">${lockText}</span>
      </div>
      <div class="detail-row">
        <span class="detail-lbl">${isAr ? 'الإصدار (Rev):' : 'Revision:'}</span>
        <span class="detail-val">${tile.rev || 1}</span>
      </div>
    </div>

    <div class="external-tools-box">
      <a href="${idUrl}" target="_blank" rel="noopener noreferrer" class="external-tool-btn">
        ✏️ ${isAr ? 'فتح في iD' : 'Open in iD'}
      </a>
      <button type="button" class="external-tool-btn" id="btn-josm-remote">
        ⚡ ${isAr ? 'فتح في JOSM' : 'Open in JOSM'}
      </button>
    </div>

    <div class="inspector-actions-group">
      ${actionButtonsHtml}
      ${tile.state !== 'skipped' && tile.state !== 'validated' ? `
        <button type="button" class="tile-action-btn secondary" id="btn-action-skip">
          ${isAr ? 'تخطي المربع (S)' : 'Skip Tile (S)'}
        </button>
      ` : ''}
    </div>
  `;

  // Bind JOSM remote click
  document.getElementById('btn-josm-remote')?.addEventListener('click', async () => {
    try {
      await fetch(josmUrl, { mode: 'no-cors' });
      showToast(isAr ? 'تم إرسال الأمر إلى JOSM بنجاح.' : 'Sent command to JOSM.', 'success');
    } catch (err) {
      console.warn('JOSM Remote Control call failed:', err);
      showToast(
        isAr ? 'تعذر الاتصال بـ JOSM عبر المنفذ 8111. تأكد من تشغيل البرنامج وتفعيل Remote Control.' : 'Could not reach JOSM on port 8111. Ensure JOSM is running with Remote Control enabled.',
        'error'
      );
    }
  });

  // Action listeners
  document.getElementById('btn-action-lock-mapping')?.addEventListener('click', () => executeTileAction(tile, 'lock', { kind: 'mapping' }));
  document.getElementById('btn-action-lock-validation')?.addEventListener('click', () => executeTileAction(tile, 'lock', { kind: 'validation' }));
  document.getElementById('btn-action-done')?.addEventListener('click', () => executeTileAction(tile, 'done'));
  document.getElementById('btn-action-approve')?.addEventListener('click', () => executeTileAction(tile, 'approve'));
  document.getElementById('btn-action-release')?.addEventListener('click', () => executeTileAction(tile, 'release'));
  document.getElementById('btn-action-skip')?.addEventListener('click', () => executeTileAction(tile, 'skip'));
  document.getElementById('btn-action-invalidate')?.addEventListener('click', () => openInvalidateModal(tile));
}

// ==========================================
// 3. Tile Transitions & API Calls
// ==========================================
async function executeTileAction(tile, action, extraBody = {}) {
  const isAr = currentLang === 'ar';

  // Demo simulation mode
  if (currentSprint?._isDemo) {
    const updated = { ...tile };
    const myUid = OsmApi.uid() || 1001;
    const myName = OsmApi.userName() || 'demo_mapper';

    if (action === 'lock') {
      const lockKind = extraBody.kind || (tile.state === 'mapped' ? 'validation' : 'mapping');
      updated.state = lockKind === 'mapping' ? 'mapping' : 'validating';
      updated.lock = { osm_uid: myUid, display_name: myName, kind: lockKind, expires_at: new Date(Date.now() + 7200000).toISOString() };
      updated.rev = (tile.rev || 1) + 1;
    } else if (action === 'release') {
      updated.state = tile.state === 'mapping' ? 'ready' : 'mapped';
      updated.lock = null;
      updated.rev = (tile.rev || 1) + 1;
    } else if (action === 'done') {
      updated.state = 'mapped';
      updated.mapped_by = myUid;
      updated.lock = null;
      updated.rev = (tile.rev || 1) + 1;
    } else if (action === 'approve') {
      updated.state = 'validated';
      updated.validated_by = myUid;
      updated.lock = null;
      updated.rev = (tile.rev || 1) + 1;
    } else if (action === 'invalidate') {
      updated.state = 'invalidated';
      updated.skip_reason = extraBody.reason;
      updated.lock = null;
      updated.rev = (tile.rev || 1) + 1;
    } else if (action === 'skip') {
      updated.state = 'skipped';
      updated.skip_reason = extraBody.reason || 'skipped';
      updated.lock = null;
      updated.rev = (tile.rev || 1) + 1;
    }

    const idx = currentTiles.findIndex(t => t.tile_id === updated.tile_id);
    if (idx !== -1) {
      currentTiles[idx] = updated;
    }
    renderTileGrid(currentTiles);
    updateBoardProgressStats(currentTiles);
    initOrUpdateSprintMap(currentTiles);
    renderInspector(updated);
    showToast(isAr ? 'تم تحديث حالة المربع محلياً (وضع العرض التوضيحي).' : 'Tile status updated locally (Demo Mode).', 'success');
    return;
  }

  // Real sprint: Check auth first
  if (!OsmApi.token()) {
    showToast(
      isAr ? 'يرجى تسجيل الدخول بحساب OpenStreetMap للقيام بهذا الإجراء.' : 'Please sign in with OpenStreetMap to perform this action.',
      'warning'
    );
    return;
  }

  try {
    const res = await fetch(`/api/v1/sprints/${currentSprint.slug}/tiles/${tile.tile_id}`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        'X-Manara-CSRF': '1',
        'If-Match': `"${tile.rev}"`
      },
      body: JSON.stringify({
        action,
        rev: tile.rev,
        ...extraBody
      })
    });

    if (res.status === 401) {
      showToast(
        isAr ? 'انتهت جلستك، يرجى تسجيل الدخول مجدداً عبر OSM.' : 'Session expired. Please log in again via OpenStreetMap.',
        'warning'
      );
      return;
    }

    if (res.status === 404) {
      showToast(
        isAr ? 'المربع أو الحملة غير موجودة على الخادم.' : 'Tile or sprint not found on server.',
        'error'
      );
      return;
    }

    if (res.status === 409) {
      showToast(
        isAr ? 'تم تعديل المربع من قبل مستخدم آخر، سيتم تحديث اللوحة.' : 'Conflict: Tile was modified by another user. Reloading...',
        'warning'
      );
      await fetchBoardTiles(currentSprint.slug);
      return;
    }

    if (res.status === 403) {
      const errData = await res.json().catch(() => ({}));
      showToast(
        errData.detail || (isAr ? 'غير مصرح بهذا الإجراء (مثال: لا يمكن التحقق من تعديلاتك الذاتية).' : 'Forbidden action (e.g. self-validation is not allowed).'),
        'error'
      );
      return;
    }

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      showToast(errData.detail || (isAr ? 'حدث خطأ أثناء تنفيذ الإجراء.' : 'Failed to execute action.'), 'error');
      return;
    }

    const updated = await res.json();
    const idx = currentTiles.findIndex(t => t.tile_id === updated.tile_id);
    if (idx !== -1) {
      currentTiles[idx] = updated;
    }
    renderTileGrid(currentTiles);
    updateBoardProgressStats(currentTiles);
    initOrUpdateSprintMap(currentTiles);
    renderInspector(updated);
    showToast(isAr ? 'تم تحديث حالة المربع بنجاح.' : 'Tile status updated successfully.', 'success');
  } catch (err) {
    console.warn('Tile action API call error:', err);
    showToast(isAr ? 'تعذر الاتصال بالخادم.' : 'Could not reach server.', 'error');
  }
}

function openInvalidateModal(tile) {
  const modal = document.getElementById('invalidate-modal');
  const textarea = document.getElementById('invalidate-reason-input');
  const confirmBtn = document.getElementById('btn-confirm-invalidate');
  const cancelBtn = document.getElementById('btn-cancel-invalidate');

  if (!modal || !textarea || !confirmBtn) return;
  modal.style.display = 'flex';
  textarea.value = '';
  textarea.focus();

  const handleConfirm = () => {
    const reason = textarea.value.trim();
    if (!reason) {
      showToast(currentLang === 'ar' ? 'يرجى ذكر سبب الرفض أو النواقص المطلوبة.' : 'Please provide a reason for invalidation.', 'warning');
      return;
    }
    modal.style.display = 'none';
    cleanup();
    executeTileAction(tile, 'invalidate', { reason });
  };

  const handleCancel = () => {
    modal.style.display = 'none';
    cleanup();
  };

  function cleanup() {
    confirmBtn.removeEventListener('click', handleConfirm);
    cancelBtn.removeEventListener('click', handleCancel);
  }

  confirmBtn.addEventListener('click', handleConfirm);
  cancelBtn?.addEventListener('click', handleCancel);
}

// ==========================================
// 4. Polling & Keyboard Shortcuts
// ==========================================
function startPolling(slug) {
  if (pollInterval) clearInterval(pollInterval);
  pollInterval = setInterval(() => {
    fetchBoardTiles(slug);
  }, 60000); // 60s background polling
}

function setupGlobalShortcuts() {
  window.addEventListener('keydown', (e) => {
    // Never hijack browser/OS shortcuts (Ctrl+A, Ctrl+L, Cmd+D ...).
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (['input', 'textarea'].includes(document.activeElement?.tagName?.toLowerCase())) {
      return;
    }

    const key = shortcutKey(e);

    if (key === 'n') {
      const nextTile = findNextReadyTile(currentTiles);
      if (nextTile) {
        selectedTileId = nextTile.tile_id;
        renderTileGrid(currentTiles);
        renderInspector(nextTile);
        highlightMapTile(nextTile.tile_id);
      }
    } else if (key === 'Escape') {
      const modal = document.getElementById('invalidate-modal');
      if (modal && modal.style.display === 'flex') {
        modal.style.display = 'none';
      }
    } else if (selectedTileId) {
      const tile = currentTiles.find(t => t.tile_id === selectedTileId);
      if (!tile) return;

      if (key === 'l' && (tile.state === 'ready' || tile.state === 'invalidated' || tile.state === 'mapped')) {
        executeTileAction(tile, 'lock', { kind: tile.state === 'mapped' ? 'validation' : 'mapping' });
      } else if (key === 'd' && tile.state === 'mapping') {
        executeTileAction(tile, 'done');
      } else if (key === 'a' && (tile.state === 'validating' || tile.state === 'mapped')) {
        executeTileAction(tile, 'approve');
      } else if (key === 'x' && (tile.state === 'validating' || tile.state === 'mapped')) {
        openInvalidateModal(tile);
      } else if (key === 's' && (tile.state === 'ready' || tile.state === 'mapping')) {
        executeTileAction(tile, 'skip');
      }
    }
  });
}

// Language toggle hook
document.getElementById('btn-toggle-lang')?.addEventListener('click', () => {
  setLanguage(currentLang === 'ar' ? 'en' : 'ar');
  renderAuthWidget();
  if (currentSprint) {
    renderBoardHeader();
    renderTileGrid(currentTiles);
    updateBoardProgressStats(currentTiles);
    initOrUpdateSprintMap(currentTiles);
    if (selectedTileId) {
      const tile = currentTiles.find(t => t.tile_id === selectedTileId);
      if (tile) renderInspector(tile);
    }
  } else {
    loadSprintsList();
  }
});

// Run Init
if (typeof document !== 'undefined' && document.getElementById('sprints-list-view')) {
  setLanguage(currentLang);
  initTasksWorkspace();
  initAnalytics();
}
