import { test, expect } from '@playwright/test';
import { open, mapCentre, KITS } from './helpers.js';

// OSM compliance: never the OSMF tile servers, and the OSM API,
// Osmose and Overpass only on a user action, never on load or while panning.
for (const kit of KITS) {
  test(`${kit.name}: no OSM tile, API, Osmose or Overpass requests on load or pan`, async ({ page }) => {
    const hosts = new Set();
    page.on('request', r => hosts.add(new URL(r.url()).host));

    await open(page, `/${kit.query}#map=11/24.7136/46.6753&lang=en`);
    const c = await mapCentre(page);
    await page.mouse.move(c.x, c.y);
    await page.mouse.down();
    await page.mouse.move(c.x + 200, c.y + 80, { steps: 8 });
    await page.mouse.up();
    await page.waitForTimeout(2000);

    for (const forbidden of ['tile.openstreetmap.org', 'api.openstreetmap.org', 'osmose.openstreetmap.fr', 'overpass-api.de', 'planet.openstreetmap.org']) {
      expect(hosts, forbidden).not.toContain(forbidden);
    }
  });
}
