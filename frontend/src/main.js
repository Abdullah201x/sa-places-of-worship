// Entry point of the map page. The map backend (Leaflet, or MapLibre with
// ?map=gl) is chosen and loaded first, then app.js, which only talks to it
// through map_kit.js. Translations register before app.js builds any UI.
import './styles/fonts.css';
import './styles/index.css';

import './translations.js';
import './translations_static.js';
import { initAnalytics } from './analytics.js';
import { setKit } from './map_kit.js';

const { kit } = await import('./kit_leaflet.js');
setKit(kit);
await import('./app.js');

initAnalytics();
