// /?map=gl opens the MapLibre preview at /mapgl, keeping the hash (view and
// language). Leaflet stays the default; anything else, including ?map=leaflet,
// loads it as before.
if (new URLSearchParams(window.location.search).get('map') === 'gl') {
  window.location.replace(`/mapgl${window.location.hash}`);
}
