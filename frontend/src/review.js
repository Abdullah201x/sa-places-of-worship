// Mapper review workflow: fixed/skipped marks, the N/P review queue,
// permalinks and keyboard shortcuts. Uses app.js globals (map, filteredPlaces,
// currentMode, ...) at call time.
import { addTranslations, currentLang, t, fmtNum } from './i18n.js';
import { shortcutKey } from './keys.js';
import { map, allPlaces, filteredPlaces, currentMode, currentReligionFilter, currentImprovementFilter, currentSearchQuery, setCurrentSearchQuery, currentQiblaSort, selectedPlace, osmTypeOf, updateImprovementIssueCounts, showToast, showDetails, filterData } from './app.js';

addTranslations({
  reviewFixed: ['✓ تم الإصلاح', '✓ Fixed'],
  reviewSkipped: ['⏭ تم التخطي', '⏭ Skipped'],
  reviewMarkFixed: ['✓ تم الإصلاح (F)', '✓ Mark fixed (F)'],
  reviewMarkSkip: ['⏭ تخطي (S)', '⏭ Skip (S)'],
  reviewUnmark: ['↺ إلغاء العلامة', '↺ Clear mark'],
  reviewMarkedFixedToast: ['تم وضع علامة "تم الإصلاح". ستختفي العلامة تلقائياً عند وصول بيانات أحدث من OSM.', 'Marked as fixed. The mark clears itself once newer OSM data arrives.'],
  reviewMarkedSkippedToast: ['تم تخطي هذا المكان.', 'Place skipped.'],
  reviewCounter: ['{label} [{pos} من {total}]', '{label} [{pos} of {total}]'],
  reviewLabelQiblaLeast: ['الأقل دقة', 'Least accurate'],
  reviewLabelQiblaMost: ['الأكثر دقة', 'Most accurate'],
  reviewLabelNearest: ['الأقرب للخريطة', 'Nearest first'],
  reviewEmpty: ['لا توجد أماكن للمراجعة', 'Nothing left to review'],
  reviewedToday: ['راجعت اليوم: {n}', 'Reviewed today: {n}'],
  reviewDone: ['انتهت قائمة المراجعة الحالية 🎉', 'You reached the end of this review list 🎉'],
});

