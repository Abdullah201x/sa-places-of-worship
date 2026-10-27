// In-app tag fixes for tag-based issues, uploaded through OsmApi (js/osm_api.js).
// Every edit is previewed and confirmed by the mapper; the batch only holds
// fixes that were reviewed one by one, then uploads them in one changeset
// (the osm x wikidata batch pattern). There is deliberately no "fix all".
import { addTranslations, t, fmtNum, fmtDate, onLanguageChange } from './i18n.js';
import { ReviewMarks, refreshAfterReviewChange } from './review.js';
import { Exporters } from './exporters.js';
import { OsmApi, EditHistory } from './osm_api.js';
import { allPlaces, selectedPlace, denomLabel, osmTypeOf, getIssues, invalidateIssues, updateImprovementIssueCounts, showToast, placeName, showDetails } from './app.js';

addTranslations({
  quickFixesTitle: ['⚡ إصلاح سريع (OSM API)', '⚡ Quick fix (OSM API)'],
  quickFixesLogin: ['سجّل الدخول بحساب OSM لإصلاح هذه الوسوم مباشرة من هنا.', 'Log in with OSM to fix these tags right here.'],
  quickFixesRelogin: ['تسجيل دخولك الحالي لا يتضمن صلاحية التعديل (write_api). سجّل الخروج ثم الدخول مجدداً.', 'Your current login lacks edit permission (write_api). Log out and in again.'],
  fix_missing_amenity: ['إضافة amenity=place_of_worship', 'Add amenity=place_of_worship'],
  fix_building_yes: ['تعديل building=yes إلى building=mosque', 'Change building=yes to building=mosque'],
  fix_missing_name_en: ['إضافة الاسم بالإنجليزية (name:en)', 'Add the English name (name:en)'],
  fix_missing_denom: ['تحديد المذهب (denomination)', 'Set the denomination'],
  editDialogTitle: ['مراجعة التعديل قبل الرفع', 'Review the edit before uploading'],
  editTarget: ['العنصر:', 'Element:'],
  editChanges: ['التغييرات:', 'Changes:'],
  editIfMissing: ['(إن لم يكن موجوداً)', '(if missing)'],
  editNameEnLabel: ['الاسم بالإنجليزية:', 'English name:'],
  editNameEnPlaceholder: ['مثال: Al Rahma Mosque', 'e.g. Al Rahma Mosque'],
  editDenomLabel: ['المذهب:', 'Denomination:'],
  editComment: ['تعليق مجموعة التغييرات (changeset):', 'Changeset comment:'],
  editSource: ['المصدر:', 'Source:'],
  sourceLocal: ['معرفة محلية', 'Local knowledge'],
  sourceSurvey: ['مسح ميداني', 'Survey'],
  sourceImagery: ['صور Esri الجوية', 'Esri World Imagery'],
  editUploadNow: ['رفع الآن', 'Upload now'],
  editAddToBatch: ['إضافة إلى الدفعة', 'Add to batch'],
  editCancel: ['إلغاء', 'Cancel'],
  editValueRequired: ['يرجى إدخال القيمة أولاً.', 'Please enter a value first.'],
  editUploading: ['جارٍ الرفع إلى OpenStreetMap...', 'Uploading to OpenStreetMap...'],
  editSuccess: ['تم رفع التعديل بنجاح.', 'Edit uploaded.'],
  editViewChangeset: ['عرض مجموعة التغييرات', 'View changeset'],
  editUnchanged: ['لا حاجة للتعديل: الوسوم على OSM مصححة بالفعل.', 'Nothing to change: the tags on OSM are already fixed.'],
  editConflict: ['تم تعديل هذا العنصر على OSM منذ آخر تحديث للبيانات (النسخة {v}). هل تريد المتابعة وتطبيق التعديل على النسخة الحالية؟', 'This element was edited on OSM since the data was published (now version {v}). Apply the fix to the current version anyway?'],
  editFailed: ['فشل الرفع: {msg}', 'Upload failed: {msg}'],
  editAuthExpired: ['انتهت صلاحية تسجيل الدخول. سجّل الدخول مجدداً.', 'Your login has expired. Please log in again.'],
  batchAdded: ['أضيف إلى الدفعة ({n} تعديل).', 'Added to the batch ({n} edits).'],
  batchAlready: ['هذا التعديل موجود في الدفعة بالفعل.', 'This edit is already in the batch.'],
  batchDock: ['🧺 الدفعة ({n})', '🧺 Batch ({n})'],
  batchTitle: ['دفعة التعديلات', 'Edit batch'],
  batchIntro: ['تُرفع جميع التعديلات أدناه في مجموعة تغييرات واحدة. كل تعديل راجعته بنفسك.', 'All edits below are uploaded in a single changeset. Each one was reviewed by you.'],
  batchEmpty: ['الدفعة فارغة.', 'The batch is empty.'],
  batchRemove: ['إزالة', 'Remove'],
  batchUpload: ['رفع {n} تعديل في مجموعة تغييرات واحدة', 'Upload {n} edits in one changeset'],
  batchClear: ['إفراغ الدفعة', 'Clear batch'],
  batchProgress: ['جارٍ الرفع {current} / {total}...', 'Uploading {current} / {total}...'],
  batchDone: ['تم: {ok} نجح، {skipped} دون تغيير، {conflicts} تعارض، {errors} خطأ.', 'Done: {ok} uploaded, {skipped} unchanged, {conflicts} conflicts, {errors} errors.'],
  batchConflictsKept: ['بقيت التعديلات المتعارضة أو الفاشلة في الدفعة لمراجعتها.', 'Conflicting or failed edits were kept in the batch for review.'],
  historyBtn: ['سجل تعديلاتي', 'My edits'],
  historyTitle: ['سجل التعديلات من هذا المتصفح', 'Edits made from this browser'],
  historyEmpty: ['لم ترفع أي تعديلات من هذا المتصفح بعد.', 'No edits uploaded from this browser yet.'],
  historyItems: ['{n} عنصر', '{n} elements'],
  historyExportCsv: ['تصدير CSV', 'Export CSV'],
  historyExportJson: ['تصدير JSON', 'Export JSON'],
  historyClear: ['مسح السجل', 'Clear history'],
  historyClearConfirm: ['مسح سجل التعديلات المحلي؟ (لا يؤثر على OSM)', 'Clear the local edit history? (OSM is not affected)'],
  close: ['إغلاق', 'Close'],
});

