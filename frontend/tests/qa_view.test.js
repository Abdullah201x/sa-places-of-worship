import { describe, it, expect } from 'vitest';
import { fmtNum } from '../src/i18n.js';
import {
  QA_PAGE_SIZE,
  setQAIssues,
  formatSeverityBadge,
  formatStatusBadge,
  calculateDistanceKm,
  sortIssues,
  SEVERITY_ORDER,
} from '../src/qa_view.js';

describe('QA Workspace formatting and triage helpers', () => {
  it('correctly orders severities', () => {
    expect(SEVERITY_ORDER.high).toBeGreaterThan(SEVERITY_ORDER.medium);
    expect(SEVERITY_ORDER.medium).toBeGreaterThan(SEVERITY_ORDER.low);
  });

  it('formats severity badges in Arabic and English', () => {
    const highAr = formatSeverityBadge('high', 'ar');
    expect(highAr.className).toBe('sev-high');
    expect(highAr.label).toBe('حرجة');

    const highEn = formatSeverityBadge('high', 'en');
    expect(highEn.className).toBe('sev-high');
    expect(highEn.label).toBe('High');

    const med = formatSeverityBadge('medium', 'en');
    expect(med.className).toBe('sev-med');
    expect(med.label).toBe('Medium');

    const low = formatSeverityBadge('low', 'en');
    expect(low.className).toBe('sev-low');
    expect(low.label).toBe('Low');

    const fallback = formatSeverityBadge(null, 'en');
    expect(fallback.className).toBe('sev-med');
  });

  it('formats status badges in Arabic and English', () => {
    const fixedAr = formatStatusBadge('fixed', 'ar');
    expect(fixedAr.className).toBe('status-fixed');
    expect(fixedAr.label).toBe('تم الإصلاح');

    const fixedEn = formatStatusBadge('fixed', 'en');
    expect(fixedEn.className).toBe('status-fixed');
    expect(fixedEn.label).toBe('Fixed');

    const skipped = formatStatusBadge('skipped', 'en');
    expect(skipped.className).toBe('status-skipped');
    expect(skipped.label).toBe('Skipped');

    const open = formatStatusBadge('open', 'en');
    expect(open.className).toBe('status-open');
    expect(open.label).toBe('Open');

    const fallback = formatStatusBadge(null, 'en');
    expect(fallback.className).toBe('status-open');
  });

  it('calculates geographic distance using Haversine formula', () => {
    // Riyadh (24.7136, 46.6753) to Makkah (21.3891, 39.8579) ~ 790-800 km
    const d = calculateDistanceKm(24.7136, 46.6753, 21.3891, 39.8579);
    expect(d).toBeGreaterThan(780);
    expect(d).toBeLessThan(820);

    // Invalid coordinates return null
    expect(calculateDistanceKm(NaN, 46.0, 21.0, 39.0)).toBeNull();
    expect(calculateDistanceKm(24.0, null, 21.0, 39.0)).toBeNull();
  });

  it('sorts issues by severity', () => {
    const sample = [
      { osm_id: 1, severity: 'low' },
      { osm_id: 2, severity: 'high' },
      { osm_id: 3, severity: 'medium' },
      { osm_id: 4, severity: 'high' },
    ];
    const sorted = sortIssues(sample, 'severity');
    expect(sorted.map(s => s.osm_id)).toEqual([2, 4, 3, 1]);
  });

  it('sorts issues by distance to map center', () => {
    const center = [24.7, 46.6]; // Near Riyadh
    const sample = [
      { osm_id: 1, coordinates: [39.8, 21.4] }, // Makkah (~800km)
      { osm_id: 2, coordinates: [46.65, 24.72] }, // Riyadh (~5km)
      { osm_id: 3, coordinates: [50.1, 26.4] }, // Dammam (~400km)
    ];
    const sorted = sortIssues(sample, 'distance', center);
    expect(sorted.map(s => s.osm_id)).toEqual([2, 3, 1]);
  });

  it('sorts issues alphabetically by name', () => {
    const sample = [
      { osm_id: 1, name: 'مسجد النور' },
      { osm_id: 2, name: 'جامع الراجحي' },
      { osm_id: 3, name: 'مسجد بلال' },
    ];
    const sorted = sortIssues(sample, 'name');
    expect(sorted[0].name).toBe('جامع الراجحي');
  });
});


// Just enough DOM for renderQATable(): a tbody that records appended rows.
function makeFakeDom() {
  const makeEl = (tag) => {
    let children = [];
    const el = {
      tag,
      className: '',
      innerHTML: '',
      textContent: '',
      value: undefined,
      parent: null,
      attrs: {},
      get children() { return children; },
      setAttribute(k, v) { el.attrs[k] = String(v); },
      getAttribute(k) { return el.attrs[k] ?? null; },
      appendChild(c) {
        const incoming = c.isFragment ? [...c.children] : [c];
        incoming.forEach(x => { x.parent = el; });
        children.push(...incoming);
        return c;
      },
      querySelector(sel) {
        const cls = sel.replace(/^\./, '');
        return children.find(c => c.className.split(' ').includes(cls)) || null;
      },
      remove() {
        if (el.parent) el.parent.setChildren(el.parent.children.filter(c => c !== el));
      },
      setChildren(c) { children = c; },
    };
    Object.defineProperty(el, 'innerHTML', {
      get: () => '',
      set: (v) => { if (v === '') children = []; },
    });
    return el;
  };
  const tbody = makeEl('tbody');
  const count = makeEl('span');
  const byId = { 'qa-table-body': tbody, 'qa-count': count };
  globalThis.document = {
    getElementById: (id) => byId[id] || null,
    createElement: makeEl,
    createDocumentFragment: () => { const f = makeEl('frag'); f.isFragment = true; return f; },
    querySelectorAll: () => tbody.children.filter(c => c.className.includes('qa-row')),
    addEventListener: () => {},
  };
  return { tbody, count };
}

describe('QA table rendering', () => {
  it('renders only one page of a very large issue list', () => {
    const { tbody, count } = makeFakeDom();
    const issues = Array.from({ length: 20000 }, (_, i) => ({
      osm_id: i, osm_type: 'way', rule_id: 'missing_amenity', severity: 'high', name: `m${i}`,
    }));
    setQAIssues(issues);

    const rows = tbody.children.filter(c => c.className.includes('qa-row'));
    expect(rows).toHaveLength(QA_PAGE_SIZE);
    expect(tbody.children.some(c => c.className === 'qa-more-row')).toBe(true);
    expect(count.textContent).toContain(fmtNum(20000));
  });

  it('shows no more-row when everything fits in one page', () => {
    const { tbody } = makeFakeDom();
    setQAIssues([{ osm_id: 1, osm_type: 'node', rule_id: 'missing_name', severity: 'low' }]);
    expect(tbody.children.filter(c => c.className.includes('qa-row'))).toHaveLength(1);
    expect(tbody.children.some(c => c.className === 'qa-more-row')).toBe(false);
  });
});
