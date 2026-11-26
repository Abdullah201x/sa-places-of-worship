// Data Hub & Open Data Catalog (/data)
import './styles/fonts.css';
import './styles/page.css';
import './styles/data.css';
import './translations_static.js';
import { currentLang, setLanguage, addTranslations, fmtNum } from './i18n.js';
import { initAnalytics } from './analytics.js';
import {
  formatBytes,
  buildOverpassTurboUrl,
  formatShaBadge,
  filterManifestFiles,
} from './data_view.js';

addTranslations({
  dataTitle: ['مركز البيانات المفتوحة والتحميل | منارة', 'Open Data Hub & Downloads | Manara'],
  dataHeroHeading: ['مركز البيانات الجغرافية المفتوحة', 'Open Geospatial Data Hub'],
  dataHeroSubtitle: [
    'حمّل بيانات بيوت العبادة وفجوات التغطية واقتراحات ويكي بيانات في المملكة العربية السعودية بصيغ متعددة مع قيم التحقق SHA-256.',
    'Download places of worship, coverage gaps, and Wikidata suggestions in Saudi Arabia across multiple formats with SHA-256 checksums.'
  ],
  licenseText: [
    'البيانات منشورة بموجب ترخيص قواعد البيانات المفتوحة (ODbL 1.0) وتنسب إلى مساهمي OpenStreetMap.',
    'Data published under the Open Database License (ODbL 1.0) and attributed to © OpenStreetMap contributors.'
  ],
  searchPlaceholder: ['ابحث بالاسم أو الطبقة أو المسار...', 'Search by name, layer, or filename...'],
  allLayers: ['جميع الطبقات', 'All Layers'],
  layerPlaces: ['بيوت العبادة (Places)', 'Places of Worship'],
  layerGaps: ['فجوات التغطية (Gaps)', 'Coverage Gaps'],
  layerSuggestions: ['اقتراحات ويكي بيانات', 'Wikidata Suggestions'],
  layerBoundary: ['الحدود والمناطق', 'Boundaries & Regions'],
  allFormats: ['جميع الصيغ', 'All Formats'],
  formatGeojson: ['GeoJSON', 'GeoJSON'],
  formatCsv: ['CSV (جداول)', 'CSV (Spreadsheet)'],
  formatPmtiles: ['PMTiles (متجهات)', 'PMTiles (Vector)'],
  colFilename: ['الملف والمعرف', 'File & ID'],
  colScope: ['النطاق', 'Scope'],
  colLayer: ['الطبقة', 'Layer'],
  colFormat: ['الصيغة', 'Format'],
  colRecords: ['السجلات', 'Records'],
  colSize: ['الحجم', 'Size'],
  colSha256: ['بصمة SHA-256', 'SHA-256 Checksum'],
  colDownload: ['تحميل', 'Download'],
  downloadBtn: ['تحميل مباشر', 'Download'],
  copiedSha: ['تم نسخ بصمة SHA-256 للحافظة!', 'SHA-256 checksum copied to clipboard!'],
  presetsTitle: ['استعلامات Overpass Turbo الجاهزة', 'Pre-configured Overpass Turbo Queries'],
  presetsSubtitle: [
    'استعلم مباشرة عن أحدث بيانات مساجد المملكة مباشرة من خوادم خريطة الشارع المفتوحة دون الحاجة لتحميل ملفات كبيرة.',
    'Query the live OpenStreetMap database directly for Saudi mosques without downloading full extracts.'
  ],
  runOverpassBtn: ['تشغيل في Overpass Turbo ↗', 'Run in Overpass Turbo ↗'],
  datasetVersionLbl: ['إصدار الحزمة الحالية:', 'Dataset Version:'],
  pbfDateLbl: ['تاريخ استخراج OSM:', 'OSM PBF Date:'],
});

let manifestData = null;
let activeFilters = { scope: 'all', layer: 'all', format: 'all', query: '' };

export async function loadManifest() {
  const tableBody = document.getElementById('data-table-body');
  if (!tableBody) return;

  try {
    const res = await fetch('/data/manifest.json');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    manifestData = await res.json();
    renderMetadata(manifestData);
    renderFilesTable();
    renderOverpassPresets(manifestData.overpass_presets || []);
  } catch (err) {
    tableBody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--color-danger); padding: 24px;">فشل في تحميل بيانات الفهرس (manifest.json)</td></tr>`;
  }
}

function renderMetadata(manifest) {
  const metaVer = document.getElementById('meta-dataset-version');
  const metaDate = document.getElementById('meta-pbf-date');
  if (metaVer) metaVer.textContent = manifest.dataset_version || '–';
  if (metaDate) metaDate.textContent = manifest.pbf_date || '–';
}

