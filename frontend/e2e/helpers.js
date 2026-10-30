import { expect } from '@playwright/test';

const SITE = 'https://localhost:8000';

// Collects what must never happen on any page: uncaught errors, CSP violations
// and failed requests. Backend calls (/api, /auth) are ignored because the smoke
// tests run without the FastAPI backend, and so are optional generated overlays.
export function watchPage(page) {
  const problems = [];
  page.on('pageerror', e => problems.push(`pageerror: ${e.message.slice(0, 200)}`));
  page.on('console', m => {
    if (/Content Security Policy|Refused to/i.test(m.text())) problems.push(`csp: ${m.text().slice(0, 200)}`);
  });
  page.on('response', r => {
    const url = new URL(r.url());
    if (r.status() < 400 || url.origin !== SITE) return;
    if (/^\/(api|auth|region|place)\//.test(url.pathname)) return;
    if (url.pathname.endsWith('.pmtiles')) return;
    problems.push(`http ${r.status()}: ${url.pathname}`);
  });
  return problems;
}

// Loads a page and waits for the network to settle. Hash params (map view, mode, lang) go on the URL.
export async function open(page, path, { settle = 2500 } = {}) {
  await page.goto(path, { waitUntil: 'networkidle' });
  await page.waitForTimeout(settle);
}

// "1,439 in view" -> 1439
export async function viewCount(page) {
  const text = await page.locator('#sb-visible-count').textContent();
  return Number(text.replace(/[^\d]/g, ''));
}

export const KITS = [
  { name: 'maplibre', query: '' },
  { name: 'leaflet', query: '?map=leaflet' },
];

// Centre of the map element, where a permalinked place sits.
export async function mapCentre(page) {
  const box = await page.locator('#map').boundingBox();
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}

export { expect };
