// Saudi Places of Worship Tagging Directory (/tags)
import './styles/fonts.css';
import './styles/page.css';
import './styles/tags.css';
import { currentLang, setLanguage, addTranslations } from './i18n.js';
import { ArabicText } from './arabic.js';
import { initAnalytics } from './analytics.js';

addTranslations({
  tagsTitle: ['دليل وسوم المساجد | منارة: خريطة بيوت الله', 'Tag Directory | Manara: Saudi Places of Worship Map'],
  heroTitle: ['دليل وسوم المساجد في السعودية', 'Saudi Places of Worship Tag Directory'],
  heroSubtitle: [
    'المرجع المعتمد لوسوم خريطة الشارع المفتوحة في المملكة العربية السعودية، يربط الوسوم بقواعد الجودة، الأمثلة، وإحصاءات الاستخدام الحية.',
    'The standard reference for OpenStreetMap mosque tags in Saudi Arabia, connecting tags with QA rules, examples, and live usage stats.'
  ],
  searchPlaceholder: ['ابحث في الوسوم، المفاتيح، أو القواعد... (اضغط / للتركيز)', 'Search tags, keys, or rules... (press / to focus)'],
  filterAll: ['الكل', 'All'],
  filterApproved: ['المعتمدة', 'Approved'],
  filterDiscouraged: ['غير المحبذة', 'Discouraged'],
  filterWorship: ['الوسوم الأساسية', 'Core Worship'],
  statusApproved: ['معتمد', 'Approved'],
  statusDiscouraged: ['غير محبذ', 'Discouraged'],
  saudiGuidelines: ['إرشادات الاستخدام في السعودية', 'Saudi Mapping Guidelines'],
  liveUsageInKSA: ['الاستخدام في مساجد المملكة:', 'Usage across Saudi mosques:'],
  commonCooccurring: ['أكثر الوسوم المرافقة:', 'Common with:'],
  goodExample: ['✓ استخدام صحيح', '✓ Recommended example'],
  badExample: ['✕ خطأ شائع', '✕ Discouraged usage'],
  whyReason: ['السبب:', 'Why:'],
  associatedRules: ['قواعد الجودة المرتبطة:', 'Associated QA rules:'],
  inspectInQA: ['افحص في الجودة', 'Inspect in QA'],
  transliterateToolTitle: ['أداة الترجمة الصوتية الفورية (UNGEGN/GASGI)', 'Instant Transliteration Tool (UNGEGN/GASGI)'],
  transliteratePlaceholder: ['اكتب اسم المسجد بالعربية...', 'Type Arabic mosque name...'],
  copyText: ['نسخ', 'Copy'],
  copiedText: ['تم النسخ!', 'Copied!'],
  openInId: ['فتح في iD', 'Open in iD'],
  overpassQuery: ['استعلام Overpass', 'Overpass Turbo'],
  osmWiki: ['ويكي OSM', 'OSM Wiki'],
  emptyResults: ['لا توجد وسوم مطابقة لبحثك.', 'No matching tags found.'],
});

let allTagDocs = [];
let activeFilter = 'all';
let searchQuery = '';

async function loadTagDocs() {
  try {
    const res = await fetch('/data/tags.json');
    if (res.ok) {
      allTagDocs = await res.json();
    }
  } catch (err) {
    console.warn('Failed to load /data/tags.json:', err);
  }

  // Fallback to minimal core list if fetch failed or empty
  if (!allTagDocs || allTagDocs.length === 0) {
    allTagDocs = [
      {
        key: 'amenity',
        value: 'place_of_worship',
        status: 'approved',
        applies_to: ['node', 'way', 'relation'],
        label: { ar: 'مكان عبادة', en: 'Place of worship' },
        saudi_notes: {
          ar: 'الوسم الأساسي لجميع المساجد والمصليات في المملكة العربية السعودية. يجب أن يترافق دائمًا مع religion=muslim.',
          en: 'The primary tag for all mosques and prayer halls in Saudi Arabia. Must always accompany religion=muslim.'
        },
        examples: {
          good: [{ tags: { amenity: 'place_of_worship', religion: 'muslim', building: 'mosque', name: 'جامع الملك فهد' } }],
          bad: [{ tags: { building: 'mosque' }, why: { ar: 'ينقص وسم amenity=place_of_worship', en: 'Missing amenity=place_of_worship' } }]
        },
        rules: ['missing_amenity', 'stale_data', 'duplicate_poi'],
        wiki: 'https://wiki.openstreetmap.org/wiki/Tag:amenity=place_of_worship'
      }
    ];
  }

  updateStatsRibbon();
  renderGrid();
  handleUrlHash();
}

