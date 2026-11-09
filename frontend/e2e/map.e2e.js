import { test, expect } from '@playwright/test';
import { watchPage, open, viewCount, mapCentre, KITS } from './helpers.js';

// The same checks on both map backends (Leaflet by default, MapLibre with ?map=gl),
// using only backend-independent selectors, then a parity test that compares them.
const POPUP = '.leaflet-popup, .maplibregl-popup';
const PLACE = 'way/1305005679'; // مسجد السلولي, Riyadh

// Zoom as written in the permalink (Leaflet's numbering on both backends).
const zoomInUrl = page => page.evaluate(() => Number(new URLSearchParams(location.hash.slice(1)).get('map')?.split('/')[0]));

for (const kit of KITS) {
  test.describe(kit.name, () => {
    const url = hash => `/${kit.query}${hash}&lang=en`;

    test('renders the data and counts what is in view', async ({ page }) => {
      const problems = watchPage(page);
      await open(page, url('#map=12/24.7136/46.6753'));
      await expect(page.locator('#loading-overlay')).toHaveClass(/hidden/); // faded out with opacity, which Playwright still counts as visible
      expect(await viewCount(page)).toBeGreaterThan(500);
      expect(problems).toEqual([]);
    });

    test('a permalinked place is selected and shown in the details panel', async ({ page }) => {
      await open(page, url(`#place=${PLACE}`));
      await expect(page.locator('#sb-selection')).toContainText(PLACE);
      await expect(page.locator('#details-name-ar')).toHaveText('مسجد السلولي');
    });

    test('clicking a place opens its popup and selects it', async ({ page }) => {
      await open(page, url('#map=16/24.72435/46.67189'));
      const c = await mapCentre(page);
      await page.mouse.click(c.x, c.y);
      await expect(page.locator(POPUP)).toBeVisible();
      await expect(page.locator('#sb-selection')).toContainText(PLACE);
    });

    test('clicking a cluster zooms in', async ({ page }) => {
      await open(page, url('#map=12/24.7136/46.6753'));
      const before = await zoomInUrl(page);
      // A cluster on the open part of the map, clear of the sidebar and the top bar.
      const target = await page.evaluate(() => {
        const free = [...document.querySelectorAll('.marker-cluster-custom')].map(e => e.getBoundingClientRect())
          .filter(r => r.x + r.width / 2 < 800 && r.y > 90 && r.y < 700);
        const r = free[3] || free[0];
        return r && { x: r.x + r.width / 2, y: r.y + r.height / 2 };
      });
      expect(target, 'a cluster is on screen').toBeTruthy();
      await page.mouse.click(target.x, target.y);
      await expect.poll(() => zoomInUrl(page), { timeout: 15_000 }).toBeGreaterThan(before);
    });

    test('right-click opens the add-mosque menu and drops the pin', async ({ page }) => {
      await open(page, url('#map=14/24.7136/46.6753'));
      await page.mouse.click(300, 300, { button: 'right' });
      await page.locator('.custom-context-popup .ctx-add-mosque').click();
      await expect(page.locator('.add-mosque-marker')).toBeVisible();
      await expect(page.locator('#add-mosque-coords-display')).toHaveText(/^\d+\.\d+, \d+\.\d+$/);
    });

    test('all four basemaps can be selected, with the compass following the satellite', async ({ page }) => {
      const problems = watchPage(page);
      await open(page, url('#map=13/24.7136/46.6753'));
      for (const key of ['light', 'streets', 'satellite', 'dark']) {
        await page.locator(`[data-basemap=${key}]`).click();
        await page.waitForTimeout(1200);
        await expect(page.locator(`[data-basemap=${key}]`)).toHaveClass(/active/);
        const compassShown = await page.evaluate(() => !document.getElementById('qibla-compass').classList.contains('hidden'));
        expect(compassShown).toBe(key === 'satellite');
      }
      expect(problems).toEqual([]);
    });

    test('gap and improve modes redraw, and the density sliders work', async ({ page }) => {
      const problems = watchPage(page);
      await open(page, url('#map=11/24.7136/46.6753'));
      for (const mode of ['gap', 'improve', 'poi']) {
        await page.locator(`#mode-${mode}`).click();
        await page.waitForTimeout(1200);
        await expect(page.locator(`#mode-${mode}`)).toHaveClass(/active/);
        expect(await viewCount(page)).toBeGreaterThan(0);
      }
      await page.locator('#slider-radius').fill('40');
      await page.locator('#slider-blur').fill('30');
      await page.waitForTimeout(500);
      expect(problems).toEqual([]);
    });

    test('Wikidata suggestions load, cluster and open a popup', async ({ page }) => {
      await open(page, url('#map=16/24.4784/39.6124'));
      await page.locator('#suggestions-toggle').evaluate(el => el.click());
      await expect(page.locator('#suggestions-badge')).toContainText(/suggestions/, { timeout: 30_000 });
      await page.waitForTimeout(1500);
      const c = await mapCentre(page);
      await page.mouse.click(c.x, c.y);
      await expect(page.locator('.suggestion-popup')).toBeVisible();
    });

    test('the permalink follows a pan', async ({ page }) => {
      await open(page, url('#map=12/24.7136/46.6753'));
      const c = await mapCentre(page);
      await page.mouse.move(c.x - 300, c.y - 100);
      await page.mouse.down();
      await page.mouse.move(c.x - 100, c.y - 40, { steps: 8 });
      await page.mouse.up();
      await expect.poll(() => page.evaluate(() => new URLSearchParams(location.hash.slice(1)).get('map')), { timeout: 10_000 })
        .not.toBe('12/24.71360/46.67530');
    });
  });
}

// What the user sees must not depend on the backend: same bounds, same counts.
test('both backends agree on what is in view', async ({ browser }) => {
  const counts = {};
  for (const kit of KITS) {
    const page = await browser.newPage();
    for (const hash of ['#map=12/24.7136/46.6753', '#map=7/24.5/46.5', '#mode=gap&map=11/24.7136/46.6753', '#mode=improve&map=13/24.7136/46.6753']) {
      await open(page, `/${kit.query}${hash}&lang=en`);
      (counts[hash] ||= {})[kit.name] = await viewCount(page);
    }
    await page.close();
  }
  for (const [hash, byKit] of Object.entries(counts)) {
    expect(byKit.leaflet, hash).toBe(byKit.maplibre);
  }
});
