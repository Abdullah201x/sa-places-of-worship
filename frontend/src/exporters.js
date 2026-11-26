// Exports and editor hand-offs for the currently filtered places, based on
// MappingTools in the osm x wikidata project (js/tools.js).
import { addTranslations, currentLang, t, fmtNum } from './i18n.js';
import { downloadFile } from './ui.js';
import { map, filteredPlaces, currentMode, currentReligionFilter, currentImprovementFilter, osmTypeOf, getIssues, showToast } from './app.js';

addTranslations({
  exportTitle: ['📤 تصدير القائمة الحالية', '📤 Export current list'],
  exportCsv: ['CSV (Excel)', 'CSV (Excel)'],
  exportMapRoulette: ['MapRoulette GeoJSON', 'MapRoulette GeoJSON'],
  exportJosmVisible: ['تحميل المرئي في JOSM', 'Load visible in JOSM'],
  exportOverpass: ['Overpass Turbo', 'Overpass Turbo'],
  exportEmpty: ['لا توجد أماكن في القائمة الحالية للتصدير.', 'The current list is empty; nothing to export.'],
  exportDone: ['تم تصدير {n} مكان.', 'Exported {n} places.'],
  josmVisibleNone: ['لا توجد أماكن ظاهرة في النطاق الحالي. قرّب الخريطة على منطقة.', 'No listed places in the current view. Zoom in on an area first.'],
  josmVisibleCapped: ['تم إرسال أول {n} مكان فقط إلى JOSM (قرّب الخريطة لتقليل العدد).', 'Only the first {n} places were sent to JOSM (zoom in to narrow the list).'],
  josmVisibleSent: ['تم إرسال {n} مكان إلى JOSM.', 'Sent {n} places to JOSM.'],
  josmUnreachable: ['تعذر الاتصال بـ JOSM. يرجى تشغيل JOSM وتفعيل التحكم عن بعد (Remote Control) في الإعدادات.', 'Could not reach JOSM. Start JOSM and enable Remote Control in its preferences.'],
  overpassUnsupported: ['هذا الفحص محسوب من الهندسة أو التعلم الآلي ولا يمكن التعبير عنه في Overpass؛ يعرض الاستعلام كل أماكن العبادة في النطاق.', 'This check is computed from geometry/ML and cannot be expressed in Overpass; the query shows all places of worship in view.'],
  mrInstruction: ['راجع {name} ({osm}) وأصلح: {issues}', 'Review {name} ({osm}) and fix: {issues}'],
});