function updateStatsRibbon() {
  const totalAnalyzed = allTagDocs.find(d => d.usage_sa)?.usage_sa?.count || 14022;
  const ribbonCount = document.getElementById('ribbon-total-places');
  const ribbonTags = document.getElementById('ribbon-cataloged-tags');
  if (ribbonCount) ribbonCount.textContent = totalAnalyzed.toLocaleString();
  if (ribbonTags) ribbonTags.textContent = allTagDocs.length.toString();
}

function tagMatchesFilter(doc, filter) {
  if (filter === 'all') return true;
  if (filter === 'approved') return doc.status === 'approved';
  if (filter === 'discouraged') return doc.status === 'discouraged' || doc.status === 'deprecated';
  if (filter === 'worship') {
    return ['amenity', 'building', 'religion', 'denomination'].includes(doc.key);
  }
  return true;
}

function tagMatchesQuery(doc, q) {
  if (!q) return true;
  const normQ = ArabicText.normalize(q);
  const keyNorm = ArabicText.normalize(doc.key);
  const valNorm = doc.value ? ArabicText.normalize(doc.value) : '';
  const arLabel = doc.label?.ar ? ArabicText.normalize(doc.label.ar) : '';
  const enLabel = doc.label?.en ? ArabicText.normalize(doc.label.en) : '';
  const arNotes = doc.saudi_notes?.ar ? ArabicText.normalize(doc.saudi_notes.ar) : '';
  const enNotes = doc.saudi_notes?.en ? ArabicText.normalize(doc.saudi_notes.en) : '';

  if (keyNorm.includes(normQ) || valNorm.includes(normQ)) return true;
  if (arLabel.includes(normQ) || enLabel.includes(normQ)) return true;
  if (arNotes.includes(normQ) || enNotes.includes(normQ)) return true;

  if (doc.rules && doc.rules.some(r => r.toLowerCase().includes(q.toLowerCase()))) {
    return true;
  }
  return false;
}

function formatTagsObj(tags) {
  return Object.entries(tags)
    .map(([k, v]) => `${k}=${v}`)
    .join('\n');
}

