// Leaflet and its plugins are UMD builds that extend the global L, so L has to
// exist before they are evaluated. main.js imports this module first.
import L from 'leaflet';

window.L = L;
