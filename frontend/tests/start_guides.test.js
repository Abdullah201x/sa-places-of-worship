import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { ArabicText } from '../src/arabic.js';
import { filterEasyQueue } from '../src/start.js';

describe('Beginner Onboarding (/start) Easy Queue Filter', () => {
  const samplePlaces = [
    {
      properties: {
        name: 'جامع الملك فهد',
        name_en: 'Mosque', // placeholder to fix
        amenity: 'place_of_worship'
      }
    },
    {
      properties: {
        name: 'مسجد التقوى',
        name_en: '', // missing to fix
        amenity: 'place_of_worship'
      }
    },
    {
      properties: {
        name: 'مسجد', // generic name, should NOT be in easy queue
        name_en: 'Mosque',
        amenity: 'place_of_worship'
      }
    },
    {
      properties: {
        name: 'جامع الراجحي',
        name_en: 'Al Rajhi Grand Mosque', // already fixed, should NOT be in queue
        amenity: 'place_of_worship'
      }
    }
  ];

  it('filters only named mosques lacking English transliteration', () => {
    const queue = filterEasyQueue(samplePlaces);
    expect(queue).toHaveLength(2);
    expect(queue[0].properties.name).toBe('جامع الملك فهد');
    expect(queue[1].properties.name).toBe('مسجد التقوى');
  });

  it('produces UNGEGN-compliant suggestions for queued places', () => {
    const queue = filterEasyQueue(samplePlaces);
    const place1 = queue[0];
    const suggestion1 = ArabicText.suggestEnglishName(place1.properties.name);
    expect(suggestion1).toBe('King Fahd Grand Mosque');

    const place2 = queue[1];
    const suggestion2 = ArabicText.suggestEnglishName(place2.properties.name);
    expect(suggestion2).toBe('Al-Taqwa Mosque');
  });
});

describe('Documentation Guides (/guides)', () => {
  const root = path.resolve(__dirname, '../../content/guides');
  const requiredGuides = [
    'names-and-transliteration.md',
    'outlines-vs-nodes.md',
    'josm-setup.md',
    'review-etiquette.md'
  ];

  it('contains all 4 required markdown guides', () => {
    requiredGuides.forEach(file => {
      const fullPath = path.join(root, file);
      expect(fs.existsSync(fullPath)).toBe(true);
      const content = fs.readFileSync(fullPath, 'utf8');
      expect(content).toContain('Arabic');
      expect(content).toContain('English');
    });
  });

  it('validates guide contents contain essential guidelines', () => {
    const namesContent = fs.readFileSync(path.join(root, 'names-and-transliteration.md'), 'utf8');
    expect(namesContent).toContain('Grand Mosque');
    expect(namesContent).toContain('Al-');

    const outlinesContent = fs.readFileSync(path.join(root, 'outlines-vs-nodes.md'), 'utf8');
    expect(outlinesContent).toContain('building=mosque');
    expect(outlinesContent).toContain('duplicate_poi');

    const josmContent = fs.readFileSync(path.join(root, 'josm-setup.md'), 'utf8');
    expect(josmContent).toContain('8111');
    expect(josmContent).toContain('Remote Control');
  });
});
