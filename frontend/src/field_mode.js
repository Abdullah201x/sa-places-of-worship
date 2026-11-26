// Manara Field: Lightweight Mobile On-The-Ground Resurvey Mode
// Rapid tap-based amenities survey (women's facilities, wheelchair access, Jumu'ah status, sign name check).
import { currentLang } from './i18n.js';
import { EditBatch, createBatchEditItem } from './editing.js';

export function computeHaversineDistance(lat1, lon1, lat2, lon2) {
  const R = 6371000; // Earth radius in meters
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
            Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
            Math.sin(dLon / 2) * Math.sin(dLon / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return Math.round(R * c);
}

export function findNearbyPlaces(places, userLat, userLon, maxDist = 300) {
  if (!Array.isArray(places)) return [];
  const nearby = [];

  for (const place of places) {
    let lat, lon;
    if (place.geometry && place.geometry.coordinates) {
      lon = place.geometry.coordinates[0];
      lat = place.geometry.coordinates[1];
    } else if (place.lat !== undefined && place.lon !== undefined) {
      lat = place.lat;
      lon = place.lon;
    } else {
      continue;
    }

    const dist = computeHaversineDistance(userLat, userLon, lat, lon);
    if (dist <= maxDist) {
      nearby.push({
        ...place,
        distanceMeters: dist,
        lat,
        lon
      });
    }
  }

  return nearby.sort((a, b) => a.distanceMeters - b.distanceMeters);
}

export const SURVEY_QUESTIONS = [
  {
    id: 'female_prayer_room',
    title: { ar: 'مصلى النساء', en: "Women's Prayer Room" },
    prompt: {
      ar: 'هل يتوفر مدخل أو مصلى مخصص للنساء؟',
      en: "Is there a dedicated women's prayer room or entrance?"
    },
    options: [
      { id: 'yes', label: { ar: '✓ متوفر', en: '✓ Available' }, value: 'yes' },
      { id: 'no', label: { ar: '✕ غير متوفر', en: '✕ None' }, value: 'no' }
    ]
  },
  {
    id: 'wheelchair_access',
    title: { ar: 'دخول الكراسي المتحركة', en: 'Wheelchair Accessibility' },
    prompt: {
      ar: 'هل المدخل وقاعة الصلاة مهيأة للكراسي المتحركة؟',
      en: 'Is the prayer hall wheelchair accessible without steps?'
    },
    options: [
      { id: 'yes', label: { ar: '✓ مهيأ بالكامل', en: '✓ Fully Accessible' }, value: 'yes' },
      { id: 'limited', label: { ar: '⚡ وصول جزئي', en: '⚡ Limited' }, value: 'limited' },
      { id: 'no', label: { ar: '✕ غير مهيأ (درج)', en: '✕ Inaccessible' }, value: 'no' }
    ]
  },
  {
    id: 'place_of_worship_type',
    title: { ar: 'صلاة الجمعة والصفة', en: 'Friday Prayer Status' },
    prompt: {
      ar: 'هل هو جامع تقام به صلاة الجمعة أم مسجد فروض فقط؟',
      en: 'Is this a Friday Jumu’ah Grand Mosque or daily neighborhood mosque?'
    },
    options: [
      { id: 'mosque_jumuah', label: { ar: '🕌 جامع (جمعة)', en: '🕌 Grand Mosque' }, value: 'mosque' },
      { id: 'musalla', label: { ar: '🚪 مصلى مجمع/محطة', en: '🚪 Prayer Hall (Musalla)' }, value: 'musalla' }
    ]
  }
];

export function queueSurveyAnswer(place, questionId, value) {
  const item = createBatchEditItem(place.properties, questionId, value, 'survey');
  if (!item) return false;
  EditBatch.add(item);
  return true;
}

export function renderFieldSurveyorUI(containerEl, userLat, userLon, nearbyPlaces, onSelectPlace) {
  if (!containerEl) return;
  const isAr = currentLang === 'ar';

  if (!nearbyPlaces || nearbyPlaces.length === 0) {
    containerEl.innerHTML = `
      <div style="text-align: center; padding: 28px 16px; color: var(--color-text-muted);">
        <div style="font-size: 32px; margin-bottom: 10px;">📍</div>
        <p style="font-size: 14px; font-weight: 600; color: var(--color-text); margin-bottom: 4px;">
          ${isAr ? 'لا توجد مساجد مرصودة ضمن 300 متر' : 'No mapped mosques within 300m'}
        </p>
        <p style="font-size: 12px;">
          ${isAr ? 'يمكنك استخدام خيار "إضافة مسجد" لتوثيق هذا الموقع إذا كنت أمام دار عبادة غير مسجلة.' : 'You can use "Add Mosque" if you are at an unmapped place of worship.'}
        </p>
      </div>
    `;
    return;
  }

  const placesHtml = nearbyPlaces.map(p => {
    const props = p.properties || {};
    const name = (isAr ? props.name : props.name_en) || props.name || props.name_en || (isAr ? 'مسجد غير مسمى' : 'Unnamed Mosque');
    const dist = `${p.distanceMeters}m`;

    const questionsHtml = SURVEY_QUESTIONS.map(q => {
      const qTitle = isAr ? q.title.ar : q.title.en;
      const qPrompt = isAr ? q.prompt.ar : q.prompt.en;

      const optsHtml = q.options.map(opt => {
        const optLabel = isAr ? opt.label.ar : opt.label.en;
        return `
          <button type="button" class="field-opt-btn" data-place-id="${props.osm_id}" data-q-id="${q.id}" data-val="${opt.value}" style="flex: 1; padding: 8px 10px; font-size: 11px; font-weight: 600; border-radius: 8px; border: 1px solid var(--panel-border); background: rgba(255,255,255,0.04); color: var(--color-text); cursor: pointer; transition: all 0.2s;">
            ${optLabel}
          </button>
        `;
      }).join('');

      return `
        <div class="field-question-row" style="margin-top: 10px; padding: 10px; background: rgba(0,0,0,0.25); border-radius: 10px;">
          <div style="font-size: 11px; font-weight: 600; color: var(--color-primary); margin-bottom: 2px;">${qTitle}</div>
          <div style="font-size: 11px; color: var(--color-text-muted); margin-bottom: 8px;">${qPrompt}</div>
          <div style="display: flex; gap: 6px;">
            ${optsHtml}
          </div>
        </div>
      `;
    }).join('');

    return `
      <div class="field-place-card" style="padding: 14px; margin-bottom: 12px; background: var(--panel-bg); border: 1px solid var(--panel-border); border-radius: 14px;">
        <div style="display: flex; justify-content: space-between; align-items: baseline;">
          <h3 style="font-size: 15px; font-weight: 700; color: var(--color-text); margin: 0;">${name}</h3>
          <span style="font-size: 11px; font-weight: 700; color: var(--color-accent); padding: 2px 6px; background: rgba(0,255,135,0.1); border-radius: 6px;">📍 ${dist}</span>
        </div>
        ${questionsHtml}
      </div>
    `;
  }).join('');

  containerEl.innerHTML = `
    <div class="field-surveyor-header" style="margin-bottom: 14px;">
      <h2 style="font-size: 16px; font-weight: 700; color: var(--color-text); display: flex; align-items: center; gap: 8px;">
        <span>📱</span> <span>${isAr ? 'المسح الميداني الذكي (منارة فيلد)' : 'Smart Field Surveyor (Manara Field)'}</span>
      </h2>
      <p style="font-size: 12px; color: var(--color-text-muted); margin: 0;">
        ${isAr ? `تم العثور على ${nearbyPlaces.length} مساجد ضمن نطاق 300م من موقعك.` : `Found ${nearbyPlaces.length} mosques within 300m of your location.`}
      </p>
    </div>
    <div class="field-places-list">
      ${placesHtml}
    </div>
  `;

  // Attach button event listeners
  containerEl.querySelectorAll('.field-opt-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const pId = btn.getAttribute('data-place-id');
      const qId = btn.getAttribute('data-q-id');
      const val = btn.getAttribute('data-val');
      const place = nearbyPlaces.find(p => String(p.properties?.osm_id) === String(pId));
      if (place && queueSurveyAnswer(place, qId, val)) {
        btn.style.background = 'rgba(0, 242, 254, 0.2)';
        btn.style.borderColor = 'var(--color-primary)';
        btn.style.color = 'var(--color-primary)';
      }
    });
  });
}
