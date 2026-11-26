// Satellite AI mosque candidates (scripts/ai_background_sweeper.py), published to the backend by
// scripts/publish_ai_detections.py. Like the Wikidata suggestions they are private to OSM users on
// MANARA_SUGGESTIONS_ALLOWLIST: the panel stays hidden and nothing is requested for anyone else.
// Each candidate can be marked "mosque" / "not a mosque" / "unsure"; the verdicts go back into the
// model's training data.

import { kit } from './map_kit.js';
import { addTranslations, fmtNum, t } from './i18n.js';
import { showToast } from './ui.js';

addTranslations({
  aiTitle: ['مسجد مرشّح بالذكاء الاصطناعي', 'AI mosque candidate'],
  aiDual: ['ظهر في صور Esri و Mapbox', 'Seen on Esri + Mapbox imagery'],
  aiSingle: ['ظهر في مصدر صور واحد', 'Seen on one imagery source'],
  aiConfidence: ['ثقة النموذج', 'Model confidence'],
  aiRegion: ['المنطقة', 'Region'],
  aiArea: ['المساحة التقديرية', 'Estimated area'],
  aiVotes: ['المراجعات', 'Reviews'],
  aiQuestion: ['هل المبنى المحدد مسجد؟ تحقق من صور الأقمار الصناعية.', 'Is the outlined building a mosque? Check the satellite imagery.'],
  aiYes: ['✅ مسجد', '✅ Mosque'],
  aiNo: ['❌ ليس مسجداً', '❌ Not a mosque'],
  aiUnsure: ['❓ غير متأكد', '❓ Unsure'],
  aiSatellite: ['🛰️ صور الأقمار الصناعية', '🛰️ Satellite view'],
  aiNext: ['التالي', 'Next'],
  aiEditId: ['أضفه في iD ↗', 'Add in iD ↗'],
  aiSaved: ['تم حفظ مراجعتك', 'Review saved'],
  aiSaveFailed: ['تعذر حفظ المراجعة', 'Could not save the review'],
  aiSignIn: ['انتهت الجلسة. سجّل الدخول عبر OpenStreetMap مرة أخرى.', 'Session expired. Sign in with OpenStreetMap again.'],
  aiAllDone: ['راجعت جميع المرشحين 🎉', 'You have reviewed every candidate 🎉'],
  aiLoaded: ['تم تحميل {n} مرشحاً من الذكاء الاصطناعي', 'Loaded {n} AI candidates'],
  aiLoadFailed: ['تعذر تحميل مرشحي الذكاء الاصطناعي', 'Could not load the AI candidates'],
});

const VERDICTS = [['positive', 'aiYes'], ['negative', 'aiNo'], ['unsure', 'aiUnsure']];
const FOOTPRINT_SRC = 'ai-footprints';

let map = null;
let showSatelliteAt = null;
let layer = null;
let loading = null;
let footprintsMounted = false;
const byId = new Map(); // id -> { props, lat, lon, marker }

/** Called once the backend has confirmed the viewer may see suggestions. */
export function setupAiDetections(deps) {
  map = deps.map;
  showSatelliteAt = deps.showSatelliteAt;
  const section = document.getElementById('ai-section');
  if (section) section.style.display = '';
  document.getElementById('ai-toggle')?.addEventListener('change', e => setVisible(e.target.checked));
  document.getElementById('ai-review-next')?.addEventListener('click', () => {
    const toggle = document.getElementById('ai-toggle');
    if (toggle && !toggle.checked) {
      toggle.checked = true;
      setVisible(true);
    }
    ensureLoaded().then(() => goToNext(null));
  });
}

function setVisible(visible) {
  if (!visible) {
    if (layer && map.hasLayer(layer)) map.removeLayer(layer);
    setFootprintsVisible(false);
    return;
  }
  ensureLoaded().then(() => {
    if (layer && !map.hasLayer(layer) && document.getElementById('ai-toggle')?.checked) map.addLayer(layer);
    setFootprintsVisible(true);
  });
}

