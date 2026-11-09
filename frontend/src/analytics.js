// Umami analytics (Manara's own instance, proxied same-origin under /stats/
// so ad blockers leave it alone). Nothing is loaded unless the build sets
// VITE_UMAMI_WEBSITE_ID. Events carry no personal data: never pass OSM user
// names or anything typed by the user.

const WEBSITE_ID = import.meta.env.VITE_UMAMI_WEBSITE_ID;
const DOMAINS = import.meta.env.VITE_UMAMI_DOMAINS || 'manara.saudiosm.org';

export function trackEvent(name, data) {
  if (import.meta.env.DEV) console.debug(`[umami] ${name}`, data || {});
  try {
    if (window.umami && typeof window.umami.track === 'function') window.umami.track(name, data);
  } catch (e) {
    // Analytics must never break the app
  }
}

// Clicks on these controls are tracked as events, by delegation so the
// markup and app.js need no analytics code.
const CLICK_EVENTS = [
  ['.mode-btn[data-mode]', el => ['Mode switch', { mode: el.dataset.mode }]],
  ['.improve-item[data-improve]', el => ['Issue filter', { issue: el.dataset.improve }]],
  ['.export-btn[id^="btn-export-"]', el => ['Export', { type: el.id.slice('btn-export-'.length) }]],
  ['#btn-toggle-lang', () => ['Language toggle', { to: document.documentElement.lang === 'ar' ? 'en' : 'ar' }]],
];

export function initAnalytics() {
  document.addEventListener('click', e => {
    for (const [selector, describe] of CLICK_EVENTS) {
      const el = e.target.closest(selector);
      if (el) {
        trackEvent(...describe(el));
        return;
      }
    }
  }, true);

  if (!WEBSITE_ID) return;
  const script = document.createElement('script');
  script.defer = true;
  script.src = '/stats/script.js';
  script.dataset.websiteId = WEBSITE_ID;
  script.dataset.hostUrl = '/stats';
  script.dataset.domains = DOMAINS;
  script.dataset.doNotTrack = 'true';
  document.head.appendChild(script);
}
