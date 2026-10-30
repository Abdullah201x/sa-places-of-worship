// The map backend ("kit") chosen at startup: Leaflet by default, MapLibre with
// ?map=gl. main.js loads one kit and registers it here before app.js runs, so
// app.js never touches a map library directly. See kit_leaflet.js for the
// shape every kit implements.
export let kit = null;

export function setKit(k) {
  kit = k;
}

export function wantsGl(search = window.location.search) {
  return new URLSearchParams(search).get('map') === 'gl';
}
