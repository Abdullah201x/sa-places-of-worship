// Command Palette (Ctrl+K or /)
// Unified instant discovery & command palette across regions, QA rules, places, and actions.
import { ArabicText } from './arabic.js';
import { currentLang } from './i18n.js';

export const REGIONS = [
  { code: 'SA-01', name_ar: 'منطقة الرياض', name_en: 'Riyadh Region', center: [24.7136, 46.6753], zoom: 11 },
  { code: 'SA-02', name_ar: 'منطقة مكة المكرمة', name_en: 'Makkah Region', center: [21.3891, 39.8579], zoom: 12 },
  { code: 'SA-03', name_ar: 'منطقة المدينة المنورة', name_en: 'Madinah Region', center: [24.5247, 39.5692], zoom: 12 },
  { code: 'SA-04', name_ar: 'المنطقة الشرقية', name_en: 'Eastern Province', center: [26.4207, 50.0888], zoom: 11 },
  { code: 'SA-05', name_ar: 'منطقة القصيم', name_en: 'Al-Qassim Region', center: [26.3260, 43.9750], zoom: 11 },
  { code: 'SA-06', name_ar: 'منطقة حائل', name_en: "Ha'il Region", center: [27.5114, 41.7208], zoom: 11 },
  { code: 'SA-07', name_ar: 'منطقة تبوك', name_en: 'Tabuk Region', center: [28.3835, 36.5662], zoom: 11 },
  { code: 'SA-08', name_ar: 'منطقة الحدود الشمالية', name_en: 'Northern Borders Region', center: [30.9753, 41.0381], zoom: 11 },
  { code: 'SA-09', name_ar: 'منطقة جازان', name_en: 'Jazan Region', center: [16.8892, 42.5706], zoom: 11 },
  { code: 'SA-10', name_ar: 'منطقة نجران', name_en: 'Najran Region', center: [17.5656, 44.2289], zoom: 11 },
  { code: 'SA-11', name_ar: 'منطقة الباحة', name_en: 'Al-Bahah Region', center: [20.0129, 41.4677], zoom: 11 },
  { code: 'SA-12', name_ar: 'منطقة الجوف', name_en: 'Al-Jawf Region', center: [29.9539, 40.1970], zoom: 11 },
  { code: 'SA-14', name_ar: 'منطقة عسير', name_en: "'Asir Region", center: [18.2164, 42.5053], zoom: 11 },
];

export const QA_RULES = [
  { id: 'missing_name_en', name_ar: 'الاسم بالإنجليزي مفقود أو مطابق للعربي', name_en: 'Missing English Name (name:en)', badge: 'QA' },
  { id: 'missing_denom', name_ar: 'المذهب غير محدد (سني/شيعي)', name_en: 'Missing Denomination', badge: 'QA' },
  { id: 'qibla_deviation', name_ar: 'انحراف حاد عن القبلة (≥ 20°)', name_en: 'Severe Qibla Deviation', badge: 'QA' },
  { id: 'ml_geometry_anomaly', name_ar: 'شذوذ هندسي (ذكاء اصطناعي)', name_en: 'ML Geometry Anomaly', badge: 'QA' },
  { id: 'building_yes', name_ar: 'مسجد مصنف building=yes', name_en: 'Mosque tagged building=yes', badge: 'QA' },
  { id: 'missing_amenity', name_ar: 'مبنى مسجد بدون وسم amenity', name_en: 'Building missing amenity tag', badge: 'QA' },
  { id: 'duplicate_poi', name_ar: 'مكرر: مبنى ونقطة داخله', name_en: 'Mapped twice (building & node)', badge: 'QA' },
  { id: 'mapped_as_node', name_ar: 'مرسوم كنقطة وليس كمبنى', name_en: 'Mapped as Node instead of outline', badge: 'QA' },
  { id: 'size_too_small', name_ar: 'مبنى صغير جداً عن المعتاد', name_en: 'Building footprint too small', badge: 'QA' },
  { id: 'size_too_large', name_ar: 'مبنى كبير جداً عن المعتاد', name_en: 'Building footprint too large', badge: 'QA' },
  { id: 'stale_data', name_ar: 'بيانات قديمة (إصدار 1 منذ 5+ سنوات)', name_en: 'Stale data (version 1)', badge: 'QA' },
  { id: 'outdated_tags', name_ar: 'وسوم قديمة أو غير قياسية', name_en: 'Outdated or non-standard tags', badge: 'QA' },
];

