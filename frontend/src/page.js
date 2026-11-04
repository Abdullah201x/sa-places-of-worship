// Entry point of the content pages (about, privacy, community). Each page holds both
// languages in [data-lang] blocks; CSS shows the one matching <html lang>,
// and the shared i18n module handles the toggle and the remembered choice.
import './styles/fonts.css';
import './styles/page.css';
import './translations_static.js';
import { currentLang, setLanguage, addTranslations } from './i18n.js';
import { initAnalytics } from './analytics.js';

addTranslations({
  aboutTitle: ['عن المشروع | منارة: خارطة أماكن العبادة', 'About | Manara: Saudi Places of Worship Map'],
  privacyTitle: ['الخصوصية | منارة: خارطة أماكن العبادة', 'Privacy | Manara: Saudi Places of Worship Map'],
  communityTitle: ['إحصاءات المجتمع والتغطية | منارة: خارطة أماكن العبادة', 'Community & Coverage Stats | Manara: Saudi Places of Worship Map'],
});

document.getElementById('btn-toggle-lang').addEventListener('click', () => {
  setLanguage(currentLang === 'ar' ? 'en' : 'ar');
});
setLanguage(currentLang);
initAnalytics();
