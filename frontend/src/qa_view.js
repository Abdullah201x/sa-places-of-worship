// QA Workspace (List-first issue triage view with keyboard navigation)
// Toggleable with 'L' or the 'QA' topbar tab.
import { currentLang, fmtNum } from './i18n.js';
import { shortcutKey } from './keys.js';

export const SEVERITY_ORDER = { high: 3, medium: 2, low: 1 };

export function formatSeverityBadge(severity, lang = 'ar') {
  const isAr = lang === 'ar';
  const s = (severity || 'medium').toLowerCase();
  if (s === 'high') {
    return { glyph: '▲', label: isAr ? 'حرجة' : 'High', className: 'sev-high' };
  }
  if (s === 'low') {
    return { glyph: '▽', label: isAr ? 'منخفضة' : 'Low', className: 'sev-low' };
  }
  return { glyph: '●', label: isAr ? 'متوسطة' : 'Medium', className: 'sev-med' };
}

export function formatStatusBadge(status, lang = 'ar') {
  const isAr = lang === 'ar';
  const s = (status || 'open').toLowerCase();
  if (s === 'fixed') {
    return { glyph: '✓', label: isAr ? 'تم الإصلاح' : 'Fixed', className: 'status-fixed' };
  }
  if (s === 'skipped') {
    return { glyph: '⏭', label: isAr ? 'تم التخطي' : 'Skipped', className: 'status-skipped' };
  }
  return { glyph: '○', label: isAr ? 'مفتوحة' : 'Open', className: 'status-open' };
}

