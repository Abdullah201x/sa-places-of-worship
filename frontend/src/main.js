// Entry point of the map page. app.js imports the Leaflet bundle itself, so the
// translation tables only need to register before app.js builds any UI.
import './map_switch.js';
import './styles/fonts.css';
import './styles/index.css';

import './translations.js';
import './translations_static.js';
import { initAnalytics } from './analytics.js';
import './app.js';

initAnalytics();
