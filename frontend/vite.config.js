import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vite';
import basicSsl from '@vitejs/plugin-basic-ssl';

const here = path.dirname(fileURLToPath(import.meta.url));

// Generated datasets the app may fetch from /data/. In production Caddy serves
// /data/ from the published data folder; in dev and preview this plugin serves
// the same names (and only those) from MANARA_DATA_DIR, by default the repo
// root where the pipeline currently writes them.
const DATA_FILES = new Set([
  'summary.json',
  'places_of_worship_sa.geojson',
  'worship_gaps_sa.json',
  'sa_boundary.geojson',
  'mosque_sizes.json',
  'mosque_anomalies.json',
  'suggested_mosques_sa.geojson',
]);
const dataDir = path.resolve(here, process.env.MANARA_DATA_DIR || '..');

// The production Content-Security-Policy lives in deploy/Caddyfile.manara;
// `npm run preview` sends the same header so a policy violation shows up
// locally before it ships.
const caddyfile = fs.readFileSync(path.resolve(here, '../deploy/Caddyfile.manara'), 'utf8');
const CSP = caddyfile.match(/Content-Security-Policy "([^"]+)"/)[1];

function serveData(req, res, next) {
  const url = new URL(req.url, 'http://localhost');
  if (!url.pathname.startsWith('/data/')) return next();
  const name = url.pathname.slice('/data/'.length);
  if (!DATA_FILES.has(name)) {
    res.statusCode = 404;
    return res.end('Not found');
  }
  const type = name.endsWith('.geojson') ? 'application/geo+json' : 'application/json';
  res.setHeader('Content-Type', `${type}; charset=utf-8`);
  fs.createReadStream(path.join(dataDir, name))
    .on('error', () => { res.statusCode = 404; res.end('Not found'); })
    .pipe(res);
}

// Clean URLs for the content pages, as Caddy's try_files does in production.
const PAGES = new Set(['/about', '/privacy']);
function cleanUrls(req, res, next) {
  const [pathname, query] = req.url.split('?');
  if (PAGES.has(pathname)) req.url = `${pathname}.html${query ? `?${query}` : ''}`;
  next();
}

const dataPlugin = {
  name: 'manara-data',
  configureServer(server) { server.middlewares.use(cleanUrls); server.middlewares.use(serveData); },
  configurePreviewServer(server) { server.middlewares.use(cleanUrls); server.middlewares.use(serveData); },
};

// OSM OAuth only accepts HTTPS redirect URIs, so dev and preview run on
// https://localhost:8000/ (the redirect URI registered for local testing).
export default defineConfig({
  appType: 'mpa',
  plugins: [basicSsl(), dataPlugin],
  server: {
    port: 8000,
    strictPort: true,
    proxy: {
      '/api': 'http://127.0.0.1:8010',
      '/auth': 'http://127.0.0.1:8010',
    },
  },
  preview: { port: 8000, strictPort: true, headers: { 'Content-Security-Policy': CSP } },
  build: {
    // Lightning CSS (Vite's default CSS minifier) collapses
    // backdrop-filter + -webkit-backdrop-filter with var() values into the
    // prefixed one only, which Chrome ignores: the glass panels lose their blur.
    cssMinify: 'esbuild',
    // Keep fonts as files: the CSP allows font-src 'self' only, not data: URIs.
    assetsInlineLimit: filePath => (filePath.endsWith('.woff2') ? false : undefined),
    rollupOptions: {
      input: {
        main: path.resolve(here, 'index.html'),
        about: path.resolve(here, 'about.html'),
        privacy: path.resolve(here, 'privacy.html'),
      },
    },
  },
});
