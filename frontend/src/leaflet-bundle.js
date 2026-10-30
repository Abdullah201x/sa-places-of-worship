// Leaflet with its plugins and styles. app.js imports this first: it uses the
// global L while its own module body runs, so L must exist before that. Import
// order is the only thing guaranteeing it (the plugins are UMD builds that
// extend the global L), so keep leaflet-setup.js first.
import './leaflet-setup.js';
import 'leaflet.markercluster';
import 'leaflet.heat';
import './vendor/BoundaryCanvas.js';

import 'leaflet/dist/leaflet.css';
import 'leaflet.markercluster/dist/MarkerCluster.css';
import 'leaflet.markercluster/dist/MarkerCluster.Default.css';
