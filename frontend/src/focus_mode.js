// Focus Mode: Fast-triage and rapid QA fixing workflow.
// Keeps mapper in a focused state for a specific issue rule (e.g. building=yes),
// with controls to jump to the nearest similar issue, 1-click batching,
// and reminders to limit changeset sizes according to OSM best practices.

import { addTranslations, t, currentLang, fmtNum } from './i18n.js';
import { shortcutKey } from './keys.js';
import { calculateDistanceKm } from './qa_view.js';
import { ReviewMarks, refreshAfterReviewChange } from './review.js';
import { EditBatch, createBatchEditItem, openBatchDialog, refreshAfterEdits } from './editing.js';
import { OsmApi } from './osm_api.js';
import { getIssues } from './app.js';
import { showToast } from './ui.js';

export function placeName(props) {
  if (!props) return '';
  return props.name || props.name_en || (currentLang === 'ar' ? 'مكان بدون اسم' : 'Unnamed place');
}

export const CHANGESET_LIMITS = {
  TIP_THRESHOLD: 15,
  WARN_THRESHOLD: 25,
  MAX_RECOMMENDED: 50,
};

addTranslations({
  focusModeBadge: ['🎯 وضع التركيز', '🎯 Focus Mode'],
  focusModeTitle: ['وضع التركيز: {rule}', 'Focus Mode: {rule}'],
  focusRemainingCount: ['متبقي {n} مكان مشابه', '{n} similar places remaining'],
  focusNearestInfo: ['الأقرب: {name} ({dist})', 'Nearest: {name} ({dist})'],
  focusFixAndNext: ['⚡ إضافة للدفعة والتالي', '⚡ Add to Batch & Next'],
  focusNextNearest: ['⏩ الأقرب التالي', '⏩ Next Nearest'],
  focusPrev: ['⏪ السابق', '⏪ Previous'],
  focusSkip: ['⏭️ تخطي', '⏭️ Skip'],
  focusExit: ['✕ إنهاء التركيز', '✕ Exit Focus'],
  focusBatchBtn: ['🧺 الدفعة ({n})', '🧺 Batch ({n})'],
  focusEnterBtn: ['🎯 وضع التركيز لمشابهات هذا الخطأ', '🎯 Focus on similar issues'],
  focusStartRule: ['🎯 بدء وضع التركيز ({rule})', '🎯 Start Focus Mode ({rule})'],
  focusAllDone: ['🎉 اكتملت مراجعة جميع المساجد المشابهة لهذا الخطأ!', '🎉 All similar places for this rule have been reviewed!'],
  focusBatchAdded: ['✓ أضيف للدفعة ({n} تعديل) · الأقرب: {dist}', '✓ Added to batch ({n} edits) · Nearest: {dist}'],
  focusLoginRequired: ['سجّل الدخول بحساب OSM أولاً لتتمكن من إضافة التعديلات إلى الدفعة.', 'Log in with OSM first to add fixes to the batch.'],
  focusNoPrevious: ['لا توجد أماكن سابقة في هذه الجلسة.', 'No previous places in this focus session.'],
  changesetSizeTip: ['💡 حجم مناسب: {n} تعديل (يُنصح بـ 20-30 تعديل للمجموعة).', '💡 Good batch size: {n} edits (20–30 edits recommended per changeset).'],
  changesetSizeWarn: ['⚠️ تذكير: بلغت الدفعة {n} تعديلاً. يُنصح برفع مجموعة التغييرات الآن للحفاظ على حجم معتدل ومراجعة أسهل على OSM.', '⚠️ Reminder: Batch has {n} edits. Uploading now is recommended to keep your changeset size moderate for peer review.'],
  changesetSizeAlert: ['🛑 تنبيه: وصلت الدفعة إلى {n} تعديلاً (الحد الأقصى الموصى به 50). يرجى رفع مجموعة التغييرات الآن لتفادي المجموعات الضخمة على OSM!', '🛑 Alert: Batch reached {n} edits (50 is max recommended). Please upload your changeset now to avoid massive diffs on OSM!'],
  changesetUploadNow: ['رفع الدفعة الآن', 'Upload Batch Now'],
  changesetGuideTitle: ['إرشادات حجم مجموعة التغييرات (OSM Changeset Size)', 'OSM Changeset Size Guidelines'],
  changesetGuideBody: ['توصي إرشادات مجتمع خريطة الشارع المفتوحة بإبقاء مجموعات التغييرات صغيرة ومحددة (بين 20 و 50 تعديلاً كحد أقصى) لتسهيل مراجعتها على أدوات مثل OSMCha وتجنب التعارضات الكبيرة.', 'OpenStreetMap community best practices recommend keeping changesets small (20 to 50 edits maximum) so peer mappers can easily inspect them on OSMCha and merge conflicts are minimized.'],
  changesetMeterLabel: ['{n} / 50 تعديل (الحد الأقصى الموصى به)', '{n} / 50 edits (recommended maximum)'],
});