function createTagCard(doc, lang) {
  const card = document.createElement('article');
  const tagSlug = doc.value ? `${doc.key}=${doc.value}` : doc.key;
  card.className = 'tag-card';
  card.id = `tag-${tagSlug.replace(/[^a-zA-Z0-9_-]/g, '_')}`;
  card.dataset.tagSlug = tagSlug;

  const isAr = lang === 'ar';
  const label = isAr ? (doc.label?.ar || doc.label?.en) : (doc.label?.en || doc.label?.ar);
  const subLabel = isAr ? doc.label?.en : doc.label?.ar;
  const notes = isAr ? (doc.saudi_notes?.ar || doc.saudi_notes?.en) : (doc.saudi_notes?.en || doc.saudi_notes?.ar);

  // Status badge class and text
  const statusClass = doc.status === 'approved' ? 'approved' : 'discouraged';
  const statusText = doc.status === 'approved'
    ? (isAr ? 'معتمد' : 'Approved')
    : (isAr ? 'غير محبذ' : 'Discouraged');

  // Applies to pills
  const appliesPills = (doc.applies_to || []).map(t => {
    const name = isAr ? (t === 'node' ? 'نقطة' : t === 'way' ? 'مبنى / خط' : 'علاقة') : t;
    return `<span class="tag-applies-pill">${name}</span>`;
  }).join('');

  // Live usage box
  let usageHtml = '';
  if (doc.usage_sa) {
    const count = doc.usage_sa.count?.toLocaleString() || '0';
    const pct = doc.usage_sa.percentage ? `${doc.usage_sa.percentage}%` : '';
    const withKeys = Object.entries(doc.usage_sa.with_key || {})
      .slice(0, 5)
      .map(([k, c]) => `<span class="cooccur-pill">${k} (${c.toLocaleString()})</span>`)
      .join('');

    usageHtml = `
      <div class="live-usage-box">
        <div>
          <span>${isAr ? 'الاستخدام في السعودية:' : 'Saudi Usage:'}</span>
          <span class="usage-metric-primary">${count} ${isAr ? 'مسجد' : 'mosques'} (${pct})</span>
        </div>
        ${withKeys ? `<div class="usage-cooccur"><span>${isAr ? 'يرافق:' : 'With:'}</span>${withKeys}</div>` : ''}
      </div>
    `;
  }

  // Good and bad examples
  let examplesHtml = '';
  const goodList = doc.examples?.good || [];
  const badList = doc.examples?.bad || [];
  if (goodList.length > 0 || badList.length > 0) {
    const goodHtml = goodList.map(ex => `
      <div class="example-box good">
        <div class="example-header">${isAr ? '✓ استخدام صحيح وموصى به' : '✓ Recommended tag format'}</div>
        <pre class="example-tags">${formatTagsObj(ex.tags)}</pre>
      </div>
    `).join('');

    const badHtml = badList.map(ex => {
      const why = isAr ? (ex.why?.ar || ex.why?.en) : (ex.why?.en || ex.why?.ar);
      return `
        <div class="example-box bad">
          <div class="example-header">${isAr ? '✕ خطأ شائع' : '✕ Discouraged format'}</div>
          <pre class="example-tags">${formatTagsObj(ex.tags)}</pre>
          ${why ? `<div class="example-why"><strong>${isAr ? 'السبب:' : 'Why:'}</strong> ${why}</div>` : ''}
        </div>
      `;
    }).join('');

    examplesHtml = `
      <div class="tag-examples-section">
        ${goodHtml}
        ${badHtml}
      </div>
    `;
  }

  // QA Rule Linkages
  let rulesHtml = '';
  if (doc.rules && doc.rules.length > 0) {
    const ruleBadges = doc.rules.map(r => `
      <a href="/qa?rule=${encodeURIComponent(r)}" class="qa-rule-link" title="${isAr ? 'افحص هذه القاعدة في قائمة الجودة' : 'Inspect rule in QA queue'}">
        ⚠ ${r}
      </a>
    `).join('');
    rulesHtml = `
      <div class="tag-rules-list">
        <span>${isAr ? 'قواعد الجودة المرتبطة:' : 'Linked QA Rules:'}</span>
        ${ruleBadges}
      </div>
    `;
  }

  // Transliteration Tool Box
  let toolHtml = '';
  if (doc.tools && doc.tools.includes('transliterate')) {
    toolHtml = `
      <div class="tool-box-transliterate" data-transliterate-box>
        <div class="tool-box-title">🔤 ${isAr ? 'أداة الترجمة الصوتية الفورية (UNGEGN/GASGI)' : 'Instant Transliteration Tool (UNGEGN/GASGI)'}</div>
        <div class="transliterate-form">
          <input type="text" placeholder="${isAr ? 'اكتب اسم المسجد بالعربية (مثل: جامع الملك فهد)...' : 'Type Arabic mosque name...'}" class="transliterate-input" />
        </div>
        <div class="transliterate-result" style="display: none;">
          <span class="result-text"></span>
          <button type="button" class="copy-btn">${isAr ? 'نسخ' : 'Copy'}</button>
        </div>
      </div>
    `;
  }

  // External Action Links
  const overpassQuery = doc.value
    ? `[out:json][timeout:25];area["ISO3166-1"="SA"]->.sa;(nwr["${doc.key}"="${doc.value}"](area.sa););out body;>;out skel qt;`
    : `[out:json][timeout:25];area["ISO3166-1"="SA"]->.sa;(nwr["${doc.key}"](area.sa););out body;>;out skel qt;`;
  const overpassUrl = `https://overpass-turbo.eu/?Q=${encodeURIComponent(overpassQuery)}&R`;
  const idUrl = `https://www.openstreetmap.org/edit?editor=id#map=16/24.7136/46.6753`;

  card.innerHTML = `
    <div class="tag-card-header">
      <div class="tag-pill-group">
        <span class="tag-badge-pill">${tagSlug}</span>
        <span class="tag-status-badge ${statusClass}">${statusText}</span>
        ${appliesPills}
      </div>
    </div>

    <h2 class="tag-card-title">
      ${label}
      ${subLabel ? `<span class="en-sub">(${subLabel})</span>` : ''}
    </h2>

    <div class="saudi-note-box">
      <strong>🕌 ${isAr ? 'إرشادات الاستخدام في السعودية' : 'Saudi Arabia Mapping Guidelines'}</strong>
      <div>${notes}</div>
    </div>

    ${usageHtml}
    ${examplesHtml}
    ${toolHtml}

    <div class="tag-card-footer">
      ${rulesHtml}
      <div class="tag-links-group">
        <a href="${idUrl}" target="_blank" rel="noopener noreferrer" class="ext-action-btn">
          ✏️ ${isAr ? 'فتح في iD' : 'Open in iD'}
        </a>
        <a href="${overpassUrl}" target="_blank" rel="noopener noreferrer" class="ext-action-btn">
          ⚡ ${isAr ? 'استعلام Overpass' : 'Overpass'}
        </a>
        ${doc.wiki ? `
          <a href="${doc.wiki}" target="_blank" rel="noopener noreferrer" class="ext-action-btn">
            📖 ${isAr ? 'ويكي OSM' : 'OSM Wiki'}
          </a>
        ` : ''}
      </div>
    </div>
  `;

  return card;
}

