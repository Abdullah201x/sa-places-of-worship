// Public /community statistics dashboard (Phase 5a).
// Reads exclusively from Manara's own FastAPI endpoints (/api/v1/stats*, /api/v1/meta).
// Makes zero calls to api.openstreetmap.org and stores no personal data.
import { escapeHtml } from './escape.js';
import './page.js';
import {
  currentLang,
  t,
  fmtNum,
  fmtDate,
  addTranslations,
  onLanguageChange,
} from './i18n.js';

addTranslations({
  errLoadFailed: [
    'تعذّر تحميل بيانات الإحصاءات من الخادم. يرجى المحاولة مرة أخرى.',
    'Could not load statistics from the server. Please try again.',
  ],
  metaVersionLabel: ['إصدار البيانات:', 'Dataset version:'],
  metaPbfDateLabel: ['تاريخ مستخلص OSM:', 'OSM extract date:'],
  metaPublishedLabel: ['آخر تحديث:', 'Last updated:'],
  metaRegionsLabel: ['المناطق الإدارية:', 'Administrative provinces:'],

  kpiTotalPlaces: ['إجمالي أماكن العبادة', 'Total Places of Worship'],
  kpiTotalPlacesSub: ['منها {muslim} مسجد ومصلى ({pct}٪)', '{muslim} Muslim mosques & musallas ({pct}%)'],
  kpiPolygonShare: ['مرسوم كمضلع مبنى (Way)', 'Traced as Building Polygons'],
  kpiPolygonShareSub: ['{ways} مضلع مقابل {nodes} نقطة مفردة', '{ways} polygons vs {nodes} single points'],
  kpiTotalGaps: ['فجوات التغطية السكانية', 'Populated Coverage Gaps'],
  kpiTotalGapsSub: ['خلايا طرق تبعد > ٧٥٠م عن أي مسجد', 'Road-network grid cells > 750 m from a mosque'],
  kpiTotalSuggestions: ['اقتراحات ويكي بيانات', 'Wikidata Suggestions'],
  kpiTotalSuggestionsSub: ['{named} مسماة · {unnamed} بدون اسم', '{named} named · {unnamed} unnamed'],
  kpiSuggestionsFallbackSub: ['مساجد موثقة في ويكي بيانات غير مرصودة في OSM', 'Mosques in Wikidata missing from OSM'],
  kpiQiblaDeviated: ['انحراف حاد عن القبلة (≥ 20°)', 'Severe Qibla Deviation (≥ 20°)'],
  kpiQiblaDeviatedSub: ['من أصل {footprints} مبنى مقاس ({pct}٪)', 'Out of {footprints} measured footprints ({pct}%)'],
  kpiAnomalies: ['شذوذ هندسي بالذكاء الاصطناعي', 'ML Geometry Anomalies'],
  kpiAnomaliesSub: ['مبانٍ غير معتادة الشكل (Isolation Forest)', 'Unusual building footprints (Isolation Forest)'],

  geomPanelTitle: ['التمثيل الهندسي وتكامل البيانات', 'Geometry Representation & Completeness'],
  geomPanelSub: [
    'توزيع العناصر بين مبانٍ مرسومة بالكامل ونقاط تحتاج إلى رسم حدود المبنى.',
    'Distribution of mapped elements between traced building outlines and single points needing outlines.',
  ],
  geomWaysLabel: ['مضلعات مبانٍ وعلاقات (Ways / Relations)', 'Building Polygons & Relations'],
  geomNodesLabel: ['نقاط مفردة (Nodes)', 'Single Points (Nodes)'],
  sugSplitTitle: ['تفصيل اقتراحات ويكي بيانات المفقودة', 'Missing Wikidata Suggestions Split'],
  sugNamedLabel: ['مساجد مسماة جاهزة للمراجعة', 'Named mosques ready for review'],
  sugUnnamedLabel: ['مساجد عامة / بدون اسم', 'Generic / unnamed mosques'],

  issuesPanelTitle: ['تفصيل مؤشرات الجودة والفحوصات المكانية', 'Quality Checks & Spatial Audit Breakdown'],
  issuesPanelSub: [
    'أبرز الفحوصات الآلية التي يكتشفها خط المعالجة اليومي عبر المملكة.',
    'Key automated checks detected by the daily processing pipeline across Saudi Arabia.',
  ],
  issueNodeTitle: ['مرسوم كنقطة وليس كمساحة (Node)', 'Mapped as a Point, Not an Area (Node)'],
  issueNodeMeta: ['من إجمالي أماكن العبادة ({total})', 'of total places of worship ({total})'],
  issueQiblaTitle: ['انحراف حاد عن اتجاه القبلة (≥ 20°)', 'Severe Qibla Misalignment (≥ 20°)'],
  issueQiblaMeta: ['من المباني المقاسة هندسياً ({total})', 'of geometrically measured buildings ({total})'],
  issueMergedTitle: ['مكرر مدمج (مبنى + نقطة بداخله)', 'Merged Duplicate (Building + Interior Node)'],
  issueMergedMeta: ['عناصر مكررة تم توحيدها أثناء المعالجة', 'duplicate POI nodes merged into buildings'],
  issueAnomalyTitle: ['شذوذ هندسي مكتشف بـ Isolation Forest', 'Geometry Anomaly (Isolation Forest)'],
  issueAnomalyMeta: ['من المباني المقاسة هندسياً ({total})', 'of geometrically measured buildings ({total})'],

  totalKingdomRow: ['إجمالي المملكة (١٣ منطقة)', 'Kingdom Total (13 Provinces)'],
  allKingdomOption: ['جميع مناطق المملكة (١٣ منطقة)', 'All Kingdom (13 Provinces)'],

  metricPlaces: ['الأماكن المرصودة', 'Mapped Places'],
  metricCoveragePct: ['نسبة التغطية الحالية في OSM', 'Current OSM Coverage Ratio'],
  metricGaps: ['فجوات التغطية', 'Coverage Gaps'],
  metricSuggestions: ['اقتراحات ويكي بيانات', 'Wikidata Suggestions'],
  metricQibla: ['انحراف القبلة (≥ 20°)', 'Qibla Deviation (≥ 20°)'],
  metricAnomalies: ['الشذوذ الهندسي', 'Geometry Anomalies'],

  historyEarlyNoticeTitle: ['بدأ تسجيل السجل الزمني في ٢٨ أكتوبر ٢٠٢٦', 'Historical tracking started on 28 October 2026'],
  historyEarlyNoticeBody: [
    'تُسجَّل لقطة جديدة تلقائياً بعد كل تحديث يومي لبيانات OpenStreetMap (٢٣:٣٠ بالتوقيت العالمي). يتسع المنحنى الزمني يوماً بعد يوم مع تراكم القراءات.',
    'A new snapshot is recorded automatically after each daily OpenStreetMap pipeline run (23:30 UTC). The trend line will grow day by day as snapshots accumulate.',
  ],
  historyEmpty: ['لا توجد لقطات زمنية مسجلة لهذا النطاق بعد.', 'No historical snapshots recorded for this selection yet.'],
  historyDeltaSinceStart: ['التغير منذ أول لقطة مسجلة:', 'Change since first recorded snapshot:'],
  historySnapshotsCount: ['عدد اللقطات المسجلة: {n}', 'Recorded snapshots: {n}'],
  historyColVersion: ['رقم اللقطة', 'Snapshot Version'],
  historyColDate: ['تاريخ التسجيل', 'Recorded At'],
  historyColPlaces: ['الأماكن', 'Places'],
  historyColGaps: ['الفجوات', 'Gaps'],
  historyColSuggestions: ['المقترحات', 'Suggestions'],
  historyColAnomalies: ['الشذوذ الهندسي', 'Anomalies'],

  leaderboardEmpty: ['لا يوجد مساهمون مشاركون في لوحة الشرف حالياً.', 'No mappers participating in the leaderboard yet.'],
  leaderboardFixes: ['{n} إصلاح موثق', '{n} verified fixes'],
  leaderboardEdits: ['{n} مجموعة تعديلات', '{n} changesets'],
  editsEmpty: ['لا توجد تعديلات موثقة بالوسم مسجلة بعد.', 'No verified changesets recorded yet.'],
  editsElementsCount: ['{n} معلماً', '{n} elements'],
  optInTitle: ['حسابك: {name}', 'Your account: {name}'],
  optInDesc: ['المشاركة في لوحة الشرف اختيارية تماماً. عند التفعيل، يظهر اسمك ورتبتك بناءً على التعديلات الموثقة بالوسم #sa-worship-map.', 'Participation in the leaderboard is completely opt-in. When enabled, your name and rank appear based on verified edits with #sa-worship-map.'],
  optInBtnEnable: ['تفعيل المشاركة في لوحة الشرف', 'Opt-in to Leaderboard'],
  optInBtnDisable: ['إلغاء المشاركة (إخفاء من اللوحة)', 'Opt-out (Hide from Leaderboard)'],
  optInActiveBadge: ['مشارك نشط في لوحة الشرف', 'Active Leaderboard Participant'],
  optInInactiveBadge: ['غير مشارك (مخفي)', 'Not participating (Hidden)'],
  optInGuestNotice: ['سجّل الدخول بحساب OpenStreetMap لإظهار خيارات المشاركة في لوحة الشرف.', 'Log in with your OpenStreetMap account to configure your leaderboard participation.'],
});