function renderFilesTable() {
  const tableBody = document.getElementById('data-table-body');
  if (!tableBody || !manifestData) return;

  const files = filterManifestFiles(manifestData.files || [], activeFilters);

  if (!files.length) {
    tableBody.innerHTML = `<tr><td colspan="8" style="text-align: center; color: var(--color-text-muted); padding: 32px;">لا توجد ملفات مطابقة للبحث</td></tr>`;
    return;
  }

  tableBody.innerHTML = files.map(f => {
    const formatClass = `format-${f.format.toLowerCase()}`;
    const shaShort = formatShaBadge(f.sha256);
    const sizeStr = formatBytes(f.bytes);
    const countStr = f.features != null ? fmtNum(f.features) : '–';
    const scopeStr = f.scope || 'SA';

    return `
      <tr>
        <td>
          <div style="font-weight: 600; color: var(--color-text);">${f.path}</div>
          <div style="font-size: 0.78rem; color: var(--color-text-muted); font-family: monospace;">${f.id}</div>
        </td>
        <td><span style="font-family: monospace; font-size: 0.85rem; font-weight: 600; padding: 2px 6px; border-radius: 4px; background: rgba(255,255,255,0.06);">${scopeStr}</span></td>
        <td><span style="text-transform: capitalize;">${f.layer}</span></td>
        <td><span class="file-format-badge ${formatClass}">${f.format}</span></td>
        <td>${countStr}</td>
        <td>${sizeStr}</td>
        <td>
          <button type="button" class="sha-badge-btn" data-sha="${f.sha256}" title="انقر لنسخ SHA-256 بالكامل">
            ${shaShort} 📋
          </button>
        </td>
        <td>
          <a href="/data/${f.path}" class="download-link-btn" download>
            ↓ تحميل
          </a>
        </td>
      </tr>
    `;
  }).join('');

  // Attach clipboard copy listeners
  tableBody.querySelectorAll('[data-sha]').forEach(btn => {
    btn.addEventListener('click', () => {
      const sha = btn.getAttribute('data-sha');
      if (sha && navigator.clipboard) {
        navigator.clipboard.writeText(sha);
        showToast(currentLang === 'ar' ? 'تم نسخ بصمة SHA-256 للحافظة!' : 'SHA-256 copied to clipboard!');
      }
    });
  });
}

function renderOverpassPresets(presets) {
  const container = document.getElementById('overpass-presets-grid');
  if (!container) return;

  const isAr = currentLang === 'ar';
  let customBbox = null;
  try {
    const urlParams = new URLSearchParams(window.location.search);
    customBbox = urlParams.get('bbox') || (typeof sessionStorage !== 'undefined' ? sessionStorage.getItem('manara_map_bbox') : null);
  } catch {
    // Ignore storage errors
  }

  container.innerHTML = presets.map(p => {
    const label = isAr ? (p.label.ar || p.label.en) : (p.label.en || p.label.ar);
    const overpassUrl = buildOverpassTurboUrl(p.query, customBbox);

    return `
      <div class="preset-card">
        <div>
          <h3>${label} ${customBbox ? `<span class="badge-scope" style="font-size: 11px; margin-inline-start: 8px; color: var(--color-primary);">${isAr ? '📍 النطاق المحدد' : '📍 Current Viewport'}</span>` : ''}</h3>
          <pre><code>${p.query}</code></pre>
        </div>
        <a href="${overpassUrl}" target="_blank" rel="noopener noreferrer" class="btn-overpass">
          ${isAr ? 'تشغيل في Overpass Turbo ↗' : 'Run in Overpass Turbo ↗'}
        </a>
      </div>
    `;
  }).join('');
}

function showToast(msg) {
  let toast = document.getElementById('copy-toast');
  if (!toast) {
    toast = document.createElement('div');
    toast.id = 'copy-toast';
    toast.className = 'copy-toast';
    document.body.appendChild(toast);
  }
  toast.textContent = msg;
  toast.classList.add('show');
  setTimeout(() => {
    toast.classList.remove('show');
  }, 2200);
}

// Wire Filter Controls
function setupFilters() {
  const searchInput = document.getElementById('data-search-input');
  const regionSelect = document.getElementById('filter-region');
  const layerSelect = document.getElementById('filter-layer');
  const formatSelect = document.getElementById('filter-format');

  searchInput?.addEventListener('input', (e) => {
    activeFilters.query = e.target.value;
    renderFilesTable();
  });

  regionSelect?.addEventListener('change', (e) => {
    activeFilters.scope = e.target.value;
    renderFilesTable();
  });

  layerSelect?.addEventListener('change', (e) => {
    activeFilters.layer = e.target.value;
    renderFilesTable();
  });

  formatSelect?.addEventListener('change', (e) => {
    activeFilters.format = e.target.value;
    renderFilesTable();
  });
}

// Language toggle hook
document.getElementById('btn-toggle-lang')?.addEventListener('click', () => {
  setLanguage(currentLang === 'ar' ? 'en' : 'ar');
  renderFilesTable();
  if (manifestData?.overpass_presets) {
    renderOverpassPresets(manifestData.overpass_presets);
  }
});

// Run Init
if (typeof document !== 'undefined' && document.getElementById('data-table-body')) {
  setLanguage(currentLang);
  setupFilters();
  loadManifest();
  initAnalytics();
}