export const FIX_COMMENT_SUMMARY = {
  missing_amenity: 'add amenity=place_of_worship',
  building_yes: 'building=yes -> building=mosque',
  missing_name_en: 'add name:en',
  missing_denom: 'add denomination',
};

// Issue id -> how to fix it. target: which OSM object gets the tags ("poi" is
// the merged POI node when there is one, otherwise the place itself).
export const QUICK_FIXES = {
  missing_amenity: {
    target: 'place',
    source: 'local knowledge',
    edits: () => ({ set: { amenity: 'place_of_worship' }, setIfMissing: { religion: 'muslim' } })
  },
  building_yes: {
    target: 'place',
    source: 'Esri World Imagery',
    applies: props => props.geom_type !== 'Point',
    edits: () => ({ set: { building: 'mosque' } })
  },
  missing_name_en: {
    target: 'poi',
    source: 'local knowledge',
    input: 'text',
    edits: v => ({ set: { 'name:en': v } })
  },
  missing_denom: {
    target: 'poi',
    source: 'local knowledge',
    input: 'select',
    options: ['sunni', 'shia', 'ibadi'],
    edits: v => ({ set: { denomination: v } })
  }
};

export function fixTarget(props, fix) {
  if (fix.target === 'poi' && props.poi_node_id) {
    return { type: 'node', id: props.poi_node_id, expectedVersion: props._editedNodeVersion || props.poi_node_version };
  }
  return { type: osmTypeOf(props), id: props.osm_id, expectedVersion: props._editedVersion || props.version };
}

export function findPlaceByKey(key) {
  return allPlaces.find(f => ReviewMarks.keyOf(f.properties) === key);
}

