// Entry point of the map page. Import order matters: Leaflet must be global
// before the plugins, and the translation tables must register before app.js
// builds any UI.
import './leaflet-setup.js';
import 'leaflet.markercluster';
import 'leaflet.heat';
import './vendor/BoundaryCanvas.js';

import 'leaflet/dist/leaflet.css';
import 'leaflet.markercluster/dist/MarkerCluster.css';
import 'leaflet.markercluster/dist/MarkerCluster.Default.css';
import './styles/fonts.css';
import './styles/index.css';

import './translations.js';
import './translations_static.js';
import { initAnalytics } from './analytics.js';
import './app.js';

initAnalytics();
