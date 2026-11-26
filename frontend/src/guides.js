// Documentation Guides Page (/guides)
import './styles/fonts.css';
import './styles/page.css';
import './styles/guides.css';
import { currentLang, setLanguage, addTranslations } from './i18n.js';
import { initAnalytics } from './analytics.js';

addTranslations({
  guidesTitle: ['أدلة التحرير ورسم المساجد | منارة: خريطة بيوت الله', 'Mapping Guides | Manara: Saudi Places of Worship Map'],
  heroTitle: ['أدلة وإرشادات رسم المساجد', 'Mosque Mapping & Documentation Guides'],
  heroSubtitle: [
    'دليل شامل للمساهمين في خريطة الشارع المفتوحة بالمملكة: قواعد الأسماء، التمييز بين المباني والنقاط، إعداد المحررات، وآداب التعاون.',
    'Comprehensive guides for OpenStreetMap contributors in Saudi Arabia: naming rules, outlines vs nodes, editor setup, and collaboration etiquette.'
  ],
});

document.getElementById('btn-toggle-lang')?.addEventListener('click', () => {
  setLanguage(currentLang === 'ar' ? 'en' : 'ar');
});

setLanguage(currentLang);
initAnalytics();
