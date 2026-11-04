// Beginner Onboarding Flow (/start)
import './styles/fonts.css';
import './styles/page.css';
import './styles/start.css';
import { currentLang, setLanguage, addTranslations } from './i18n.js';
import { ArabicText } from './arabic.js';
import { OsmApi } from './osm_api.js';
import { initAnalytics } from './analytics.js';
import { showToast } from './ui.js';

addTranslations({
  startTitle: ['ابدأ هنا: مسار المبتدئين | منارة', 'Start Here: Beginner Onboarding | Manara'],
  heroTitle: ['مسار المساهمين الجدد في 3 خطوات', 'New Contributor Path in 3 Steps'],
  heroSubtitle: [
    'ابدأ رحلتك في تحسين خريطة بيوت الله في المملكة: سجل دخولك، أصلح اسماً إنجليزياً واحداً مع الاقتراح الآلي، وتعرف على قواعد التوسيم.',
    'Begin your journey improving Saudi places of worship on OSM: sign in, fix one English name with automated transliteration, and learn tagging rules.'
  ],
  step1Title: ['الخطوة 1: تسجيل الدخول عبر OpenStreetMap', 'Step 1: Sign in with OpenStreetMap'],
  step2Title: ['الخطوة 2: تصحيح اسم إنجليزي مقترح', 'Step 2: Guided Fix with Transliteration'],
  step3Title: ['الخطوة 3: مبارك! أصلحت مسجداً في الخريطة', 'Step 3: Congratulations! First Mosque Fixed'],
  signedInAs: ['أنت مسجل الدخول باسم:', 'Signed in as:'],
  notSignedIn: ['لم تسجل الدخول بعد. قم بربط حسابك لحفظ تعديلاتك مباشرة على الخريطة.', 'Not signed in yet. Connect your OSM account to publish edits.'],
  loginBtnText: ['تسجيل الدخول عبر OpenStreetMap', 'Sign in with OpenStreetMap'],
  loadingQueue: ['جاري تجهيز قائمة المساجد المقترحة للتصحيح...', 'Loading curated beginner queue...'],
  noPlacesLeft: ['رائع! تم استعراض جميع المساجد المقترحة في هذه الجلسة.', 'Awesome! All suggested places in this session have been reviewed.'],
  suggestedNameLabel: ['الاسم الإنجليزي المقترح طبقاً للمعايير الوطنية (GASGI):', 'Suggested English Name per national standards (GASGI):'],
  acceptAndSaveBtn: ['قبول وحفظ التعديل في OSM', 'Accept & Save to OSM'],
  skipBtn: ['تخطي للمسجد التالي', 'Skip to next'],
  openInIdBtn: ['التحرير في محرر iD', 'Edit in iD'],
  savingEdit: ['جاري إرسال التعديل إلى OpenStreetMap...', 'Submitting edit to OpenStreetMap...'],
  saveSuccessText: ['تم إرسال تعديلك بنجاح إلى خريطة الشارع المفتوحة!', 'Your edit was published successfully to OpenStreetMap!'],
  nextStepsHeading: ['ماذا بعد ذلك؟', 'What to do next?'],
  viewRuleLinkText: ['تعرف على وسم name:en في دليل الوسوم ←', 'Learn more about name:en in Tag Directory ←'],
  exploreQaLinkText: ['انتقل إلى قائمة الجودة الكاملة (/qa) ←', 'Explore full QA Queue (/qa) ←'],
  sandboxBadge: ['وضع تدريب تجريبي (وضع قراءة فقط - الحفظ الفعلي معطل)', 'Practice Sandbox Mode (Read-only demo - live saving disabled)'],
});

export let easyQueue = [];
export let currentIndex = 0;

