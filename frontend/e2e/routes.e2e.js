import { test, expect } from '@playwright/test';
import { watchPage, open } from './helpers.js';

// Every page, in both languages: it loads without uncaught errors, CSP violations
// or failed requests, shows the language that was asked for, and does not scroll
// sideways (the RTL layout and the phone viewport are where that breaks).
const ROUTES = ['/', '/about', '/privacy', '/community', '/tags', '/guides', '/start', '/tasks', '/data', '/mapgl'];

for (const lang of ['ar', 'en']) {
  for (const route of ROUTES) {
    test(`${route} loads cleanly in ${lang}`, async ({ page }) => {
      const problems = watchPage(page);
      await open(page, `${route}#lang=${lang}`);

      expect(problems).toEqual([]);
      await expect(page.locator('html')).toHaveAttribute('lang', lang);
      await expect(page.locator('html')).toHaveAttribute('dir', lang === 'ar' ? 'rtl' : 'ltr');
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow, 'horizontal overflow in px').toBeLessThanOrEqual(1);
    });
  }
}