function ensureLoaded() {
  if (!loading) {
    loading = fetch('/api/v1/ai/detections', { credentials: 'same-origin', headers: { Accept: 'application/json' } })
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(data => {
        layer = kit.createAiDetectionLayer({ formatCount: fmtNum });
        for (const f of data.features || []) {
          const [lon, lat] = f.geometry.coordinates;
          const entry = { props: f.properties, lat, lon };
          entry.marker = kit.createAiDetectionMarker({
            lat, lon, verdict: f.properties.my_verdict, popupContent: () => buildPopup(entry),
          });
          byId.set(f.properties.id, entry);
          layer.addLayer(entry.marker);
        }
        mountFootprints();
        updateCounts();
        showToast(t('aiLoaded', { n: fmtNum(byId.size) }));
      })
      .catch(err => {
        console.error('AI detections:', err);
        showToast(t('aiLoadFailed'), 'error');
        loading = null;
        const toggle = document.getElementById('ai-toggle');
        if (toggle) toggle.checked = false;
        throw err;
      });
  }
  return loading;
}

// -- Footprint outlines (visible from zoom 15, where the building itself is readable) ----------

function footprintsGeojson() {
  const features = [];
  for (const e of byId.values()) {
    if (!e.props.footprint) continue;
    const geometry = typeof e.props.footprint === 'string' ? JSON.parse(e.props.footprint) : e.props.footprint;
    features.push({ type: 'Feature', properties: { cls: e.props.my_verdict || 'pending' }, geometry });
  }
  return { type: 'FeatureCollection', features };
}

function verdictColor() {
  const colors = kit.aiVerdictColors;
  return ['match', ['get', 'cls'], ...Object.entries(colors).flat(), colors.pending];
}

function mountFootprints() {
  map.whenReady(() => {
    const gl = map.gl;
    if (!gl || footprintsMounted) return;
    gl.addSource(FOOTPRINT_SRC, { type: 'geojson', data: footprintsGeojson() });
    map.addStyleLayer({ id: `${FOOTPRINT_SRC}-fill`, type: 'fill', source: FOOTPRINT_SRC, minzoom: 14,
      paint: { 'fill-color': verdictColor(), 'fill-opacity': 0.12 } }, 'places');
    map.addStyleLayer({ id: `${FOOTPRINT_SRC}-line`, type: 'line', source: FOOTPRINT_SRC, minzoom: 14,
      paint: { 'line-color': verdictColor(), 'line-width': 2.5 } }, 'places');
    footprintsMounted = true;
    setFootprintsVisible(Boolean(document.getElementById('ai-toggle')?.checked));
  });
}

function setFootprintsVisible(visible) {
  const gl = map && map.gl;
  if (!gl || !footprintsMounted) return;
  for (const id of [`${FOOTPRINT_SRC}-fill`, `${FOOTPRINT_SRC}-line`]) {
    if (gl.getLayer(id)) gl.setLayoutProperty(id, 'visibility', visible ? 'visible' : 'none');
  }
}

function refreshFootprints() {
  const src = map && map.gl && map.gl.getSource(FOOTPRINT_SRC);
  if (src) src.setData(footprintsGeojson());
}

// -- Panel counters ----------------------------------------------------------------------------

function updateCounts() {
  let pending = 0;
  for (const e of byId.values()) if (!e.props.my_verdict) pending++;
  const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = fmtNum(v); };
  set('ai-count-total', byId.size);
  set('ai-count-pending', pending);
  const badge = document.getElementById('ai-badge');
  if (badge) {
    badge.textContent = fmtNum(pending);
    badge.style.display = pending > 0 ? 'inline-block' : 'none';
  }
}

// -- Popup ---------------------------------------------------------------------------------------

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') node.className = v;
    else if (k === 'text') node.textContent = v;
    else node.setAttribute(k, v);
  }
  children.flat().forEach(c => c && node.append(c));
  return node;
}

function metaRow(label, value) {
  return el('div', { class: 'suggestion-meta-item' },
    el('span', { class: 'suggestion-meta-label', text: label }),
    el('span', { class: 'suggestion-meta-val', text: value }));
}

function buildPopup(entry) {
  const root = el('div', { class: 'suggestion-popup ai-popup', dir: document.documentElement.dir || 'rtl' });
  renderPopup(root, entry);
  return root;
}

