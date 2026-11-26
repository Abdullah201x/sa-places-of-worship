// Osmose QA Ecosystem Integration
// Fetches nearby issues on user demand (GET https://osmose.openstreetmap.fr/api/0.3/issues.json).
// Zero background polling; cached in sessionStorage.
import { currentLang } from './i18n.js';

export function buildOsmoseApiUrl(lat, lon, delta = 0.01) {
  const west = (lon - delta).toFixed(4);
  const south = (lat - delta).toFixed(4);
  const east = (lon + delta).toFixed(4);
  const north = (lat + delta).toFixed(4);
  return `https://osmose.openstreetmap.fr/api/0.3/issues.json?bbox=${west},${south},${east},${north}`;
}

export function buildOsmoseMapUrl(lat, lon, zoom = 16) {
  const lang = currentLang === 'ar' ? 'ar' : 'en';
  return `https://osmose.openstreetmap.fr/${lang}/map/#zoom=${zoom}&lat=${lat.toFixed(5)}&lon=${lon.toFixed(5)}`;
}

export async function fetchNearbyOsmoseIssues(lat, lon, delta = 0.01) {
  const cacheKey = `osmose_${lat.toFixed(3)}_${lon.toFixed(3)}`;
  try {
    if (typeof sessionStorage !== 'undefined') {
      const cached = sessionStorage.getItem(cacheKey);
      if (cached) {
        return { issues: JSON.parse(cached), cached: true };
      }
    }
  } catch {
    // Ignore storage errors
  }

  const url = buildOsmoseApiUrl(lat, lon, delta);
  const controller = typeof AbortController !== 'undefined' ? new AbortController() : null;
  const timeoutId = controller ? setTimeout(() => controller.abort(), 6000) : null;

  try {
    const res = await fetch(url, {
      headers: { 'Accept': 'application/json' },
      signal: controller ? controller.signal : undefined,
    });
    if (timeoutId) clearTimeout(timeoutId);
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    const data = await res.json();
    const issues = Array.isArray(data.issues) ? data.issues : [];
    try {
      if (typeof sessionStorage !== 'undefined') {
        sessionStorage.setItem(cacheKey, JSON.stringify(issues));
      }
    } catch {
      // Ignore storage quota
    }
    return { issues, cached: false };
  } catch (err) {
    if (timeoutId) clearTimeout(timeoutId);
    throw err;
  }
}

export function renderOsmoseResults(containerEl, result, lat, lon) {
  if (!containerEl) return;
  const isAr = currentLang === 'ar';
  containerEl.style.display = 'block';

  if (!result || result.error) {
    const mapUrl = buildOsmoseMapUrl(lat, lon);
    containerEl.innerHTML = `
      <div class="osmose-card error">
        <p style="margin-bottom: 6px; font-size: 12px; color: var(--color-warn);">
          ${isAr ? 'تعذّر الاتصال بخادم Osmose.' : 'Could not connect to Osmose server.'}
        </p>
        <a href="${mapUrl}" target="_blank" rel="noopener noreferrer" class="osmose-link-btn">
          ${isAr ? 'عرض تنبيهات المنطقة على موقع Osmose ↗' : 'View area issues on Osmose ↗'}
        </a>
      </div>
    `;
    return;
  }

  const issues = result.issues || [];
  if (issues.length === 0) {
    const mapUrl = buildOsmoseMapUrl(lat, lon);
    containerEl.innerHTML = `
      <div class="osmose-card success" style="padding: 10px 12px; background: rgba(0, 255, 135, 0.08); border: 1px solid rgba(0, 255, 135, 0.25); border-radius: 8px; font-size: 12px; color: #a8ffcc; display: flex; align-items: center; justify-content: space-between;">
        <span>✓ ${isAr ? 'لا توجد تنبيهات Osmose ضمن نطاق 2 كم' : 'No Osmose QA alerts within 2 km'}</span>
        <a href="${mapUrl}" target="_blank" rel="noopener noreferrer" style="color: var(--color-primary); font-size: 11px; text-decoration: underline;">
          ${isAr ? 'موقع Osmose ↗' : 'Osmose map ↗'}
        </a>
      </div>
    `;
    return;
  }

  const mapUrl = buildOsmoseMapUrl(lat, lon);
  const itemsHtml = issues.slice(0, 5).map(issue => {
    const title = issue.title ? (issue.title.auto || issue.title[isAr ? 'ar' : 'en'] || issue.title.en || Object.values(issue.title)[0] || 'Alert') : 'QA Alert';
    const issueUrl = `https://osmose.openstreetmap.fr/en/issue/${issue.id}`;
    const badgeColor = issue.severity === 1 ? 'var(--color-danger, #ff453a)' : 'var(--color-warn, #ffb03a)';
    return `
      <li style="margin-bottom: 6px; font-size: 11px; display: flex; align-items: baseline; justify-content: space-between; gap: 8px;">
        <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: ${badgeColor};">⚠️ ${title}</span>
        <a href="${issueUrl}" target="_blank" rel="noopener noreferrer" style="color: var(--color-primary); flex-shrink: 0; text-decoration: underline;">
          #${issue.id} ↗
        </a>
      </li>
    `;
  }).join('');

  containerEl.innerHTML = `
    <div class="osmose-card alerts" style="padding: 10px 12px; background: rgba(255, 176, 58, 0.08); border: 1px solid rgba(255, 176, 58, 0.3); border-radius: 8px;">
      <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; font-size: 12px; font-weight: 600; color: #ffb03a;">
        <span>${isAr ? `تنبيهات Osmose القريبة (${issues.length})` : `Nearby Osmose Alerts (${issues.length})`}</span>
        <a href="${mapUrl}" target="_blank" rel="noopener noreferrer" style="font-size: 11px; color: var(--color-primary); font-weight: normal; text-decoration: underline;">
          ${isAr ? 'عرض الكل ↗' : 'View all ↗'}
        </a>
      </div>
      <ul style="list-style: none; padding: 0; margin: 0;">
        ${itemsHtml}
      </ul>
    </div>
  `;
}
