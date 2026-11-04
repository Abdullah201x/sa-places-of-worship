// In-app tag fixes for tag-based issues, uploaded through OsmApi (js/osm_api.js).
// Every edit is previewed and confirmed by the mapper; the batch only holds
// fixes that were reviewed one by one, then uploads them in one changeset
// (the osm x wikidata batch pattern). There is deliberately no "fix all".
import { addTranslations, t, fmtNum, fmtDate, onLanguageChange, currentLang } from './i18n.js';
import { ArabicText } from './arabic.js';
import { ReviewMarks, refreshAfterReviewChange } from './review.js';
import { Exporters } from './exporters.js';
import { OsmApi, EditHistory } from './osm_api.js';
import { FIELDS, MOSQUE_PRESET, BUILDING_YES_RULE, fieldLabel, fieldPlaceholder, fieldOptions, optionLabel, normalizeValue, validateValue, outdatedRules, upgradeChanges, tagsFromProps } from './presets.js';
import { allPlaces, selectedPlace, denomLabel, osmTypeOf, getIssues, invalidateIssues, updateImprovementIssueCounts, showToast, placeName, showDetails } from './app.js';
import { FocusMode, CHANGESET_LIMITS, getChangesetSizeReminder } from './focus_mode.js';

addTranslations({
  quickFixesTitle: ['⚡ إصلاح سريع (OSM API)', '⚡ Quick fix (OSM API)'],
  quickFixesLogin: ['سجّل الدخول بحساب OSM لإصلاح هذه الوسوم مباشرة من هنا.', 'Log in with OSM to fix these tags right here.'],
  quickFixesRelogin: ['تسجيل دخولك الحالي لا يتضمن صلاحية التعديل (write_api). سجّل الخروج ثم الدخول مجدداً.', 'Your current login lacks edit permission (write_api). Log out and in again.'],
  fix_missing_amenity: ['إضافة amenity=place_of_worship', 'Add amenity=place_of_worship'],
  fix_building_yes: ['تعديل building=yes إلى building=mosque', 'Change building=yes to building=mosque'],
  fix_missing_name_en: ['إضافة الاسم بالإنجليزية (name:en)', 'Add the English name (name:en)'],
  suggestNameEnBtn: ['✨ اقتراح الاسم الذكي (GASGI)', '✨ Smart Suggest (GASGI)'],
  fix_missing_denom: ['تحديد المذهب (denomination)', 'Set the denomination'],
  fix_outdated_tags: ['تحديث الوسوم القديمة', 'Upgrade outdated tags'],
  fieldUnset: ['-- غير محدد --', '-- Not specified --'],
  fieldErr_tooLong: ['{field}: القيمة أطول من 255 حرفاً.', '{field}: the value is longer than 255 characters.'],
  fieldErr_notNumber: ['{field}: يجب أن تكون القيمة عدداً صحيحاً موجباً.', '{field}: must be a whole, non-negative number.'],
  fieldErr_badOption: ['{field}: اختر قيمة من القائمة.', '{field}: choose a value from the list.'],
  fieldErr_badFormat: ['{field}: صيغة غير صحيحة.', '{field}: the format is not valid.'],
  editDialogTitle: ['مراجعة التعديل قبل الرفع', 'Review the edit before uploading'],
  editTarget: ['العنصر:', 'Element:'],
  editChanges: ['التغييرات:', 'Changes:'],
  editIfMissing: ['(إن لم يكن موجوداً)', '(if missing)'],
  editComment: ['تعليق مجموعة التغييرات (changeset):', 'Changeset comment:'],
  editSource: ['المصدر:', 'Source:'],
  sourceLocal: ['معرفة محلية', 'Local knowledge'],
  sourceSurvey: ['مسح ميداني', 'Survey'],
  sourceTranslating: ['ترجمة', 'Translating'],
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
  outdated_tags: 'upgrade outdated tags',
};

// Issue id -> how to fix it, built from the mosque preset (presets.js).
// target: which OSM object gets the tags ("poi" is the merged POI node when
// there is one, otherwise the place itself); a function picks per place.
// field: the preset field the mapper fills in. edits(value, props) returns
// what OsmApi.applyEditsToTags applies to the element's current tags.
export const QUICK_FIXES = {
  missing_amenity: {
    target: 'place',
    source: 'local knowledge',
    edits: () => {
      const { amenity, ...rest } = MOSQUE_PRESET.addTags;
      return { set: { amenity }, setIfMissing: rest };
    }
  },
  building_yes: {
    target: 'place',
    source: 'Esri World Imagery',
    applies: props => props.geom_type !== 'Point',
    edits: () => ({ upgrade: [BUILDING_YES_RULE] })
  },
  missing_name_en: {
    target: 'poi',
    source: 'translating',
    field: 'name:en',
    edits: v => ({ set: { [FIELDS['name:en'].key]: v } })
  },
  missing_denom: {
    target: 'poi',
    source: 'local knowledge',
    field: 'denomination',
    edits: v => ({ set: { [FIELDS.denomination.key]: v } })
  },
  outdated_tags: {
    // building=* is on the outline; religion and denomination are usually on
    // the merged POI node.
    target: props => (outdatedRules(props).every(r => Object.keys(r.old).every(k => k === 'building')) ? 'place' : 'poi'),
    source: 'local knowledge',
    edits: (_, props) => ({ upgrade: outdatedRules(props) })
  }
};

export function fixTarget(props, fix) {
  const target = typeof fix.target === 'function' ? fix.target(props) : fix.target;
  if (target === 'poi' && props.poi_node_id) {
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
  const markSynced = ReviewMarks.set(props, 'fixed');
  const tags = result.newTags || {};
  if (tags.amenity !== undefined) props.amenity = tags.amenity;
  if (tags.religion !== undefined) props.religion = tags.religion;
  if (tags.denomination !== undefined) props.denomination = tags.denomination;
  else if (result.oldTags && 'denomination' in result.oldTags) props.denomination = 'unknown';
  if (tags['name:en'] !== undefined) props.name_en = props.name_en_original = tags['name:en'];
  if (result.type === osmTypeOf(props) && result.id === props.osm_id) {
    if (tags.building !== undefined) props.building = tags.building;
    props._editedVersion = result.newVersion;
  } else {
    props._editedNodeVersion = result.newVersion;
  }
  return markSynced;
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

  const focusBtn = document.createElement('button');
  focusBtn.type = 'button';
  focusBtn.className = 'quick-fix-focus-btn';
  focusBtn.textContent = t('focusEnterBtn');
  focusBtn.addEventListener('click', () => {
    const coords = selectedPlace ? [selectedPlace.lat, selectedPlace.lon] : null;
    FocusMode.enter({
      ruleId: fixes[0],
      place: { properties: props, geometry: coords ? { coordinates: [coords[1], coords[0]] } : null },
      placesList: allPlaces
    });
  });
  buttons.appendChild(focusBtn);

  box.appendChild(buttons);
  box.style.display = 'block';
}

// ---------------------------------------------------------------------------
// Edit dialog
// ---------------------------------------------------------------------------
export function sourceSelect(selected) {
  const select = document.createElement('select');
  select.className = 'auth-input edit-source';
  [['local knowledge', 'sourceLocal'], ['survey', 'sourceSurvey'], ['translating', 'sourceTranslating'], ['Esri World Imagery', 'sourceImagery']].forEach(([value, key]) => {
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

export function describeEdits(edits, props) {
  const lines = [];
  if (edits.upgrade) {
    upgradeChanges(tagsFromProps(props), edits.upgrade).forEach(({ key, from, to }) => {
      if (from !== undefined) lines.push(`- ${key}=${from}`);
      if (to !== undefined) lines.push(`+ ${key}=${to}`);
    });
  }
  Object.entries(edits.set || {}).forEach(([k, v]) => lines.push(`+ ${k}=${v}`));
  Object.entries(edits.setIfMissing || {}).forEach(([k, v]) => lines.push(`+ ${k}=${v} ${t('editIfMissing')}`));
  (edits.del || []).forEach(k => lines.push(`- ${k}`));
  return lines;
}

// ---------------------------------------------------------------------------
// Preset fields (presets.js) as form controls, shared by the quick-fix dialog
// and the add-mosque form. Each control carries data-field="<field id>".
// ---------------------------------------------------------------------------
function optionText(fieldId, value) {
  const label = optionLabel(fieldId, value, currentLang)
    || (FIELDS[fieldId].key === 'denomination' ? denomLabel(value) : value);
  return label === value ? value : `${label} (${value})`;
}

export function createFieldInput(fieldId, value = '') {
  const field = FIELDS[fieldId];
  let input;
  if (field.type === 'combo') {
    input = document.createElement('select');
    ['', ...fieldOptions(fieldId)].forEach(v => {
      const opt = document.createElement('option');
      opt.value = v;
      opt.textContent = v ? optionText(fieldId, v) : t('fieldUnset');
      input.appendChild(opt);
    });
    input.value = fieldOptions(fieldId).includes(value) ? value : '';
    input.className = 'auth-input';
  } else if (field.type === 'check') {
    input = document.createElement('input');
    input.type = 'checkbox';
    input.checked = normalizeValue(fieldId, value) === field.checkValue;
  } else {
    input = document.createElement('input');
    input.type = 'text';
    if (field.type === 'number') input.inputMode = 'numeric';
    input.placeholder = fieldPlaceholder(fieldId, currentLang);
    input.value = value || '';
    input.className = 'auth-input';
  }
  if (field.dir) input.dir = field.dir;
  input.dataset.field = fieldId;
  return input;
}

// Label + control in the dialogs' usual wrapper. A check renders as a
// checkbox row naming the tag it writes.
export function createFieldRow(fieldId, value, idPrefix) {
  const field = FIELDS[fieldId];
  const input = createFieldInput(fieldId, value);
  input.id = `${idPrefix}-${fieldId.replace(/[^a-z0-9]+/gi, '-')}`;
  if (field.type === 'check') {
    const row = document.createElement('label');
    row.className = 'checkbox-label preset-check';
    const text = document.createElement('span');
    text.textContent = `${fieldLabel(fieldId, currentLang)} (${field.key}=${field.checkValue})`;
    row.append(input, text);
    return row;
  }
  const wrap = document.createElement('div');
  wrap.className = 'client-id-config';
  const label = document.createElement('label');
  label.htmlFor = input.id;
  label.textContent = `${fieldLabel(fieldId, currentLang)} (${field.key}):`;
  wrap.append(label, input);
  return wrap;
}

// { fieldId: raw value } for every preset control under root.
export function readFieldValues(root) {
  const values = {};
  root.querySelectorAll('[data-field]').forEach(el => {
    values[el.dataset.field] = el.type === 'checkbox' ? el.checked : el.value;
  });
  return values;
}

// Marks the invalid controls and returns the message for the first one
// (focused), or null when there are no errors.
export function showFieldErrors(root, errors) {
  root.querySelectorAll('[data-field]').forEach(el => el.removeAttribute('aria-invalid'));
  errors.forEach(({ fieldId }) => {
    root.querySelector(`[data-field="${fieldId}"]`)?.setAttribute('aria-invalid', 'true');
  });
  if (!errors.length) return null;
  const { fieldId, code } = errors[0];
  const first = root.querySelector(`[data-field="${fieldId}"]`);
  const details = first?.closest('details');
  if (details) details.open = true;
  first?.focus();
  return t(`fieldErr_${code}`, { field: fieldLabel(fieldId, currentLang) });
}

export function createBatchEditItem(props, fixId, value = null, customSource = null) {
  const fix = QUICK_FIXES[fixId];
  if (!fix) return null;
  const target = fixTarget(props, fix);
  const label = placeName(props);
  const source = customSource || fix.source || 'Esri World Imagery';
  return {
    ...target,
    edits: fix.edits(value, props),
    label,
    fixId,
    summary: FIX_COMMENT_SUMMARY[fixId] + (value ? ` (${value})` : ''),
    placeKey: ReviewMarks.keyOf(props),
    source
  };
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
    if (fix.field) {
      const wrap = createFieldRow(fix.field, '', 'edit-field');
      input = wrap.querySelector('[data-field]');
      if (fix.field === 'name:en') {
        const arabicName = props.name_original || props['name:ar'] || props.name_ar || props.name_ar_original || props.name || '';
        const suggested = ArabicText.suggestEnglishName(arabicName);
        if (suggested) {
          input.value = suggested;
          const suggestBtn = document.createElement('button');
          suggestBtn.type = 'button';
          suggestBtn.className = 'quick-fix-btn';
          suggestBtn.style.marginTop = '6px';
          suggestBtn.style.fontSize = '0.82rem';
          suggestBtn.style.padding = '4px 8px';
          suggestBtn.style.cursor = 'pointer';
          suggestBtn.textContent = `${t('suggestNameEnBtn')}: "${suggested}"`;
          suggestBtn.addEventListener('click', () => {
            input.value = suggested;
            input.dispatchEvent(new Event('input'));
          });
          wrap.appendChild(suggestBtn);
        }
      }
      body.appendChild(wrap);
    }

    const changesLabel = document.createElement('label');
    changesLabel.className = 'edit-changes-label';
    changesLabel.textContent = t('editChanges');
    const preview = document.createElement('pre');
    preview.className = 'edit-diff';
    preview.dir = 'ltr';
    const currentValue = () => (input ? normalizeValue(fix.field, input.value) : '');
    const updatePreview = () => { preview.textContent = describeEdits(fix.edits(currentValue() || '…', props), props).join('\n'); };
    if (input) ['input', 'change'].forEach(ev => input.addEventListener(ev, updatePreview));
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
      if (fix.field && !value) {
        showToast(t('editValueRequired'), 'error');
        return null;
      }
      const code = fix.field && validateValue(fix.field, value);
      const error = code && showFieldErrors(body, [{ fieldId: fix.field, code }]);
      if (error) {
        showToast(error, 'error');
        return null;
      }
      return createBatchEditItem(props, fixId, value, source.value);
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
      if (ok) {
        close();
        if (FocusMode.isActive()) {
          FocusMode.goToNearestSimilarIssue();
        }
      }
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
        if (FocusMode.isActive()) {
          FocusMode.goToNearestSimilarIssue();
        }
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
    let { changesetId, results } = await OsmApi.applyEdits([item], { comment, source, deferReport: true });
    let r = results[0];
    if (r.status === 'conflict') {
      if (!window.confirm(t('editConflict', { v: r.currentVersion }))) return false;
      ({ changesetId, results } = await OsmApi.applyEdits([{ ...item, force: true }], { comment, source, deferReport: true }));
      r = results[0];
    }
    if (r.status === 'success') {
      // Mark first, report second: /api/v1/edits binds the changeset to the mark.
      await applyUploadedTagsToPlace(item.placeKey, r);
      if (changesetId) OsmApi.reportEdit(changesetId);
      refreshAfterEdits();
      showToast(t('editSuccess'), 'success', { link: { href: OsmApi.changesetUrl(changesetId), text: t('editViewChangeset') } });
      return true;
    }
    if (r.status === 'unchanged') {
      const f = findPlaceByKey(item.placeKey);
      if (f) ReviewMarks.set(f.properties, 'fixed');
      if (changesetId) OsmApi.reportEdit(changesetId);
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
  _listeners: new Set(),

  subscribe(fn) {
    this._listeners.add(fn);
    return () => this._listeners.delete(fn);
  },

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
    this._listeners.forEach(fn => {
      try { fn(items); } catch (_) {}
    });
  },

  isQueued(placeKeyOrProps, fixId = null) {
    const key = typeof placeKeyOrProps === 'string'
      ? placeKeyOrProps
      : ReviewMarks.keyOf(placeKeyOrProps);
    const items = this.items();
    if (fixId) {
      return items.some(i => i.placeKey === key && i.fixId === fixId);
    }
    return items.some(i => i.placeKey === key);
  },

  add(item) {
    const items = this.items();
    if (items.some(i => i.type === item.type && i.id === item.id && i.fixId === item.fixId)) return false;
    items.push(item);
    this._save(items);

    // Changeset size reminder check
    const count = items.length;
    if (
      count === CHANGESET_LIMITS.WARN_THRESHOLD ||
      count === CHANGESET_LIMITS.MAX_RECOMMENDED ||
      (count > CHANGESET_LIMITS.MAX_RECOMMENDED && count % 10 === 0)
    ) {
      const reminder = getChangesetSizeReminder(count, currentLang);
      if (reminder && reminder.shouldWarn) {
        showToast(reminder.text, reminder.level === 'alert' ? 'error' : 'warning');
      }
    }
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
  const rem = getChangesetSizeReminder(n, currentLang);
  dock.textContent = t('batchDock', { n: fmtNum(n) }) + (rem.shouldWarn ? ` ${rem.shortText}` : '');
  dock.className = `batch-dock ${rem.level !== 'ok' ? rem.level : ''}`;
  dock.title = rem.text;
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

    if (items.length) {
      const guideBox = document.createElement('div');
      const rem = getChangesetSizeReminder(items.length, currentLang);
      guideBox.className = `changeset-size-guide ${items.length >= CHANGESET_LIMITS.MAX_RECOMMENDED ? 'alert' : items.length >= CHANGESET_LIMITS.WARN_THRESHOLD ? 'warn' : 'ok'}`;
      guideBox.innerHTML = `
        <div class="size-guide-header">
          <span class="size-guide-icon">${items.length >= CHANGESET_LIMITS.MAX_RECOMMENDED ? '🛑' : items.length >= CHANGESET_LIMITS.WARN_THRESHOLD ? '⚠️' : '💡'}</span>
          <strong class="size-guide-title">${t('changesetGuideTitle')}</strong>
        </div>
        <p class="size-guide-body">${t('changesetGuideBody')}</p>
        <div class="size-guide-meter">
          <div class="meter-track">
            <div class="meter-fill ${items.length >= CHANGESET_LIMITS.MAX_RECOMMENDED ? 'alert' : items.length >= CHANGESET_LIMITS.WARN_THRESHOLD ? 'warn' : 'ok'}" style="width: ${Math.min(100, Math.round(items.length / CHANGESET_LIMITS.MAX_RECOMMENDED * 100))}%"></div>
          </div>
          <span class="meter-label">${t('changesetMeterLabel', { n: fmtNum(items.length) })}</span>
        </div>
        ${rem.shouldWarn ? `<div class="size-guide-alert">${rem.text}</div>` : ''}
      `;
      body.appendChild(guideBox);
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
            deferReport: true,
            onProgress: ({ current, total }) => {
              bar.style.width = `${Math.round(current / total * 100)}%`;
              progressText.textContent = t('batchProgress', { current: fmtNum(current), total: fmtNum(total) });
            }
          });
          const counts = { success: 0, unchanged: 0, conflict: 0, error: 0 };
          const markSyncs = [];
          results.forEach(r => {
            counts[r.status] = (counts[r.status] || 0) + 1;
            if (r.status === 'success') markSyncs.push(applyUploadedTagsToPlace(r.placeKey, r));
            if (r.status === 'unchanged') {
              const f = findPlaceByKey(r.placeKey);
              if (f) ReviewMarks.set(f.properties, 'fixed');
            }
          });
          // Marks reach the server before the changeset is reported for binding.
          await Promise.all(markSyncs);
          if (changesetId) OsmApi.reportEdit(changesetId);
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