// ---------------------------------------------------------------------------
// Marks: localStorage { "way/123": { status, version, at } }. A mark expires
// automatically once the published data has a newer version of the object,
// i.e. someone edited it in OSM since it was marked.
// ---------------------------------------------------------------------------
export const ReviewMarks = {
  KEY: 'gcc_review_marks',
  _marks: null,

  _load() {
    if (this._marks) return this._marks;
    try {
      this._marks = JSON.parse(localStorage.getItem(this.KEY)) || {};
    } catch (e) {
      this._marks = {};
    }
    return this._marks;
  },

  _save() {
    try {
      localStorage.setItem(this.KEY, JSON.stringify(this._marks));
    } catch (e) {
      // Ignore storage errors in private browsing
    }
  },

  keyOf(props) {
    return `${osmTypeOf(props)}/${props.osm_id}`;
  },

  get(props) {
    const mark = this._load()[this.keyOf(props)];
    if (!mark) return null;
    if (mark.version && props.version > mark.version) return null; // edited since: issue re-evaluated from fresh data
    return mark;
  },

  // Returns a promise that settles once the mark reached the server (never
  // rejects), so callers can wait for it before asking /api/v1/edits to bind
  // the changeset to this mark.
  set(props, status) {
    this._load()[this.keyOf(props)] = { status, version: props.version, at: Date.now() };
    let synced = Promise.resolve();
    if (localStorage.getItem('osm_access_token')) {
      const type = osmTypeOf(props);
      synced = fetch(`/api/v1/reviews/${type}/${props.osm_id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', 'X-Manara-CSRF': '1' },
        body: JSON.stringify({ status, version: props.version })
      }).catch(e => console.warn('Could not sync review mark to server:', e));
    }
    this._save();
    return synced;
  },

  clear(props) {
    delete this._load()[this.keyOf(props)];
    if (localStorage.getItem('osm_access_token')) {
      const type = osmTypeOf(props);
      fetch(`/api/v1/reviews/${type}/${props.osm_id}`, {
        method: 'DELETE',
        headers: { 'X-Manara-CSRF': '1' }
      }).catch(e => console.warn('Could not delete review mark on server:', e));
    }
    this._save();
  },

  async sync() {
    try {
      const res = await fetch('/api/v1/reviews');
      if (!res.ok) return;
      const data = await res.json();
      if (!data.marks) return;
      const local = this._load();
      let changed = false;
      for (const [key, serverMark] of Object.entries(data.marks)) {
        if (!local[key] || local[key].version <= serverMark.version) {
          local[key] = {
            status: serverMark.status,
            version: serverMark.version,
            at: serverMark.created_at ? new Date(serverMark.created_at).getTime() : Date.now(),
            verified: serverMark.verified,
          };
          changed = true;
        }
      }
      if (changed) this._save();

      // One-time import of legacy local marks upon first authenticated run
      if (localStorage.getItem('osm_access_token') && !localStorage.getItem('gcc_marks_migrated')) {
        for (const [key, mark] of Object.entries(local)) {
          if (!data.marks[key]) {
            const [type, id] = key.split('/');
            fetch(`/api/v1/reviews/${type}/${id}`, {
              method: 'PUT',
              headers: { 'Content-Type': 'application/json', 'X-Manara-CSRF': '1' },
              body: JSON.stringify({ status: mark.status, version: mark.version || 1 }),
            }).catch(() => {});
          }
        }
        localStorage.setItem('gcc_marks_migrated', '1');
      }
    } catch (_) {}
  },

  countToday() {
    const start = new Date();
    start.setHours(0, 0, 0, 0);
    return Object.values(this._load()).filter(m => m.at >= start.getTime()).length;
  },

  // Drops marks that newer data has superseded so storage doesn't grow forever.
  prune(places) {
    const marks = this._load();
    const versions = new Map(places.map(f => [this.keyOf(f.properties), f.properties.version]));
    let changed = false;
    Object.keys(marks).forEach(k => {
      const v = versions.get(k);
      if (v === undefined || (marks[k].version && v > marks[k].version)) {
        delete marks[k];
        changed = true;
      }
    });
    if (changed) this._save();
  }
};

export let hideReviewedPlaces = true;
export function setHideReviewedPlaces(value) {
  hideReviewedPlaces = value;
}

export function isHiddenByReview(props) {
  return hideReviewedPlaces && currentMode === 'improve' && ReviewMarks.get(props) !== null;
}

export function markCurrentPlace(status) {
  if (!selectedPlace) return;
  ReviewMarks.set(selectedPlace.properties, status);
  showToast(t(status === 'fixed' ? 'reviewMarkedFixedToast' : 'reviewMarkedSkippedToast'));
  refreshAfterReviewChange();
  navigateReview(1);
}

export function clearCurrentMark() {
  if (!selectedPlace) return;
  ReviewMarks.clear(selectedPlace.properties);
  refreshAfterReviewChange();
}

// Rebuilds the filtered list (and so the review queue) around the selected
// place. If the place is now hidden, "next" starts from the nearest remaining
// one (or the most severe remaining one for the Qibla list).
export function refreshAfterReviewChange() {
  updateImprovementIssueCounts();
  filterData();
  reviewIndex = selectedPlace ? reviewQueue.findIndex(f => f.properties === selectedPlace.properties) : -1;
  updateReviewNavUI();
  renderReviewActions();
}

export function renderReviewActions() {
  const box = document.getElementById('details-review-actions');
  if (!box) return;
  if (!selectedPlace || currentMode !== 'improve') {
    box.style.display = 'none';
    return;
  }
  const mark = ReviewMarks.get(selectedPlace.properties);
  const status = document.getElementById('details-review-status');
  status.textContent = mark ? t(mark.status === 'fixed' ? 'reviewFixed' : 'reviewSkipped') : '';
  status.style.display = mark ? '' : 'none';
  document.getElementById('btn-review-fixed').textContent = t('reviewMarkFixed');
  document.getElementById('btn-review-skip').textContent = t('reviewMarkSkip');
  const unmark = document.getElementById('btn-review-unmark');
  unmark.textContent = t('reviewUnmark');
  unmark.style.display = mark ? '' : 'none';
  box.style.display = 'flex';
}

// ---------------------------------------------------------------------------
// Review queue: N / P step through the places matching the active filter.
// The Qibla filter keeps its severity order; every other list is ordered by
// distance from where the map was when the list was built, so stepping
// through it walks outward from the area you're looking at.
// ---------------------------------------------------------------------------
export let reviewQueue = [];
export let reviewIndex = -1;

export function rebuildReviewQueue() {
  if (currentMode === 'improve' && currentImprovementFilter === 'qibla_deviation') {
    reviewQueue = filteredPlaces.slice();
  } else if (map) {
    const c = map.getCenter();
    const cosLat = Math.cos(c.lat * Math.PI / 180);
    const dist = f => {
      const dx = (f.geometry.coordinates[0] - c.lng) * cosLat;
      const dy = f.geometry.coordinates[1] - c.lat;
      return dx * dx + dy * dy;
    };
    reviewQueue = filteredPlaces.map(f => [dist(f), f]).sort((a, b) => a[0] - b[0]).map(p => p[1]);
  } else {
    reviewQueue = filteredPlaces.slice();
  }
  reviewIndex = -1;
  updateReviewNavUI();
}

export function navigateReview(direction) {
  if (currentMode === 'gap' || reviewQueue.length === 0) {
    showToast(t('reviewEmpty'), 'error');
    return;
  }
  const n = reviewQueue.length;
  let next = reviewIndex < 0 ? (direction > 0 ? 0 : n - 1) : reviewIndex + direction;
  if (next >= n || next < 0) {
    showToast(t('reviewDone'));
    next = (next + n) % n;
  }
  reviewIndex = next;
  const target = reviewQueue[reviewIndex];
  const [lon, lat] = target.geometry.coordinates;
  map.flyTo([lat, lon], Math.max(map.getZoom(), 18), { duration: 0.8 });
  showDetails(target.properties, lat, lon);
  updateReviewNavUI();
}

export function updateReviewNavUI() {
  const counterEl = document.getElementById('review-nav-counter');
  const box = document.getElementById('review-nav-box');
  if (!counterEl || !box) return;
  box.style.display = currentMode === 'gap' ? 'none' : 'flex';

  let label = t('reviewLabelNearest');
  if (currentMode === 'improve' && currentImprovementFilter === 'qibla_deviation') {
    label = t(currentQiblaSort === 'least_accurate' ? 'reviewLabelQiblaLeast' : 'reviewLabelQiblaMost');
  }
  if (reviewQueue.length === 0) {
    counterEl.textContent = t('reviewEmpty');
  } else {
    const pos = reviewIndex < 0 ? '–' : fmtNum(reviewIndex + 1);
    let text = t('reviewCounter', { label, pos, total: fmtNum(reviewQueue.length) });
    const dev = reviewQueue[reviewIndex]?.properties?.ml_anomaly?.qibla_dev;
    if (currentImprovementFilter === 'qibla_deviation' && currentMode === 'improve' && dev !== undefined && reviewIndex >= 0) {
      text += ` (${dev}°)`;
    }
    counterEl.textContent = text;
  }
  const today = document.getElementById('review-today-count');
  if (today) {
    const n = ReviewMarks.countToday();
    today.textContent = t('reviewedToday', { n: fmtNum(n) });
    today.style.display = currentMode === 'improve' && n > 0 ? '' : 'none';
  }
}

// ---------------------------------------------------------------------------
// Permalinks: #mode=improve&issue=missing_name&rel=all&q=...&map=15/24.71/46.67&place=way/123&lang=en
// ---------------------------------------------------------------------------
export const Permalink = {
  _applying: false,

  read() {
    return new URLSearchParams(window.location.hash.slice(1));
  },

  update() {
    if (this._applying || !map) return;
    const p = new URLSearchParams();
    p.set('mode', currentMode);
    if (currentMode === 'improve' && currentImprovementFilter !== 'all') p.set('issue', currentImprovementFilter);
    if (currentMode === 'poi' && currentReligionFilter !== 'all') p.set('rel', currentReligionFilter);
    if (currentSearchQuery.trim() && currentMode !== 'gap') p.set('q', currentSearchQuery.trim());
    const c = map.getCenter();
    p.set('map', `${Math.round(map.getZoom())}/${c.lat.toFixed(5)}/${c.lng.toFixed(5)}`);
    if (selectedPlace && currentMode !== 'gap') p.set('place', ReviewMarks.keyOf(selectedPlace.properties));
    if (currentLang !== 'ar') p.set('lang', currentLang);
    // Keep "/" readable in map=z/lat/lon and place=way/123.
    const hash = '#' + p.toString().replace(/%2F/g, '/');
    if (hash !== window.location.hash) {
      history.replaceState(null, '', window.location.pathname + window.location.search + hash);
    }
  },

  // Called once after the data has loaded.
  apply() {
    const p = this.read();
    if (![...p.keys()].length) return;
    this._applying = true;
    try {
      const q = p.get('q');
      if (q) {
        setCurrentSearchQuery(q);
        const box = document.getElementById('search-input');
        if (box) box.value = q;
      }
      const rel = p.get('rel');
      if (rel) document.querySelector(`#religion-filters .chip[data-religion="${CSS.escape(rel)}"]`)?.click();
      const mode = p.get('mode');
      if (mode === 'gap' || mode === 'improve') document.getElementById(`mode-${mode}`)?.click();
      const issue = p.get('issue');
      if (issue && mode === 'improve') document.querySelector(`[data-improve="${CSS.escape(issue)}"]`)?.click();
      if (q && mode !== 'improve' && !issue && !rel) filterData();

      const view = (p.get('map') || '').split('/').map(Number);
      if (view.length === 3 && view.every(Number.isFinite)) map.setView([view[1], view[2]], view[0]);

      const place = p.get('place');
      if (place) {
        const [type, id] = place.split('/');
        const f = allPlaces.find(x => String(x.properties.osm_id) === id && osmTypeOf(x.properties) === type);
        if (f) {
          const [lon, lat] = f.geometry.coordinates;
          if (view.length !== 3) map.setView([lat, lon], 18);
          showDetails(f.properties, lat, lon);
        }
      }
    } finally {
      this._applying = false;
    }
    this.update();
  }
};

export let permalinkTimer = null;
export function updatePermalinkSoon() {
  clearTimeout(permalinkTimer);
  permalinkTimer = setTimeout(() => Permalink.update(), 300);
}

// ---------------------------------------------------------------------------
// Keyboard shortcuts (ignored while typing in a field)
// ---------------------------------------------------------------------------
export function setupKeyboardShortcuts() {
  document.addEventListener('keydown', (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const tag = (e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || tag === 'select' || e.target.isContentEditable) return;
    const anyModalOpen = [...document.querySelectorAll('.auth-overlay')].some(o => !o.classList.contains('hidden'));
    if (anyModalOpen && e.key !== 'Escape') return;

    const key = shortcutKey(e);
    const click = id => document.getElementById(id)?.click();
    const handlers = {
      n: () => navigateReview(1),
      p: () => navigateReview(-1),
      j: () => selectedPlace && click('btn-edit-josm'),
      i: () => selectedPlace && click('btn-edit-osm'),
      o: () => selectedPlace && click('btn-view-osm'),
      f: () => currentMode === 'improve' && markCurrentPlace('fixed'),
      s: () => currentMode === 'improve' && markCurrentPlace('skipped'),
      '1': () => click('mode-poi'),
      '2': () => click('mode-gap'),
      '3': () => click('mode-improve'),
      '?': () => document.getElementById('shortcuts-overlay')?.classList.remove('hidden'),
    };
    const handler = handlers[key];
    if (handler) {
      e.preventDefault();
      handler();
    }
  });
}
