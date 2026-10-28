// Strings built by app.js (both languages). Static page text is in
// translations_static.js; the review, export and editing modules register
// their own strings next to their code.
import { addTranslations } from './i18n.js';

addTranslations({
  // Religion / denomination labels
  rel_muslim: ['مسلم (مسجد)', 'Muslim (mosque)'],
  rel_christian: ['مسيحي', 'Christian'],
  rel_unknown: ['غير محدد', 'Unspecified'],
  rel_other: ['ديانات أخرى', 'Other religions'],
  denom_sunni: ['أهل السنة والجماعة (سني)', 'Sunni'],
  denom_shia: ['شيعي', 'Shia'],
  denom_ibadi: ['إباضي', 'Ibadi'],
  denom_unknown: ['غير معروف / غير محدد', 'Unknown / unspecified'],
  denom_ahmadia: ['أحمدية', 'Ahmadiyya'],
  denom_ismailia: ['إسماعيلية', 'Ismaili'],

  // Issue badges and labels
  issuesNeedReview: ['{n} مكان يحتاج تدقيق', '{n} places need review'],
  popupIssueCount: ['⚠️ لديه {n} مشكلة جودة', '⚠️ {n} quality issues'],
  labelTotalPlaces: ['إجمالي الأماكن', 'Total places'],
  labelVisiblePlaces: ['في النطاق المرئي', 'In current view'],
  labelTotalImprove: ['أماكن تحتاج تحسين', 'Places needing work'],
  labelVisibleImprove: ['تحتاج تحسين بالنطاق', 'Needing work in view'],
  labelTotalGaps: ['الفجوات المكتشفة', 'Detected gaps'],
  labelVisibleGaps: ['الفجوات في النطاق', 'Gaps in view'],
  dataUpdated: ['بيانات OSM بتاريخ {date}', 'OSM data as of {date}'],
  loadError: ['فشل في تحميل بيانات الخريطة. يرجى تحديث الصفحة أو المحاولة لاحقاً.', 'Failed to load the map data. Please reload the page or try again later.'],

  // Details panel
  unnamed: ['غير مسمى', 'Unnamed'],
  unspecified: ['غير محدد', 'Unspecified'],
  saudiArabia: ['المملكة العربية السعودية', 'Saudi Arabia'],
  guestContributor: ['مساهم OSM (سجل دخولك)', 'OSM contributor (log in)'],
  hiddenGdpr: ['محجوب بموجب GDPR', 'Hidden under GDPR'],
  anonymous: ['مجهول', 'Anonymous'],
  qiblaVeryAccurate: ['دقيق جداً', 'very accurate'],
  qiblaSevere: ['انحراف حاد', 'severe deviation'],
  qiblaSlight: ['انحراف طفيف', 'slight deviation'],
  qiblaAxes: ['القبلة: {q}° | المبنى: {b}°', 'Qibla: {q}° | building: {b}°'],

  // JOSM / iD
  josmSent: ['تم إرسال الموقع ومعرّف المعلم إلى JOSM بنجاح!', 'Location and object sent to JOSM.'],
  josmLoadFailed: ['فشل JOSM في تحميل المعلم. تأكد من تفعيل Remote Control.', 'JOSM could not load the object. Check that Remote Control is enabled.'],
  josmAreaSent: ['تم إرسال النطاق الحالي إلى JOSM. يمكنك الآن إضافة معلم المسجد.', 'Current view sent to JOSM. You can now add the mosque.'],
  josmAreaFailed: ['فشل JOSM في تحميل النطاق. تأكد من تفعيل Remote Control.', 'JOSM could not load the area. Check that Remote Control is enabled.'],

  // Wikidata suggestions
  sugLoading: ['جارٍ تحميل اقتراحات ويكي بيانات...', 'Loading Wikidata suggestions...'],
  sugBadge: ['{n} مقترح', '{n} suggestions'],
  sugLoaded: ['تم تحميل {n} مسجداً مقترحاً من ويكي بيانات بنجاح!', 'Loaded {n} suggested mosques from Wikidata.'],
  sugLoadFailed: ['تعذر تحميل ملف اقتراحات المساجد (suggested_mosques_sa.geojson)', 'Could not load the mosque suggestions (suggested_mosques_sa.geojson).'],
  sugUnnamed: ['مسجد بدون اسم محدد', 'Mosque without a specific name'],
  sugOverKm: ['أكثر من 1 كم', 'over 1 km'],
  sugMetres: ['{n} م', '{n} m'],
  sugGeneric: ['⚠️ اسم عام / غير محدد - تحقق ميدانياً', '⚠️ Generic / unspecified name – verify on the ground'],
  sugVerified: ['✓ اسم معتمد في ويكي بيانات', '✓ Name recorded in Wikidata'],
  sugQid: ['معرف ويكي بيانات:', 'Wikidata ID:'],
  sugNearest: ['أقرب مكان عبادة بـ OSM:', 'Nearest OSM place of worship:'],
  sugCoords: ['الإحداثيات:', 'Coordinates:'],
  sugSatelliteTitle: ['معاينة فورية للمبنى أو القبة عبر الأقمار الصناعية', 'Preview the building or dome on satellite imagery'],
  sugSatellite: ['🛰️ معاينة بالأقمار الصناعية (Esri)', '🛰️ Satellite preview (Esri)'],
  sugCopyTitle: ['نسخ وسوم المسجد الجاهزة للحافظة', 'Copy ready-made mosque tags to the clipboard'],
  sugCopy: ['📋 نسخ الوسوم', '📋 Copy tags'],
  sugDirectTitle: ['إضافة المسجد مباشرة كعقدة إلى OpenStreetMap من هذا الموقع', 'Add the mosque directly as a node to OpenStreetMap from this website'],
  sugDirect: ['⚡ إضافة كعقدة مباشرة', '⚡ Add directly (OSM Node)'],
  sugIdTitle: ['فتح المحرر في متصفح الويب', 'Open the editor in the browser'],
  sugId: ['✏️ فتح في iD', '✏️ Open in iD'],
  sugJosmTitle: ['إرسال نقطة المسجد مباشرة لمحرر JOSM', 'Send the mosque point straight to JOSM'],
  sugJosm: ['⚡ إضافة في JOSM', '⚡ Add in JOSM'],
  sugSatelliteToast: ['تم التبديل لخريطة الأقمار الصناعية والتقريب لمعاينة المسجد.', 'Switched to satellite imagery and zoomed in on the mosque.'],
  tagsCopied: ['تم نسخ الوسوم بنجاح إلى الحافظة! جاهزة للصق في المحرر.', 'Tags copied to the clipboard, ready to paste into the editor.'],
  copyFailed: ['تعذر النسخ للحافظة تلقائياً.', 'Could not copy to the clipboard.'],
  copyUnsupported: ['المتصفح لا يدعم النسخ التلقائي للحافظة.', 'This browser does not support copying to the clipboard.'],
  sugJosmWorking: ['جارٍ التواصل مع JOSM لتحميل المنطقة وإضافة المسجد...', 'Asking JOSM to load the area and add the mosque...'],
  sugJosmAdded: ['تمت إضافة نقطة المسجد في JOSM بنجاح! راجع الوسوم وموقع المبنى قبل الرفع.', 'Mosque point added in JOSM. Check the tags and position before uploading.'],
  sugJosmAddFailed: ['فشل JOSM في إضافة النقطة. تأكد من تفعيل "Create new objects" في إعدادات Remote Control.', 'JOSM could not add the point. Enable "Create new objects" in the Remote Control settings.'],
  sugDirectSuccess: ['تمت إضافة مقترح ويكي بيانات كعقدة مسجد على OSM بنجاح!', 'Wikidata suggestion added directly as an OSM mosque node!'],

  // Direct Mosque Node Creation
  addMosqueSuccess: ['تمت إضافة المسجد كعقدة بنجاح إلى OpenStreetMap!', 'Mosque node added to OpenStreetMap successfully!'],
  addMosqueViewNode: ['عرض العقدة على OSM', 'View node on OSM'],
  addMosqueModeActiveToast: ['وضع إضافة مسجد: انقر على أي موقع في الخريطة لتحديد المسجد.', 'Add Mosque mode: click anywhere on the map to place the mosque.'],
  addMosqueModeDeactivated: ['تم إيقاف وضع إضافة مسجد.', 'Add Mosque mode deactivated.'],
  addMosqueContextAction: ['إضافة مسجد هنا كعقدة OSM 🕌', 'Add mosque here as OSM node 🕌'],
  noteContextAction: ['إضافة ملاحظة OSM هنا 📝', 'Add OSM note here 📝'],
  addMosqueLoginRequired: ['يتطلب رفع المسجد تسجيل الدخول بحساب OpenStreetMap.', 'Adding a mosque requires logging in with an OpenStreetMap account.'],
  addMosqueUploading: ['جارٍ إنشاء العقدة ورفعها إلى OpenStreetMap...', 'Creating node and uploading to OpenStreetMap...'],
  addMosqueFailed: ['فشل رفع المسجد: {msg}', 'Failed to add mosque: {msg}'],
  addMosquePostedAs: ['سيتم النشر بحساب OSM: {name}', 'Will be uploaded as OSM user: {name}'],
  addMosqueNeedsAuth: ['يجب تسجيل الدخول بحساب OpenStreetMap مع صلاحية write_api لرفع المعالم.', 'You must log in with OpenStreetMap (write_api scope) to upload nodes.'],

  // CARTO
  cartoBadgeOn: ['CARTO (مفعّل)', 'CARTO (on)'],
  cartoBadgeOff: ['مفتاح CARTO', 'CARTO key'],
  cartoStatusOn: ['مفتاح CARTO مفعّل بنجاح. يتم استخدام خرائط CARTO الرسمية بدون أي علامة مائية.', 'CARTO key active. Official CARTO maps are in use, without watermarks.'],
  cartoStatusOff: ['الخرائط الافتراضية نشطة (Esri Canvas - بدون علامات مائية وبدون مفتاح).', 'Default maps active (Esri Canvas, no watermarks, no key).'],
  cartoEnabled: ['تم تفعيل خرائط CARTO بالمفتاح بنجاح!', 'CARTO maps enabled with your key.'],
  cartoDefault: ['تم اعتماد خرائط Esri الافتراضية بدون مفتاح.', 'Using the default Esri maps (no key).'],
  cartoRestored: ['تمت استعادة خرائط Esri الافتراضية بدون علامات مائية.', 'Default Esri maps restored.'],

  // Redirect URI copy
  copied: ['تم النسخ!', 'Copied!'],
  redirectCopied: ['تم نسخ عنوان العودة (Redirect URI) إلى الحافظة.', 'Redirect URI copied to the clipboard.'],
  redirectCopyFailed: ['فشل في نسخ عنوان العودة تلقائياً. يرجى نسخه يدوياً.', 'Could not copy the redirect URI; please copy it by hand.'],

  // Notes
  notePostedAs: ['سيتم نشر الملاحظة باسم: {name}', 'The note will be posted as: {name}'],
  notePostedAnon: ['سيتم نشر الملاحظة كزائر مجهول (بدون تسجيل دخول).', 'The note will be posted anonymously (not logged in).'],
  noteWorshipBody: ['يوجد هنا مكان عبادة غير موجود على الخريطة.', 'There is a place of worship here that is missing from the map.'],
  noteNameLine: ['الاسم: {v}', 'Name: {v}'],
  noteReligionLine: ['الديانة: {v}', 'Religion: {v}'],
  noteFixmeRequired: ['يرجى وصف المشكلة قبل الإرسال.', 'Please describe the problem before sending.'],
  noteGoneNameRequired: ['يرجى إدخال اسم المعلم قبل الإرسال.', 'Please enter the place name before sending.'],
  noteGoneBody: ['المعلم غير موجود على أرض الواقع رغم ظهوره على الخريطة (قد تكون البيانات قديمة).', 'This place does not exist on the ground although it is on the map (the data may be outdated).'],
  noteTextRequired: ['يرجى كتابة نص الملاحظة قبل الإرسال.', 'Please write the note text before sending.'],
  noteSent: ['تم إرسال الملاحظة بنجاح!', 'Note sent!'],
  noteView: ['عرض الملاحظة', 'View note'],
  noteFailed: ['فشل في إرسال الملاحظة إلى OpenStreetMap: {msg}', 'Failed to send the note to OpenStreetMap: {msg}'],
  noteOpenOnOsm: ['فتح الملاحظة على OSM', 'Open the note on OSM'],

  // User widget
  osmUser: ['مستخدم OSM', 'OSM user'],
  welcomeUser: ['مرحباً، <strong id="user-display-name">{name}</strong>', 'Hello, <strong id="user-display-name">{name}</strong>'],
  osmContributor: ['مساهم في OpenStreetMap', 'OpenStreetMap contributor'],
  logout: ['تسجيل خروج', 'Log out'],
  logoutTitle: ['تسجيل الخروج', 'Log out'],
  browsingAsGuest: ['<span style="color: var(--color-text-muted);">تصفح كـ <strong>زائر (بيانات مجهلة)</strong></span>', '<span style="color: var(--color-text-muted);">Browsing as a <strong>guest (anonymised data)</strong></span>'],
  guestRole: ['سجل دخولك لعرض المساهمين والتعديل', 'Log in to see contributors and edit'],
  login: ['تسجيل دخول', 'Log in'],
  loginTitle: ['تسجيل الدخول باستخدام OSM', 'Log in with OSM'],
});