export function formatDistance(km, lang = 'ar') {
  if (km === null || km === undefined || !Number.isFinite(km)) return '–';
  const isAr = lang === 'ar';
  if (km < 1) {
    const meters = Math.round(km * 1000);
    return `${meters} ${isAr ? 'م' : 'm'}`;
  }
  return `${km.toFixed(1)} ${isAr ? 'كم' : 'km'}`;
}

export function getFeatureCoordinates(f) {
  if (!f) return null;
  if (Array.isArray(f.coordinates) && f.coordinates.length >= 2) {
    return [f.coordinates[1], f.coordinates[0]]; // [lat, lon]
  }
  if (f.geometry && Array.isArray(f.geometry.coordinates)) {
    const coords = f.geometry.coordinates;
    if (typeof coords[0] === 'number') {
      return [coords[1], coords[0]]; // [lat, lon]
    }
  }
  if (Number.isFinite(f.lat) && Number.isFinite(f.lon)) {
    return [f.lat, f.lon];
  }
  return null;
}

export function doesPlaceMatchRule(props, ruleId) {
  if (!props || !ruleId) return false;
  if (ruleId === 'building_yes') {
    // Same exclusion as QUICK_FIXES.building_yes.applies in editing.js
    return props.religion === 'muslim' && props.building === 'yes' && props.geom_type !== 'Point';
  }
  // getIssues() applies the user's current size/Qibla thresholds, matching the QA list
  return getIssues(props).some(r => r.id === ruleId);
}

export function getChangesetSizeReminder(count, lang = 'ar') {
  const isAr = lang === 'ar';
  if (count >= CHANGESET_LIMITS.MAX_RECOMMENDED) {
    return {
      level: 'alert',
      text: isAr
        ? `🛑 تنبيه: وصلت الدفعة إلى ${count} تعديلاً (الحد الأقصى الموصى به 50). يرجى رفع مجموعة التغييرات الآن لتفادي المجموعات الضخمة على OSM!`
        : `🛑 Alert: Batch reached ${count} edits (50 is max recommended). Please upload your changeset now to avoid massive diffs on OSM!`,
      shortText: isAr ? `🛑 الحد الأقصى (${count})` : `🛑 Limit reached (${count})`,
      shouldWarn: true,
    };
  }
  if (count >= CHANGESET_LIMITS.WARN_THRESHOLD) {
    return {
      level: 'warn',
      text: isAr
        ? `⚠️ تذكير: بلغت الدفعة ${count} تعديلاً. يُنصح برفع مجموعة التغييرات الآن للحفاظ على حجم معتدل ومراجعة أسهل على OSM.`
        : `⚠️ Reminder: Batch has ${count} edits. Uploading now is recommended to keep your changeset size moderate for peer review.`,
      shortText: isAr ? `⚠️ يُنصح بالرفع (${count})` : `⚠️ Upload recommended (${count})`,
      shouldWarn: true,
    };
  }
  if (count >= CHANGESET_LIMITS.TIP_THRESHOLD) {
    return {
      level: 'tip',
      text: isAr
        ? `💡 حجم مناسب: ${count} تعديل (يُنصح بـ 20-30 تعديل للمجموعة).`
        : `💡 Good batch size: ${count} edits (20–30 edits recommended per changeset).`,
      shortText: isAr ? `💡 حجم مناسب (${count})` : `💡 Good size (${count})`,
      shouldWarn: false,
    };
  }
  return {
    level: 'ok',
    text: isAr ? `${count} تعديل في الدفعة` : `${count} edits in batch`,
    shortText: `${count}`,
    shouldWarn: false,
  };
}

