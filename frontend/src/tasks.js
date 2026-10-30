// Task Tracker & Sprints Workspace (/tasks)
import './styles/fonts.css';
import './styles/page.css';
import './styles/tasks.css';
import { currentLang, setLanguage, addTranslations } from './i18n.js';
import { initAnalytics } from './analytics.js';
import {
  TILE_STATE_LABELS,
  generateIdEditorUrl,
  generateJosmRemoteUrl,
  findNextReadyTile,
  formatTileStateBadge,
  calculateSprintProgress,
} from './tasks_view.js';

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
});

let currentSprint = null;
let currentTiles = [];
let selectedTileId = null;
let currentRevMax = 0;
let pollInterval = null;

// ==========================================
// Initialization & Routing
// ==========================================
export async function initTasksWorkspace() {
  const params = new URLSearchParams(window.location.search);
  const sprintSlug = params.get('sprint');

  if (sprintSlug) {
    await loadSprintBoard(sprintSlug);
  } else {
    await loadSprintsList();
  }

  setupGlobalShortcuts();
}

// ==========================================
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

  // Fallback demo sprint if empty
  if (!sprints || sprints.length === 0) {
    sprints = [
      {
        id: 1,
        slug: 'al-kharj-mosques-2026',
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
          <span class="sprint-hashtag">${s.hashtag}</span>
        </div>
        <h3 class="sprint-card-title">${title}</h3>
        <p style="color: var(--color-text-muted); font-size: 0.88rem; margin: 6px 0 14px;">
          ${isAr ? (s.instructions?.ar || s.instructions?.en || '') : (s.instructions?.en || s.instructions?.ar || '')}
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

  // Fallback demo sprint if not found
  if (!currentSprint) {
    currentSprint = {
      id: 1,
      slug,
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

  if (titleEl) titleEl.textContent = isAr ? (currentSprint.title?.ar || currentSprint.title?.en) : (currentSprint.title?.en || currentSprint.title?.ar);
  if (tagEl) tagEl.textContent = currentSprint.hashtag;

  if (exportBtn) {
    exportBtn.href = `/api/v1/sprints/${currentSprint.slug}/maproulette`;
  }
}

async function fetchBoardTiles(slug) {
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
      if (selectedTileId) {
        const found = currentTiles.find(t => t.tile_id === selectedTileId);
        if (found) renderInspector(found);
      }
    }
  } catch (err) {
    console.warn('Failed to fetch sprint tiles:', err);
  }

  // Fallback demo tiles if empty
  if (!currentTiles || currentTiles.length === 0) {
    currentTiles = generateDemoTiles();
    renderTileGrid(currentTiles);
    updateBoardProgressStats(currentTiles);
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
    const cell = document.createElement('div');
    cell.className = `tile-cell ${t.state} ${t.tile_id === selectedTileId ? 'selected' : ''}`;
    cell.dataset.tileId = t.tile_id;
    cell.title = `Tile: ${t.tile_id} (${t.state})`;

    cell.innerHTML = `
      <span>${t.tile_id}</span>
      <span class="tile-workload-badge">${t.workload || 0}</span>
    `;

    cell.addEventListener('click', () => {
      document.querySelectorAll('.tile-cell').forEach(c => c.classList.remove('selected'));
      cell.classList.add('selected');
      selectedTileId = t.tile_id;
      renderInspector(t);
    });

    container.appendChild(cell);
  });
}

function renderInspector(tile) {
  const panel = document.getElementById('board-inspector-body');
  if (!panel) return;

  const isAr = currentLang === 'ar';
  const stateLabel = isAr ? TILE_STATE_LABELS[tile.state]?.ar : TILE_STATE_LABELS[tile.state]?.en;
  const currentUserUid = localStorage.getItem('osm_access_token') ? (parseInt(localStorage.getItem('osm_uid') || '0', 10) || 0) : null;
  const isOwnMapped = Boolean(currentUserUid && tile.mapped_by && currentUserUid === tile.mapped_by);

  let lockText = isAr ? 'متاح للقفل والعمل' : 'Available to lock';
  if (tile.lock) {
    lockText = `@${tile.lock.display_name || 'user'}`;
  }

  let actionButtonsHtml = '';

  if (tile.state === 'ready') {
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
    } catch (err) {
      console.warn('JOSM Remote Control call failed:', err);
      alert(isAr ? 'تعذر الاتصال بـ JOSM عبر المنفذ 8111. تأكد من تشغيل البرنامج وتفعيل Remote Control.' : 'Could not reach JOSM on port 8111. Ensure JOSM is running with Remote Control enabled.');
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
  try {
    const res = await fetch(`/api/v1/sprints/${currentSprint.slug}/tiles/${tile.tile_id}`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        'If-Match': `"${tile.rev}"`
      },
      body: JSON.stringify({
        action,
        rev: tile.rev,
        ...extraBody
      })
    });

    if (res.status === 409) {
      alert(isAr ? 'تم تعديل المربع من قبل مستخدم آخر، سيتم تحديث اللوحة.' : 'Conflict: Tile was modified by another user. Reloading...');
      await fetchBoardTiles(currentSprint.slug);
      return;
    }

    if (res.status === 403) {
      const errData = await res.json().catch(() => ({}));
      alert(errData.detail || (isAr ? 'غير مصرح بهذا الإجراء (مثال: لا يمكن التحقق من تعديلاتك الذاتية).' : 'Forbidden action (e.g. self-validation is not allowed).'));
      return;
    }

    if (res.ok) {
      const updated = await res.json();
      const idx = currentTiles.findIndex(t => t.tile_id === updated.tile_id);
      if (idx !== -1) {
        currentTiles[idx] = updated;
      }
      renderTileGrid(currentTiles);
      updateBoardProgressStats(currentTiles);
      renderInspector(updated);
    }
  } catch (err) {
    console.warn('Tile action API call error:', err);
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
      alert(currentLang === 'ar' ? 'يرجى ذكر سبب الرفض أو النواقص المطلوبة.' : 'Please provide a reason for invalidation.');
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
    if (['input', 'textarea'].includes(document.activeElement?.tagName?.toLowerCase())) {
      return;
    }

    if (e.key === 'n' || e.key === 'N') {
      const nextTile = findNextReadyTile(currentTiles);
      if (nextTile) {
        selectedTileId = nextTile.tile_id;
        renderTileGrid(currentTiles);
        renderInspector(nextTile);
      }
    } else if (e.key === 'Escape') {
      const modal = document.getElementById('invalidate-modal');
      if (modal && modal.style.display === 'flex') {
        modal.style.display = 'none';
      }
    } else if (selectedTileId) {
      const tile = currentTiles.find(t => t.tile_id === selectedTileId);
      if (!tile) return;

      if ((e.key === 'l' || e.key === 'L') && (tile.state === 'ready' || tile.state === 'mapped')) {
        executeTileAction(tile, 'lock', { kind: tile.state === 'ready' ? 'mapping' : 'validation' });
      } else if ((e.key === 'd' || e.key === 'D') && tile.state === 'mapping') {
        executeTileAction(tile, 'done');
      } else if ((e.key === 'a' || e.key === 'A') && (tile.state === 'validating' || tile.state === 'mapped')) {
        executeTileAction(tile, 'approve');
      } else if ((e.key === 'x' || e.key === 'X') && (tile.state === 'validating' || tile.state === 'mapped')) {
        openInvalidateModal(tile);
      } else if ((e.key === 's' || e.key === 'S') && (tile.state === 'ready' || tile.state === 'mapping')) {
        executeTileAction(tile, 'skip');
      }
    }
  });
}

// Language toggle hook
document.getElementById('btn-toggle-lang')?.addEventListener('click', () => {
  setLanguage(currentLang === 'ar' ? 'en' : 'ar');
  if (currentSprint) {
    renderBoardHeader();
    renderTileGrid(currentTiles);
    updateBoardProgressStats(currentTiles);
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
