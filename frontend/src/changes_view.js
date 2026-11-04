// Changes & Activity Monitor Workspace (List-first change triage view with keyboard navigation)
// Toggleable with the 'Changes' topbar tab or shortcut.
import { currentLang, fmtNum } from './i18n.js';
import { shortcutKey } from './keys.js';

export function formatKindBadge(kind, lang = 'ar') {
  const isAr = lang === 'ar';
  const k = (kind || 'modified').toLowerCase();
  if (k === 'created') {
    return { glyph: '＋', label: isAr ? 'إضافة جديدة' : 'Created', className: 'kind-created' };
  }
  if (k === 'deleted') {
    return { glyph: '✕', label: isAr ? 'حذف' : 'Deleted', className: 'kind-deleted' };
  }
  if (k === 'upgraded') {
    return { glyph: '⇪', label: isAr ? 'ترقية لمبنى' : 'Upgraded', className: 'kind-upgraded' };
  }
  return { glyph: '✎', label: isAr ? 'تعديل' : 'Modified', className: 'kind-modified' };
}

export function formatSourceBadge(source, confirmed = false, lang = 'ar') {
  const isAr = lang === 'ar';
  if (confirmed) {
    return { glyph: '✓', label: isAr ? 'مؤكد يومياً' : 'Confirmed', className: 'src-confirmed' };
  }
  if (source === 'live') {
    return { glyph: '●', label: isAr ? 'مباشر (Live)' : 'Live', className: 'src-live' };
  }
  return { glyph: '◆', label: isAr ? 'يومي (Daily)' : 'Daily', className: 'src-daily' };
}

export function formatTriageBadge(status, lang = 'ar') {
  const isAr = lang === 'ar';
  const s = (status || 'unreviewed').toLowerCase();
  if (s === 'reviewed') {
    return { glyph: '✓', label: isAr ? 'تمت المراجعة' : 'Reviewed', className: 'triage-reviewed' };
  }
  if (s === 'flagged') {
    return { glyph: '⚑', label: isAr ? 'بحاجة لتراجع' : 'Flagged', className: 'triage-flagged' };
  }
  if (s === 'reverted') {
    return { glyph: '↩', label: isAr ? 'تم التراجع' : 'Reverted', className: 'triage-reverted' };
  }
  return { glyph: '○', label: isAr ? 'غير مراجع' : 'Unreviewed', className: 'triage-unreviewed' };
}

export function formatTagDiffSummary(tagDiff) {
  if (!tagDiff || typeof tagDiff !== 'object') return '–';
  const parts = [];

  const modified = tagDiff.modified || {};
  for (const [k, v] of Object.entries(modified)) {
    const before = v?.before ?? '';
    const after = v?.after ?? '';
    parts.push(`${k}: ${before} → ${after}`);
  }

  const added = tagDiff.added || {};
  for (const [k, v] of Object.entries(added)) {
    parts.push(`+${k}=${v}`);
  }

  const removed = tagDiff.removed || {};
  for (const [k, v] of Object.entries(removed)) {
    parts.push(`-${k}=${v}`);
  }

  return parts.length ? parts.slice(0, 3).join(' · ') : '–';
}

export function buildOsmHistoryUrl(osmType, osmId) {
  if (!osmType || !osmId) return 'https://www.openstreetmap.org';
  return `https://www.openstreetmap.org/${osmType}/${osmId}/history`;
}

export function buildOsmchaUrl(changesetId, coords = null) {
  if (changesetId) {
    return `https://osmcha.org/changesets/${changesetId}`;
  }
  if (coords && coords.length === 2) {
    const [lon, lat] = coords;
    const minLon = (lon - 0.05).toFixed(4);
    const maxLon = (lon + 0.05).toFixed(4);
    const minLat = (lat - 0.05).toFixed(4);
    const maxLat = (lat + 0.05).toFixed(4);
    return `https://osmcha.org/?in_bbox=${minLon},${minLat},${maxLon},${maxLat}`;
  }
  return 'https://osmcha.org/';
}