export function findNearestSimilarIssue(currentPlace, ruleId, places = [], options = {}) {
  if (!ruleId || !places || !places.length) {
    return { nearest: null, distanceKm: null, remainingCount: 0, allSimilar: [] };
  }

  const currentCoords = getFeatureCoordinates(currentPlace);
  const excludeKeys = options.excludeKeys instanceof Set
    ? options.excludeKeys
    : new Set(options.excludeKeys || []);

  if (currentPlace && currentPlace.properties) {
    excludeKeys.add(ReviewMarks.keyOf(currentPlace.properties));
  } else if (currentPlace && currentPlace.osm_id) {
    excludeKeys.add(`${currentPlace.osm_type || 'way'}/${currentPlace.osm_id}`);
  }

  const candidates = [];

  for (let i = 0; i < places.length; i++) {
    const p = places[i];
    const props = p.properties || {};
    const key = ReviewMarks.keyOf(props);

    if (excludeKeys.has(key)) continue;

    // Check review mark (skip already fixed or skipped places)
    const mark = ReviewMarks.get(props);
    if (mark && (mark.status === 'fixed' || mark.status === 'skipped')) continue;

    // Check if already queued in EditBatch
    if (EditBatch.isQueued(key, ruleId)) continue;

    // Check rule match
    const matches = options.matcher
      ? options.matcher(props, ruleId)
      : doesPlaceMatchRule(props, ruleId);

    if (!matches) continue;

    const coords = getFeatureCoordinates(p);
    if (!coords) continue;

    let dist = 99999;
    if (currentCoords) {
      const d = calculateDistanceKm(currentCoords[0], currentCoords[1], coords[0], coords[1]);
      if (d !== null) dist = d;
    }

    candidates.push({ place: p, distanceKm: dist, coords, key });
  }

  candidates.sort((a, b) => {
    if (a.distanceKm !== b.distanceKm) return a.distanceKm - b.distanceKm;
    const idA = a.place.properties?.osm_id || a.place.id || 0;
    const idB = b.place.properties?.osm_id || b.place.id || 0;
    return idA - idB;
  });

  const nearest = candidates.length > 0 ? candidates[0].place : null;
  const distanceKm = candidates.length > 0 ? candidates[0].distanceKm : null;

  return {
    nearest,
    distanceKm: distanceKm === 99999 ? null : distanceKm,
    remainingCount: candidates.length,
    allSimilar: candidates.map(c => c.place),
  };
}

// ---------------------------------------------------------------------------
// Focus Mode State & Controller
// ---------------------------------------------------------------------------
let focusActive = false;
let focusRuleId = null;
let currentFocusPlace = null;
let focusHistory = [];
let focusCallbacks = {};
let keydownListener = null;

