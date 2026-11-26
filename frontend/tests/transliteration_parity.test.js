import { describe, it, expect } from 'vitest';
import { ArabicText } from '../src/arabic.js';

describe('Arabic Transliteration Parity & Rules (GASGI/UNGEGN)', () => {
  const cases = [
    { ar: 'جامع الملك فهد', en: 'King Fahd Grand Mosque' },
    { ar: 'جامع الملك سلمان بن عبدالعزيز', en: 'King Salman bin Abdulaziz Grand Mosque' },
    { ar: 'جامع خادم الحرمين الشريفين', en: 'Custodian of the Two Holy Mosques Grand Mosque' },
    { ar: 'مسجد الأمير سلطان بن عبد العزيز', en: 'Prince Sultan bin Abdulaziz Mosque' },
    { ar: 'مسجد بلال بن رباح', en: 'Bilal bin Rabah Mosque' },
    { ar: 'مسجد أبو بكر الصديق', en: 'Abu Bakr Al-Siddiq Mosque' },
    { ar: 'مسجد عمر بن الخطاب', en: 'Omar bin Al-Khattab Mosque' },
    { ar: 'مسجد عثمان بن عفان', en: 'Othman bin Affan Mosque' },
    { ar: 'مسجد علي بن أبي طالب', en: 'Ali bin Abi Talib Mosque' },
    { ar: 'مسجد خالد بن الوليد', en: 'Khalid bin Al-Waleed Mosque' },
    { ar: 'مسجد سعد بن أبي وقاص', en: 'Saad bin Abi Waqqas Mosque' },
    { ar: 'مسجد أبي ذر الغفاري', en: 'Abu Dharr Al-Ghifari Mosque' },
    { ar: 'مسجد ذي النورين', en: 'Dhu Al-Nurayn Mosque' },
    { ar: 'مسجد التقوى', en: 'Al-Taqwa Mosque' },
    { ar: 'جامع الراجحي', en: 'Al-Rajhi Grand Mosque' },
    { ar: 'جامع عبد اللطيف', en: 'Abdullatif Grand Mosque' },
    { ar: 'جامع عبد الصمد', en: 'Abdulsamad Grand Mosque' },
    { ar: 'جامع عبد الوهاب', en: 'Abdulwahhab Grand Mosque' },
    { ar: 'جامع عبد المحسن', en: 'Abdulmohsen Grand Mosque' },
    { ar: 'جامع عبد الرحمن', en: 'Abdulrahman Grand Mosque' },
    { ar: 'مسجد عبد العزيز', en: 'Abdulaziz Mosque' },
    { ar: 'مسجد الهدى والتقوى', en: 'Al-Huda and Al-Taqwa Mosque' },
    { ar: 'مسجد الصفا والمروة', en: 'Al-Safa and Al-Marwah Mosque' },
    { ar: 'مسجد النور والضياء', en: 'Al-Noor and Al-Diya Mosque' },
    { ar: 'مسجد والدة عبدالله المرشد', en: 'Walidat Abdullah Al-Murshid Mosque' },
    { ar: 'مصلى العيد', en: 'Al-Eid Musalla' },
    { ar: 'مصلى رجال', en: "Men's Musalla" },
    { ar: 'مصلى نساء', en: "Women's Musalla" },
    { ar: 'مسجد توفيق', en: 'Tawfiq Mosque' },
    { ar: 'مسجد محمود', en: 'Mahmoud Mosque' },
    { ar: 'مسجد منصور', en: 'Mansour Mosque' },
    { ar: 'مسجد أحد', en: 'Uhud Mosque' },
    { ar: 'مسجد طيبة', en: 'Taybah Mosque' },
    { ar: 'مسجد حطين', en: 'Hittin Mosque' },
    { ar: 'مسجد اليرموك', en: 'Al-Yarmouk Mosque' },
  ];

  it('transliterates all standard worship places correctly', () => {
    for (const { ar, en } of cases) {
      expect(ArabicText.suggestEnglishName(ar)).toBe(en);
    }
  });

  it('strips parenthesized and bare pious eulogies cleanly without leaving empty parens', () => {
    expect(ArabicText.suggestEnglishName('مسجد عمر بن الخطاب (رضي الله عنه)')).toBe('Omar bin Al-Khattab Mosque');
    expect(ArabicText.suggestEnglishName('مسجد علي بن أبي طالب (كرم الله وجهه)')).toBe('Ali bin Abi Talib Mosque');
    expect(ArabicText.suggestEnglishName('جامع الملك عبد الله (رحمه الله)')).toBe('King Abdullah Grand Mosque');
    expect(ArabicText.suggestEnglishName('مسجد عمر بن الخطاب رضي الله عنه')).toBe('Omar bin Al-Khattab Mosque');
    expect(ArabicText.suggestEnglishName('جامع الملك عبد الله رحمه الله')).toBe('King Abdullah Grand Mosque');
    expect(ArabicText.suggestEnglishName('مسجد عائشة (رضي الله عنها)')).toBe('Aisha Mosque');
  });

  it('suppresses false-positive civic and non-religious entities', () => {
    const nonReligious = [
      'مدرسة ابن خلدون',
      'مستشفى الملك فيصل',
      'جامعة الملك سعود',
      'كلية الشريعة',
      'جمعية البر الخيرية',
      'نادي الشباب',
      'شارع مسجد قباء',
      'مقبرة الشهداء',
    ];
    for (const name of nonReligious) {
      expect(ArabicText.suggestEnglishName(name)).toBe('');
      expect(ArabicText.classifyMosqueType(name)).toBe('non_religious');
    }
  });

  it('correctly detects eulogies with hasEulogy', () => {
    expect(ArabicText.hasEulogy('مسجد عمر بن الخطاب رضي الله عنه')).toBe(true);
    expect(ArabicText.hasEulogy('مسجد عمر بن الخطاب (رضي الله عنه)')).toBe(true);
    expect(ArabicText.hasEulogy('جامع الملك فهد رحمه الله')).toBe(true);
    expect(ArabicText.hasEulogy('مسجد التقوى')).toBe(false);
    expect(ArabicText.hasEulogy('جامع الراجحي')).toBe(false);
  });
});
