// Entry point of the map page. The map backend (Leaflet, or MapLibre with
// ?map=gl) is chosen and loaded first, then app.js, which only talks to it
// through map_kit.js. Translations register before app.js builds any UI.
import './styles/fonts.css';
import './styles/index.css';

import './translations.js';
import './translations_static.js';
import { initAnalytics } from './analytics.js';
import { setKit } from './map_kit.js';

const { kit } = await import('./kit_gl.js');
setKit(kit);
const { boot } = await import('./app.js');
if (boot) boot();

initAnalytics();

if (typeof navigator !== 'undefined' && 'serviceWorker' in navigator && (window.location.protocol === 'https:' || window.location.hostname === 'localhost')) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  });
}