export const FocusMode = {
  isActive() {
    return focusActive;
  },

  getActiveRule() {
    return focusRuleId;
  },

  getCurrentPlace() {
    return currentFocusPlace;
  },

  setup(callbacks = {}) {
    focusCallbacks = callbacks;

    // Listen to EditBatch changes to keep Focus HUD updated
    EditBatch.subscribe(() => {
      if (focusActive) {
        this.renderHUD();
      }
    });

    if (!keydownListener) {
      keydownListener = (e) => {
        if (!focusActive) return;
        if (e.ctrlKey || e.metaKey || e.altKey) return;

        const tag = (e.target.tagName || '').toLowerCase();
        if (tag === 'input' || tag === 'textarea' || tag === 'select' || e.target.isContentEditable) return;
        const anyModalOpen = [...document.querySelectorAll('.auth-overlay')].some(o => !o.classList.contains('hidden'));
        if (anyModalOpen) return;

        const key = shortcutKey(e);
        const handled = key === 'Escape' || key === ']' || key === 'n' || key === '[' || key === 'p' ||
          key === 's' || key === 'f' || key === ' ' || key === 'b' || key === 'u' ||
          e.key === 'ArrowRight' || e.key === 'ArrowLeft';
        // Keep the review/QA shortcuts (n/p/f/s) from also firing on the same key
        if (handled) e.stopPropagation();

        if (key === 'Escape') {
          e.preventDefault();
          this.exit();
        } else if (key === ']' || key === 'n' || e.key === 'ArrowRight') {
          e.preventDefault();
          this.goToNearestSimilarIssue();
        } else if (key === '[' || key === 'p' || e.key === 'ArrowLeft') {
          e.preventDefault();
          this.goToPrevious();
        } else if (key === 's') {
          e.preventDefault();
          this.skipCurrentAndGoToNext();
        } else if (key === 'f' || key === ' ') {
          e.preventDefault();
          this.fixCurrentAndGoToNext();
        } else if (key === 'b' || key === 'u') {
          e.preventDefault();
          openBatchDialog();
        }
      };
      // Capture phase, so this runs before the bubble-phase review/QA handlers
      document.addEventListener('keydown', keydownListener, true);
    }
  },

  enter({ ruleId, place, placesList = null }) {
    if (!ruleId) return;
    focusActive = true;
    focusRuleId = ruleId;
    currentFocusPlace = place;
    focusHistory = [];

    if (placesList && focusCallbacks.setPlacesList) {
      focusCallbacks.setPlacesList(placesList);
    }

    this.renderHUD();

    // Check if initial batch size has a reminder
    const itemsCount = EditBatch.items().length;
    if (itemsCount >= CHANGESET_LIMITS.WARN_THRESHOLD) {
      const rem = getChangesetSizeReminder(itemsCount, currentLang);
      if (rem.shouldWarn) {
        showToast(rem.text, rem.level === 'alert' ? 'error' : 'warning');
      }
    }
  },

  exit() {
    focusActive = false;
    focusRuleId = null;
    currentFocusPlace = null;
    focusHistory = [];
    const hud = document.getElementById('focus-mode-hud');
    if (hud) hud.classList.add('hidden');
  },

  setCurrentPlace(place) {
    currentFocusPlace = place;
    if (focusActive) {
      this.renderHUD();
    }
  },

  goToNearestSimilarIssue() {
    if (!focusActive || !focusRuleId) return;

    const places = focusCallbacks.getPlaces ? focusCallbacks.getPlaces() : [];
    const { nearest } = findNearestSimilarIssue(
      currentFocusPlace,
      focusRuleId,
      places
    );

    if (!nearest) {
      showToast(t('focusAllDone'), 'success');
      this.renderHUD();
      return;
    }

    if (currentFocusPlace) {
      focusHistory.push(currentFocusPlace);
    }

    currentFocusPlace = nearest;
    const coords = getFeatureCoordinates(nearest);

    if (coords && focusCallbacks.onNavigateToPlace) {
      focusCallbacks.onNavigateToPlace(nearest, coords[0], coords[1]);
    }

    this.renderHUD();
  },

  goToPrevious() {
    if (!focusActive || !focusHistory.length) {
      showToast(t('focusNoPrevious'), 'info');
      return;
    }

    const prev = focusHistory.pop();
    currentFocusPlace = prev;
    const coords = getFeatureCoordinates(prev);

    if (coords && focusCallbacks.onNavigateToPlace) {
      focusCallbacks.onNavigateToPlace(prev, coords[0], coords[1]);
    }

    this.renderHUD();
  },

  skipCurrentAndGoToNext() {
    if (!focusActive || !currentFocusPlace) return;

    const props = currentFocusPlace.properties || currentFocusPlace;
    ReviewMarks.set(props, 'skipped');
    refreshAfterReviewChange();

    this.goToNearestSimilarIssue();
  },

  async fixCurrentAndGoToNext() {
    if (!focusActive || !currentFocusPlace || !focusRuleId) return;

    const props = currentFocusPlace.properties || currentFocusPlace;

    // Check if user has OSM edit permissions
    if (!OsmApi.canEdit()) {
      showToast(t('focusLoginRequired'), 'warning');
      if (focusCallbacks.onOpenEditDialog) {
        focusCallbacks.onOpenEditDialog(props, focusRuleId);
      }
      return;
    }

    // Deterministic tag fixes can be queued with one key. building=yes ->
    // building=mosque is not one of them: the footprint must be confirmed on
    // imagery, so it goes through the edit dialog (tag diff, explicit upload).
    if (focusRuleId === 'missing_amenity' || focusRuleId === 'outdated_tags') {
      const item = createBatchEditItem(props, focusRuleId);
      if (!item) return;

      const added = EditBatch.add(item);
      if (added) {
        // The place is marked fixed (and its tags updated locally) only after
        // the batch uploads; until then findNearestSimilarIssue skips it
        // because it is queued, and discarding the batch leaves it untouched.
        refreshAfterEdits();

        const count = EditBatch.items().length;
        const places = focusCallbacks.getPlaces ? focusCallbacks.getPlaces() : [];
        const nextInfo = findNearestSimilarIssue(currentFocusPlace, focusRuleId, places);
        const distStr = formatDistance(nextInfo.distanceKm, currentLang);

        showToast(
          t('focusBatchAdded', { n: fmtNum(count), dist: distStr }),
          'success'
        );

        // Advance to next nearest
        this.goToNearestSimilarIssue();
      } else {
        showToast(t('batchAlready'), 'error');
      }
    } else {
      // Fixes requiring text input (name:en, denomination, etc.) open the edit dialog
      if (focusCallbacks.onOpenEditDialog) {
        focusCallbacks.onOpenEditDialog(props, focusRuleId);
      }
    }
  },

  renderHUD() {
    if (!focusActive) return;

    let hud = document.getElementById('focus-mode-hud');
    if (!hud) {
      hud = document.createElement('div');
      hud.id = 'focus-mode-hud';
      hud.className = 'focus-mode-hud';
      hud.setAttribute('role', 'region');
      hud.setAttribute('aria-label', t('focusModeBadge'));
      document.body.appendChild(hud);
    }

    hud.classList.remove('hidden');

    const places = focusCallbacks.getPlaces ? focusCallbacks.getPlaces() : [];
    const { nearest, distanceKm, remainingCount } = findNearestSimilarIssue(
      currentFocusPlace,
      focusRuleId,
      places
    );

    const isAr = currentLang === 'ar';
    const props = currentFocusPlace?.properties || currentFocusPlace || {};
    const curName = placeName(props) || (isAr ? 'مكان غير مسمى' : 'Unnamed place');
    const nextName = nearest ? placeName(nearest.properties || nearest) : (isAr ? 'لا يوجد' : 'None');
    const distText = formatDistance(distanceKm, currentLang);
    const batchCount = EditBatch.items().length;
    const reminder = getChangesetSizeReminder(batchCount, currentLang);

    // Rule display title
    const ruleTitles = {
      building_yes: isAr ? 'building=yes (تصنيف مبنى عام)' : 'building=yes (Generic Building)',
      missing_amenity: isAr ? 'missing_amenity (مبنى بدون وسم)' : 'missing_amenity (Untagged Outline)',
      missing_name_en: isAr ? 'missing_name_en (الاسم بالإنجليزي)' : 'missing_name_en (English Name)',
      missing_denom: isAr ? 'missing_denom (المذهب)' : 'missing_denom (Denomination)',
      qibla_deviation: isAr ? 'qibla_deviation (انحراف القبلة)' : 'qibla_deviation (Qibla Deviation)',
      ml_geometry_anomaly: isAr ? 'ml_geometry_anomaly (شذوذ هندسي)' : 'ml_geometry_anomaly (ML Anomaly)',
      duplicate_poi: isAr ? 'duplicate_poi (مكرر)' : 'duplicate_poi (Duplicate POI)',
      outdated_tags: isAr ? 'outdated_tags (وسوم قديمة)' : 'outdated_tags (Outdated Tags)',
    };
    const ruleLabel = ruleTitles[focusRuleId] || focusRuleId;

    hud.innerHTML = `
      <div class="focus-hud-container" dir="${isAr ? 'rtl' : 'ltr'}">
        <div class="focus-hud-header">
          <div class="focus-hud-title-wrap">
            <span class="focus-hud-badge">🎯 ${isAr ? 'وضع التركيز' : 'Focus Mode'}</span>
            <span class="focus-hud-rule">${escapeHtml(ruleLabel)}</span>
            <span class="focus-hud-count">(${fmtNum(remainingCount)} ${isAr ? 'مشابه متبقي' : 'similar left'})</span>
          </div>

          <div class="focus-hud-current-info">
            <span class="focus-current-label">${isAr ? 'الحالي:' : 'Current:'}</span>
            <strong class="focus-current-name">${escapeHtml(curName)}</strong>
            <span class="focus-divider">·</span>
            <span class="focus-next-label">${isAr ? 'الأقرب التالي:' : 'Next:'}</span>
            <span class="focus-next-name">${escapeHtml(nextName)} (${distText})</span>
          </div>

          <button type="button" id="focus-btn-exit" class="focus-btn-exit" title="${t('focusExit')} (Esc)">
            ✕
          </button>
        </div>

        <div class="focus-hud-toolbar">
          <div class="focus-hud-actions-primary">
            <button type="button" id="focus-btn-fix" class="focus-action-btn primary" title="${t('focusFixAndNext')} (Space / F)">
              <span class="btn-icon">⚡</span>
              <span>${t('focusFixAndNext')}</span>
              <kbd class="focus-kbd">Space</kbd>
            </button>

            <button type="button" id="focus-btn-next" class="focus-action-btn" title="${t('focusNextNearest')} (] / N)">
              <span class="btn-icon">⏩</span>
              <span>${t('focusNextNearest')}</span>
              <kbd class="focus-kbd">]</kbd>
            </button>

            <button type="button" id="focus-btn-skip" class="focus-action-btn subtle" title="${t('focusSkip')} (S)">
              <span class="btn-icon">⏭️</span>
              <span>${t('focusSkip')}</span>
              <kbd class="focus-kbd">S</kbd>
            </button>

            <button type="button" id="focus-btn-prev" class="focus-action-btn subtle" title="${t('focusPrev')} ([ / P)" ${focusHistory.length === 0 ? 'disabled' : ''}>
              <span class="btn-icon">⏪</span>
              <span>${t('focusPrev')}</span>
              <kbd class="focus-kbd">[</kbd>
            </button>
          </div>

          <div class="focus-hud-batch-section">
            <button type="button" id="focus-btn-batch" class="focus-batch-btn ${reminder.level !== 'ok' ? reminder.level : ''}" title="${escapeHtml(reminder.text)}">
              <span class="batch-icon">🧺</span>
              <span class="batch-text">${t('focusBatchBtn', { n: fmtNum(batchCount) })}</span>
              ${reminder.shouldWarn ? `<span class="reminder-tag">${reminder.shortText}</span>` : ''}
            </button>
          </div>
        </div>

        ${reminder.shouldWarn ? `
          <div class="focus-changeset-warning ${reminder.level}">
            <span class="warn-icon">${reminder.level === 'alert' ? '🛑' : '⚠️'}</span>
            <span class="warn-text">${escapeHtml(reminder.text)}</span>
            <button type="button" id="focus-btn-upload-now" class="focus-warn-action">
              ${t('changesetUploadNow')} 🚀
            </button>
          </div>
        ` : ''}
      </div>
    `;

    // Bind HUD events
    document.getElementById('focus-btn-exit')?.addEventListener('click', () => this.exit());
    document.getElementById('focus-btn-fix')?.addEventListener('click', () => this.fixCurrentAndGoToNext());
    document.getElementById('focus-btn-next')?.addEventListener('click', () => this.goToNearestSimilarIssue());
    document.getElementById('focus-btn-skip')?.addEventListener('click', () => this.skipCurrentAndGoToNext());
    document.getElementById('focus-btn-prev')?.addEventListener('click', () => this.goToPrevious());
    document.getElementById('focus-btn-batch')?.addEventListener('click', () => openBatchDialog());
    document.getElementById('focus-btn-upload-now')?.addEventListener('click', () => openBatchDialog());
  }
};

function escapeHtml(str) {
  return String(str || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}