// Reflects uploaded tags in the loaded data so the issue disappears now, and
// marks the place fixed so it stays hidden until the pipeline publishes the
// new version.
export function applyUploadedTagsToPlace(placeKey, result) {
  const f = findPlaceByKey(placeKey);
  if (!f) return;
  const props = f.properties;
  ReviewMarks.set(props, 'fixed');
  const tags = result.newTags || {};
  if (tags.amenity !== undefined) props.amenity = tags.amenity;
  if (tags.religion !== undefined) props.religion = tags.religion;
  if (tags.denomination !== undefined) props.denomination = tags.denomination;
  if (tags['name:en'] !== undefined) props.name_en = props.name_en_original = tags['name:en'];
  if (result.type === osmTypeOf(props) && result.id === props.osm_id) {
    if (tags.building !== undefined) props.building = tags.building;
    props._editedVersion = result.newVersion;
  } else {
    props._editedNodeVersion = result.newVersion;
  }
}

export function refreshAfterEdits() {
  invalidateIssues();
  updateImprovementIssueCounts();
  refreshAfterReviewChange();
  if (selectedPlace) showDetails(selectedPlace.properties, selectedPlace.lat, selectedPlace.lon);
}

// ---------------------------------------------------------------------------
// Details panel: list the fixes available for the selected place
// ---------------------------------------------------------------------------
export function renderQuickFixes(props) {
  const box = document.getElementById('details-quick-fixes');
  if (!box) return;
  const fixes = getIssues(props)
    .map(i => i.id)
    .filter(id => QUICK_FIXES[id] && (!QUICK_FIXES[id].applies || QUICK_FIXES[id].applies(props)));
  if (!fixes.length) {
    box.style.display = 'none';
    return;
  }
  box.innerHTML = '';
  const title = document.createElement('h3');
  title.className = 'mapper-tools-title';
  title.textContent = t('quickFixesTitle');
  box.appendChild(title);

  if (!OsmApi.canEdit()) {
    const hint = document.createElement('p');
    hint.className = 'quick-fix-hint';
    hint.textContent = t(OsmApi.token() ? 'quickFixesRelogin' : 'quickFixesLogin');
    box.appendChild(hint);
  }
  const buttons = document.createElement('div');
  buttons.className = 'quick-fix-buttons';
  fixes.forEach(id => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'quick-fix-btn';
    btn.textContent = t(`fix_${id}`);
    btn.addEventListener('click', () => openEditDialog(props, id));
    buttons.appendChild(btn);
  });
  box.appendChild(buttons);
  box.style.display = 'block';
}

// ---------------------------------------------------------------------------
// Edit dialog
// ---------------------------------------------------------------------------
export function sourceSelect(selected) {
  const select = document.createElement('select');
  select.className = 'auth-input edit-source';
  [['local knowledge', 'sourceLocal'], ['survey', 'sourceSurvey'], ['Esri World Imagery', 'sourceImagery']].forEach(([value, key]) => {
    const opt = document.createElement('option');
    opt.value = value;
    opt.textContent = t(key);
    if (value === selected) opt.selected = true;
    select.appendChild(opt);
  });
  return select;
}

export function commentField(value) {
  const wrap = document.createElement('div');
  wrap.className = 'client-id-config';
  const label = document.createElement('label');
  label.textContent = t('editComment');
  const area = document.createElement('textarea');
  area.className = 'auth-input edit-comment';
  area.rows = 2;
  area.maxLength = 255;
  area.dir = 'ltr';
  area.value = value;
  const counter = document.createElement('span');
  counter.className = 'input-help edit-comment-counter';
  const update = () => { counter.textContent = `${[...area.value].length} / 255`; };
  area.addEventListener('input', update);
  update();
  wrap.append(label, area, counter);
  return { wrap, area };
}

export function describeEdits(edits) {
  const lines = [];
  Object.entries(edits.set || {}).forEach(([k, v]) => lines.push(`+ ${k}=${v}`));
  Object.entries(edits.setIfMissing || {}).forEach(([k, v]) => lines.push(`+ ${k}=${v} ${t('editIfMissing')}`));
  (edits.del || []).forEach(k => lines.push(`- ${k}`));
  return lines;
}

