// Arabic name helpers. Mirrors normalize_arabic() / is_generic_mosque_name()
// in common.py (ported from the osm x wikidata project); keep both in sync.

const CHAR_MAP = {
  "ء": "'", "أ": "A", "إ": "I", "آ": "Aa", "ٱ": "A", "ا": "a",
  "ب": "b", "ت": "t", "ث": "th", "ج": "j", "ح": "h", "خ": "kh",
  "د": "d", "ذ": "dh", "ر": "r", "ز": "z", "س": "s", "ش": "sh",
  "ص": "s", "ض": "d", "ط": "t", "ظ": "dh", "ع": "a", "غ": "gh",
  "ف": "f", "ق": "q", "ك": "k", "ل": "l", "م": "m", "ن": "n",
  "ه": "h", "و": "w", "ي": "y", "ى": "a", "ة": "ah", "ؤ": "'", "ئ": "'"
};

const EULOGIES = [
  /(?:^|\s)رضي\s+الله\s+(?:عنه|عنها|عنهم|عنهما)(?=\s|$)/g,
  /(?:^|\s)رضوان\s+الله\s+عليهم?(?=\s|$)/g,
  /(?:^|\s)صلى\s+الله\s+عليه\s+وسلم(?=\s|$)/g,
  /(?:^|\s)عليه\s+(?:الصلاة\s+و)?السلام(?=\s|$)/g,
  /(?:^|\s)عليهم\s+(?:الصلاة\s+و)?السلام(?=\s|$)/g,
  /(?:^|\s)رحمه\s+الله(?=\s|$)/g,
  /(?:^|\s)رحمها\s+الله(?=\s|$)/g,
  /(?:^|\s)رحمهم\s+الله(?=\s|$)/g,
  /(?:^|\s)غفر\s+الله\s+له(?=\s|$)/g,
  /(?:^|\s)عفا\s+الله\s+عنه(?=\s|$)/g,
  /(?:^|\s)أسكنه\s+فسيح\s+جناته(?=\s|$)/g,
  /(?:^|\s)كرم\s+الله\s+وجهه(?=\s|$)/g,
  /(?:^|\s)حفظه\s+الله(?=\s|$)/g,
  /(?:^|\s)وفقه\s+الله(?=\s|$)/g,
  /(?:^|\s)أيده\s+الله(?=\s|$)/g,
  /(?:^|\s)قدس\s+سره(?=\s|$)/g,
  /(?:^|\s)تبارك\s+وتعالى(?=\s|$)/g,
  /(?:^|\s)عز\s+وجل(?=\s|$)/g,
  /(?:^|\s)سبحانه\s+وتعالى(?=\s|$)/g
];

const TITLE_MAP = {
  'جامع': 'Grand Mosque',
  'الجامع': 'Grand Mosque',
  'مسجد': 'Mosque',
  'المسجد': 'Mosque',
  'مصلى': 'Musalla',
  'مصلّى': 'Musalla',
  'المصلى': 'Musalla',
  'روضة': 'Rawdah',
  'الروضة': 'Rawdah',
  'محراب': 'Mihrab',
  'مجمع': 'Complex',
  'مركز': 'Center',
  'المركز': 'Center'
};

const HONORIFICS_MAP = {
  'خادم الحرمين الشريفين': 'Custodian of the Two Holy Mosques',
  'ولي العهد': 'Crown Prince',
  'الملك': 'King',
  'الملكه': 'Queen',
  'الملكة': 'Queen',
  'الأمير': 'Prince',
  'الامير': 'Prince',
  'الأميرة': 'Princess',
  'الاميرة': 'Princess',
  'السلطان': 'Sultan',
  'الخليفة': 'Caliph',
  'الوالي': 'Governor',
  'الإمام': 'Imam',
  'الامام': 'Imam',
  'الشيخ': 'Sheikh',
  'الشيخة': 'Sheikha',
  'شيخ الإسلام': 'Sheikh Al-Islam',
  'سيد الشهداء': 'Sayyid Al-Shuhada',
  'الشهيد': 'Martyr',
  'شهداء الواجب': 'Duty Martyrs',
  'شهداء الحد الجنوبي': 'Southern Border Martyrs',
  'الشهداء': 'Al-Shuhada',
  'السيدة': 'Sayyidah',
  'سيدة': 'Sayyidah',
  'أم المؤمنين': "Umm Al-Mu'minin",
  'ام المؤمنين': "Umm Al-Mu'minin",
  'سيف الله': 'Saifullah',
  'سيف الله المسلول': 'Saifullah Al-Maslool',
  'ذو النورين': 'Dhu Al-Nurayn',
  'ذي النورين': 'Dhu Al-Nurayn',
  'ذات النطاقين': 'Dhat Al-Nitaqayn',
  'الصديق': 'Al-Siddiq',
  'الفاروق': 'Al-Farooq',
  'الطيار': 'Al-Tayyar',
  'الخلفاء الراشدين': 'Rightly Guided Caliphs',
  'الخلفاء الراشدون': 'Rightly Guided Caliphs'
};

const PATRONYMICS = {
  'بن': 'bin',
  'ابن': 'Ibn',
  'بنت': 'bint',
  'أبو': 'Abu',
  'ابو': 'Abu',
  'أبي': 'Abi',
  'ابي': 'Abi',
  'أم': 'Umm',
  'ام': 'Umm',
  'آل': 'Al',
  'ذو': 'Dhu',
  'ذي': 'Dhi',
  'ذات': 'Dhat',
  'أهل': 'Ahl',
  'اهل': 'Ahl',
  'أولاد': 'Awlad',
  'بني': 'Bani',
  'بنو': 'Banu'
};

