// Live mosque updates: pure helpers shared by app.js (delta from
// GET /api/v1/places/live, plus the uploader's own just-added mosques).
// See docs/live-gap-updates-plan.md.

// The single mapping from OSM tags to the place-property shape used by the
// static GeoJSON; used for both Manara uploads and server deltas.
export function tagsToPlaceProps(tags) {
  const t = tags || {};
  const isMosque = t.amenity === 'mosque' || t.building === 'mosque';
  return {
    name: t.name || t['name:ar'] || 'مسجد',
    name_en: t['name:en'] || '',
    name_ar: t['name:ar'] || '',
    name_original: t.name || '',
    name_ar_original: t['name:ar'] || '',
    name_en_original: t['name:en'] || '',
    religion: t.religion || (isMosque ? 'muslim' : 'unknown'),
    denomination: t.denomination || 'unknown',
    building: t.building || '',
    amenity: t.amenity || 'place_of_worship',
    wheelchair: t.wheelchair || '',
    female: t['female:prayer_room'] || '',
    capacity: t.capacity || '',
    wikidata: t.wikidata || '',
  };
}

function typeOf(props) {
  if (props.osm_type) return props.osm_type;
  if (props.geom_type === 'Point') return 'node';
  if (props.geom_type === 'Relation') return 'relation';
  return 'way';
}

// A server feature ({properties: {osm_type, osm_id, version, edited_at, region_code, tags}})
// as a place feature.
export function liveFeatureToPlace(f) {
  const p = f.properties || {};
  return {
    type: 'Feature',
    properties: {
      ...tagsToPlaceProps(p.tags),
      osm_id: p.osm_id,
      osm_type: p.osm_type || 'node',
      geom_type: 'Point',
      version: p.version,
      edited_at: p.edited_at,
      region_code: p.region_code,
      _live: true,
    },
    geometry: f.geometry,
  };
}

// Applies a live delta ({features, removed}) to `places` in place.
// - `removed` drops the object, and a snapshot place whose inner node it is (poi_node_id);
// - a feature already present from the snapshot wins; an earlier live copy is replaced.
// Returns true when `places` changed.
export function mergeLivePlaces(places, delta) {
  let changed = false;
  const removed = (delta && delta.removed) || [];
  if (removed.length) {
    const gone = new Set(removed.map(r => `${r.osm_type}/${r.osm_id}`));
    const goneNodes = new Set(removed.filter(r => r.osm_type === 'node').map(r => r.osm_id));
    let w = 0;
    for (let i = 0; i < places.length; i++) {
      const p = places[i].properties;
      const drop = gone.has(`${typeOf(p)}/${p.osm_id}`) || (p.poi_node_id && goneNodes.has(p.poi_node_id));
      if (drop) changed = true;
      else places[w++] = places[i];
    }
    places.length = w;
  }

  const features = (delta && delta.features) || [];
  if (features.length) {
    const index = new Map();
    places.forEach((f, i) => index.set(`${typeOf(f.properties)}/${f.properties.osm_id}`, i));
    for (const feat of features) {
      const key = `${typeOf(feat.properties)}/${feat.properties.osm_id}`;
      const at = index.get(key);
      if (at === undefined) {
        index.set(key, places.length);
        places.push(feat);
        changed = true;
      } else if (places[at].properties._live || places[at].properties._newlyAdded) {
        places[at] = feat;
        changed = true;
      }
    }
  }
  return changed;
}

// Points of mosques that exist only in the live layer (they clear gap cells).
export function livePoints(places) {
  const pts = [];
  for (const f of places) {
    if ((f.properties._live || f.properties._newlyAdded) && f.geometry && f.geometry.coordinates) {
      pts.push({ lon: f.geometry.coordinates[0], lat: f.geometry.coordinates[1] });
    }
  }
  return pts;
}

// Mosques the user added from Manara, kept across reloads (even when the backend
// is unreachable) until the published dataset is newer than the upload.
export const LocalAdds = {
  KEY: 'manara_local_adds_v1',

  all() {
    try {
      return JSON.parse(localStorage.getItem(this.KEY)) || {};
    } catch (_) {
      return {};
    }
  },

  add(nodeId, lat, lon, tags) {
    const adds = this.all();
    adds[nodeId] = { nodeId, lat, lon, tags: { ...tags }, uploadedAt: Date.now() };
    try {
      localStorage.setItem(this.KEY, JSON.stringify(adds));
    } catch (_) {}
  },

  prune(pbfTimestampMs) {
    if (!pbfTimestampMs) return;
    const adds = this.all();
    let changed = false;
    for (const [k, a] of Object.entries(adds)) {
      if (a.uploadedAt <= pbfTimestampMs) {
        delete adds[k];
        changed = true;
      }
    }
    if (changed) {
      try {
        localStorage.setItem(this.KEY, JSON.stringify(adds));
      } catch (_) {}
    }
  },

  // The adds as a live delta (features only).
  asDelta() {
    const features = Object.values(this.all()).map(a => ({
      type: 'Feature',
      properties: {
        osm_type: 'node',
        osm_id: a.nodeId,
        version: 1,
        edited_at: new Date(a.uploadedAt).toISOString(),
        tags: a.tags,
      },
      geometry: { type: 'Point', coordinates: [a.lon, a.lat] },
    }));
    return { features, removed: [] };
  },
};
