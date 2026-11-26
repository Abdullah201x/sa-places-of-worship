import { test, expect } from '@playwright/test';
import { watchPage, open } from './helpers.js';

// Satellite AI candidates: the panel appears only for allowlisted reviewers, "Start reviewing"
// opens the highest-confidence unreviewed candidate, and a verdict is PUT to the backend and
// reflected in the popup and the counters. The backend is mocked (smoke tests run without it).

const DETECTIONS = {
  type: 'FeatureCollection',
  features: [
    {
      type: 'Feature', id: 'ai_det_00090',
      geometry: { type: 'Point', coordinates: [46.6753, 24.7136] },
      properties: {
        id: 'ai_det_00090', confidence: 0.91, dual: true, region_code: 'SA-01', region_name: 'Riyadh Province',
        qibla: 244.1, area_m2: 812.4, model: 'best_v5_obb.pt',
        footprint: '{"type":"Polygon","coordinates":[[[46.6752,24.7135],[46.6754,24.7135],[46.6754,24.7137],[46.6752,24.7137],[46.6752,24.7135]]]}',
        n_positive: 0, n_negative: 0, n_unsure: 0, my_verdict: null,
      },
    },
    {
      type: 'Feature', id: 'ai_det_00091',
      geometry: { type: 'Point', coordinates: [46.69, 24.72] },
      properties: {
        id: 'ai_det_00091', confidence: 0.55, dual: false, region_code: 'SA-01', region_name: 'Riyadh Province',
        qibla: 244.1, area_m2: null, model: 'best_v5_obb.pt', footprint: null,
        n_positive: 0, n_negative: 2, n_unsure: 0, my_verdict: null,
      },
    },
  ],
};

async function mockBackend(page, { allowed }) {
  const reviews = [];
  await page.route('**/api/v1/me', route => route.fulfill({
    json: { osm_uid: 42, display_name: 'Reviewer', can_view_suggestions: allowed },
  }));
  await page.route('**/api/v1/ai/detections', route => route.fulfill({ json: DETECTIONS }));
  await page.route('**/api/v1/ai/detections/*/review', async route => {
    const req = route.request();
    const body = req.postDataJSON();
    reviews.push({ method: req.method(), url: req.url(), body, csrf: req.headers()['x-manara-csrf'] });
    await route.fulfill({ json: { id: 'ai_det_00090', my_verdict: body.verdict, n_positive: 1, n_negative: 0, n_unsure: 0 } });
  });
  return reviews;
}

test('reviewers can step through AI candidates and mark them', async ({ page }) => {
  const problems = watchPage(page);
  const reviews = await mockBackend(page, { allowed: true });
  await open(page, '/#map=12/24.7136/46.6753&lang=en');

  await expect(page.locator('#ai-section')).toBeVisible();
  await page.locator('#ai-review-next').click();

  const popup = page.locator('.ai-popup');
  await expect(popup).toBeVisible();
  await expect(popup).toContainText('ai_det_00090'); // highest confidence first
  await expect(popup).toContainText('Seen on Esri + Mapbox imagery');
  await expect(page.locator('#ai-count-pending')).toHaveText('2');
  await expect(page.locator('#ai-toggle')).toBeChecked();

  await popup.locator('.btn-ai-positive').click();
  await expect(popup.locator('.btn-ai-positive')).toHaveClass(/active/);
  await expect(popup).toContainText('✅ 1');
  await expect(page.locator('#ai-count-pending')).toHaveText('1');
  expect(reviews).toHaveLength(1);
  expect(reviews[0]).toMatchObject({ method: 'PUT', body: { verdict: 'positive' }, csrf: '1' });
  expect(reviews[0].url).toContain('/api/v1/ai/detections/ai_det_00090/review');

  await popup.locator('.btn-ai-next').click();
  await expect(page.locator('.ai-popup')).toContainText('ai_det_00091');
  await expect(page.locator('.ai-popup')).toContainText('Seen on one imagery source');

  expect(problems).toEqual([]);
});

test('the AI panel stays hidden and nothing is fetched for other users', async ({ page }) => {
  await mockBackend(page, { allowed: false });
  let fetched = false;
  page.on('request', r => { if (r.url().includes('/api/v1/ai/')) fetched = true; });
  await open(page, '/#map=12/24.7136/46.6753&lang=en');
  await expect(page.locator('#ai-section')).toBeHidden();
  expect(fetched).toBe(false);
});
