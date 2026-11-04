// The map backend ("kit") chosen at startup: MapLibre GL by default, with
// ?map=leaflet as a fallback. main.js loads one kit and registers it here before
// app.js runs, so app.js never touches a map library directly. See kit_leaflet.js
// for the shape every kit implements.
export let kit = null;

export function setKit(k) {
  kit = k;
}

export function wantsGl(search = (typeof window !== 'undefined' ? window.location?.search : '') || '') {
  const p = new URLSearchParams(search).get('map');
  if (p === 'leaflet') return false;
  return true;
}