export function openOverlay(id, build) {
  const overlay = document.getElementById(id);
  const card = overlay.querySelector('.auth-card');
  card.innerHTML = '';
  build(card, () => overlay.classList.add('hidden'));
  overlay.classList.remove('hidden');
  return overlay;
}

export function openEditDialog(props, fixId) {
  const fix = QUICK_FIXES[fixId];
  const target = fixTarget(props, fix);
  const label = placeName(props);

  openOverlay('edit-overlay', (card, close) => {
    const header = document.createElement('div');
    header.className = 'auth-header';
    const h2 = document.createElement('h2');
    h2.textContent = t('editDialogTitle');
    const sub = document.createElement('p');
    sub.textContent = `${t(`fix_${fixId}`)} — ${label}`;
    header.append(h2, sub);

    const body = document.createElement('div');
    body.className = 'auth-body';

    const targetRow = document.createElement('p');
    targetRow.className = 'input-help';
    targetRow.textContent = `${t('editTarget')} ${target.type}/${target.id}`;
    body.appendChild(targetRow);

    let input = null;
    if (fix.input) {
      const wrap = document.createElement('div');
      wrap.className = 'client-id-config';
      const lbl = document.createElement('label');
      if (fix.input === 'text') {
        lbl.textContent = t('editNameEnLabel');
        input = document.createElement('input');
        input.type = 'text';
        input.dir = 'ltr';
        input.placeholder = t('editNameEnPlaceholder');
      } else {
        lbl.textContent = t('editDenomLabel');
        input = document.createElement('select');
        fix.options.forEach(v => {
          const opt = document.createElement('option');
          opt.value = v;
          opt.textContent = `${denomLabel(v)} (${v})`;
          input.appendChild(opt);
        });
      }
      input.className = 'auth-input';
      wrap.append(lbl, input);
      body.appendChild(wrap);
    }

    const changesLabel = document.createElement('label');
    changesLabel.className = 'edit-changes-label';
    changesLabel.textContent = t('editChanges');
    const preview = document.createElement('pre');
    preview.className = 'edit-diff';
    preview.dir = 'ltr';
    const currentValue = () => (input ? input.value.trim() : '');
    const updatePreview = () => { preview.textContent = describeEdits(fix.edits(currentValue() || '…')).join('\n'); };
    if (input) input.addEventListener('input', updatePreview);
    updatePreview();
    body.append(changesLabel, preview);

    const defaultComment = `Saudi places of worship: ${FIX_COMMENT_SUMMARY[fixId]} (${target.type}/${target.id})`;
    const comment = commentField(defaultComment);
    body.appendChild(comment.wrap);

    const sourceWrap = document.createElement('div');
    sourceWrap.className = 'client-id-config';
    const sourceLabel = document.createElement('label');
    sourceLabel.textContent = t('editSource');
    const source = sourceSelect(fix.source);
    sourceWrap.append(sourceLabel, source);
    body.appendChild(sourceWrap);

    const buildItem = () => {
      const value = currentValue();
      if (fix.input && !value) {
        showToast(t('editValueRequired'), 'error');
        return null;
      }
      return {
        ...target,
        edits: fix.edits(value),
        label,
        fixId,
        summary: FIX_COMMENT_SUMMARY[fixId] + (value ? ` (${value})` : ''),
        placeKey: ReviewMarks.keyOf(props),
        source: source.value
      };
    };

    const uploadBtn = document.createElement('button');
    uploadBtn.className = 'auth-submit-btn';
    uploadBtn.textContent = t('editUploadNow');
    uploadBtn.disabled = !OsmApi.canEdit();
    uploadBtn.addEventListener('click', async () => {
      const item = buildItem();
      if (!item) return;
      uploadBtn.disabled = true;
      uploadBtn.textContent = t('editUploading');
      const ok = await uploadSingle(item, comment.area.value, source.value);
      if (ok) close();
      uploadBtn.disabled = false;
      uploadBtn.textContent = t('editUploadNow');
    });

    const batchBtn = document.createElement('button');
    batchBtn.className = 'auth-skip-btn';
    batchBtn.textContent = t('editAddToBatch');
    batchBtn.disabled = !OsmApi.canEdit();
    batchBtn.addEventListener('click', () => {
      const item = buildItem();
      if (!item) return;
      if (EditBatch.add(item)) {
        showToast(t('batchAdded', { n: fmtNum(EditBatch.items().length) }));
        close();
      } else {
        showToast(t('batchAlready'), 'error');
      }
    });

    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'auth-skip-btn';
    cancelBtn.textContent = t('editCancel');
    cancelBtn.addEventListener('click', close);

    body.append(uploadBtn, batchBtn, cancelBtn);
    card.append(header, body);
    if (input) setTimeout(() => input.focus(), 50);
  });
}