function fmtPct(value, digits = 1) {
  const num = Number.isFinite(value) ? value : 0;
  return num.toLocaleString(currentLang === 'ar' ? 'ar-SA' : 'en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

// State
let overallStats = null;
let metaData = null;
let regionsData = [];
let allHistoryRows = [];
const regionHistoryCache = new Map();

let activeRegionMetric = 'places_count';
let tableSortKey = 'places_count';
let tableSortAsc = false;

let activeHistoryRegion = 'ALL';
let activeHistoryMetric = 'places_count';

let currentUser = null;
let leaderboardList = [];
let recentEditsList = [];
let fixedIssuesList = [];

async function fetchJson(url) {
  const res = await fetch(url, { headers: { Accept: 'application/json' } });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status} (${url})`);
  }
  return res.json();
}

function enrichRegions(rawRegions) {
  return rawRegions.map(r => {
    const places = Number(r.places_count || 0);
    const suggestions = Number(r.suggestions_count || 0);
    const denom = places + suggestions;
    const coverage_pct = denom > 0 ? (places / denom) * 100 : 0;
    return {
      ...r,
      places_count: places,
      gaps_count: Number(r.gaps_count || 0),
      suggestions_count: suggestions,
      anomalies_count: Number(r.anomalies_count || 0),
      qibla_deviated_count: Number(r.qibla_deviated_count || 0),
      coverage_pct,
    };
  });
}

function renderMetaBar() {
  const bar = document.getElementById('community-meta-bar');
  if (!bar || !overallStats) return;

  const pills = [];
  if (metaData && metaData.version) {
    pills.push(
      `<span class="meta-pill"><strong>${escapeHtml(t('metaVersionLabel'))}</strong> <code dir="ltr">${escapeHtml(metaData.version)}</code></span>`
    );
  }
  if (metaData && metaData.pbf_date) {
    pills.push(
      `<span class="meta-pill"><strong>${escapeHtml(t('metaPbfDateLabel'))}</strong> <span dir="ltr">${escapeHtml(metaData.pbf_date)}</span></span>`
    );
  }
  if (metaData && metaData.published_at) {
    pills.push(
      `<span class="meta-pill"><strong>${escapeHtml(t('metaPublishedLabel'))}</strong> ${escapeHtml(fmtDate(metaData.published_at, true))}</span>`
    );
  }
  pills.push(
    `<span class="meta-pill"><strong>${escapeHtml(t('metaRegionsLabel'))}</strong> ${escapeHtml(fmtNum(overallStats.total_regions || 13))}</span>`
  );
  bar.innerHTML = pills.join('');
}

function renderKpiCards() {
  const grid = document.getElementById('kpi-grid');
  if (!grid || !overallStats) return;

  const totalPlaces = Number(overallStats.total_places || 0);
  const muslimPlaces = Number(overallStats.muslim_places || 0);
  const muslimPct = totalPlaces > 0 ? fmtPct((muslimPlaces / totalPlaces) * 100, 1) : fmtPct(0, 1);

  const ds = metaData?.summary?.datasets || {};
  const waysCount = Number(ds.places?.ways || 0) + Number(ds.places?.relations || 0);
  const nodesCount = Number(ds.places?.nodes || 0);
  const hasGeomSplit = waysCount + nodesCount > 0;
  const polygonPct = hasGeomSplit ? fmtPct((waysCount / (waysCount + nodesCount)) * 100, 1) : null;

  const footprintsCount = Number(ds.sizes?.count || ds.anomalies?.count || waysCount || totalPlaces);
  const qiblaCount = Number(overallStats.qibla_deviated_places || 0);
  const qiblaPct = footprintsCount > 0 ? fmtPct((qiblaCount / footprintsCount) * 100, 1) : fmtPct(0, 1);

  const namedSug = ds.suggestions?.named;
  const unnamedSug = ds.suggestions?.unnamed;

  const cards = [
    {
      accent: 'cyan',
      value: fmtNum(totalPlaces),
      label: t('kpiTotalPlaces'),
      sub: t('kpiTotalPlacesSub', { muslim: fmtNum(muslimPlaces), pct: muslimPct }),
    },
    hasGeomSplit
      ? {
          accent: 'emerald',
          value: `${polygonPct}%`,
          label: t('kpiPolygonShare'),
          sub: t('kpiPolygonShareSub', { ways: fmtNum(waysCount), nodes: fmtNum(nodesCount) }),
        }
      : {
          accent: 'emerald',
          value: fmtNum(overallStats.total_regions || 13),
          label: t('metaRegionsLabel'),
          sub: '',
        },
    {
      accent: 'amber',
      value: fmtNum(overallStats.total_gaps || 0),
      label: t('kpiTotalGaps'),
      sub: t('kpiTotalGapsSub'),
    },
    {
      accent: 'purple',
      value: fmtNum(overallStats.total_suggestions || 0),
      label: t('kpiTotalSuggestions'),
      sub:
        namedSug !== undefined && unnamedSug !== undefined
          ? t('kpiTotalSuggestionsSub', { named: fmtNum(namedSug), unnamed: fmtNum(unnamedSug) })
          : t('kpiSuggestionsFallbackSub'),
    },
    {
      accent: 'gold',
      value: fmtNum(qiblaCount),
      label: t('kpiQiblaDeviated'),
      sub: t('kpiQiblaDeviatedSub', { footprints: fmtNum(footprintsCount), pct: qiblaPct }),
    },
    {
      accent: 'coral',
      value: fmtNum(overallStats.anomaly_places || 0),
      label: t('kpiAnomalies'),
      sub: t('kpiAnomaliesSub'),
    },
  ];

  grid.innerHTML = cards
    .map(
      c => `
      <article class="kpi-card accent-${c.accent}">
        <div class="kpi-value">${escapeHtml(c.value)}</div>
        <div class="kpi-label">${escapeHtml(c.label)}</div>
        ${c.sub ? `<div class="kpi-sub">${escapeHtml(c.sub)}</div>` : ''}
      </article>
    `
    )
    .join('');
}

function renderIssueBreakdown() {
  const container = document.getElementById('issues-breakdown-container');
  if (!container || !overallStats) return;

  const totalPlaces = Number(overallStats.total_places || 1);
  const ds = metaData?.summary?.datasets || {};
  const waysCount = Number(ds.places?.ways || 0) + Number(ds.places?.relations || 0);
  const nodesCount = Number(ds.places?.nodes || Math.max(0, totalPlaces - waysCount));
  const mergedNodes = Number(ds.places?.merged_nodes || 0);
  const footprintsCount = Number(ds.sizes?.count || waysCount || totalPlaces);

  const waysPct = totalPlaces > 0 ? (waysCount / totalPlaces) * 100 : 0;
  const nodesPct = totalPlaces > 0 ? (nodesCount / totalPlaces) * 100 : 0;

  const totalSug = Number(overallStats.total_suggestions || 0);
  const namedSug = Number(ds.suggestions?.named ?? totalSug);
  const unnamedSug = Number(ds.suggestions?.unnamed ?? 0);
  const namedSugPct = totalSug > 0 ? (namedSug / totalSug) * 100 : 0;
  const unnamedSugPct = totalSug > 0 ? (unnamedSug / totalSug) * 100 : 0;

  const qiblaCount = Number(overallStats.qibla_deviated_places || 0);
  const anomalyCount = Number(overallStats.anomaly_places || 0);

  const checks = [
    {
      id: 'mapped_as_node',
      icon: '📍',
      title: t('issueNodeTitle'),
      meta: t('issueNodeMeta', { total: fmtNum(totalPlaces) }),
      count: nodesCount,
      pct: totalPlaces > 0 ? (nodesCount / totalPlaces) * 100 : 0,
      color: 'amber',
    },
    {
      id: 'qibla_deviation',
      icon: '🕋',
      title: t('issueQiblaTitle'),
      meta: t('issueQiblaMeta', { total: fmtNum(footprintsCount) }),
      count: qiblaCount,
      pct: footprintsCount > 0 ? (qiblaCount / footprintsCount) * 100 : 0,
      color: 'gold',
    },
    {
      id: 'duplicate_poi',
      icon: '👯',
      title: t('issueMergedTitle'),
      meta: t('issueMergedMeta'),
      count: mergedNodes,
      pct: totalPlaces > 0 ? (mergedNodes / totalPlaces) * 100 : 0,
      color: 'cyan',
    },
    {
      id: 'ml_geometry_anomaly',
      icon: '🤖',
      title: t('issueAnomalyTitle'),
      meta: t('issueAnomalyMeta', { total: fmtNum(footprintsCount) }),
      count: anomalyCount,
      pct: footprintsCount > 0 ? (anomalyCount / footprintsCount) * 100 : 0,
      color: 'coral',
    },
  ];

  container.innerHTML = `
    <div class="panel-card">
      <h3 class="panel-title">${escapeHtml(t('geomPanelTitle'))}</h3>
      <p class="panel-sub">${escapeHtml(t('geomPanelSub'))}</p>

      <div class="stacked-bar" role="img" aria-label="${escapeHtml(t('geomPanelTitle'))}">
        <div class="stacked-seg seg-emerald" style="width: ${waysPct.toFixed(2)}%" title="${escapeHtml(t('geomWaysLabel'))}: ${escapeHtml(fmtNum(waysCount))}"></div>
        <div class="stacked-seg seg-amber" style="width: ${nodesPct.toFixed(2)}%" title="${escapeHtml(t('geomNodesLabel'))}: ${escapeHtml(fmtNum(nodesCount))}"></div>
      </div>

      <div class="stacked-legend">
        <div class="legend-item">
          <span class="legend-dot seg-emerald"></span>
          <span class="legend-label">${escapeHtml(t('geomWaysLabel'))}</span>
          <strong class="legend-val">${escapeHtml(fmtNum(waysCount))} (${escapeHtml(fmtPct(waysPct, 1))}%)</strong>
        </div>
        <div class="legend-item">
          <span class="legend-dot seg-amber"></span>
          <span class="legend-label">${escapeHtml(t('geomNodesLabel'))}</span>
          <strong class="legend-val">${escapeHtml(fmtNum(nodesCount))} (${escapeHtml(fmtPct(nodesPct, 1))}%)</strong>
        </div>
      </div>

      <hr class="panel-divider">

      <h4 class="panel-subtitle">${escapeHtml(t('sugSplitTitle'))}</h4>
      <div class="stacked-bar">
        <div class="stacked-seg seg-purple" style="width: ${namedSugPct.toFixed(2)}%"></div>
        <div class="stacked-seg seg-muted" style="width: ${unnamedSugPct.toFixed(2)}%"></div>
      </div>
      <div class="stacked-legend">
        <div class="legend-item">
          <span class="legend-dot seg-purple"></span>
          <span class="legend-label">${escapeHtml(t('sugNamedLabel'))}</span>
          <strong class="legend-val">${escapeHtml(fmtNum(namedSug))} (${escapeHtml(fmtPct(namedSugPct, 1))}%)</strong>
        </div>
        <div class="legend-item">
          <span class="legend-dot seg-muted"></span>
          <span class="legend-label">${escapeHtml(t('sugUnnamedLabel'))}</span>
          <strong class="legend-val">${escapeHtml(fmtNum(unnamedSug))} (${escapeHtml(fmtPct(unnamedSugPct, 1))}%)</strong>
        </div>
      </div>
    </div>

    <div class="panel-card">
      <h3 class="panel-title">${escapeHtml(t('issuesPanelTitle'))}</h3>
      <p class="panel-sub">${escapeHtml(t('issuesPanelSub'))}</p>

      <div class="checks-list">
        ${checks
          .map(
            item => `
          <a href="/#mode=improve&issue=${encodeURIComponent(item.id)}" class="check-row check-row-link">
            <div class="check-row-head">
              <div class="check-title-wrap">
                <span class="check-icon">${item.icon}</span>
                <div>
                  <div class="check-title">${escapeHtml(item.title)}</div>
                  <div class="check-meta">${escapeHtml(item.meta)}</div>
                </div>
              </div>
              <div class="check-numbers">
                <strong class="check-count">${escapeHtml(fmtNum(item.count))}</strong>
                <span class="check-pct">(${escapeHtml(fmtPct(item.pct, 1))}%)</span>
              </div>
            </div>
            <div class="check-bar-track">
              <div class="check-bar-fill fill-${item.color}" style="width: ${Math.min(100, Math.max(1.5, item.pct)).toFixed(2)}%"></div>
            </div>
          </a>
        `
          )
          .join('')}
      </div>
    </div>
  `;
}

function regionDisplayName(r) {
  return currentLang === 'ar' ? r.name : r.name_en || r.name;
}

function metricColorClass(metric) {
  switch (metric) {
    case 'places_count':
      return 'fill-cyan';
    case 'coverage_pct':
      return 'fill-emerald';
    case 'gaps_count':
      return 'fill-amber';
    case 'suggestions_count':
      return 'fill-purple';
    case 'qibla_deviated_count':
      return 'fill-gold';
    case 'anomalies_count':
      return 'fill-coral';
    default:
      return 'fill-cyan';
  }
}

function renderRegionsBars() {
  const container = document.getElementById('regions-bars-container');
  if (!container || !regionsData.length) return;

  const sorted = [...regionsData].sort((a, b) => Number(b[activeRegionMetric] || 0) - Number(a[activeRegionMetric] || 0));
  const maxVal = Math.max(
    1,
    ...sorted.map(r => (activeRegionMetric === 'coverage_pct' ? 100 : Number(r[activeRegionMetric] || 0)))
  );
  const colorClass = metricColorClass(activeRegionMetric);

  container.innerHTML = sorted
    .map(r => {
      const rawVal = Number(r[activeRegionMetric] || 0);
      const pctWidth = activeRegionMetric === 'coverage_pct' ? rawVal : (rawVal / maxVal) * 100;
      const formattedVal =
        activeRegionMetric === 'coverage_pct' ? `${fmtPct(rawVal, 1)}%` : fmtNum(rawVal);

      return `
        <div class="region-bar-row">
          <div class="region-bar-label">
            <span class="region-code-badge" dir="ltr">${escapeHtml(r.code)}</span>
            <span class="region-name-text">${escapeHtml(regionDisplayName(r))}</span>
          </div>
          <div class="region-bar-track">
            <div class="region-bar-fill ${colorClass}" style="width: ${Math.max(rawVal > 0 ? 1.5 : 0, pctWidth).toFixed(2)}%"></div>
          </div>
          <div class="region-bar-val">${escapeHtml(formattedVal)}</div>
        </div>
      `;
    })
    .join('');
}

function renderRegionsTable() {
  const tbody = document.getElementById('regions-tbody');
  const tfoot = document.getElementById('regions-tfoot');
  if (!tbody || !tfoot || !regionsData.length) return;

  const sorted = [...regionsData].sort((a, b) => {
    if (tableSortKey === 'name') {
      const cmp = regionDisplayName(a).localeCompare(regionDisplayName(b), currentLang === 'ar' ? 'ar' : 'en');
      return tableSortAsc ? cmp : -cmp;
    }
    const diff = Number(a[tableSortKey] || 0) - Number(b[tableSortKey] || 0);
    return tableSortAsc ? diff : -diff;
  });

  // Update header sort indicators
  document.querySelectorAll('#regions-table th.sortable-th').forEach(th => {
    const key = th.dataset.sort;
    const ind = th.querySelector('.sort-indicator');
    if (key === tableSortKey) {
      th.classList.add('active-sort');
      if (ind) ind.textContent = tableSortAsc ? '↑' : '↓';
    } else {
      th.classList.remove('active-sort');
      if (ind) ind.textContent = '';
    }
  });

  tbody.innerHTML = sorted
    .map(
      r => `
      <tr>
        <td>
          <span class="region-code-badge" dir="ltr">${escapeHtml(r.code)}</span>
          <strong>${escapeHtml(regionDisplayName(r))}</strong>
        </td>
        <td class="num-col">${escapeHtml(fmtNum(r.places_count))}</td>
        <td class="num-col">
          <span class="table-pct-pill">${escapeHtml(fmtPct(r.coverage_pct, 1))}%</span>
        </td>
        <td class="num-col">${escapeHtml(fmtNum(r.gaps_count))}</td>
        <td class="num-col">${escapeHtml(fmtNum(r.suggestions_count))}</td>
        <td class="num-col">${escapeHtml(fmtNum(r.qibla_deviated_count))}</td>
        <td class="num-col">${escapeHtml(fmtNum(r.anomalies_count))}</td>
      </tr>
    `
    )
    .join('');

  const totPlaces = regionsData.reduce((s, r) => s + r.places_count, 0);
  const totGaps = regionsData.reduce((s, r) => s + r.gaps_count, 0);
  const totSug = regionsData.reduce((s, r) => s + r.suggestions_count, 0);
  const totQibla = regionsData.reduce((s, r) => s + r.qibla_deviated_count, 0);
  const totAnom = regionsData.reduce((s, r) => s + r.anomalies_count, 0);
  const totCovPct = totPlaces + totSug > 0 ? (totPlaces / (totPlaces + totSug)) * 100 : 0;

  tfoot.innerHTML = `
    <tr class="totals-row">
      <td><strong>${escapeHtml(t('totalKingdomRow'))}</strong></td>
      <td class="num-col"><strong>${escapeHtml(fmtNum(totPlaces))}</strong></td>
      <td class="num-col"><strong>${escapeHtml(fmtPct(totCovPct, 1))}%</strong></td>
      <td class="num-col"><strong>${escapeHtml(fmtNum(totGaps))}</strong></td>
      <td class="num-col"><strong>${escapeHtml(fmtNum(totSug))}</strong></td>
      <td class="num-col"><strong>${escapeHtml(fmtNum(totQibla))}</strong></td>
      <td class="num-col"><strong>${escapeHtml(fmtNum(totAnom))}</strong></td>
    </tr>
  `;
}

function populateHistoryRegionSelect() {
  const select = document.getElementById('history-region-select');
  if (!select) return;

  const currentVal = activeHistoryRegion;
  const options = [
    `<option value="ALL">${escapeHtml(t('allKingdomOption'))}</option>`,
    ...regionsData.map(
      r => `<option value="${escapeHtml(r.code)}">${escapeHtml(r.code)} — ${escapeHtml(regionDisplayName(r))}</option>`
    ),
  ];
  select.innerHTML = options.join('');
  select.value = currentVal;
}

function getAggregatedKingdomSeries(rows) {
  // If backend provided pre-aggregated 'ALL' rows, return them directly
  const allRows = rows.filter(r => r.region_code === 'ALL');
  if (allRows.length > 0) {
    return allRows
      .map(r => ({
        version: r.version || '-',
        recorded_at: r.recorded_at,
        places_count: Number(r.places_count || 0),
        gaps_count: Number(r.gaps_count || 0),
        suggestions_count: Number(r.suggestions_count || 0),
        anomalies_count: Number(r.anomalies_count || 0),
      }))
      .sort((a, b) => new Date(a.recorded_at).getTime() - new Date(b.recorded_at).getTime());
  }

  const byVersion = new Map();
  rows.forEach(row => {
    const ver = row.version || row.recorded_at;
    if (!ver) return;
    let entry = byVersion.get(ver);
    if (!entry) {
      entry = {
        version: row.version || '-',
        recorded_at: row.recorded_at,
        places_count: 0,
        gaps_count: 0,
        suggestions_count: 0,
        anomalies_count: 0,
        regions_seen: 0,
      };
      byVersion.set(ver, entry);
    }
    entry.places_count += Number(row.places_count || 0);
    entry.gaps_count += Number(row.gaps_count || 0);
    entry.suggestions_count += Number(row.suggestions_count || 0);
    entry.anomalies_count += Number(row.anomalies_count || 0);
    entry.regions_seen += 1;
    if (row.recorded_at && (!entry.recorded_at || row.recorded_at > entry.recorded_at)) {
      entry.recorded_at = row.recorded_at;
    }
  });

  return Array.from(byVersion.values())
    .filter(entry => entry.regions_seen >= 13)
    .sort((a, b) => new Date(a.recorded_at).getTime() - new Date(b.recorded_at).getTime());
}

function getRegionSeries(rows, regionCode) {
  return rows
    .filter(r => r.region_code === regionCode)
    .map(r => ({
      version: r.version || '-',
      recorded_at: r.recorded_at,
      places_count: Number(r.places_count || 0),
      gaps_count: Number(r.gaps_count || 0),
      suggestions_count: Number(r.suggestions_count || 0),
      anomalies_count: Number(r.anomalies_count || 0),
    }))
    .sort((a, b) => new Date(a.recorded_at).getTime() - new Date(b.recorded_at).getTime());
}

function historyMetricColor(metric) {
  switch (metric) {
    case 'places_count':
      return '#00f2fe';
    case 'gaps_count':
      return '#ffb03a';
    case 'suggestions_count':
      return '#a855f7';
    case 'anomalies_count':
      return '#f43f5e';
    default:
      return '#00f2fe';
  }
}

function historyMetricLabel(metric) {
  switch (metric) {
    case 'places_count':
      return t('metricPlaces');
    case 'gaps_count':
      return t('metricGaps');
    case 'suggestions_count':
      return t('metricSuggestions');
    case 'anomalies_count':
      return t('metricAnomalies');
    default:
      return '';
  }
}

async function renderHistorySection() {
  const chartWrap = document.getElementById('history-chart-wrap');
  const tableWrap = document.getElementById('history-table-wrap');
  if (!chartWrap || !tableWrap) return;

  let series = [];
  if (activeHistoryRegion === 'ALL') {
    series = getAggregatedKingdomSeries(allHistoryRows);
  } else {
    if (!regionHistoryCache.has(activeHistoryRegion)) {
      try {
        const data = await fetchJson(`/api/v1/stats/history?region=${encodeURIComponent(activeHistoryRegion)}&limit=100`);
        regionHistoryCache.set(activeHistoryRegion, data.history || []);
      } catch (_) {
        regionHistoryCache.set(
          activeHistoryRegion,
          allHistoryRows.filter(r => r.region_code === activeHistoryRegion)
        );
      }
    }
    series = getRegionSeries(regionHistoryCache.get(activeHistoryRegion) || [], activeHistoryRegion);
  }

  if (!series.length) {
    chartWrap.innerHTML = `<div class="history-empty-box">${escapeHtml(t('historyEmpty'))}</div>`;
    tableWrap.innerHTML = '';
    return;
  }

  const strokeColor = historyMetricColor(activeHistoryMetric);
  const values = series.map(pt => Number(pt[activeHistoryMetric] || 0));
  const minVal = Math.min(...values);
  const maxVal = Math.max(...values);
  const firstVal = values[0];
  const lastVal = values[values.length - 1];
  const delta = lastVal - firstVal;
  const deltaSign = delta > 0 ? `+${fmtNum(delta)}` : fmtNum(delta);

  // Build inline SVG time-series chart (handles 1, 2, or N points cleanly)
  const width = 760;
  const height = 230;
  const padLeft = 68;
  const padRight = 36;
  const padTop = 28;
  const padBottom = 44;
  const plotW = width - padLeft - padRight;
  const plotH = height - padTop - padBottom;

  const span = maxVal - minVal;
  const yLow = span === 0 ? Math.max(0, minVal - Math.max(5, Math.round(minVal * 0.05))) : minVal - span * 0.15;
  const yHigh = span === 0 ? maxVal + Math.max(5, Math.round(maxVal * 0.05) || 5) : maxVal + span * 0.15;
  const yRange = Math.max(1, yHigh - yLow);

  const xOf = i =>
    series.length === 1 ? padLeft + plotW / 2 : padLeft + (i / (series.length - 1)) * plotW;
  const yOf = val => padTop + plotH - ((val - yLow) / yRange) * plotH;

  const points = series.map((pt, idx) => ({
    x: xOf(idx),
    y: yOf(Number(pt[activeHistoryMetric] || 0)),
    val: Number(pt[activeHistoryMetric] || 0),
    dateStr: fmtDate(pt.recorded_at, series.length <= 3),
    version: pt.version,
  }));

  // Grid lines (3 horizontal levels)
  const yTicks = [yLow, (yLow + yHigh) / 2, yHigh];
  const gridSvg = yTicks
    .map(tickVal => {
      const y = yOf(tickVal).toFixed(1);
      return `
        <line x1="${padLeft}" y1="${y}" x2="${width - padRight}" y2="${y}" stroke="rgba(255,255,255,0.08)" stroke-dasharray="4 4" />
        <text x="${padLeft - 10}" y="${Number(y) + 4}" text-anchor="end" fill="#94a3b8" font-size="11">${escapeHtml(fmtNum(Math.round(tickVal)))}</text>
      `;
    })
    .join('');

  let pathSvg = '';
  if (points.length === 1) {
    const p = points[0];
    pathSvg = `
      <line x1="${padLeft}" y1="${p.y.toFixed(1)}" x2="${width - padRight}" y2="${p.y.toFixed(1)}" stroke="${strokeColor}" stroke-width="2" stroke-dasharray="6 4" opacity="0.6" />
    `;
  } else {
    const lineD = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ');
    const areaD = `${lineD} L ${points[points.length - 1].x.toFixed(1)} ${(padTop + plotH).toFixed(1)} L ${points[0].x.toFixed(1)} ${(padTop + plotH).toFixed(1)} Z`;
    pathSvg = `
      <path d="${areaD}" fill="url(#historyAreaGrad)" />
      <path d="${lineD}" fill="none" stroke="${strokeColor}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />
    `;
  }

  const labelStep = Math.max(1, Math.ceil(points.length / 6));
  const dotsSvg = points
    .map((p, i) => {
      const showLabel = i === 0 || i === points.length - 1 || i % labelStep === 0;
      return `
        <g class="chart-point">
          <circle cx="${p.x.toFixed(1)}" cy="${p.y.toFixed(1)}" r="5" fill="#0a0b10" stroke="${strokeColor}" stroke-width="3">
            <title>${escapeHtml(p.version)} (${escapeHtml(p.dateStr)}): ${escapeHtml(fmtNum(p.val))}</title>
          </circle>
          ${
            showLabel
              ? `<text x="${p.x.toFixed(1)}" y="${(p.y - 11).toFixed(1)}" text-anchor="middle" fill="#f1f5f9" font-size="11" font-weight="700">${escapeHtml(fmtNum(p.val))}</text>
                 <text x="${p.x.toFixed(1)}" y="${height - 12}" text-anchor="middle" fill="#94a3b8" font-size="11">${escapeHtml(p.dateStr)}</text>`
              : ''
          }
        </g>
      `;
    })
    .join('');

  const earlyNoticeHtml =
    series.length <= 2
      ? `
      <div class="history-early-banner">
        <span class="early-icon">ℹ️</span>
        <div>
          <strong>${escapeHtml(t('historyEarlyNoticeTitle'))}</strong>
          <p>${escapeHtml(t('historyEarlyNoticeBody'))}</p>
        </div>
      </div>
    `
      : '';

  chartWrap.innerHTML = `
    ${earlyNoticeHtml}
    <div class="history-summary-strip">
      <span class="history-summary-item">
        <strong>${escapeHtml(historyMetricLabel(activeHistoryMetric))}:</strong>
        ${escapeHtml(fmtNum(lastVal))}
      </span>
      <span class="history-summary-item">
        ${escapeHtml(t('historyDeltaSinceStart'))}
        <strong class="delta-badge ${delta === 0 ? 'delta-neutral' : delta > 0 ? 'delta-up' : 'delta-down'}" dir="ltr">${escapeHtml(deltaSign)}</strong>
      </span>
      <span class="history-summary-item muted">
        ${escapeHtml(t('historySnapshotsCount', { n: fmtNum(series.length) }))}
      </span>
    </div>
    <div class="svg-chart-container" dir="ltr">
      <svg viewBox="0 0 ${width} ${height}" class="history-svg" role="img" aria-label="${escapeHtml(historyMetricLabel(activeHistoryMetric))}">
        <defs>
          <linearGradient id="historyAreaGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="${strokeColor}" stop-opacity="0.28" />
            <stop offset="100%" stop-color="${strokeColor}" stop-opacity="0.0" />
          </linearGradient>
        </defs>
        ${gridSvg}
        ${pathSvg}
        ${dotsSvg}
      </svg>
    </div>
  `;

  // Render compact reverse-chronological table of snapshots (latest first)
  const latestFirst = [...series].reverse().slice(0, 15);
  tableWrap.innerHTML = `
    <div class="table-scroll-wrap">
      <table class="community-table compact-table">
        <thead>
          <tr>
            <th>${escapeHtml(t('historyColVersion'))}</th>
            <th>${escapeHtml(t('historyColDate'))}</th>
            <th class="num-col">${escapeHtml(t('historyColPlaces'))}</th>
            <th class="num-col">${escapeHtml(t('historyColGaps'))}</th>
            <th class="num-col">${escapeHtml(t('historyColSuggestions'))}</th>
            <th class="num-col">${escapeHtml(t('historyColAnomalies'))}</th>
          </tr>
        </thead>
        <tbody>
          ${latestFirst
            .map(
              row => `
            <tr>
              <td><code dir="ltr">${escapeHtml(row.version)}</code></td>
              <td>${escapeHtml(fmtDate(row.recorded_at, true))}</td>
              <td class="num-col">${escapeHtml(fmtNum(row.places_count))}</td>
              <td class="num-col">${escapeHtml(fmtNum(row.gaps_count))}</td>
              <td class="num-col">${escapeHtml(fmtNum(row.suggestions_count))}</td>
              <td class="num-col">${escapeHtml(fmtNum(row.anomalies_count))}</td>
            </tr>
          `
            )
            .join('')}
        </tbody>
      </table>
    </div>
  `;
}

function renderAvatarBadge(name, className = 'avatar-thumb') {
  const initial = (name || '?').trim()[0].toUpperCase();
  let hash = 0;
  for (let i = 0; i < (name || '').length; i++) hash = (hash * 31 + name.charCodeAt(i)) % 360;
  return `<span class="${className} initials-badge" style="background-color: hsl(${hash}, 40%, 35%); color: #fff; display: inline-flex; align-items: center; justify-content: center; font-weight: 700; border-radius: 50%; user-select: none;">${escapeHtml(initial)}</span>`;
}

function renderUserOptinBox() {
  const box = document.getElementById('user-optin-box');
  if (!box) return;

  if (!currentUser) {
    box.style.display = 'none';
    return;
  }

  box.style.display = 'flex';
  const isOptedIn = Boolean(currentUser.leaderboard_opt_in);
  const badgeClass = isOptedIn ? 'badge-emerald' : 'badge-muted';
  const badgeText = isOptedIn ? t('optInActiveBadge') : t('optInInactiveBadge');
  const btnText = isOptedIn ? t('optInBtnDisable') : t('optInBtnEnable');
  const btnClass = isOptedIn ? 'community-btn btn-secondary' : 'community-btn btn-primary';

  box.innerHTML = `
    <div class="user-optin-info">
      <div class="user-avatar-wrap">
        ${renderAvatarBadge(currentUser.display_name, 'user-avatar-img')}
      </div>
      <div>
        <div class="user-optin-title">
          <strong>${escapeHtml(t('optInTitle', { name: currentUser.display_name }))}</strong>
          <span class="user-optin-badge ${badgeClass}">${escapeHtml(badgeText)}</span>
        </div>
        <p class="user-optin-desc">${escapeHtml(t('optInDesc'))}</p>
      </div>
    </div>
    <button type="button" id="btn-toggle-optin" class="${btnClass}">${escapeHtml(btnText)}</button>
  `;

  document.getElementById('btn-toggle-optin')?.addEventListener('click', toggleOptIn);
}

async function toggleOptIn() {
  if (!currentUser) return;
  const newStatus = !currentUser.leaderboard_opt_in;
  try {
    const res = await fetch('/api/v1/me', {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'X-Manara-CSRF': '1' },
      body: JSON.stringify({ leaderboard_opt_in: newStatus }),
    });
    if (res.ok) {
      const data = await res.json();
      currentUser = data.user;
      renderUserOptinBox();
      const lbRes = await fetchJson('/api/v1/leaderboard').catch(() => ({ leaderboard: [] }));
      leaderboardList = lbRes.leaderboard || [];
      renderLeaderboard();
    }
  } catch (err) {
    console.error('Could not toggle leaderboard opt-in:', err);
  }
}

function renderLeaderboard() {
  const container = document.getElementById('leaderboard-container');
  if (!container) return;

  if (!leaderboardList.length) {
    container.innerHTML = `<div class="empty-feed-box">${escapeHtml(t('leaderboardEmpty'))}</div>`;
    return;
  }

  container.innerHTML = `
    <div class="leaderboard-list">
      ${leaderboardList.map((m, idx) => {
        const medal = idx === 0 ? '🥇' : idx === 1 ? '🥈' : idx === 2 ? '🥉' : `#${idx + 1}`;
        const medalClass = idx === 0 ? 'rank-gold' : idx === 1 ? 'rank-silver' : idx === 2 ? 'rank-bronze' : 'rank-num';
        return `
          <div class="leaderboard-row">
            <span class="rank-badge ${medalClass}">${medal}</span>
            <div class="mapper-avatar">
              ${renderAvatarBadge(m.display_name, 'avatar-thumb')}
            </div>
            <div class="mapper-meta">
              <span class="mapper-name">${escapeHtml(m.display_name)}</span>
              <span class="mapper-osm-total">${escapeHtml(fmtNum(m.osm_changesets))} OSM changesets</span>
            </div>
            <div class="mapper-stats">
              <span class="mapper-stat-val">${escapeHtml(t('leaderboardFixes', { n: fmtNum(m.verified_fixes_count || 0) }))}</span>
              <span class="mapper-stat-sub">${escapeHtml(t('leaderboardEdits', { n: fmtNum(m.verified_edits_count || 0) }))}</span>
            </div>
          </div>
        `;
      }).join('')}
    </div>
  `;
}

function renderRecentEdits() {
  const container = document.getElementById('recent-edits-container');
  if (!container) return;

  if (!recentEditsList.length) {
    container.innerHTML = `<div class="empty-feed-box">${escapeHtml(t('editsEmpty'))}</div>`;
    return;
  }

  container.innerHTML = `
    <div class="recent-edits-list">
      ${recentEditsList.map(e => `
        <div class="recent-edit-row">
          <div class="edit-row-top">
            <div class="mapper-avatar-mini">
              ${renderAvatarBadge(e.display_name, 'avatar-thumb-mini')}
            </div>
            <div class="edit-mapper-name">
              <strong>${escapeHtml(e.display_name)}</strong>
              <a href="https://www.openstreetmap.org/changeset/${escapeHtml(e.changeset_id)}" target="_blank" rel="noopener" class="changeset-link" dir="ltr">#${escapeHtml(e.changeset_id)} ↗</a>
            </div>
            <span class="edit-time">${escapeHtml(fmtDate(e.verified_at, true))}</span>
          </div>
          <div class="edit-comment">${escapeHtml(e.comment || '#sa-worship-map')}</div>
          <div class="edit-tags-pill">
            <span class="edit-badge">${escapeHtml(t('editsElementsCount', { n: fmtNum(e.objects_count || 0) }))}</span>
          </div>
        </div>
      `).join('')}
    </div>
  `;
}

function formatTagDiff(tagDiff) {
  if (!tagDiff || typeof tagDiff !== 'object') return '–';
  const parts = [];
  for (const [k, v] of Object.entries(tagDiff.modified || {})) {
    parts.push(`${k}: ${v?.before ?? ''} → ${v?.after ?? ''}`);
  }
  for (const [k, v] of Object.entries(tagDiff.added || {})) {
    parts.push(`+${k}=${v}`);
  }
  return parts.length ? parts.slice(0, 3).join(' · ') : '–';
}

function renderFixedIssues() {
  const container = document.getElementById('fixed-issues-container');
  if (!container) return;

  if (!fixedIssuesList.length) {
    container.innerHTML = `<div class="empty-feed-box">${currentLang === 'ar' ? 'لا توجد إصلاحات مؤكدة مسجلة حديثاً' : 'No recently confirmed fixed issues yet'}</div>`;
    return;
  }

  container.innerHTML = `
    <div class="recent-edits-list">
      ${fixedIssuesList.map(ch => {
        const pName = ch.name || (currentLang === 'ar' ? 'مكان عبادة' : 'Place of worship');
        const objRef = `${ch.osm_type}/${ch.osm_id}`;
        return `
          <div class="recent-edit-row">
            <div class="edit-row-top">
              <span class="badge status-fixed" style="font-size: 11px;">✓ ${currentLang === 'ar' ? 'تم الإصلاح' : 'Fixed'}</span>
              <div class="edit-mapper-name">
                <strong dir="auto">${escapeHtml(pName)}</strong>
                <a href="https://www.openstreetmap.org/${escapeHtml(objRef)}" target="_blank" rel="noopener" class="changeset-link" dir="ltr">${escapeHtml(objRef)} ↗</a>
              </div>
              <span class="edit-time">${escapeHtml(fmtDate(ch.observed_at || ch.osm_timestamp, true))}</span>
            </div>
            <div class="edit-comment">
              <code dir="ltr" style="font-size: 11px; color: #94a3b8;">${escapeHtml(formatTagDiff(ch.tag_diff))}</code>
            </div>
            ${ch.region_code ? `
              <div class="edit-tags-pill">
                <span class="edit-badge">${escapeHtml(ch.region_code)}</span>
              </div>
            ` : ''}
          </div>
        `;
      }).join('')}
    </div>
  `;
}

function renderAll() {
  if (!overallStats) return;
  renderMetaBar();
  renderKpiCards();
  renderIssueBreakdown();
  renderRegionsBars();
  renderRegionsTable();
  populateHistoryRegionSelect();
  renderHistorySection();
  renderUserOptinBox();
  renderLeaderboard();
  renderRecentEdits();
  renderFixedIssues();
}

function bindEvents() {
  // Region metric tabs
  const regionTabs = document.getElementById('region-metric-tabs');
  if (regionTabs) {
    regionTabs.addEventListener('click', e => {
      const btn = e.target.closest('button[data-metric]');
      if (!btn) return;
      activeRegionMetric = btn.dataset.metric;
      regionTabs.querySelectorAll('.metric-chip').forEach(b => {
        const active = b === btn;
        b.classList.toggle('active', active);
        b.setAttribute('aria-selected', active ? 'true' : 'false');
      });
      renderRegionsBars();
    });
  }

  // Sortable table headers
  document.querySelectorAll('#regions-table th.sortable-th').forEach(th => {
    th.addEventListener('click', () => {
      const key = th.dataset.sort;
      if (!key) return;
      if (tableSortKey === key) {
        tableSortAsc = !tableSortAsc;
      } else {
        tableSortKey = key;
        tableSortAsc = key === 'name';
      }
      renderRegionsTable();
    });
  });

  // History region filter
  const historySelect = document.getElementById('history-region-select');
  if (historySelect) {
    historySelect.addEventListener('change', () => {
      activeHistoryRegion = historySelect.value || 'ALL';
      renderHistorySection();
    });
  }

  // History metric tabs
  const historyTabs = document.getElementById('history-metric-tabs');
  if (historyTabs) {
    historyTabs.addEventListener('click', e => {
      const btn = e.target.closest('button[data-hmetric]');
      if (!btn) return;
      activeHistoryMetric = btn.dataset.hmetric;
      historyTabs.querySelectorAll('.metric-chip').forEach(b => {
        const active = b === btn;
        b.classList.toggle('active', active);
        b.setAttribute('aria-selected', active ? 'true' : 'false');
      });
      renderHistorySection();
    });
  }

  const retryBtn = document.getElementById('btn-retry-load');
  if (retryBtn) {
    retryBtn.addEventListener('click', () => loadCommunityData());
  }
}

async function loadCommunityData() {
  const errBox = document.getElementById('community-error');
  const errText = document.getElementById('community-error-text');
  if (errBox) errBox.style.display = 'none';

  try {
    const [statsRes, regionsRes, historyRes, metaRes, meRes, lbRes, editsRes, changesRes] = await Promise.all([
      fetchJson('/api/v1/stats'),
      fetchJson('/api/v1/stats/regions'),
      fetchJson('/api/v1/stats/history?limit=1170'),
      fetchJson('/api/v1/meta').catch(() => null),
      fetchJson('/api/v1/me').catch(() => null),
      fetchJson('/api/v1/leaderboard').catch(() => ({ leaderboard: [] })),
      fetchJson('/api/v1/edits/recent').catch(() => ({ edits: [] })),
      fetchJson('/api/v1/changes?flag=issue-fixed&limit=20').catch(() => ({ changes: [] })),
    ]);

    overallStats = statsRes;
    metaData = metaRes;
    regionsData = enrichRegions(regionsRes.regions || []);
    allHistoryRows = historyRes.history || [];
    currentUser = meRes;
    leaderboardList = lbRes.leaderboard || [];
    recentEditsList = editsRes.edits || [];
    fixedIssuesList = changesRes.changes || [];

    renderAll();
  } catch (err) {
    console.error('Failed to load community stats:', err);
    if (errBox && errText) {
      errText.textContent = t('errLoadFailed');
      errBox.style.display = 'flex';
    }
  }
}

bindEvents();
onLanguageChange(() => {
  const errBox = document.getElementById('community-error');
  const errText = document.getElementById('community-error-text');
  if (errBox && errBox.style.display !== 'none' && errText) {
    errText.textContent = t('errLoadFailed');
  }
  renderAll();
});
loadCommunityData();