function renderPopup(root, entry) {
  const p = entry.props;
  const idUrl = `https://www.openstreetmap.org/edit?editor=id#map=19/${entry.lat.toFixed(6)}/${entry.lon.toFixed(6)}`;
  const votes = `✅ ${fmtNum(p.n_positive || 0)} · ❌ ${fmtNum(p.n_negative || 0)} · ❓ ${fmtNum(p.n_unsure || 0)}`;

  const verdictButtons = VERDICTS.map(([verdict, key]) => {
    const b = el('button', { type: 'button', class: `btn-sug-action btn-ai-verdict btn-ai-${verdict}`, text: t(key) });
    if (p.my_verdict === verdict) {
      b.classList.add('active');
      b.setAttribute('aria-pressed', 'true');
    }
    b.addEventListener('click', () => submitVerdict(entry, verdict, root, b));
    return b;
  });

  const sat = el('button', { type: 'button', class: 'btn-sug-action btn-sug-satellite', text: t('aiSatellite') });
  sat.addEventListener('click', () => showSatelliteAt && showSatelliteAt(entry.lat, entry.lon));
  const next = el('button', { type: 'button', class: 'btn-sug-action btn-ai-next', text: t('aiNext') });
  next.addEventListener('click', () => goToNext(p.id));

  root.replaceChildren(
    el('div', { class: 'suggestion-popup-header' },
      el('h3', { class: 'suggestion-title', text: `🛰️ ${t('aiTitle')}` }),
      el('div', { class: 'suggestion-subtitle', dir: 'ltr', text: p.id })),
    el('div', {}, el('span', { class: p.dual ? 'badge-sug-verified' : 'badge-sug-generic', text: p.dual ? t('aiDual') : t('aiSingle') })),
    el('div', { class: 'suggestion-meta-list' },
      metaRow(t('aiConfidence'), `${Math.round((p.confidence || 0) * 100)}%`),
      p.region_name || p.region_code ? metaRow(t('aiRegion'), p.region_name || p.region_code) : null,
      p.area_m2 ? metaRow(t('aiArea'), `${fmtNum(Math.round(p.area_m2))} m²`) : null,
      metaRow(t('aiVotes'), votes)),
    el('p', { class: 'ai-question', text: t('aiQuestion') }),
    el('div', { class: 'ai-verdicts', role: 'group', 'aria-label': t('aiQuestion') }, verdictButtons),
    el('div', { class: 'suggestion-actions' },
      sat,
      el('a', { href: idUrl, target: '_blank', rel: 'noopener noreferrer', class: 'btn-sug-action btn-sug-id', text: t('aiEditId') }),
      next),
  );
}

async function submitVerdict(entry, verdict, root, button) {
  root.querySelectorAll('.btn-ai-verdict').forEach(b => { b.disabled = true; });
  try {
    const res = await fetch(`/api/v1/ai/detections/${encodeURIComponent(entry.props.id)}/review`, {
      method: 'PUT',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json', 'X-Manara-CSRF': '1' },
      body: JSON.stringify({ verdict }),
    });
    if (res.status === 401) {
      showToast(t('aiSignIn'), 'error');
      return;
    }
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const tally = await res.json();
    Object.assign(entry.props, {
      my_verdict: tally.my_verdict, n_positive: tally.n_positive, n_negative: tally.n_negative, n_unsure: tally.n_unsure,
    });
    // Re-colour the pin and outline: the cluster layer reads `cls` when its data is rebuilt.
    entry.marker.cls = tally.my_verdict;
    layer.removeLayer(entry.marker);
    layer.addLayer(entry.marker);
    refreshFootprints();
    updateCounts();
    renderPopup(root, entry);
    showToast(t('aiSaved'));
    root.querySelector('.btn-ai-next')?.focus();
  } catch (err) {
    console.error('AI review:', err);
    showToast(t('aiSaveFailed'), 'error');
  } finally {
    root.querySelectorAll('.btn-ai-verdict').forEach(b => { b.disabled = false; });
    if (button && !root.contains(button)) root.querySelector(`.btn-ai-${verdict}`)?.focus();
  }
}

/** Highest-confidence candidate the viewer has not judged yet, on satellite imagery. */
function goToNext(currentId) {
  const pending = [...byId.values()]
    .filter(e => !e.props.my_verdict && e.props.id !== currentId)
    .sort((a, b) => (b.props.confidence || 0) - (a.props.confidence || 0));
  if (!pending.length) {
    showToast(t('aiAllDone'));
    return;
  }
  const e = pending[0];
  map.closePopup();
  if (showSatelliteAt) showSatelliteAt(e.lat, e.lon);
  // The popup is tall and opens below the pin: once centred, lift the pin into the upper third
  // so the verdict and Next buttons are on screen.
  const gl = map.gl;
  if (gl) gl.once('moveend', () => gl.panBy([0, gl.getContainer().clientHeight * 0.3], { duration: 300 }));
  map.openPopup([e.lon, e.lat], { node: buildPopup(e), closeButton: true, offset: 10, anchor: 'top' });
}