const DIVINE_NAMES = {
  'الله': 'Allah', 'الرحمن': 'Al-Rahman', 'الرحيم': 'Al-Raheem', 'الملك': 'Al-Malik',
  'القدوس': 'Al-Quddus', 'السلام': 'Al-Salam', 'المؤمن': "Al-Mu'min", 'المهيمن': 'Al-Muhaymin',
  'العزيز': 'Al-Aziz', 'الجبار': 'Al-Jabbar', 'المتكبر': 'Al-Mutakabbir', 'الخالق': 'Al-Khaliq',
  'البارئ': 'Al-Bari', 'المصور': 'Al-Musawwir', 'الغفار': 'Al-Ghaffar', 'القهار': 'Al-Qahhar',
  'الوهاب': 'Al-Wahhab', 'الرزاق': 'Al-Razzaq', 'الفتاح': 'Al-Fattah', 'العليم': 'Al-Aleem',
  'القابض': 'Al-Qabid', 'الباسط': 'Al-Basit', 'الخافض': 'Al-Khafid', 'الرافع': 'Al-Rafi',
  'المعز': "Al-Mu'izz", 'المذل': 'Al-Mudhill', 'السميع': 'Al-Samee', 'البصير': 'Al-Baseer',
  'الحكم': 'Al-Hakam', 'العدل': 'Al-Adl', 'اللطيف': 'Al-Latif', 'الخبير': 'Al-Khabeer',
  'الحليم': 'Al-Haleem', 'العظيم': 'Al-Azeem', 'الغفور': 'Al-Ghafoor', 'الشكور': 'Al-Shakoor',
  'العلي': 'Al-Ali', 'الكبير': 'Al-Kabeer', 'الحفيظ': 'Al-Hafeez', 'المقيت': 'Al-Muqeet',
  'الحسيب': 'Al-Haseeb', 'الجليل': 'Al-Jaleel', 'الكريم': 'Al-Kareem', 'الرقيب': 'Al-Raqeeb',
  'المجيب': 'Al-Mujeeb', 'الواسع': 'Al-Wasi', 'الحكيم': 'Al-Hakeem', 'الودود': 'Al-Wadood',
  'المجيد': 'Al-Majeed', 'الباعث': "Al-Ba'ith", 'الشهيد': 'Al-Shaheed', 'الحق': 'Al-Haqq',
  'الوكيل': 'Al-Wakeel', 'القوي': 'Al-Qawi', 'المتين': 'Al-Mateen', 'الولي': 'Al-Wali',
  'الحميد': 'Al-Hameed', 'المحصي': 'Al-Muhsi', 'المبدئ': 'Al-Mubdi', 'المعيد': "Al-Mu'id",
  'المحيي': 'Al-Muhyi', 'المميت': 'Al-Mumeet', 'الحي': 'Al-Hayy', 'القيوم': 'Al-Qayyoom',
  'الواجد': 'Al-Wajid', 'الماجد': 'Al-Majid', 'الواحد': 'Al-Wahid', 'الأحد': 'Al-Ahad',
  'الاحد': 'Al-Ahad', 'الصمد': 'Al-Samad', 'القادر': 'Al-Qadir', 'المقتدر': 'Al-Muqtadir',
  'المقدم': 'Al-Muqaddim', 'المؤخر': "Al-Mu'akhkhir", 'الأول': 'Al-Awwal', 'الاول': 'Al-Awwal',
  'الآخر': 'Al-Akhir', 'الاخر': 'Al-Akhir', 'الظاهر': 'Al-Zahir', 'الباطن': 'Al-Batin',
  'المتعالي': "Al-Muta'ali", 'البر': 'Al-Birr', 'التواب': 'Al-Tawwab', 'المنتقم': 'Al-Muntaqim',
  'العفو': 'Al-Afuww', 'الرؤوف': "Al-Ra'oof", 'المقسط': 'Al-Muqsit', 'الجامع': 'Al-Jami',
  'الغني': 'Al-Ghani', 'المغني': 'Al-Mughni', 'المانع': 'Al-Mani', 'الضار': 'Al-Darr',
  'النافع': 'Al-Nafi', 'النور': 'Al-Noor', 'الهادي': 'Al-Hadi', 'البديع': 'Al-Badi',
  'الباقي': 'Al-Baqi', 'الوارث': 'Al-Warith', 'الرشيد': 'Al-Rasheed', 'الصبور': 'Al-Saboor'
};

const ABD_SPECIAL = {
  'عبدالعزيز': 'Abdulaziz', 'عبد العزيز': 'Abdulaziz',
  'عبدالله': 'Abdullah', 'عبد الله': 'Abdullah',
  'عبدالرحمن': 'Abdulrahman', 'عبد الرحمن': 'Abdulrahman',
  'عبدالرحيم': 'Abdulraheem', 'عبد الرحيم': 'Abdulraheem',
  'عبدالملك': 'Abdulmalik', 'عبد الملك': 'Abdulmalik',
  'عبدالمحسن': 'Abdulmohsen', 'عبد المحسن': 'Abdulmohsen',
  'عبداللطيف': 'Abdullatif', 'عبد اللطيف': 'Abdullatif',
  'عبدالوهاب': 'Abdulwahhab', 'عبد الوهاب': 'Abdulwahhab',
  'عبدالصمد': 'Abdulsamad', 'عبد الصمد': 'Abdulsamad',
  'عبدالسلام': 'Abdulsalam', 'عبد السلام': 'Abdulsalam',
  'عبدالكريم': 'Abdulkarim', 'عبد الكريم': 'Abdulkarim',
  'عبدالمجيد': 'Abdulmajeed', 'عبد المجيد': 'Abdulmajeed',
  'عبدالحكيم': 'Abdulhakeem', 'عبد الحكيم': 'Abdulhakeem',
  'عبدالفتاح': 'Abdulfattah', 'عبد الفتاح': 'Abdulfattah',
  'عبدالرزاق': 'Abdulrazzaq', 'عبد الرزاق': 'Abdulrazzaq',
  'عبدالعليم': 'Abdulaleem', 'عبد العليم': 'Abdulaleem',
  'عبدالحميد': 'Abdulhameed', 'عبد الحميد': 'Abdulhameed',
  'عبدالقادر': 'Abdulqadir', 'عبد القادر': 'Abdulqadir',
  'عبدالغفور': 'Abdulghafur', 'عبد الغفور': 'Abdulghafur',
  'عبدالخالق': 'Abdulkhaliq', 'عبد الخالق': 'Abdulkhaliq',
  'عبدالقدوس': 'Abdulquddus', 'عبد القدوس': 'Abdulquddus',
  'عبدالهادي': 'Abdulhadi', 'عبد الهادي': 'Abdulhadi',
  'عبدالباسط': 'Abdulbasit', 'عبد الباسط': 'Abdulbasit',
  'عبدالجبار': 'Abduljabbar', 'عبد الجبار': 'Abduljabbar',
  'عبدالمطلب': 'Abdulmuttalib', 'عبد المطلب': 'Abdulmuttalib',
  'عبدالمنان': 'Abdulmannan', 'عبد المنان': 'Abdulmannan',
  'عبدالحي': 'Abdulhayy', 'عبد الحي': 'Abdulhayy',
  'عبدالقيوم': 'Abdulqayyum', 'عبد القيوم': 'Abdulqayyum',
  'عبدالعظيم': 'Abdulazeem', 'عبد العظيم': 'Abdulazeem',
  'عبدالغني': 'Abdulghani', 'عبد الغني': 'Abdulghani',
  'عبدالواحد': 'Abdulwahid', 'عبد الواحد': 'Abdulwahid',
  'عبدالأحد': 'Abdulahad', 'عبد الأحد': 'Abdulahad',
  'عبدالستار': 'Abdulsattar', 'عبد الستار': 'Abdulsattar',
  'عبدالصبور': 'Abdulsaboor', 'عبد الصبور': 'Abdulsaboor',
  'عبدالباري': 'Abdulbari', 'عبد الباري': 'Abdulbari',
  'عبدالرؤوف': 'Abdulraouf', 'عبد الرؤوف': 'Abdulraouf',
  'عبدالإله': 'Abdulilah', 'عبد الإله': 'Abdulilah',
  'عبدالاله': 'Abdulilah', 'عبد الاله': 'Abdulilah',
  'عبدالمولى': 'Abdulmawla', 'عبد المولى': 'Abdulmawla'
};