export function handleEditError(err) {
  if (err.message === 'AUTH_EXPIRED' || err.message === 'NOT_AUTHENTICATED') {
    showToast(t('editAuthExpired'), 'error');
    document.getElementById('osm-auth-overlay').classList.remove('hidden');
  } else {
    showToast(t('editFailed', { msg: err.message }), 'error');
  }
}

export async function uploadSingle(item, comment, source) {
  try {
    let { changesetId, results } = await OsmApi.applyEdits([item], { comment, source });
    let r = results[0];
    if (r.status === 'conflict') {
      if (!window.confirm(t('editConflict', { v: r.currentVersion }))) return false;
      ({ changesetId, results } = await OsmApi.applyEdits([{ ...item, force: true }], { comment, source }));
      r = results[0];
    }
    if (r.status === 'success') {
      applyUploadedTagsToPlace(item.placeKey, r);
      refreshAfterEdits();
      showToast(t('editSuccess'), 'success', { link: { href: OsmApi.changesetUrl(changesetId), text: t('editViewChangeset') } });
      return true;
    }
    if (r.status === 'unchanged') {
      const f = findPlaceByKey(item.placeKey);
      if (f) ReviewMarks.set(f.properties, 'fixed');
      refreshAfterEdits();
      showToast(t('editUnchanged'));
      return true;
    }
    showToast(t('editFailed', { msg: r.error || r.status }), 'error');
  } catch (err) {
    handleEditError(err);
  }
  return false;
}

// ---------------------------------------------------------------------------
// Batch queue (localStorage), uploaded as one changeset
// ---------------------------------------------------------------------------
export const EditBatch = {
  KEY: 'gcc_edit_batch',

  items() {
    try {
      return JSON.parse(localStorage.getItem(this.KEY)) || [];
    } catch (e) {
      return [];
    }
  },

  _save(items) {
    try {
      localStorage.setItem(this.KEY, JSON.stringify(items));
    } catch (e) {
      // Ignore storage errors in private browsing
    }
    renderBatchDock();
  },

  add(item) {
    const items = this.items();
    if (items.some(i => i.type === item.type && i.id === item.id && i.fixId === item.fixId)) return false;
    items.push(item);
    this._save(items);
    return true;
  },

  remove(index) {
    const items = this.items();
    items.splice(index, 1);
    this._save(items);
  },

  replace(items) {
    this._save(items);
  }
};

export function renderBatchDock() {
  const dock = document.getElementById('batch-dock');
  if (!dock) return;
  const n = EditBatch.items().length;
  dock.textContent = t('batchDock', { n: fmtNum(n) });
  dock.style.display = n ? '' : 'none';
}

