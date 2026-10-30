import { defineConfig } from '@playwright/test';

// Smoke tests against the built site (`npm run smoke` builds first). They use the
// system Chrome locally and Playwright's Chromium in CI. The preview server is
// HTTPS with a self-signed certificate (OSM OAuth needs https), hence
// ignoreHTTPSErrors. WebGL runs on a software rasteriser (SwiftShader), so the
// MapLibre tests are slow; keep one worker and generous timeouts.
export default defineConfig({
  testDir: 'e2e',
  testMatch: '**/*.e2e.js',
  timeout: 120_000,
  expect: { timeout: 20_000 },
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
  use: {
    baseURL: 'https://localhost:8000',
    ignoreHTTPSErrors: true,
    channel: process.env.CI ? undefined : 'chrome',
    launchOptions: { args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] },
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1280, height: 800 } } },
    // Phone-sized: every route must still load and not overflow sideways.
    { name: 'mobile', testMatch: '**/routes.e2e.js', use: { viewport: { width: 390, height: 844 }, hasTouch: true } },
  ],
  webServer: {
    command: 'npx vite preview',
    url: 'https://localhost:8000/',
    ignoreHTTPSErrors: true,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
