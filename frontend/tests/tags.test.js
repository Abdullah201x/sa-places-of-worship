import { describe, it, expect } from 'vitest';
import { ArabicText } from '../src/arabic.js';

describe('Tag Directory Search & Filter Logic', () => {
  const sampleDocs = [
    {
      key: 'amenity',
      value: 'place_of_worship',
      status: 'approved',
      applies_to: ['node', 'way', 'relation'],
      label: { ar: 'مكان عبادة', en: 'Place of worship' },
      saudi_notes: {
        ar: 'الوسم الأساسي لجميع المساجد والمصليات في المملكة العربية السعودية.',
        en: 'The primary tag for all mosques and prayer halls in Saudi Arabia.'
      },
      rules: ['missing_amenity', 'stale_data'],
    },
    {
      key: 'building',
      value: 'mosque',
      status: 'approved',
      applies_to: ['way', 'relation'],
      label: { ar: 'مبنى مسجد', en: 'Mosque building' },
      saudi_notes: {
        ar: 'يستخدم لتحديد حدود مبنى المسجد الفعلية. تجنب استخدام building=yes للمساجد.',
        en: 'Used for the physical building outline of a mosque. Avoid generic building=yes.'
      },
      rules: ['missing_amenity', 'building_yes', 'mapped_as_node'],
    },
    {
      key: 'building',
      value: 'yes',
      status: 'discouraged',
      applies_to: ['way', 'relation'],
      label: { ar: 'مبنى عام (غير محدد)', en: 'Generic building' },
      saudi_notes: {
        ar: 'غير محبذ لمباني المساجد. يُستبدل دائماً بـ building=mosque.',
        en: 'Discouraged for mosque buildings. Always upgrade to building=mosque.'
      },
      rules: ['building_yes'],
    },
    {
      key: 'name:en',
      status: 'approved',
      applies_to: ['node', 'way', 'relation'],
      label: { ar: 'الاسم بالإنجليزية', en: 'English name' },
      saudi_notes: {
        ar: 'الاسم المترجم صوتياً أو المترجم بالإنجليزية طبقاً للمعايير الوطنية.',
        en: 'Transliterated or translated English name per national standards.'
      },
      rules: ['missing_name_en'],
      tools: ['transliterate'],
    },
    {
      key: 'denomination',
      value: 'sunni',
      status: 'approved',
      applies_to: ['node', 'way', 'relation'],
      label: { ar: 'أهل السنة والجماعة', en: 'Sunni' },
      saudi_notes: {
        ar: 'المذهب الأكثر انتشاراً لمساجد المملكة.',
        en: 'The predominant denomination for mosques in Saudi Arabia.'
      },
      rules: ['missing_denom'],
    }
  ];

  function matchesQuery(doc, q) {
    if (!q) return true;
    const normQ = ArabicText.normalize(q);
    const keyNorm = ArabicText.normalize(doc.key);
    const valNorm = doc.value ? ArabicText.normalize(doc.value) : '';
    const arLabel = doc.label?.ar ? ArabicText.normalize(doc.label.ar) : '';
    const enLabel = doc.label?.en ? ArabicText.normalize(doc.label.en) : '';
    const arNotes = doc.saudi_notes?.ar ? ArabicText.normalize(doc.saudi_notes.ar) : '';
    const enNotes = doc.saudi_notes?.en ? ArabicText.normalize(doc.saudi_notes.en) : '';

    if (keyNorm.includes(normQ) || valNorm.includes(normQ)) return true;
    if (arLabel.includes(normQ) || enLabel.includes(normQ)) return true;
    if (arNotes.includes(normQ) || enNotes.includes(normQ)) return true;
    if (doc.rules && doc.rules.some(r => r.toLowerCase().includes(q.toLowerCase()))) return true;
    return false;
  }

  function matchesFilter(doc, filter) {
    if (filter === 'all') return true;
    if (filter === 'approved') return doc.status === 'approved';
    if (filter === 'discouraged') return doc.status === 'discouraged' || doc.status === 'deprecated';
    if (filter === 'worship') {
      return ['amenity', 'building', 'religion', 'denomination'].includes(doc.key);
    }
    return true;
  }

  it('matches by English key and value', () => {
    const results = sampleDocs.filter(d => matchesQuery(d, 'place_of_worship'));
    expect(results).toHaveLength(1);
    expect(results[0].key).toBe('amenity');

    const buildingResults = sampleDocs.filter(d => matchesQuery(d, 'building'));
    expect(buildingResults).toHaveLength(2);
  });

  it('matches by Arabic label with orthographic normalization', () => {
    // "مسجد" search should match "مبنى مسجد"
    const results = sampleDocs.filter(d => matchesQuery(d, 'مسجد'));
    expect(results.length).toBeGreaterThanOrEqual(1);

    // "اهل" (without hamza) should match "أهل السنة والجماعة"
    const sunniResults = sampleDocs.filter(d => matchesQuery(d, 'اهل'));
    expect(sunniResults).toHaveLength(1);
    expect(sunniResults[0].value).toBe('sunni');
  });

  it('matches by associated QA rule ID', () => {
    const results = sampleDocs.filter(d => matchesQuery(d, 'missing_amenity'));
    expect(results).toHaveLength(2);
  });

  it('filters by approval status correctly', () => {
    const approved = sampleDocs.filter(d => matchesFilter(d, 'approved'));
    expect(approved).toHaveLength(4);

    const discouraged = sampleDocs.filter(d => matchesFilter(d, 'discouraged'));
    expect(discouraged).toHaveLength(1);
    expect(discouraged[0].value).toBe('yes');
  });

  it('integrates UNGEGN transliteration for name:en tool', () => {
    const doc = sampleDocs.find(d => d.key === 'name:en');
    expect(doc.tools).toContain('transliterate');

    // Jami' -> Grand Mosque
    const transliterated = ArabicText.suggestEnglishName('جامع الملك فهد');
    expect(transliterated).toBe('King Fahd Grand Mosque');

    // Masjid -> Mosque
    const mosqueTaqwa = ArabicText.suggestEnglishName('مسجد التقوى');
    expect(mosqueTaqwa).toBe('Al-Taqwa Mosque');
  });

  it('formats Overpass queries scoped to Saudi Arabia', () => {
    const doc = sampleDocs[0];
    const query = doc.value
      ? `[out:json][timeout:25];area["ISO3166-1"="SA"]->.sa;(nwr["${doc.key}"="${doc.value}"](area.sa););out body;>;out skel qt;`
      : `[out:json][timeout:25];area["ISO3166-1"="SA"]->.sa;(nwr["${doc.key}"](area.sa););out body;>;out skel qt;`;
    expect(query).toContain('area["ISO3166-1"="SA"]');
    expect(query).toContain('nwr["amenity"="place_of_worship"]');
  });
});