function escapeHtml(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export function filterEasyQueue(places) {
  return (places || []).filter(f => {
    const p = f.properties || f;
    const arName = (p.name_original || p['name:ar'] || p.name || '').trim();
    const enName = (p.name_en_original || p['name:en'] || p.name_en || '').trim();
    if (!arName || ArabicText.isGenericMosqueName(arName)) return false;
    return !enName || enName.toLowerCase() === 'mosque' || enName === arName;
  });
}

function checkAuthStatus() {
  const token = OsmApi.token();
  const username = OsmApi.userName();

  const node1 = document.getElementById('step-node-1');
  const authBox = document.getElementById('auth-status-container');

  if (token) {
    if (node1) node1.classList.add('completed');
    if (authBox) {
      authBox.innerHTML = `
        <div class="user-status-text">
          <span style="color: var(--color-emerald); font-weight: 700;">✓</span>
          <span>${escapeHtml(currentLang === 'ar' ? 'أنت مسجل الدخول باسم:' : 'Signed in as:')}</span>
          <strong style="color: var(--color-primary); font-family: var(--font-mono);">@${escapeHtml(username || 'mapper')}</strong>
        </div>
      `;
    }
  } else {
    if (authBox) {
      authBox.innerHTML = `
        <div class="user-status-text">
          <span>${escapeHtml(currentLang === 'ar' ? 'لم تسجل الدخول بعد. قم بربط حسابك لحفظ تعديلاتك مباشرة على الخريطة.' : 'Not signed in yet. Connect your account to publish edits directly.')}</span>
        </div>
        <button type="button" id="btn-osm-login" class="osm-login-btn">
          ${escapeHtml(currentLang === 'ar' ? 'تسجيل الدخول عبر OpenStreetMap' : 'Sign in with OpenStreetMap')}
        </button>
      `;
      document.getElementById('btn-osm-login')?.addEventListener('click', () => {
        sessionStorage.setItem('osm_oauth_return_hash', '#step-2');
        OsmApi.startLogin();
      });
    }
  }
}

async function loadBeginnerQueue() {
  const container = document.getElementById('queue-container');
  if (!container) return;

  container.innerHTML = `<p style="color: var(--color-text-muted);">${escapeHtml(currentLang === 'ar' ? 'جاري تجهيز قائمة المساجد المقترحة للتصحيح...' : 'Loading curated beginner queue...')}</p>`;

  try {
    // Fetch issues endpoint (lightweight ~15 KB) instead of downloading entire 6.7 MB GeoJSON
    const res = await fetch('/api/v1/issues?rule_id=missing_name_en&limit=50');
    if (res.ok) {
      const data = await res.json();
      const issues = data.issues || [];
      easyQueue = issues.filter(i => {
        const arName = (i.name || '').trim();
        return arName && !ArabicText.isGenericMosqueName(arName);
      }).map(i => ({
        osm_type: i.osm_type || 'way',
        osm_id: i.osm_id,
        name: i.name,
        name_en: i.name_en || '',
        region_name: i.region_name || '',
        coordinates: i.coordinates || [46.6753, 24.7136],
        isSandbox: false,
      }));
    }
  } catch (err) {
    console.warn('Failed to load places for start queue from API:', err);
  }

  // Fallback demo queue strictly as an explicit practice sandbox (no fake OSM IDs saved to OSM)
  if (!easyQueue || easyQueue.length === 0) {
    easyQueue = [
      {
        osm_type: 'way',
        osm_id: null,
        name: 'جامع الملك فهد',
        name_en: '',
        region_name: currentLang === 'ar' ? 'منطقة الرياض' : 'Riyadh Region',
        coordinates: [46.6753, 24.7136],
        isSandbox: true,
      },
      {
        osm_type: 'node',
        osm_id: null,
        name: 'مسجد التقوى',
        name_en: '',
        region_name: currentLang === 'ar' ? 'منطقة مكة المكرمة' : 'Makkah Region',
        coordinates: [39.1825, 21.5433],
        isSandbox: true,
      }
    ];
  }

  renderCurrentQueueItem();
}

function renderCurrentQueueItem() {
  const container = document.getElementById('queue-container');
  if (!container) return;

  if (currentIndex >= easyQueue.length) {
    container.innerHTML = `
      <div class="success-banner">
        <h3>🎉 ${escapeHtml(currentLang === 'ar' ? 'رائع جداً!' : 'Awesome Job!')}</h3>
        <p>${escapeHtml(currentLang === 'ar' ? 'تم استعراض جميع المساجد المقترحة في هذه الجلسة.' : 'All curated beginner queue mosques have been completed!')}</p>
        <a href="/qa" class="action-btn-primary" style="text-decoration: none; display: inline-block;">
          ${escapeHtml(currentLang === 'ar' ? 'انتقل إلى قائمة الجودة الكاملة (/qa)' : 'Explore full QA Queue (/qa)')}
        </a>
      </div>
    `;
    return;
  }

  const item = easyQueue[currentIndex];
  const arName = (item.name || '').trim();
  const suggestedEn = ArabicText.suggestEnglishName(arName) || 'Mosque';
  const osmId = item.osm_id != null ? String(item.osm_id) : (currentLang === 'ar' ? 'تدريب تجريبي' : 'Practice Sandbox');
  const city = item.region_name || (currentLang === 'ar' ? 'المملكة العربية السعودية' : 'Saudi Arabia');
  const coords = item.coordinates || [46.6753, 24.7136];
  const [lon, lat] = coords;
  const isSandbox = !!item.isSandbox;

  const idEditUrl = item.osm_id != null
    ? `https://www.openstreetmap.org/edit?editor=id#map=17/${lat}/${lon}`
    : '#';

  const sandboxNotice = isSandbox
    ? `<div style="background: rgba(245, 158, 11, 0.15); border: 1px solid rgba(245, 158, 11, 0.4); border-radius: 6px; padding: 8px 12px; margin-bottom: 12px; font-size: 0.85rem; color: #fbbf24;">
        ⚠️ ${escapeHtml(currentLang === 'ar' ? 'وضع تدريب تجريبي (وضع قراءة فقط - الحفظ الفعلي معطل)' : 'Practice Sandbox Mode (Read-only demo - live saving disabled)')}
      </div>`
    : '';

  container.innerHTML = `
    <div class="queue-item-card">
      ${sandboxNotice}
      <div class="queue-place-header">
        <h3 class="queue-place-name">${escapeHtml(arName)}</h3>
        <span class="queue-place-meta">📍 ${escapeHtml(city)} (ID: ${escapeHtml(osmId)})</span>
      </div>

      <div class="suggestion-box">
        <div class="suggestion-label">
          ✨ ${escapeHtml(currentLang === 'ar' ? 'الاسم الإنجليزي المقترح طبقاً للمعايير الوطنية (GASGI):' : 'Suggested English Name per national standards (GASGI):')}
        </div>
        <div class="suggestion-input-wrapper">
          <input type="text" id="input-suggested-name" value="${escapeHtml(suggestedEn)}" />
        </div>
      </div>

      <div class="tag-diff-preview">
        <div>&nbsp;&nbsp;name = ${escapeHtml(arName)}</div>
        <div class="diff-add">+ name:en = <span id="preview-diff-val">${escapeHtml(suggestedEn)}</span></div>
      </div>

      <div class="queue-actions-row">
        <button type="button" id="btn-accept-save" class="action-btn-primary">
          💾 ${escapeHtml(currentLang === 'ar' ? (isSandbox ? 'إكمال التجربة (تجريبي)' : 'قبول وحفظ التعديل في OSM') : (isSandbox ? 'Complete Practice (Demo)' : 'Accept & Save to OSM'))}
        </button>
        <button type="button" id="btn-skip-item" class="action-btn-secondary">
          ⏩ ${escapeHtml(currentLang === 'ar' ? 'تخطي للمسجد التالي' : 'Skip to next')}
        </button>
        ${!isSandbox ? `
        <a href="${escapeHtml(idEditUrl)}" target="_blank" rel="noopener noreferrer" class="action-btn-secondary">
          ✏️ ${escapeHtml(currentLang === 'ar' ? 'التحرير في محرر iD' : 'Edit in iD')}
        </a>` : ''}
      </div>
    </div>
  `;

  const input = document.getElementById('input-suggested-name');
  const preview = document.getElementById('preview-diff-val');
  if (input && preview) {
    input.addEventListener('input', () => {
      preview.textContent = input.value.trim();
    });
  }

  document.getElementById('btn-skip-item')?.addEventListener('click', () => {
    currentIndex++;
    renderCurrentQueueItem();
  });

  document.getElementById('btn-accept-save')?.addEventListener('click', async () => {
    const finalNameEn = input ? input.value.trim() : suggestedEn;
    if (!finalNameEn) return;

    if (isSandbox) {
      showSuccessState(finalNameEn, arName);
      return;
    }

    const token = OsmApi.token();
    if (!token) {
      showToast(
        currentLang === 'ar'
          ? 'يرجى تسجيل الدخول بحساب OpenStreetMap في الخطوة 1 أولاً لنتمكن من حفظ تعديلك!'
          : 'Please sign in with OpenStreetMap in Step 1 first to save your edit!',
        'warning'
      );
      return;
    }

    const saveBtn = document.getElementById('btn-accept-save');
    if (saveBtn) {
      saveBtn.disabled = true;
      saveBtn.textContent = currentLang === 'ar' ? 'جاري إرسال التعديل...' : 'Submitting edit...';
    }

    try {
      const comment = `Add English name (${finalNameEn}) for ${arName} #sa-worship-map`;
      const targetType = item.osm_type || 'way';
      const targetId = Number(item.osm_id);

      const editItem = {
        type: targetType,
        id: targetId,
        label: arName,
        edits: {
          set: { 'name:en': finalNameEn }
        }
      };

      const { results } = await OsmApi.applyEdits([editItem], {
        comment,
        source: 'translating'
      });

      const firstRes = results && results[0];
      if (firstRes && firstRes.status === 'success') {
        showSuccessState(finalNameEn, arName);
      } else {
        const errorMsg = (firstRes && (firstRes.error || firstRes.status)) || 'Upload failed';
        throw new Error(errorMsg);
      }
    } catch (err) {
      console.error('OSM upload error:', err);
      showToast(
        currentLang === 'ar'
          ? `فشل حفظ التعديل في OSM: ${err.message || 'خطأ غير معروف'}`
          : `Failed to save edit to OSM: ${err.message || 'Unknown error'}`,
        'error'
      );
      if (saveBtn) {
        saveBtn.disabled = false;
        saveBtn.textContent = currentLang === 'ar' ? 'قبول وحفظ التعديل في OSM' : 'Accept & Save to OSM';
      }
    }
  });
}

function showSuccessState(enName, arName) {
  const node2 = document.getElementById('step-node-2');
  const node3 = document.getElementById('step-node-3');
  if (node2) node2.classList.add('completed');
  if (node3) {
    node3.classList.add('active');
    node3.classList.add('completed');
  }

  const container = document.getElementById('step-3-container');
  if (container) {
    container.style.display = 'block';
    container.scrollIntoView({ behavior: 'smooth' });
    const nameEl = document.getElementById('success-place-name');
    if (nameEl) nameEl.textContent = `${arName} (${enName})`;
  }
}

if (typeof document !== 'undefined') {
  document.getElementById('btn-toggle-lang')?.addEventListener('click', () => {
    setLanguage(currentLang === 'ar' ? 'en' : 'ar');
    checkAuthStatus();
    renderCurrentQueueItem();
  });

  // Complete OAuth callback if redirected from OSM
  if (typeof window !== 'undefined' && window.location?.search?.includes('code=')) {
    OsmApi.handleCallback().then(() => {
      checkAuthStatus();
    }).catch(() => {});
  }

  // Init
  setLanguage(currentLang);
  checkAuthStatus();
  loadBeginnerQueue();
  initAnalytics();
}