export function openBatchDialog() {
  openOverlay('batch-overlay', (card, close) => {
    const items = EditBatch.items();
    const header = document.createElement('div');
    header.className = 'auth-header';
    const h2 = document.createElement('h2');
    h2.textContent = t('batchTitle');
    const intro = document.createElement('p');
    intro.textContent = t('batchIntro');
    header.append(h2, intro);

    const body = document.createElement('div');
    body.className = 'auth-body';
    if (!items.length) {
      const empty = document.createElement('p');
      empty.className = 'input-help';
      empty.textContent = t('batchEmpty');
      body.appendChild(empty);
    }

    const list = document.createElement('ul');
    list.className = 'batch-list';
    items.forEach((item, i) => {
      const li = document.createElement('li');
      const text = document.createElement('span');
      text.textContent = `${item.label} — ${item.summary} (${item.type}/${item.id})`;
      const rm = document.createElement('button');
      rm.type = 'button';
      rm.className = 'review-action-btn subtle';
      rm.textContent = t('batchRemove');
      rm.addEventListener('click', () => {
        EditBatch.remove(i);
        openBatchDialog();
      });
      li.append(text, rm);
      list.appendChild(li);
    });
    body.appendChild(list);

    if (items.length) {
      const summaries = [...new Set(items.map(i => FIX_COMMENT_SUMMARY[i.fixId]))].join(', ');
      const comment = commentField(`Saudi places of worship: fix tags on ${items.length} places (${summaries})`);
      const sourceWrap = document.createElement('div');
      sourceWrap.className = 'client-id-config';
      const sourceLabel = document.createElement('label');
      sourceLabel.textContent = t('editSource');
      const sources = [...new Set(items.map(i => i.source).filter(Boolean))];
      const source = sourceSelect(sources[0] || 'local knowledge');
      sourceWrap.append(sourceLabel, source);

      const progress = document.createElement('div');
      progress.className = 'batch-progress';
      progress.style.display = 'none';
      const bar = document.createElement('div');
      bar.className = 'batch-progress-bar';
      const progressText = document.createElement('span');
      progress.append(bar, progressText);

      const uploadBtn = document.createElement('button');
      uploadBtn.className = 'auth-submit-btn';
      uploadBtn.textContent = t('batchUpload', { n: fmtNum(items.length) });
      uploadBtn.disabled = !OsmApi.canEdit();
      uploadBtn.addEventListener('click', async () => {
        uploadBtn.disabled = true;
        progress.style.display = '';
        try {
          // The source field covers the whole changeset; one value per batch.
          const { changesetId, results } = await OsmApi.applyEdits(items, {
            comment: comment.area.value,
            source: source.value,
            onProgress: ({ current, total }) => {
              bar.style.width = `${Math.round(current / total * 100)}%`;
              progressText.textContent = t('batchProgress', { current: fmtNum(current), total: fmtNum(total) });
            }
          });
          const counts = { success: 0, unchanged: 0, conflict: 0, error: 0 };
          results.forEach(r => {
            counts[r.status] = (counts[r.status] || 0) + 1;
            if (r.status === 'success') applyUploadedTagsToPlace(r.placeKey, r);
            if (r.status === 'unchanged') {
              const f = findPlaceByKey(r.placeKey);
              if (f) ReviewMarks.set(f.properties, 'fixed');
            }
          });
          // Keep only what still needs attention.
          EditBatch.replace(items.filter((_, i) => ['conflict', 'error'].includes(results[i].status)));
          refreshAfterEdits();
          const msg = t('batchDone', {
            ok: fmtNum(counts.success), skipped: fmtNum(counts.unchanged),
            conflicts: fmtNum(counts.conflict), errors: fmtNum(counts.error)
          });
          showToast(counts.conflict || counts.error ? `${msg} ${t('batchConflictsKept')}` : msg,
            counts.error ? 'error' : 'success',
            changesetId ? { link: { href: OsmApi.changesetUrl(changesetId), text: t('editViewChangeset') } } : {});
          close();
        } catch (err) {
          handleEditError(err);
          uploadBtn.disabled = false;
        }
      });

      const clearBtn = document.createElement('button');
      clearBtn.className = 'carto-clear-btn';
      clearBtn.textContent = t('batchClear');
      clearBtn.addEventListener('click', () => {
        EditBatch.replace([]);
        close();
      });
      body.append(comment.wrap, sourceWrap, progress, uploadBtn, clearBtn);
    }

    const closeBtn = document.createElement('button');
    closeBtn.className = 'auth-skip-btn';
    closeBtn.textContent = t('close');
    closeBtn.addEventListener('click', close);
    body.appendChild(closeBtn);
    card.append(header, body);
  });
}