export const Exporters = {
  JOSM_MAX_OBJECTS: 300,

  _download(filename, content, mime) {
    downloadFile(filename, content, mime);
  },

  _filename(ext) {
    const filter = currentMode === 'improve' ? currentImprovementFilter : currentReligionFilter;
    const date = new Date().toISOString().slice(0, 10);
    return `sa-worship-${currentMode}-${filter}-${date}.${ext}`;
  },

  _issueTitles(props) {
    return getIssues(props).map(i => (currentLang === 'en' ? i.title_en : i.title_ar));
  },

  _ref(props) {
    return `${osmTypeOf(props)}/${props.osm_id}`;
  },

  _list() {
    if (!filteredPlaces.length) {
      showToast(t('exportEmpty'), 'error');
      return null;
    }
    return filteredPlaces;
  },

  // CSV with a UTF-8 BOM so Excel opens Arabic text correctly.
  exportCsv() {
    const list = this._list();
    if (!list) return;
    const cell = v => {
      let s = String(v ?? '');
      if (/^[=+\-@\t\r]/.test(s)) {
        s = "'" + s;
      }
      return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const header = ['osm_type', 'osm_id', 'poi_node_id', 'name', 'name_en', 'religion', 'denomination',
                    'lat', 'lon', 'version', 'edited_at', 'issues', 'osm_url'];
    const rows = list.map(f => {
      const p = f.properties;
      const [lon, lat] = f.geometry.coordinates;
      return [osmTypeOf(p), p.osm_id, p.poi_node_id || '', p.name_original, p.name_en_original, p.religion,
              p.denomination, lat, lon, p.version, p.edited_at, this._issueTitles(p).join(' | '),
              `https://www.openstreetmap.org/${this._ref(p)}`].map(cell).join(',');
    });
    this._download(this._filename('csv'), '\ufeff' + [header.join(','), ...rows].join('\r\n'), 'text/csv;charset=utf-8');
    showToast(t('exportDone', { n: fmtNum(list.length) }));
  },

  // A FeatureCollection MapRoulette accepts as a challenge source: one task
  // per place, identified by @id, with the detected issues as instructions.
  exportMapRoulette() {
    const list = this._list();
    if (!list) return;
    const features = list.map(f => {
      const p = f.properties;
      const issues = this._issueTitles(p);
      return {
        type: 'Feature',
        geometry: f.geometry,
        properties: {
          '@id': this._ref(p),
          name: p.name_original || '',
          'name:en': p.name_en_original || '',
          issues: issues.join(' | '),
          instruction: t('mrInstruction', { name: p.name, osm: this._ref(p), issues: issues.join('; ') })
        }
      };
    });
    this._download(this._filename('geojson'), JSON.stringify({
      type: 'FeatureCollection',
      // ODbL: derived from OSM data, so the attribution travels with the file.
      attribution: '© OpenStreetMap contributors, ODbL 1.0 (https://www.openstreetmap.org/copyright)',
      features
    }), 'application/geo+json');
    showToast(t('exportDone', { n: fmtNum(list.length) }));
  },

  // JOSM Remote Control load_object for the listed places inside the current view.
  loadVisibleInJosm() {
    const bounds = map.getBounds();
    const visible = filteredPlaces.filter(f => bounds.contains([f.geometry.coordinates[1], f.geometry.coordinates[0]]));
    if (!visible.length) {
      showToast(t('josmVisibleNone'), 'error');
      return;
    }
    const capped = visible.slice(0, this.JOSM_MAX_OBJECTS);
    const ids = [];
    capped.forEach(f => {
      const p = f.properties;
      ids.push(osmTypeOf(p)[0] + p.osm_id);
      if (p.poi_node_id) ids.push('n' + p.poi_node_id);
    });
    fetch(`http://127.0.0.1:8111/load_object?new_layer=true&objects=${ids.join(',')}`)
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        showToast(visible.length > capped.length
          ? t('josmVisibleCapped', { n: fmtNum(capped.length) })
          : t('josmVisibleSent', { n: fmtNum(capped.length) }));
      })
      .catch(() => showToast(t('josmUnreachable'), 'error'));
  },

  // Overpass QL selecting what the active check flags, where the check is
  // tag-based. Geometry/ML/history checks fall back to all places of worship.
  OVERPASS_QUERIES: {
    missing_amenity: 'nwr["building"="mosque"][!"amenity"]({{bbox}});',
    missing_name: 'nwr["amenity"="place_of_worship"][!"name"][!"name:ar"]({{bbox}});',
    missing_name_en: 'nwr["amenity"="place_of_worship"][~"^(name|name:ar)$"~"."][!"name:en"]({{bbox}});',
    missing_denom: 'nwr["amenity"="place_of_worship"]["religion"="muslim"][!"denomination"]({{bbox}});',
    building_yes: 'nwr["building"="yes"]["amenity"="place_of_worship"]["religion"="muslim"]({{bbox}});',
    mapped_as_node: 'node["amenity"="place_of_worship"]({{bbox}});',
  },

  openOverpassTurbo() {
    const issue = currentMode === 'improve' ? currentImprovementFilter : 'all';
    const body = this.OVERPASS_QUERIES[issue] ||
      'nwr["amenity"="place_of_worship"]({{bbox}});\nnwr["building"="mosque"]({{bbox}});';
    if (!this.OVERPASS_QUERIES[issue] && currentMode === 'improve' && issue !== 'all') {
      showToast(t('overpassUnsupported'));
    }
    const query = `[out:json][timeout:60];\n(\n  ${body.replace(/\n/g, '\n  ')}\n);\nout body;\n>;\nout skel qt;`;
    const c = map.getCenter();
    const url = `https://overpass-turbo.eu/?Q=${encodeURIComponent(query)}&C=${c.lat.toFixed(5)};${c.lng.toFixed(5)};${map.getZoom()}&R`;
    window.open(url, '_blank', 'noopener');
  }
};