export function buildOsmoseUrl(lat, lon) {
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    return 'https://osmose.openstreetmap.fr/';
  }
  return `https://osmose.openstreetmap.fr/ar/map/#zoom=16&lat=${lat.toFixed(5)}&lon=${lon.toFixed(5)}`;
}

let changesActive = false;
let changesList = [];
let changesFiltered = [];
let changesSelectedIdx = 0;
let changesCallbacks = {};
let latestSeenId = 0;
let pendingIncomingChanges = [];

export function isChangesWorkspaceOpen() {
  return changesActive;
}

export function openChangesWorkspace() {
  const ws = document.getElementById('changes-workspace');
  if (!ws) return;
  changesActive = true;
  ws.classList.remove('hidden');

  // Deactivate other tabs
  document.getElementById('tab-workspace-changes')?.classList.add('active');
  document.getElementById('tab-workspace-map')?.classList.remove('active');
  document.getElementById('tab-workspace-qa')?.classList.remove('active');

  loadChanges();
}

export function closeChangesWorkspace() {
  const ws = document.getElementById('changes-workspace');
  if (!ws) return;
  changesActive = false;
  ws.classList.add('hidden');

  document.getElementById('tab-workspace-changes')?.classList.remove('active');
  document.getElementById('tab-workspace-map')?.classList.add('active');

  if (typeof window !== 'undefined' && window.location?.pathname === '/changes') {
    window.history.replaceState(null, '', '/' + window.location.search + window.location.hash);
  }
}

export function toggleChangesWorkspace() {
  if (changesActive) {
    closeChangesWorkspace();
  } else {
    openChangesWorkspace();
  }
}