// ---------------------------------------------------------------------------
// History dialog
// ---------------------------------------------------------------------------
export function exportHistory(format) {
  const records = EditHistory.list();
  if (format === 'json') {
    Exporters._download(`sa-worship-edits-${new Date().toISOString().slice(0, 10)}.json`,
      JSON.stringify(records, null, 2), 'application/json');
    return;
  }
  const cell = v => {
    const s = String(v ?? '');
    return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const rows = [['changeset', 'timestamp', 'user', 'environment', 'comment', 'element', 'label', 'version', 'change'].join(',')];
  records.forEach(r => r.items.forEach(item => {
    rows.push([r.changesetId, new Date(r.timestamp).toISOString(), r.user, r.environment, r.comment,
               item.ref, item.label, item.version, item.summary].map(cell).join(','));
  }));
  Exporters._download(`sa-worship-edits-${new Date().toISOString().slice(0, 10)}.csv`,
    '﻿' + rows.join('\r\n'), 'text/csv;charset=utf-8');
}

export function openHistoryDialog() {
  openOverlay('history-overlay', (card, close) => {
    const records = EditHistory.list();
    const header = document.createElement('div');
    header.className = 'auth-header';
    const h2 = document.createElement('h2');
    h2.textContent = t('historyTitle');
    header.appendChild(h2);

    const body = document.createElement('div');
    body.className = 'auth-body';
    if (!records.length) {
      const empty = document.createElement('p');
      empty.className = 'input-help';
      empty.textContent = t('historyEmpty');
      body.appendChild(empty);
    }
    const list = document.createElement('ul');
    list.className = 'batch-list history-list';
    records.forEach(r => {
      const li = document.createElement('li');
      const a = document.createElement('a');
      a.href = r.environment === 'dev'
        ? `https://master.apis.dev.openstreetmap.org/changeset/${r.changesetId}`
        : `https://www.openstreetmap.org/changeset/${r.changesetId}`;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      a.className = 'details-link';
      a.textContent = `#${r.changesetId}`;
      const meta = document.createElement('span');
      meta.textContent = ` ${fmtDate(r.timestamp, true)} · ${t('historyItems', { n: fmtNum(r.items.length) })} · ${r.comment}`;
      li.append(a, meta);
      list.appendChild(li);
    });
    body.appendChild(list);

    if (records.length) {
      const row = document.createElement('div');
      row.className = 'export-buttons';
      [['historyExportCsv', () => exportHistory('csv')], ['historyExportJson', () => exportHistory('json')]].forEach(([key, fn]) => {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'export-btn';
        b.textContent = t(key);
        b.addEventListener('click', fn);
        row.appendChild(b);
      });
      const clearBtn = document.createElement('button');
      clearBtn.className = 'carto-clear-btn';
      clearBtn.textContent = t('historyClear');
      clearBtn.addEventListener('click', () => {
        if (window.confirm(t('historyClearConfirm'))) {
          EditHistory.clear();
          close();
        }
      });
      body.append(row, clearBtn);
    }
    const closeBtn = document.createElement('button');
    closeBtn.className = 'auth-skip-btn';
    closeBtn.textContent = t('close');
    closeBtn.addEventListener('click', close);
    body.appendChild(closeBtn);
    card.append(header, body);
  });
}

export function setupEditing() {
  document.getElementById('batch-dock').addEventListener('click', openBatchDialog);
  document.getElementById('btn-edit-history').addEventListener('click', openHistoryDialog);
  ['edit-overlay', 'batch-overlay', 'history-overlay'].forEach(id => {
    const overlay = document.getElementById(id);
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) overlay.classList.add('hidden');
    });
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      ['edit-overlay', 'batch-overlay', 'history-overlay'].forEach(id => document.getElementById(id).classList.add('hidden'));
    }
  });
  renderBatchDock();
  const historyBtn = document.getElementById('btn-edit-history');
  const renderHistoryBtn = () => { historyBtn.textContent = t('historyBtn'); };
  renderHistoryBtn();
  onLanguageChange(() => {
    renderBatchDock();
    renderHistoryBtn();
  });
}
