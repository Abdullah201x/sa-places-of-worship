import { describe, it, expect, beforeEach } from 'vitest';
import '../src/translations_static.js';
import { STATIC_EN, applyStaticTranslations, setLanguage, TRANSLATED_ATTRS, attrOriginals, staticPair } from '../src/i18n.js';

describe('Bilingual Static i18n & Attribute Translation Audit', () => {
  it('loads all static translations into STATIC_EN', () => {
    expect(Object.keys(STATIC_EN).length).toBeGreaterThanOrEqual(300);
  });

  it('contains translations for critical form placeholders and aria-labels', () => {
    const criticalPhrases = [
      'ابحث بالاسم أو المسار...',
      'ابحث في الوسوم، المفاتيح، أو القواعد... (اضغط / للتركيز)',
      'بحث في الملفات',
      'تصفية حسب الطبقة',
      'تصفية حسب المنطقة',
      'تصفية حسب الصيغة',
      'روابط الصفحات',
      'لوحة الأوامر والبحث السريع',
      'مساحات العمل',
      'وضع التركيز والتعديل السريع',
      'منارة — خارطة أماكن العبادة',
    ];

    criticalPhrases.forEach((phrase) => {
      expect(STATIC_EN[phrase], `Missing translation for "${phrase}"`).toBeDefined();
      expect(STATIC_EN[phrase].length).toBeGreaterThan(0);
    });
  });

  it('staticPair correctly matches registered phrases and preserves whitespace', () => {
    const pair = staticPair('  ابحث بالاسم أو المسار...  ');
    expect(pair).not.toBeNull();
    expect(pair.ar).toBe('  ابحث بالاسم أو المسار...  ');
    expect(pair.en).toBe('  Search by name, layer, or filename...  ');
  });
});