export const ACTIONS = [
  { id: 'mode_poi', name_ar: 'تفعيل وضع كثافة الأماكن (1)', name_en: 'Switch to POI Density Mode (1)', icon: '🕌' },
  { id: 'mode_gap', name_ar: 'تفعيل وضع فجوات التغطية (2)', name_en: 'Switch to Coverage Gaps Mode (2)', icon: '⚠️' },
  { id: 'mode_improve', name_ar: 'تفعيل وضع تحسين البيانات (3)', name_en: 'Switch to Data Improvement Mode (3)', icon: '🛠️' },
  { id: 'toggle_satellite', name_ar: 'تبديل طبقة الأقمار الصناعية (B)', name_en: 'Toggle Satellite Basemap (B)', icon: '🛰️' },
  { id: 'toggle_qibla', name_ar: 'إظهار / إخفاء مؤشر القبلة (Q)', name_en: 'Toggle Qibla Compass (Q)', icon: '🧭' },
  { id: 'toggle_wikidata', name_ar: 'إظهار / إخفاء اقتراحات ويكي بيانات', name_en: 'Toggle Wikidata Suggestions', icon: '💡' },
  { id: 'export_csv', name_ar: 'تصدير القائمة الحالية (CSV)', name_en: 'Export current list (CSV)', icon: '📊' },
  { id: 'edit_history', name_ar: 'فتح سجل تعديلاتي الميدانية', name_en: 'Open My Edits History', icon: '📝' },
  { id: 'shortcuts', name_ar: 'عرض اختصارات لوحة المفاتيح (?)', name_en: 'View Keyboard Shortcuts (?)', icon: '⌨️' },
  { id: 'start', name_ar: 'مسار المبتدئين (ابدأ هنا)', name_en: 'New Contributor Onboarding (Start Here)', icon: '🚀' },
  { id: 'guides', name_ar: 'أدلة وإرشادات التحرير', name_en: 'Open Documentation & Guides', icon: '📚' },
  { id: 'tasks', name_ar: 'فتح حملات التحرير والتخطيط', name_en: 'Open Mapping Tasks & Sprints', icon: '🎯' },
  { id: 'tags', name_ar: 'فتح دليل وسوم المساجد', name_en: 'Open Saudi Tag Directory', icon: '📖' },
  { id: 'data_hub', name_ar: 'فتح مركز تحميل البيانات المفتوحة', name_en: 'Open Data Downloads Hub', icon: '💾' },
  { id: 'community', name_ar: 'فتح إحصاءات المجتمع ولوحة الشرف', name_en: 'Open Community Stats & Leaderboard', icon: '🏆' },
  { id: 'toggle_lang', name_ar: 'تبديل اللغة (English / العربية)', name_en: 'Toggle Language (Arabic / English)', icon: '🌐' },
  { id: 'auth_login', name_ar: 'تسجيل الدخول عبر OpenStreetMap', name_en: 'Sign in with OpenStreetMap', icon: '👤' },
];

export function filterPaletteItems(query, lang = 'ar') {
  const q = (query || '').trim();
  if (!q) {
    // Default quick actions & top regions
    return [
      ...ACTIONS.slice(0, 4).map(a => ({ type: 'action', ...a })),
      ...QA_RULES.slice(0, 4).map(r => ({ type: 'rule', ...r })),
      ...REGIONS.slice(0, 4).map(r => ({ type: 'region', ...r })),
    ];
  }

  const normQ = ArabicText.normalize(q).toLowerCase();
  const rawQ = q.toLowerCase();

  const matches = (textAr, textEn) => {
    const nAr = ArabicText.normalize(textAr || '').toLowerCase();
    const lEn = (textEn || '').toLowerCase();
    return nAr.includes(normQ) || lEn.includes(rawQ);
  };

  const results = [];

  // 1. Match Regions
  for (const reg of REGIONS) {
    if (matches(reg.name_ar, reg.name_en) || reg.code.toLowerCase().includes(rawQ)) {
      results.push({
        type: 'region',
        id: reg.code,
        name_ar: reg.name_ar,
        name_en: reg.name_en,
        center: reg.center,
        zoom: reg.zoom,
      });
    }
  }

  // 2. Match QA Rules
  for (const rule of QA_RULES) {
    if (matches(rule.name_ar, rule.name_en) || rule.id.toLowerCase().includes(rawQ)) {
      results.push({
        type: 'rule',
        id: rule.id,
        name_ar: rule.name_ar,
        name_en: rule.name_en,
      });
    }
  }

  // 3. Match Actions
  for (const act of ACTIONS) {
    if (matches(act.name_ar, act.name_en) || act.id.toLowerCase().includes(rawQ)) {
      results.push({
        type: 'action',
        id: act.id,
        name_ar: act.name_ar,
        name_en: act.name_en,
        icon: act.icon,
      });
    }
  }

  return results.slice(0, 12);
}

let activeHandlers = {};
let selectedIdx = 0;
let currentResults = [];