export function setupChangesWorkspace(callbacks = {}) {
  changesCallbacks = callbacks;

  const ws = document.getElementById('changes-workspace');
  if (!ws) return;

  const btnClose = document.getElementById('changes-btn-close');
  if (btnClose) {
    btnClose.addEventListener('click', () => closeChangesWorkspace());
  }

  // Filter dropdowns
  const selSource = document.getElementById('changes-filter-source');
  const selRegion = document.getElementById('changes-filter-region');
  const selKind = document.getElementById('changes-filter-kind');
  const selFlag = document.getElementById('changes-filter-flag');
  const selStatus = document.getElementById('changes-filter-status');

  const onFilterChange = () => {
    applyChangesFilters();
  };

  selSource?.addEventListener('change', onFilterChange);
  selRegion?.addEventListener('change', onFilterChange);
  selKind?.addEventListener('change', onFilterChange);
  selFlag?.addEventListener('change', onFilterChange);
  selStatus?.addEventListener('change', onFilterChange);

  // New incoming changes indicator bar
  const newBar = document.getElementById('changes-new-bar');
  if (newBar) {
    newBar.addEventListener('click', () => {
      flushIncomingChanges();
    });
  }

  // Global keyboard shortcuts for Changes workspace
  document.addEventListener('keydown', (e) => {
    if (!changesActive) return;

    const tag = (e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select' || e.target.isContentEditable) return;

    const key = shortcutKey(e);
    if (key === 'Escape') {
      e.preventDefault();
      closeChangesWorkspace();
    } else if (key === 'j' || e.key === 'ArrowDown') {
      e.preventDefault();
      moveChangesSelection(1);
    } else if (key === 'k' || e.key === 'ArrowUp') {
      e.preventDefault();
      moveChangesSelection(-1);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      inspectSelectedChange();
    } else if (key === 'a') {
      e.preventDefault();
      triageSelectedChange('reviewed');
    } else if (key === 'r') {
      e.preventDefault();
      triageSelectedChange('flagged');
    } else if (key === 'h') {
      e.preventDefault();
      openSelectedOsmHistory();
    } else if (key === 'c') {
      e.preventDefault();
      openSelectedOsmcha();
    } else if (key === 'm') {
      e.preventDefault();
      openSelectedOsmose();
    } else if (key === '.') {
      e.preventDefault();
      flushIncomingChanges();
    }
  });

  // Auto-refresh polling every 60s
  setInterval(() => {
    if (!changesActive || document.hidden) return;
    pollNewChanges();
  }, 60000);
}

export function setChanges(changes) {
  changesList = changes;
  for (const c of changes) {
    if (c.id > latestSeenId) latestSeenId = c.id;
  }
  applyChangesFilters();
}

function applyChangesFilters() {
  const selSource = document.getElementById('changes-filter-source')?.value || 'all';
  const selRegion = document.getElementById('changes-filter-region')?.value || 'all';
  const selKind = document.getElementById('changes-filter-kind')?.value || 'all';
  const selFlag = document.getElementById('changes-filter-flag')?.value || 'all';
  const selStatus = document.getElementById('changes-filter-status')?.value || 'all';

  let list = [...changesList];

  if (selSource !== 'all') {
    list = list.filter(c => c.source === selSource);
  }
  if (selRegion !== 'all') {
    list = list.filter(c => c.region_code === selRegion);
  }
  if (selKind !== 'all') {
    list = list.filter(c => c.kind === selKind);
  }
  if (selFlag !== 'all') {
    list = list.filter(c => Array.isArray(c.flags) && c.flags.includes(selFlag));
  }
  if (selStatus !== 'all') {
    list = list.filter(c => {
      const s = c.triage_status || 'unreviewed';
      return s === selStatus;
    });
  }

  changesFiltered = list;
  changesSelectedIdx = 0;
  renderChangesTable();
}

function renderChangesTable() {
  const tbody = document.getElementById('changes-table-body');
  const countEl = document.getElementById('changes-count');
  if (!tbody) return;

  if (countEl) {
    const isAr = currentLang === 'ar';
    countEl.textContent = `${fmtNum(changesFiltered.length)} ${isAr ? 'تعديل مرصود' : 'events found'}`;
  }

  tbody.innerHTML = '';
  if (!changesFiltered.length) {
    const emptyTr = document.createElement('tr');
    emptyTr.className = 'changes-empty-row';
    emptyTr.innerHTML = `
      <td colspan="8" class="changes-empty-cell">
        ${currentLang === 'ar' ? 'لا توجد تغييرات مطابقة للتصفية الحالية' : 'No changes match current filters'}
      </td>
    `;
    tbody.appendChild(emptyTr);
    return;
  }

  changesFiltered.forEach((ch, idx) => {
    const tr = document.createElement('tr');
    tr.className = `changes-row ${idx === changesSelectedIdx ? 'selected' : ''}`;
    tr.setAttribute('data-idx', idx);

    const kindBadge = formatKindBadge(ch.kind, currentLang);
    const srcBadge = formatSourceBadge(ch.source, ch.confirmed, currentLang);
    const triageBadge = formatTriageBadge(ch.triage_status, currentLang);
    const pName = ch.name || (currentLang === 'ar' ? 'مكان بدون اسم' : 'Unnamed place');
    const objRef = `${ch.osm_type}/${ch.osm_id}`;
    const diffSummary = formatTagDiffSummary(ch.tag_diff);
    const flagList = Array.isArray(ch.flags) && ch.flags.length ? ch.flags.join(', ') : '–';

    tr.innerHTML = `
      <td class="changes-cell-kind"><span class="badge ${kindBadge.className}">${kindBadge.glyph} ${kindBadge.label}</span></td>
      <td class="changes-cell-name" dir="auto"><strong>${escapeHtml(pName)}</strong></td>
      <td class="changes-cell-obj"><code>${objRef}</code></td>
      <td class="changes-cell-diff"><code dir="ltr">${escapeHtml(diffSummary)}</code></td>
      <td class="changes-cell-flags"><span class="changes-flags-tag">${flagList}</span></td>
      <td class="changes-cell-region">${ch.region_code || '–'}</td>
      <td class="changes-cell-source"><span class="badge ${srcBadge.className}">${srcBadge.glyph} ${srcBadge.label}</span></td>
      <td class="changes-cell-triage"><span class="badge ${triageBadge.className}">${triageBadge.glyph} ${triageBadge.label}</span></td>
    `;

    tr.addEventListener('click', () => {
      changesSelectedIdx = idx;
      updateChangesSelection();
      inspectSelectedChange();
    });

    tbody.appendChild(tr);
  });
}

function updateChangesSelection() {
  const rows = document.querySelectorAll('#changes-table-body .changes-row');
  rows.forEach((r, i) => {
    if (i === changesSelectedIdx) {
      r.classList.add('selected');
      r.scrollIntoView({ block: 'nearest' });
    } else {
      r.classList.remove('selected');
    }
  });
}

function moveChangesSelection(delta) {
  if (!changesFiltered.length) return;
  changesSelectedIdx = Math.max(0, Math.min(changesSelectedIdx + delta, changesFiltered.length - 1));
  updateChangesSelection();
}

function inspectSelectedChange() {
  const ch = changesFiltered[changesSelectedIdx];
  if (!ch) return;
  closeChangesWorkspace();
  if (changesCallbacks.onInspectChange) {
    changesCallbacks.onInspectChange(ch);
  }
}

function triageSelectedChange(status) {
  const ch = changesFiltered[changesSelectedIdx];
  if (!ch) return;
  ch.triage_status = status;
  if (changesCallbacks.onTriageChange) {
    changesCallbacks.onTriageChange(ch, status);
  }
  updateChangesSelection();
  renderChangesTable();
}

function openSelectedOsmHistory() {
  const ch = changesFiltered[changesSelectedIdx];
  if (!ch) return;
  const url = buildOsmHistoryUrl(ch.osm_type, ch.osm_id);
  window.open(url, '_blank', 'noopener,noreferrer');
}

function openSelectedOsmcha() {
  const ch = changesFiltered[changesSelectedIdx];
  if (!ch) return;
  const url = buildOsmchaUrl(ch.changeset_id, ch.coordinates);
  window.open(url, '_blank', 'noopener,noreferrer');
}

function openSelectedOsmose() {
  const ch = changesFiltered[changesSelectedIdx];
  if (!ch || !ch.coordinates) return;
  const url = buildOsmoseUrl(ch.coordinates[1], ch.coordinates[0]);
  window.open(url, '_blank', 'noopener,noreferrer');
}

function loadChanges() {
  if (changesCallbacks.fetchChanges) {
    changesCallbacks.fetchChanges().then(changes => {
      if (changes) {
        setChanges(changes);
      }
    });
  }
}

function pollNewChanges() {
  if (!changesCallbacks.fetchChanges || !latestSeenId) return;
  changesCallbacks.fetchChanges(latestSeenId).then(newItems => {
    if (newItems && newItems.length) {
      pendingIncomingChanges.push(...newItems);
      const newBar = document.getElementById('changes-new-bar');
      if (newBar) {
        newBar.classList.remove('hidden');
        const count = pendingIncomingChanges.length;
        const msg = currentLang === 'ar' ? `${count} تعديل جديد · اضغط (.) للعرض` : `${count} new changes · press (.) to show`;
        newBar.textContent = msg;
      }
    }
  });
}

function flushIncomingChanges() {
  if (!pendingIncomingChanges.length) return;
  const combined = [...pendingIncomingChanges, ...changesList];
  pendingIncomingChanges = [];
  const newBar = document.getElementById('changes-new-bar');
  if (newBar) newBar.classList.add('hidden');
  setChanges(combined);
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