function renderGrid() {
  const container = document.getElementById('tags-grid');
  if (!container) return;

  const filtered = allTagDocs.filter(doc => tagMatchesFilter(doc, activeFilter) && tagMatchesQuery(doc, searchQuery));

  container.innerHTML = '';
  if (filtered.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <p>${currentLang === 'ar' ? 'لا توجد وسوم مطابقة لبحثك.' : 'No matching tags found.'}</p>
      </div>
    `;
    return;
  }

  filtered.forEach(doc => {
    container.appendChild(createTagCard(doc, currentLang));
  });

  setupTransliterationWidgets();
}

function setupTransliterationWidgets() {
  document.querySelectorAll('[data-transliterate-box]').forEach(box => {
    const input = box.querySelector('.transliterate-input');
    const resultBox = box.querySelector('.transliterate-result');
    const resultText = box.querySelector('.result-text');
    const copyBtn = box.querySelector('.copy-btn');

    if (!input || !resultBox || !resultText) return;

    input.addEventListener('input', () => {
      const val = input.value.trim();
      if (!val) {
        resultBox.style.display = 'none';
        return;
      }
      const transliterated = ArabicText.suggestEnglishName(val);
      if (transliterated) {
        resultText.textContent = transliterated;
        resultBox.style.display = 'flex';
      } else {
        resultBox.style.display = 'none';
      }
    });

    if (copyBtn) {
      copyBtn.addEventListener('click', async () => {
        const text = resultText.textContent;
        if (!text) return;
        try {
          await navigator.clipboard.writeText(text);
          const original = copyBtn.textContent;
          copyBtn.textContent = currentLang === 'ar' ? 'تم النسخ!' : 'Copied!';
          setTimeout(() => { copyBtn.textContent = original; }, 1500);
        } catch (err) {
          console.warn('Clipboard write failed:', err);
        }
      });
    }
  });
}

function setupSearchAndFilters() {
  const searchInput = document.getElementById('tag-search-input');
  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      searchQuery = e.target.value;
      renderGrid();
    });
  }

  // Filter Buttons
  document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      activeFilter = btn.dataset.filter || 'all';
      renderGrid();
    });
  });

  // Global Keyboard Shortcuts (/ to search, Esc to clear)
  window.addEventListener('keydown', (e) => {
    if (e.key === '/' && document.activeElement !== searchInput) {
      e.preventDefault();
      searchInput?.focus();
      searchInput?.select();
    } else if (e.key === 'Escape' && document.activeElement === searchInput) {
      searchInput.value = '';
      searchQuery = '';
      searchInput.blur();
      renderGrid();
    }
  });
}

function handleUrlHash() {
  const hash = window.location.hash.replace('#', '');
  if (!hash) return;
  const targetId = `tag-${hash.replace(/[^a-zA-Z0-9_-]/g, '_')}`;
  const el = document.getElementById(targetId);
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    el.classList.add('highlight');
  }
}

// Language toggle hook
document.getElementById('btn-toggle-lang')?.addEventListener('click', () => {
  setLanguage(currentLang === 'ar' ? 'en' : 'ar');
  renderGrid();
});

window.addEventListener('hashchange', handleUrlHash);

// Init
setLanguage(currentLang);
setupSearchAndFilters();
loadTagDocs();
initAnalytics();