export function calculateDistanceKm(lat1, lon1, lat2, lon2) {
  if (!Number.isFinite(lat1) || !Number.isFinite(lon1) || !Number.isFinite(lat2) || !Number.isFinite(lon2)) {
    return null;
  }
  const R = 6371; // Earth radius in km
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
            Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
            Math.sin(dLon / 2) * Math.sin(dLon / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return R * c;
}

export function sortIssues(issues, sortBy = 'severity', mapCenter = null) {
  const list = [...issues];
  if (sortBy === 'severity') {
    return list.sort((a, b) => {
      const diff = (SEVERITY_ORDER[b.severity] || 0) - (SEVERITY_ORDER[a.severity] || 0);
      if (diff !== 0) return diff;
      return (a.osm_id || 0) - (b.osm_id || 0);
    });
  }
  if (sortBy === 'distance' && mapCenter) {
    return list.sort((a, b) => {
      const distA = calculateDistanceKm(mapCenter[0], mapCenter[1], a.coordinates?.[1], a.coordinates?.[0]) ?? 99999;
      const distB = calculateDistanceKm(mapCenter[0], mapCenter[1], b.coordinates?.[1], b.coordinates?.[0]) ?? 99999;
      return distA - distB;
    });
  }
  if (sortBy === 'name') {
    return list.sort((a, b) => (a.name || '').localeCompare(b.name || '', 'ar'));
  }
  return list.sort((a, b) => (a.osm_id || 0) - (b.osm_id || 0));
}

let qaActive = false;
let qaIssues = [];
let qaFiltered = [];
let qaSelectedIdx = 0;
let qaRenderedCount = 0;
let qaCallbacks = {};

export const QA_PAGE_SIZE = 200;

export function isQAWorkspaceOpen() {
  return qaActive;
}

export function openQAWorkspace() {
  const ws = document.getElementById('qa-workspace');
  if (!ws) return;
  qaActive = true;
  ws.classList.remove('hidden');

  const tabQa = document.getElementById('tab-workspace-qa');
  const tabMap = document.getElementById('tab-workspace-map');
  tabQa?.classList.add('active');
  tabMap?.classList.remove('active');

  loadQAIssues();
}

export function closeQAWorkspace() {
  const ws = document.getElementById('qa-workspace');
  if (!ws) return;
  qaActive = false;
  ws.classList.add('hidden');

  const tabQa = document.getElementById('tab-workspace-qa');
  const tabMap = document.getElementById('tab-workspace-map');
  tabMap?.classList.add('active');
  tabQa?.classList.remove('active');
}

export function toggleQAWorkspace() {
  if (qaActive) {
    closeQAWorkspace();
  } else {
    openQAWorkspace();
  }
}

export function setupQAWorkspace(callbacks = {}) {
  qaCallbacks = callbacks;

  const ws = document.getElementById('qa-workspace');
  if (!ws) return;

  // View toggle buttons
  const btnClose = document.getElementById('qa-btn-close');
  if (btnClose) {
    btnClose.addEventListener('click', () => closeQAWorkspace());
  }

  const btnFocus = document.getElementById('qa-btn-focus');
  if (btnFocus) {
    btnFocus.addEventListener('click', () => {
      if (qaFiltered.length > 0) {
        inspectSelectedQAIssue();
      }
    });
  }

  // Filter dropdowns
  const selRule = document.getElementById('qa-filter-rule');
  const selRegion = document.getElementById('qa-filter-region');
  const selStatus = document.getElementById('qa-filter-status');
  const selSort = document.getElementById('qa-filter-sort');

  const onFilterChange = () => {
    applyQAFilters();
  };

  selRule?.addEventListener('change', onFilterChange);
  selRegion?.addEventListener('change', onFilterChange);
  selStatus?.addEventListener('change', onFilterChange);
  selSort?.addEventListener('change', onFilterChange);

  // One delegated listener instead of one per row
  document.getElementById('qa-table-body')?.addEventListener('click', (e) => {
    if (e.target.closest('.qa-more-btn')) {
      appendQARows(QA_PAGE_SIZE);
      return;
    }
    const tr = e.target.closest('.qa-row');
    if (!tr) return;
    qaSelectedIdx = Number(tr.getAttribute('data-idx'));
    updateRowSelection();
    inspectSelectedQAIssue();
  });

  // Global keyboard shortcuts for QA workspace
  document.addEventListener('keydown', (e) => {
    if (!qaActive) {
      // 'L' key toggles into QA workspace from map
      const tag = (e.target.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select' || e.target.isContentEditable) return;
      if (!e.ctrlKey && !e.metaKey && !e.altKey && shortcutKey(e) === 'l') {
        e.preventDefault();
        openQAWorkspace();
      }
      return;
    }

    const tag = (e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select' || e.target.isContentEditable) return;

    const key = shortcutKey(e);
    if (key === 'l' || key === 'Escape') {
      e.preventDefault();
      closeQAWorkspace();
    } else if (key === 'j' || e.key === 'ArrowDown') {
      e.preventDefault();
      moveQASelection(1);
    } else if (key === 'k' || e.key === 'ArrowUp') {
      e.preventDefault();
      moveQASelection(-1);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      inspectSelectedQAIssue();
    } else if (key === 'f') {
      e.preventDefault();
      markSelectedQAIssue('fixed');
    } else if (key === 's') {
      e.preventDefault();
      markSelectedQAIssue('skipped');
    }
  });
}

export function setQAIssues(issues) {
  qaIssues = issues;
  applyQAFilters();
}

function applyQAFilters() {
  const selRule = document.getElementById('qa-filter-rule')?.value || 'all';
  const selRegion = document.getElementById('qa-filter-region')?.value || 'all';
  const selStatus = document.getElementById('qa-filter-status')?.value || 'all';
  const selSort = document.getElementById('qa-filter-sort')?.value || 'severity';

  let list = [...qaIssues];

  if (selRule !== 'all') {
    list = list.filter(i => i.rule_id === selRule);
  }
  if (selRegion !== 'all') {
    list = list.filter(i => i.region_code === selRegion);
  }
  if (selStatus !== 'all') {
    list = list.filter(i => {
      const s = i.review_status || 'open';
      return s === selStatus;
    });
  }

  const center = qaCallbacks.getMapCenter ? qaCallbacks.getMapCenter() : null;
  qaFiltered = sortIssues(list, selSort, center);
  qaSelectedIdx = 0;
  renderQATable();
}

function renderQATable() {
  const tbody = document.getElementById('qa-table-body');
  const countEl = document.getElementById('qa-count');
  if (!tbody) return;

  if (countEl) {
    const isAr = currentLang === 'ar';
    countEl.textContent = `${fmtNum(qaFiltered.length)} ${isAr ? 'عنصر بحاجة للمراجعة' : 'issues found'}`;
  }

  tbody.innerHTML = '';
  qaRenderedCount = 0;
  if (!qaFiltered.length) {
    const emptyTr = document.createElement('tr');
    emptyTr.className = 'qa-empty-row';
    emptyTr.innerHTML = `
      <td colspan="7" class="qa-empty-cell">
        ${currentLang === 'ar' ? '🎉 لا توجد مشاكل مطابقة للتصفية المحددة' : '🎉 No issues match current filters'}
      </td>
    `;
    tbody.appendChild(emptyTr);
    return;
  }

  appendQARows(QA_PAGE_SIZE);
}

function buildStatusCell(issue) {
  const stat = formatStatusBadge(issue.review_status, currentLang);
  return `<span class="badge ${stat.className}">${stat.glyph} ${stat.label}</span>`;
}

// The full issue list can be tens of thousands of rows, so only a window of
// it is in the DOM; "show more" (or moving the selection past the end) grows it.
function appendQARows(count) {
  const tbody = document.getElementById('qa-table-body');
  if (!tbody) return;

  tbody.querySelector('.qa-more-row')?.remove();

  const mapCenter = qaCallbacks.getMapCenter ? qaCallbacks.getMapCenter() : null;
  const end = Math.min(qaRenderedCount + count, qaFiltered.length);
  const frag = document.createDocumentFragment();

  for (let idx = qaRenderedCount; idx < end; idx++) {
    const issue = qaFiltered[idx];
    const tr = document.createElement('tr');
    tr.className = `qa-row ${idx === qaSelectedIdx ? 'selected' : ''}`;
    tr.setAttribute('data-idx', idx);

    const sev = formatSeverityBadge(issue.severity, currentLang);
    const pName = issue.name || issue.name_en || (currentLang === 'ar' ? 'مكان بدون اسم' : 'Unnamed place');
    const objRef = `${issue.osm_type}/${issue.osm_id}`;

    let distText = '–';
    if (mapCenter && issue.coordinates) {
      const km = calculateDistanceKm(mapCenter[0], mapCenter[1], issue.coordinates[1], issue.coordinates[0]);
      if (km !== null) {
        distText = `${km.toFixed(1)} ${currentLang === 'ar' ? 'كم' : 'km'}`;
      }
    }

    tr.innerHTML = `
      <td class="qa-cell-sev"><span class="badge ${sev.className}">${sev.glyph} ${sev.label}</span></td>
      <td class="qa-cell-name" dir="auto"><strong>${escapeHtml(pName)}</strong></td>
      <td class="qa-cell-obj"><code>${objRef}</code></td>
      <td class="qa-cell-rule"><span class="qa-rule-tag">${issue.rule_id}</span></td>
      <td class="qa-cell-region">${issue.region_code || '–'}</td>
      <td class="qa-cell-dist">${distText}</td>
      <td class="qa-cell-status">${buildStatusCell(issue)}</td>
    `;
    frag.appendChild(tr);
  }
  qaRenderedCount = end;

  const remaining = qaFiltered.length - qaRenderedCount;
  if (remaining > 0) {
    const isAr = currentLang === 'ar';
    const moreTr = document.createElement('tr');
    moreTr.className = 'qa-more-row';
    moreTr.innerHTML = `
      <td colspan="7" class="qa-more-cell">
        <button type="button" class="qa-more-btn">${isAr ? 'عرض المزيد' : 'Show more'} (${fmtNum(remaining)})</button>
      </td>
    `;
    frag.appendChild(moreTr);
  }
  tbody.appendChild(frag);
}

function updateRowSelection() {
  const rows = document.querySelectorAll('#qa-table-body .qa-row');
  rows.forEach((r, i) => {
    if (i === qaSelectedIdx) {
      r.classList.add('selected');
      r.scrollIntoView({ block: 'nearest' });
    } else {
      r.classList.remove('selected');
    }
  });
}

function moveQASelection(delta) {
  if (!qaFiltered.length) return;
  qaSelectedIdx = Math.max(0, Math.min(qaSelectedIdx + delta, qaFiltered.length - 1));
  if (qaSelectedIdx >= qaRenderedCount) {
    appendQARows(qaSelectedIdx - qaRenderedCount + 1 + QA_PAGE_SIZE);
  }
  updateRowSelection();
}

function inspectSelectedQAIssue() {
  const issue = qaFiltered[qaSelectedIdx];
  if (!issue) return;
  closeQAWorkspace();
  if (qaCallbacks.onInspectIssue) {
    qaCallbacks.onInspectIssue(issue);
  }
}

function markSelectedQAIssue(status) {
  const issue = qaFiltered[qaSelectedIdx];
  if (!issue) return;
  issue.review_status = status;
  if (qaCallbacks.onMarkIssue) {
    qaCallbacks.onMarkIssue(issue, status);
  }
  updateRowSelection();
  // Only the marked row changes; rebuilding the table here would redo every row.
  const statusCell = document.querySelector(`#qa-table-body .qa-row[data-idx="${qaSelectedIdx}"] .qa-cell-status`);
  if (statusCell) statusCell.innerHTML = buildStatusCell(issue);
}

let qaLoading = false;

export function loadQAIssues() {
  if (!qaCallbacks.fetchIssues || qaLoading) return;
  qaLoading = true;
  qaCallbacks.fetchIssues().then(issues => {
    if (issues) {
      setQAIssues(issues);
    }
  }).catch(err => {
    console.error('Failed to load QA issues:', err);
  }).finally(() => {
    qaLoading = false;
  });
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