export function setupCommandPalette(handlers = {}) {
  activeHandlers = handlers;

  const dialog = document.getElementById('command-palette-dialog');
  const input = document.getElementById('command-palette-input');
  const list = document.getElementById('command-palette-results');
  if (!dialog || !input || !list) return;

  function render(results) {
    currentResults = results;
    selectedIdx = Math.max(0, Math.min(selectedIdx, results.length - 1));
    list.innerHTML = '';

    if (!results.length) {
      const empty = document.createElement('div');
      empty.className = 'palette-empty';
      empty.textContent = currentLang === 'ar' ? 'لا توجد نتائج مطابقة' : 'No matching results';
      list.appendChild(empty);
      return;
    }

    results.forEach((item, idx) => {
      const row = document.createElement('div');
      row.className = `palette-item ${idx === selectedIdx ? 'selected' : ''}`;
      row.setAttribute('role', 'option');
      row.setAttribute('aria-selected', idx === selectedIdx ? 'true' : 'false');

      const isAr = currentLang === 'ar';
      const title = isAr ? item.name_ar : item.name_en;
      const subtitle = isAr ? item.name_en : item.name_ar;

      let badgeText = '';
      if (item.type === 'region') badgeText = isAr ? 'منطقة' : 'Region';
      else if (item.type === 'rule') badgeText = 'QA';
      else badgeText = isAr ? 'أمر' : 'Action';

      row.innerHTML = `
        <div class="palette-item-icon">${item.icon || (item.type === 'region' ? '📍' : '⚡')}</div>
        <div class="palette-item-text">
          <span class="palette-item-title">${escapeHtml(title)}</span>
          <span class="palette-item-sub">${escapeHtml(subtitle || '')}</span>
        </div>
        <span class="palette-item-badge">${badgeText}</span>
      `;

      row.addEventListener('click', () => {
        executeItem(item);
      });
      row.addEventListener('mouseenter', () => {
        selectedIdx = idx;
        updateSelection();
      });

      list.appendChild(row);
    });
  }

  function updateSelection() {
    const rows = list.querySelectorAll('.palette-item');
    rows.forEach((r, i) => {
      if (i === selectedIdx) {
        r.classList.add('selected');
        r.setAttribute('aria-selected', 'true');
        r.scrollIntoView({ block: 'nearest' });
      } else {
        r.classList.remove('selected');
        r.setAttribute('aria-selected', 'false');
      }
    });
  }

  function executeItem(item) {
    closeCommandPalette();
    if (item.type === 'region' && activeHandlers.onSelectRegion) {
      activeHandlers.onSelectRegion(item);
    } else if (item.type === 'rule' && activeHandlers.onSelectRule) {
      activeHandlers.onSelectRule(item.id);
    } else if (item.type === 'action' && activeHandlers.onExecuteAction) {
      activeHandlers.onExecuteAction(item.id);
    }
  }

  input.addEventListener('input', (e) => {
    selectedIdx = 0;
    render(filterPaletteItems(e.target.value, currentLang));
  });

  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (currentResults.length > 0) {
        selectedIdx = (selectedIdx + 1) % currentResults.length;
        updateSelection();
      }
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (currentResults.length > 0) {
        selectedIdx = (selectedIdx - 1 + currentResults.length) % currentResults.length;
        updateSelection();
      }
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (currentResults[selectedIdx]) {
        executeItem(currentResults[selectedIdx]);
      }
    } else if (e.key === 'Escape') {
      closeCommandPalette();
    }
  });

  dialog.addEventListener('click', (e) => {
    if (e.target === dialog) {
      closeCommandPalette();
    }
  });

  // Global shortcut: Ctrl+K or /
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      toggleCommandPalette();
      return;
    }
    const tag = (e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select' || e.target.isContentEditable) return;
    if (e.key === '/' && !e.ctrlKey && !e.metaKey && !e.altKey) {
      e.preventDefault();
      openCommandPalette();
    }
  });

  // Trigger button in top bar
  const triggerBtn = document.getElementById('btn-command-palette');
  if (triggerBtn) {
    triggerBtn.addEventListener('click', () => openCommandPalette());
  }
}

export function openCommandPalette() {
  const dialog = document.getElementById('command-palette-dialog');
  const input = document.getElementById('command-palette-input');
  if (!dialog || !input) return;
  if (!dialog.open) {
    dialog.showModal();
    input.value = '';
    input.focus();
    const event = new Event('input', { bubbles: true });
    input.dispatchEvent(event);
  }
}

export function closeCommandPalette() {
  const dialog = document.getElementById('command-palette-dialog');
  if (dialog && dialog.open) {
    dialog.close();
  }
}

export function toggleCommandPalette() {
  const dialog = document.getElementById('command-palette-dialog');
  if (dialog?.open) {
    closeCommandPalette();
  } else {
    openCommandPalette();
  }
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