const ABD_MAP = {};
for (const [arName, enTrans] of Object.entries(DIVINE_NAMES)) {
  if (arName === 'الله') {
    ABD_MAP['الله'] = 'Abdullah';
    ABD_MAP['لله'] = 'Abdullah';
    continue;
  }
  const core = enTrans.replace('Al-', '').replace("'", '');
  const comp = `Abdul${core.toLowerCase()}`;
  ABD_MAP[arName] = comp;
  const stem = arName.startsWith('ال') ? arName.slice(2) : arName;
  ABD_MAP[stem] = comp;
}

const KNOWN_VOCABULARY = {
  // Prophets
  'محمد': 'Muhammad', 'إبراهيم': 'Ibrahim', 'ابراهيم': 'Ibrahim', 'موسى': 'Musa', 'عيسى': 'Isa',
  'نوح': 'Nuh', 'آدم': 'Adam', 'ادم': 'Adam', 'هود': 'Hud', 'صالح': 'Salih', 'لوط': 'Lut',
  'إسماعيل': 'Ismail', 'اسماعيل': 'Ismail', 'إسحاق': 'Ishaq', 'اسحاق': 'Ishaq', 'يعقوب': 'Yaqub',
  'يوسف': 'Yusuf', 'أيوب': 'Ayyub', 'ايوب': 'Ayyub', 'شعيب': 'Shuaib', 'هارون': 'Harun',
  'داود': 'Dawud', 'داوود': 'Dawud', 'سليمان': 'Sulaiman', 'يونس': 'Yunus', 'إلياس': 'Ilyas',
  'الياس': 'Ilyas', 'اليسع': 'Al-Yasa', 'زكريا': 'Zakariya', 'يحيى': 'Yahya',

  // Companions
  'أبو بكر': 'Abu Bakr', 'ابو بكر': 'Abu Bakr', 'أبو بكر الصديق': 'Abu Bakr Al-Siddiq',
  'ابو بكر الصديق': 'Abu Bakr Al-Siddiq', 'بكر': 'Bakr', 'البكر': 'Al-Bakr',
  'عمر': 'Omar', 'الخطاب': 'Al-Khattab', 'ابن الخطاب': 'Ibn Al-Khattab', 'عمر بن الخطاب': 'Omar bin Al-Khattab',
  'عثمان': 'Othman', 'عفان': 'Affan', 'ابن عفان': 'Ibn Affan', 'عثمان بن عفان': 'Othman bin Affan',
  'علي': 'Ali', 'طالب': 'Talib', 'أبي طالب': 'Abi Talib', 'ابي طالب': 'Abi Talib',
  'علي بن أبي طالب': 'Ali bin Abi Talib', 'علي بن ابي طالب': 'Ali bin Abi Talib',
  'خالد': 'Khalid', 'الوليد': 'Al-Waleed', 'وليد': 'Waleed', 'خالد بن الوليد': 'Khalid bin Al-Waleed',
  'بلال': 'Bilal', 'رباح': 'Rabah', 'بلال بن رباح': 'Bilal bin Rabah',
  'حمزة': 'Hamza', 'حمزة بن عبد المطلب': 'Hamza bin Abdulmuttalib', 'حمزة بن عبدالمطلب': 'Hamza bin Abdulmuttalib',
  'سعد': 'Saad', 'سعيد': 'Saeed', 'سعد بن أبي وقاص': 'Saad bin Abi Waqqas', 'سعد بن ابي وقاص': 'Saad bin Abi Waqqas',
  'وقاص': 'Waqqas', 'أبي وقاص': 'Abi Waqqas', 'ابي وقاص': 'Abi Waqqas',
  'سعد بن معاذ': 'Saad bin Muadh', 'معاذ': 'Muadh', 'جبل': 'Jabal', 'معاذ بن جبل': 'Muadh bin Jabal',
  'مصعب': 'Musab', 'عمير': 'Umair', 'مصعب بن عمير': 'Musab bin Umair',
  'طلحة': 'Talha', 'عبيد الله': 'Ubaidullah', 'طلحة بن عبيد الله': 'Talha bin Ubaidullah',
  'الزبير': 'Al-Zubair', 'العوام': 'Al-Awwam', 'الزبير بن العوام': 'Al-Zubair bin Al-Awwam',
  'أبو عبيدة': 'Abu Ubaidah', 'ابو عبيدة': 'Abu Ubaidah', 'الجراح': 'Al-Jarrah',
  'أبو عبيدة بن الجراح': 'Abu Ubaidah bin Al-Jarrah',
  'أبو هريرة': 'Abu Hurairah', 'ابو هريرة': 'Abu Hurairah',
  'أبو ذر': 'Abu Dharr', 'ابو ذر': 'Abu Dharr', 'أبي ذر': 'Abu Dharr', 'ابي ذر': 'Abu Dharr',
  'الغفاري': 'Al-Ghifari', 'ذر': 'Dharr',
  'أبو ذر الغفاري': 'Abu Dharr Al-Ghifari', 'ابو ذر الغفاري': 'Abu Dharr Al-Ghifari',
  'أبي ذر الغفاري': 'Abu Dharr Al-Ghifari', 'ابي ذر الغفاري': 'Abu Dharr Al-Ghifari',
  'سلمان': 'Salman', 'الفارسي': 'Al-Farsi', 'سلمان الفارسي': 'Salman Al-Farsi',
  'صهيب': 'Suhaib', 'الرومي': 'Al-Rumi', 'صهيب الرومي': 'Suhaib Al-Rumi',
  'عمار': 'Ammar', 'ياسر': 'Yasser', 'عمار بن ياسر': 'Ammar bin Yasser',
  'حذيفة': 'Hudhaifah', 'اليمان': 'Al-Yaman', 'حذيفة بن اليمان': 'Hudhaifah bin Al-Yaman',
  'أنس': 'Anas', 'انس': 'Anas', 'مالك': 'Malik', 'أنس بن مالك': 'Anas bin Malik', 'انس بن مالك': 'Anas bin Malik',
  'أسامة': 'Osama', 'اسامة': 'Osama', 'زيد': 'Zaid', 'أسامة بن زيد': 'Osama bin Zaid',
  'زيد بن حارثة': 'Zaid bin Harithah', 'حارثة': 'Harithah', 'زيد بن ثابت': 'Zaid bin Thabit',
  'ثابت': 'Thabit', 'حسان': 'Hassan', 'حسان بن ثابت': 'Hassan bin Thabit',
  'جعفر': 'Jafar', 'جعفر الطيار': 'Jafar Al-Tayyar',
  'الحسن': 'Al-Hassan', 'حسن': 'Hassan', 'الحسين': 'Al-Hussein', 'حسين': 'Hussein',
  'عبد الله بن عباس': 'Abdullah bin Abbas', 'ابن عباس': 'Ibn Abbas', 'عباس': 'Abbas',
  'عبد الله بن عمر': 'Abdullah bin Omar', 'ابن عمر': 'Ibn Omar',
  'عبد الله بن مسعود': 'Abdullah bin Masud', 'ابن مسعود': 'Ibn Masud', 'مسعود': 'Masud',
  'عبدالله بن مسعود': 'Abdullah bin Masud',
  'عبد الرحمن بن عوف': 'Abdulrahman bin Awf', 'عبدالرحمن بن عوف': 'Abdulrahman bin Awf', 'عوف': 'Awf',
  'عمرو بن العاص': 'Amr bin Al-Aas', 'عمرو': 'Amr', 'العاص': 'Al-Aas',
  'معاوية': 'Muawiyah', 'سفيان': 'Sufyan', 'أبي سفيان': 'Abi Sufyan',
  'الأرقم': 'Al-Arqam', 'الارقم': 'Al-Arqam', 'القعقاع': "Al-Qa'qa",
  'عكاشة': 'Ukashah', 'عكرمة': 'Ikrimah', 'البراء': 'Al-Bara', 'تميم الداري': 'Tamim Al-Dari',
  'طارق': 'Tariq', 'زياد': 'Ziyad', 'طارق بن زياد': 'Tariq bin Ziyad',
  'المغيرة': 'Al-Mughirah', 'شعبة': "Shu'bah", 'المغيرة بن شعبة': "Al-Mughirah bin Shu'bah",

  // Mothers of believers
  'خديجة': 'Khadijah', 'خديجة بنت خويلد': 'Khadijah bint Khuwaylid',
  'عائشة': 'Aisha', 'فاطمة': 'Fatima', 'فاطمة الزهراء': 'Fatima Al-Zahra', 'الزهراء': 'Al-Zahra',
  'مريم': 'Maryam', 'آسية': 'Asiya', 'اسية': 'Asiya', 'زينب': 'Zainab', 'رقية': 'Ruqayyah',
  'حفصة': 'Hafsah', 'أم كلثوم': 'Umm Kulthum', 'ام كلثوم': 'Umm Kulthum',
  'أم سلمة': 'Umm Salamah', 'ام سلمة': 'Umm Salamah', 'أسماء': 'Asma', 'اسماء': 'Asma',
  'أسماء بنت أبي بكر': 'Asma bint Abi Bakr', 'سارة': 'Sarah', 'هاجر': 'Hajar',
  'سمية': 'Sumayyah', 'الخنساء': 'Al-Khansa',

  // Scholars & Imams
  'الشافعي': "Al-Shafi'i", 'الإمام الشافعي': "Imam Al-Shafi'i", 'الامام الشافعي': "Imam Al-Shafi'i",
  'أحمد بن حنبل': 'Ahmad bin Hanbal', 'احمد بن حنبل': 'Ahmad bin Hanbal', 'ابن حنبل': 'Ibn Hanbal',
  'أبو حنيفة': 'Abu Hanifa', 'ابو حنيفة': 'Abu Hanifa', 'مالك بن أنس': 'Malik bin Anas',
  'الإمام مالك': 'Imam Malik', 'البخاري': 'Al-Bukhari', 'الإمام البخاري': 'Imam Al-Bukhari',
  'مسلم': 'Muslim', 'الإمام مسلم': 'Imam Muslim', 'النووي': 'Al-Nawawi', 'الطبري': 'Al-Tabari',
  'القرطبي': 'Al-Qurtubi', 'ابن تيمية': 'Ibn Taymiyyah', 'ابن القيم': 'Ibn Al-Qayyim',
  'ابن كثير': 'Ibn Kathir', 'ابن حجر': 'Ibn Hajar',
  'محمد بن عبد الوهاب': 'Muhammad bin Abdulwahhab', 'محمد بن عبدالوهاب': 'Muhammad bin Abdulwahhab',
  'ابن باز': 'Ibn Baz', 'بن باز': 'bin Baz', 'ابن عثيمين': 'Ibn Uthaymeen',
  'الشنقيطي': 'Al-Shanqiti', 'الألباني': 'Al-Albani', 'الالباني': 'Al-Albani',

  // Saudi Leaders
  'سعود': 'Saud', 'فيصل': 'Faisal', 'فهد': 'Fahd', 'سلطان': 'Sultan',
  'نايف': 'Nayef', 'سلمان': 'Salman', 'تركي': 'Turki', 'بندر': 'Bandar',
  'مشعل': 'Mishaal', 'مقرن': 'Muqrin', 'طلال': 'Talal', 'نواف': 'Nawaf',
  'منصور': 'Mansour', 'مساعد': 'Musaed', 'أحمد': 'Ahmad', 'احمد': 'Ahmad',
  'سطام': 'Sattam', 'متعب': 'Mutaib', 'ممدوح': 'Mamdouh',
  'محمد بن سلمان': 'Muhammad bin Salman', 'محمد بن سعود': 'Muhammad bin Saud',
  'تركي بن عبد الله': 'Turki bin Abdullah', 'تركي بن عبدالله': 'Turki bin Abdullah',
  'عبد العزيز آل سعود': 'Abdulaziz Al Saud', 'عبدالعزيز آل سعود': 'Abdulaziz Al Saud',
  'خالد الفيصل': 'Khalid Al-Faisal', 'سعود الفيصل': 'Saud Al-Faisal', 'تركي الفيصل': 'Turki Al-Faisal',

  // Benefactors & Places
  'الراجحي': 'Al-Rajhi', 'سليمان الراجحي': 'Sulaiman Al-Rajhi', 'صالح الراجحي': 'Saleh Al-Rajhi',
  'عائشة الراجحي': 'Aisha Al-Rajhi', 'الشربتلي': 'Al-Sharbatly', 'حسن الشربتلي': 'Hassan Al-Sharbatly',
  'الكعكي': 'Al-Kaaki', 'بقشان': 'Bugshan', 'بن لادن': 'Bin Laden',
  'العبيكان': 'Al-Obeikan', 'الدخيل': 'Al-Dakheel', 'الموسى': 'Al-Mousa', 'الجفالي': 'Al-Juffali',
  'الدريس': 'Al-Drees', 'دريس': 'Drees', 'الساسكو': 'Sasco', 'ساسكو': 'Sasco',
  'السهلي': 'Al-Sahli', 'النفيعي': 'Al-Nufaie', 'العمري': 'Al-Omari',

  // Historic Places & Concepts
  'قباء': 'Quba', 'القبلتين': 'Al-Qiblatain', 'الخيف': 'Al-Khaif', 'نمرة': 'Namirah',
  'المشعر الحرام': "Al-Mash'ar Al-Haram", 'التنعيم': 'Al-Taneem', 'البيعة': "Al-Baya'ah",
  'بدر': 'Badr', 'أحد': 'Uhud', 'احد': 'Uhud', 'حنين': 'Hunain', 'تبوك': 'Tabuk',
  'خيبر': 'Khaibar', 'الخندق': 'Al-Khandaq', 'مؤتة': 'Mutah', 'اليرموك': 'Al-Yarmouk',
  'القادسية': 'Al-Qadisiyyah', 'حطين': 'Hittin', 'عين جالوت': 'Ain Jalut',
  'الصفا': 'Al-Safa', 'المروة': 'Al-Marwah', 'زمزم': 'Zamzam', 'حراء': 'Hira',
  'ثور': 'Thawr', 'الطور': 'Al-Toor', 'طيبة': 'Taybah', 'يثرب': 'Yathrib',
  'مكة': 'Makkah', 'المدينة': 'Al-Madinah', 'القدس': 'Al-Quds', 'الأقصى': 'Al-Aqsa',
  'الاقصى': 'Al-Aqsa', 'الأندلس': 'Al-Andalus', 'الاندلس': 'Al-Andalus',
  'قرطبة': 'Cordoba', 'غرناطة': 'Granada', 'الوادي': 'Al-Wadi', 'النخيل': 'Al-Nakheel',
  'الحارة': 'Al-Harah', 'الحاره': 'Al-Harah', 'الصناعية': "Al-Sina'iyah", 'صناعية': "Al-Sina'iyah",

  // Concepts
  'الهدى': 'Al-Huda', 'التقوى': 'Al-Taqwa', 'الفتح': 'Al-Fath', 'الإخلاص': 'Al-Ikhlas',
  'الاخلاص': 'Al-Ikhlas', 'الفردوس': 'Al-Firdaws', 'الكوثر': 'Al-Kawthar', 'الريان': 'Al-Rayyan',
  'التوحيد': 'Al-Tawhid', 'البركة': 'Al-Barakah', 'الفرقان': 'Al-Furqan', 'الإيمان': 'Al-Iman',
  'الايمان': 'Al-Iman', 'الإحسان': 'Al-Ihsan', 'الاحسان': 'Al-Ihsan', 'الجمعة': 'Al-Jummah',
  'العيد': 'Al-Eid', 'الوالدين': 'Al-Walidayn', 'بر الوالدين': 'Birr Al-Walidayn',
  'الخير': 'Al-Khair', 'خير': 'Khair', 'البر': 'Al-Birr', 'بر': 'Birr',
  'الرحمة': 'Al-Rahmah', 'رحمة': 'Rahmah', 'الرحمه': 'Al-Rahmah', 'المغفرة': 'Al-Maghfirah',
  'الرضوان': 'Al-Ridwan', 'رضوان': 'Ridwan', 'النعيم': 'Al-Naeem', 'الجنة': 'Al-Jannah',
  'الفلاح': 'Al-Falah', 'الصالحين': 'Al-Salihin', 'المتقين': 'Al-Muttaqin', 'المحسنين': 'Al-Muhsinin',
  'الصابرين': 'Al-Sabirin', 'المهاجرين': 'Al-Muhajirin', 'الأنصار': 'Al-Ansar', 'الانصار': 'Al-Ansar',
  'الأبرار': 'Al-Abrar', 'الابرار': 'Al-Abrar', 'عباد الرحمن': 'Ibad Al-Rahman',
  'رياض الصالحين': 'Riyad Al-Salihin', 'الصحابة': 'Al-Sahabah', 'الضياء': 'Al-Diya',
  'ضياء': 'Diya', 'البينة': 'Al-Bayyinah', 'البيان': 'Al-Bayan', 'الهداية': 'Al-Hidayah',
  'الأمان': 'Al-Aman', 'الامان': 'Al-Aman', 'السكينة': 'Al-Sakinah', 'التعاون': 'Al-Taawun',
  'التوبة': 'Al-Tawbah', 'الاستقامة': 'Al-Istiqamah', 'المحطة': 'Al-Mahattah', 'محطة': 'Al-Mahattah',
  'الحي': 'Al-Hayy', 'السوق': 'Al-Souq', 'النصر': 'Al-Nasr', 'العزة': 'Al-Izzah',
  'الكرامة': 'Al-Karamah', 'المجد': 'Al-Majd', 'الحمد': 'Al-Hamd', 'الأعلى': "Al-A'la",
  'الاعلى': "Al-A'la", 'خليل': 'Khalil', 'توفيق': 'Tawfiq', 'محمود': 'Mahmoud',

  // Descriptors
  'أهلي': 'Ahli', 'اهلي': 'Ahli', 'محلي': 'Local', 'مؤقت': 'Temporary', 'صغير': 'Small',
  'كبير': 'Grand', 'الكبير': 'Al-Kabeer', 'رجال': 'Men', 'الرجال': 'Men',
  'نساء': 'Women', 'النساء': 'Women',

  // Endowments, Family Relations & Historic Figures
  'والدة': 'Walidat', 'والد': 'Walid',
  'صلاح الدين': 'Salah Al-Din', 'الأيوبي': 'Al-Ayyubi',
  'صلاح الدين الأيوبي': 'Salah Al-Din Al-Ayyubi',
  'أويس القرني': 'Owais Al-Qarni', 'أويس': 'Owais',
  'الهجرة': 'Al-Hijrah', 'هجرة': 'Hijrah',
  'البابطين': 'Al-Babtain', 'بابطين': 'Babtain',
  'السدحان': 'Al-Sadhan', 'الشميسي': 'Al-Shemaisi',
  'الفوطة': 'Al-Foutah', 'الغنام': 'Al-Ghannam',
  'المبيريك': 'Al-Mubaireek', 'السبعان': 'Al-Sabaan',
  'المرشد': 'Al-Murshid', 'الحديقة': 'Al-Hadeeqah',
  'جسر الملك فهد': 'King Fahd Causeway', 'جسر': 'Bridge',

  // Major Saudi Tribes & Surnames
  'القحطاني': 'Al-Qahtani', 'قحطان': 'Qahtan',
  'السبيعي': 'Al-Subaie', 'سبيع': 'Subaie',
  'العتيبي': 'Al-Otaibi', 'عتيبة': 'Otaibah',
  'الدوسري': 'Al-Dossari', 'دوسر': 'Dossari',
  'الغامدي': 'Al-Ghamdi', 'غامد': 'Ghamd',
  'الزهراني': 'Al-Zahrani', 'زهران': 'Zahran',
  'الحربي': 'Al-Harbi', 'حرب': 'Harb',
  'المطيري': 'Al-Mutairi', 'مطير': 'Mutair',
  'الشهري': 'Al-Shehri', 'بني شهر': 'Bani Shehr',
  'القرني': 'Al-Qarni', 'بلقرن': 'Balqarn',
  'العسيري': 'Al-Asiri', 'عسير': 'Asir',
  'المالكي': 'Al-Malki', 'بني مالك': 'Bani Malik',
  'الشمري': 'Al-Shammari', 'شمر': 'Shammar',
  'العنزي': 'Al-Anazi', 'عنزة': 'Anazah',
  'الخالدي': 'Al-Khalidi', 'بني خالد': 'Bani Khalid',
  'البقمي': 'Al-Baqami', 'السلمي': 'Al-Sulami',
  'الجهني': 'Al-Juhani', 'البلوي': 'Al-Balawi',
  'الحازمي': 'Al-Hazmi', 'التميمي': 'Al-Tamimi'
};

