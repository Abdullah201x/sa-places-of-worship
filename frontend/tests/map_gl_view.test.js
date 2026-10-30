import { describe, it, expect } from 'vitest';
import {
  buildStyle, basemapLayerIds, parseMapHash, formatMapHash, popupRows, popupLinks,
  OVERLAY_IDS, CLICK_LAYERS, LAYER_KEYS, BASEMAPS,
} from '../src/map_gl_view.js';

describe('buildStyle', () => {
  const style = buildStyle({ origin: 'https://manara.example', basemap: 'dark' });
  const layer = id => style.layers.find(l => l.id === id);

  it('points each overlay at its own pmtiles file on the page origin', () => {
    for (const id of OVERLAY_IDS) {
      expect(style.sources[id]).toMatchObject({ type: 'vector', url: `pmtiles://https://manara.example/data/${id}.pmtiles` });
      expect(layer(id)['source-layer']).toBe(id);
    }
  });

  it('shows only the chosen basemap', () => {
    for (const name of Object.keys(BASEMAPS)) {
      for (const id of basemapLayerIds(name)) {
        expect(layer(id).layout.visibility).toBe(name === 'dark' ? 'visible' : 'none');
      }
    }
  });

  it('draws overlays above every basemap layer, places on top', () => {
    const order = style.layers.map(l => l.id);
    const lastBase = Math.max(...order.map((id, i) => (id.startsWith('base-') ? i : -1)));
    expect(order.indexOf('gaps')).toBeGreaterThan(lastBase);
    expect(order.indexOf('places')).toBeGreaterThan(order.indexOf('suggestions'));
    expect(order.indexOf('suggestions')).toBeGreaterThan(order.indexOf('gaps'));
  });

  it('keeps suggestions hidden until switched on, and carries OSM attribution', () => {
    expect(layer('suggestions').layout.visibility).toBe('none');
    expect(style.sources.places.attribution).toContain('OpenStreetMap');
  });

  it('only requests origins the CSP allows', () => {
    const urls = Object.values(style.sources).flatMap(s => s.tiles || []);
    expect(urls.length).toBeGreaterThan(0);
    for (const u of urls) expect(u.startsWith('https://server.arcgisonline.com/')).toBe(true);
  });

  it('lists click layers and keys that all exist', () => {
    for (const id of CLICK_LAYERS) expect(layer(id)).toBeTruthy();
    expect(Object.values(LAYER_KEYS).sort()).toEqual([...CLICK_LAYERS].sort());
  });
});

describe('map hash', () => {
  it('round-trips zoom, lat and lon while keeping other params', () => {
    const hash = formatMapHash({ zoom: 7.5, lat: 24.7136, lon: 46.6753 }, '#lang=en');
    expect(hash).toBe('#lang=en&map=7.50/24.71360/46.67530');
    expect(parseMapHash(hash)).toEqual({ zoom: 7.5, lat: 24.7136, lon: 46.6753 });
  });

  it('rejects malformed or out-of-range values', () => {
    for (const h of ['', '#', '#map=abc', '#map=5/24', '#map=5/99/46', '#map=30/24/46', '#map=5/24/200']) {
      expect(parseMapHash(h)).toBeNull();
    }
  });
});

describe('popup content', () => {
  it('lists place fields and hides empty or unknown ones', () => {
    const rows = popupRows('places', { name: 'مسجد النور', name_en: '', religion: 'muslim', denomination: 'unknown', building: 'mosque' });
    expect(rows).toEqual([['glName', 'مسجد النور'], ['glReligion', 'muslim'], ['glBuilding', 'mosque']]);
  });

  it('formats suggestion and gap values', () => {
    expect(popupRows('suggestions', { name_ar: 'س', qid: 'Q1', nearest_osm_m: 377 }))
      .toEqual([['glName', 'س'], ['glWikidata', 'Q1'], ['glNearest', '377 m']]);
    expect(popupRows('gaps', { urgency: 100, gap_score: 29.459, road_len: 4775 }))
      .toEqual([['glUrgency', '100'], ['glScore', '29.459'], ['glRoadLength', '4775 m']]);
  });

  it('keeps hostile values as plain strings for textContent', () => {
    const [[, v]] = popupRows('places', { name: '<img src=x onerror=alert(1)>' });
    expect(v).toBe('<img src=x onerror=alert(1)>');
  });

  it('links a place to its own OSM object by type, plus iD', () => {
    const links = popupLinks('places', { osm_id: 42, osm_type: 'way' }, [46.5, 24.5]);
    expect(links[0]).toEqual({ key: 'glViewOsm', href: 'https://www.openstreetmap.org/way/42' });
    expect(links.at(-1).href).toBe('https://www.openstreetmap.org/edit?editor=id#map=18/24.50000/46.50000');
  });

  it('only links well-formed Wikidata ids', () => {
    expect(popupLinks('suggestions', { qid: 'Q16125362' }, [39, 24]).map(l => l.key)).toEqual(['glViewWikidata', 'glEditId']);
    expect(popupLinks('suggestions', { qid: 'javascript:1' }, [39, 24]).map(l => l.key)).toEqual(['glEditId']);
  });
});