const WAW_ROOT_STARTS = ['والد', 'وائل', 'واحة', 'واسط', 'وافي', 'واصل', 'وادي', 'وقاص', 'وجدي', 'وحيد', 'وديع', 'وردة', 'وفاء', 'وثيق'];

function reconstructMorphology(stem) {
  const n = stem.length;
  if (n < 3) {
    let out = '';
    for (const c of stem) out += CHAR_MAP[c] || c;
    return out.charAt(0).toUpperCase() + out.slice(1);
  }

  // 1. Taf'eel: توفيق
  if (n === 5 && stem.startsWith('ت') && stem[3] === 'ي') {
    const c1 = CHAR_MAP[stem[1]] || stem[1];
    const c2 = CHAR_MAP[stem[2]] || stem[2];
    if (stem[1] === 'و') {
      return stem[4] === 'ق' ? `Taw${c2}iq` : `Taw${c2}id`;
    }
    return stem[4] === 'ن' ? `Ta${c1}${c2}in` : `Ta${c1}${c2}eer`;
  }

  // 2. Maf'oul: محمود, منصور
  if (n === 5 && stem.startsWith('م') && stem[3] === 'و') {
    const c1 = CHAR_MAP[stem[1]] || stem[1];
    const c2 = CHAR_MAP[stem[2]] || stem[2];
    const c3 = CHAR_MAP[stem[4]] || stem[4];
    const s = `Ma${c1}${c2}ou${c3}`;
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  // 3. Fa'il/Fa'eel: كريم, خليل
  if (n === 4 && stem[2] === 'ي') {
    const c1 = CHAR_MAP[stem[0]] || stem[0];
    const c2 = CHAR_MAP[stem[1]] || stem[1];
    const c3 = CHAR_MAP[stem[3]] || stem[3];
    const s = `${c1}a${c2}i${c3}`;
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  // 4. Fa'oul: صبور, شكور
  if (n === 4 && stem[2] === 'و') {
    const c1 = CHAR_MAP[stem[0]] || stem[0];
    const c2 = CHAR_MAP[stem[1]] || stem[1];
    const c3 = CHAR_MAP[stem[3]] || stem[3];
    const s = `${c1}a${c2}ou${c3}`;
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  // 5. Fa'il: صالح, طارق
  if (n === 4 && stem[1] === 'ا') {
    const c1 = CHAR_MAP[stem[0]] || stem[0];
    const c2 = CHAR_MAP[stem[2]] || stem[2];
    const c3 = CHAR_MAP[stem[3]] || stem[3];
    const s = `${c1}a${c2}i${c3}`;
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  // 6. Fa'lan: عمران, عدنان
  if (n >= 5 && stem.endsWith('ان')) {
    const pre = stem.slice(0, -2);
    if (pre.length === 3) {
      const c1 = CHAR_MAP[pre[0]] || pre[0];
      const c2 = CHAR_MAP[pre[1]] || pre[1];
      const c3 = CHAR_MAP[pre[2]] || pre[2];
      const s = `${c1}a${c2}${c3}an`;
      return s.charAt(0).toUpperCase() + s.slice(1);
    }
  }

  // 7. Fa'eelah: طيبة, جميلة
  if (n === 5 && stem[2] === 'ي' && (stem.endsWith('ة') || stem.endsWith('ه'))) {
    const c1 = CHAR_MAP[stem[0]] || stem[0];
    const c2 = CHAR_MAP[stem[1]] || stem[1];
    if (stem[3] === 'ب') return `${c1.toUpperCase()}a${c2}bah`;
    const c3 = CHAR_MAP[stem[3]] || stem[3];
    return `${c1.toUpperCase()}a${c2}ee${c3}ah`;
  }

  // 8. Triliteral: بدر, فهد, أحد
  if (n === 3) {
    if (stem === 'أحد' || stem === 'احد') return 'Uhud';
    const c1 = CHAR_MAP[stem[0]] || stem[0];
    const c2 = CHAR_MAP[stem[1]] || stem[1];
    const c3 = CHAR_MAP[stem[2]] || stem[2];
    if (['ا', 'و', 'ي'].includes(stem[1])) {
      const v = stem[1] === 'ا' ? 'a' : (stem[1] === 'و' ? 'ou' : 'i');
      return `${c1.toUpperCase()}${v}${c3}`;
    }
    return `${c1.toUpperCase()}a${c2}${c3}`;
  }

  // Fallback letter-by-letter
  let out = '';
  for (let i = 0; i < n; i++) {
    const c = stem[i];
    if (c === 'و' && i > 0 && i < n - 1 && !['ا', 'و', 'ي'].includes(stem[i-1]) && !['ا', 'و', 'ي'].includes(stem[i+1])) {
      out += 'ou';
    } else if (c === 'ي' && i > 0 && i < n - 1 && !['ا', 'و', 'ي'].includes(stem[i-1]) && !['ا', 'و', 'ي'].includes(stem[i+1])) {
      out += 'i';
    } else if (c === 'ي' && i === n - 1) {
      out += 'i';
    } else {
      out += CHAR_MAP[c] || c;
    }
  }
  return out.charAt(0).toUpperCase() + out.slice(1);
}

function transliterateWord(word) {
  if (!word) return '';
  if (KNOWN_VOCABULARY[word]) return KNOWN_VOCABULARY[word];
  if (DIVINE_NAMES[word]) return DIVINE_NAMES[word];
  if (ABD_SPECIAL[word]) return ABD_SPECIAL[word];
  if (HONORIFICS_MAP[word]) return HONORIFICS_MAP[word];
  if (PATRONYMICS[word]) return PATRONYMICS[word];

  if (word.endsWith('ه') && KNOWN_VOCABULARY[word.slice(0, -1) + 'ة']) {
    return KNOWN_VOCABULARY[word.slice(0, -1) + 'ة'];
  }
  if (word.endsWith('ة') && KNOWN_VOCABULARY[word.slice(0, -1) + 'ه']) {
    return KNOWN_VOCABULARY[word.slice(0, -1) + 'ه'];
  }

  let hasAl = false;
  let stem = word;
  if (word.startsWith('ال') && word.length > 3) {
    hasAl = true;
    stem = word.slice(2);
  }

  if (KNOWN_VOCABULARY[stem]) {
    const res = KNOWN_VOCABULARY[stem];
    return hasAl && !res.startsWith('Al-') ? `Al-${res}` : res;
  }
  if (DIVINE_NAMES[stem]) {
    const res = DIVINE_NAMES[stem];
    return hasAl && !res.startsWith('Al-') ? `Al-${res}` : res;
  }

  const normStem = stem.replace(/[أإآ]/g, 'ا');
  if (KNOWN_VOCABULARY[normStem]) {
    const res = KNOWN_VOCABULARY[normStem];
    return hasAl && !res.startsWith('Al-') ? `Al-${res}` : res;
  }
  if (normStem.endsWith('ه') && KNOWN_VOCABULARY[normStem.slice(0, -1) + 'ة']) {
    const res = KNOWN_VOCABULARY[normStem.slice(0, -1) + 'ة'];
    return hasAl && !res.startsWith('Al-') ? `Al-${res}` : res;
  }

  const morph = reconstructMorphology(stem);
  return hasAl ? `Al-${morph}` : morph;
}

export const ArabicText = {
  _tashkeel: /[ً-ٰٟ]/g,
  _tatweel: /ـ/g,
  _punct: /[^\w\s؀-ۿ]/g,

  // Removes tashkeel/tatweel, unifies alef/taa marbuta/alef maqsura/hamza
  // seats, lowercases Latin, and treats جامع and مسجد as synonyms.
  normalize(text, stripAl = false) {
    if (!text) return '';
    const s = String(text).normalize('NFKC').trim()
      .replace(this._tashkeel, '')
      .replace(this._tatweel, '')
      .replace(/[أإآٱ]/g, 'ا')
      .replace(/ة/g, 'ه')
      .replace(/ى/g, 'ي')
      .replace(/ؤ/g, 'و')
      .replace(/ئ/g, 'ي');

    const words = [];
    for (const raw of s.split(/\s+/)) {
      let w = raw.replace(this._punct, '').toLowerCase();
      if (!w) continue;
      if (stripAl && w.startsWith('ال') && w.length > 3) w = w.slice(2);
      if (w === 'جامع' || w === 'مسجد') w = 'مسجد';
      words.push(w);
    }
    return words.join(' ');
  },

  // Words that carry no identifying information in a mosque's name (normalized).
  GENERIC_NAME_WORDS: new Set([
    'مسجد', 'مصلي', 'محراب', 'جمعه', 'بدون', 'اسم', 'بلا',
    'mosque', 'masjid', 'musalla', 'jami', 'jame', 'prayer', 'room',
    'place', 'of', 'worship', 'unnamed', 'no', 'name'
  ]),

  // True for empty names and names made only of generic words/numbers
  // ("مسجد", "الجامع", "مسجد جامع", "مصلى", "Mosque", "مسجد 3").
  isGenericMosqueName(name) {
    const norm = this.normalize(name, true);
    if (!norm) return true;
    return norm.split(' ').every(w => this.GENERIC_NAME_WORDS.has(w) || /^[0-9٠-٩]+$/.test(w));
  },

  // Case/diacritic-insensitive "contains" used by the search box.
  matches(haystack, normalizedQuery) {
    return !!haystack && this.normalize(haystack).includes(normalizedQuery);
  },

  // Saudi Geographic Naming Standards (UNGEGN/GASGI) transliteration engine
  suggestEnglishName(arabicName) {
    if (!arabicName || this.isGenericMosqueName(arabicName)) return '';
    let clean = String(arabicName).normalize('NFKC').trim()
      .replace(this._tashkeel, '')
      .replace(this._tatweel, '')
      .replace(/ى(?=[ء-ي])/g, 'ي');

    // Strip pious eulogies
    for (const eulogyRe of EULOGIES) {
      clean = clean.replace(eulogyRe, '');
    }
    clean = clean.replace(/\s+/g, ' ').trim();

    const rawTokens = clean.split(/\s+/).filter(Boolean);
    if (!rawTokens.length) return '';

    let suffix = 'Mosque';
    let nameTokens = rawTokens;
    if (TITLE_MAP[rawTokens[0]]) {
      suffix = TITLE_MAP[rawTokens[0]];
      nameTokens = rawTokens.slice(1);
    }
    if (!nameTokens.length) return suffix;

    // Split conjunction 'و' (excluding words starting with root 'و')
    const splitTokens = [];
    for (const t of nameTokens) {
      if (t.startsWith('و') && !WAW_ROOT_STARTS.some(p => t.startsWith(p))) {
        if (t.length > 3 && (t.startsWith('وال') || t.startsWith('وإ') || t.startsWith('وأ'))) {
          splitTokens.push('and');
          splitTokens.push(t.slice(1));
        } else if (t === 'و') {
          splitTokens.push('and');
        } else {
          splitTokens.push(t);
        }
      } else {
        splitTokens.push(t);
      }
    }

    const parts = [];
    let i = 0;
    while (i < splitTokens.length) {
      const cur = splitTokens[i];

      if (cur === 'and') {
        parts.push('and');
        i++;
        continue;
      }

      // 4-token phrases
      if (i + 3 < splitTokens.length) {
        const four = `${cur} ${splitTokens[i+1]} ${splitTokens[i+2]} ${splitTokens[i+3]}`;
        if (HONORIFICS_MAP[four]) {
          parts.push(HONORIFICS_MAP[four]);
          i += 4;
          continue;
        }
      }

      // 3-token phrases
      if (i + 2 < splitTokens.length) {
        const three = `${cur} ${splitTokens[i+1]} ${splitTokens[i+2]}`;
        if (HONORIFICS_MAP[three]) {
          parts.push(HONORIFICS_MAP[three]);
          i += 3;
          continue;
        }
        if (KNOWN_VOCABULARY[three]) {
          parts.push(KNOWN_VOCABULARY[three]);
          i += 3;
          continue;
        }
      }

      // 2-token compound
      if (i + 1 < splitTokens.length) {
        const two = `${cur} ${splitTokens[i+1]}`;
        if (ABD_SPECIAL[two]) {
          parts.push(ABD_SPECIAL[two]);
          i += 2;
          continue;
        }
        if (HONORIFICS_MAP[two]) {
          parts.push(HONORIFICS_MAP[two]);
          i += 2;
          continue;
        }
        if (KNOWN_VOCABULARY[two]) {
          parts.push(KNOWN_VOCABULARY[two]);
          i += 2;
          continue;
        }
      }

      // Compound "عبد"
      if ((cur === 'عبد' || cur === 'العبد') && i + 1 < splitTokens.length) {
        const nxt = splitTokens[i+1];
        if (ABD_MAP[nxt]) {
          parts.push(ABD_MAP[nxt]);
          i += 2;
          continue;
        }
        const core = nxt.startsWith('ال') ? nxt.slice(2) : nxt;
        const transCore = transliterateWord(core);
        parts.push(`Abdul${transCore.toLowerCase()}`);
        i += 2;
        continue;
      }

      // Single word lookups
      if (ABD_SPECIAL[cur]) {
        parts.push(ABD_SPECIAL[cur]);
      } else if (HONORIFICS_MAP[cur]) {
        parts.push(HONORIFICS_MAP[cur]);
      } else if (PATRONYMICS[cur]) {
        let p = PATRONYMICS[cur];
        if (p === 'bin' && !parts.length) p = 'Bin';
        parts.push(p);
      } else if (KNOWN_VOCABULARY[cur]) {
        parts.push(KNOWN_VOCABULARY[cur]);
      } else if (DIVINE_NAMES[cur]) {
        parts.push(DIVINE_NAMES[cur]);
      } else {
        parts.push(transliterateWord(cur));
      }

      i++;
    }

    const core = parts.join(' ').trim();

    if (suffix === 'Musalla') {
      if (core.includes('Men')) return core.replace('Men', "Men's Musalla").trim();
      if (core.includes('Women')) return core.replace('Women', "Women's Musalla").trim();
    }

    if (['Mosque', 'Grand Mosque', 'Musalla', 'Rawdah', 'Complex', 'Center'].some(s => core.toLowerCase().endsWith(s.toLowerCase()))) {
      return core;
    }
    if (core.toLowerCase().includes(suffix.toLowerCase())) {
      return core;
    }
    return `${core} ${suffix}`.trim();
  }
};
