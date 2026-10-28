"""
Saudi Geographic Naming Standards Transliteration & NLP Engine
Compliant with UNGEGN / GASGI (General Authority for Survey and Geospatial Information)
principles for Arabic-to-English romanization of Islamic places of worship in Saudi Arabia.
"""

import re
import unicodedata

# ---------------------------------------------------------------------------
# 1. Mosque Types and Titles
# ---------------------------------------------------------------------------
TITLE_MAP = {
    "جامع": "Grand Mosque",
    "الجامع": "Grand Mosque",
    "مسجد": "Mosque",
    "المسجد": "Mosque",
    "مصلى": "Musalla",
    "مصلّى": "Musalla",
    "المصلى": "Musalla",
    "روضة": "Rawdah",
    "الروضة": "Rawdah",
    "محراب": "Mihrab",
    "مجمع": "Complex",
    "مركز": "Center",
    "المركز": "Center",
}

# ---------------------------------------------------------------------------
# 2. Honorifics, Titles & Post-nominal Eulogies
# ---------------------------------------------------------------------------
HONORIFICS_MAP = {
    # Royal & Leadership
    "خادم الحرمين الشريفين": "Custodian of the Two Holy Mosques",
    "ولي العهد": "Crown Prince",
    "الملك": "King",
    "الملكه": "Queen",
    "الملكة": "Queen",
    "الأمير": "Prince",
    "الامير": "Prince",
    "الأميرة": "Princess",
    "الاميرة": "Princess",
    "السلطان": "Sultan",
    "الخليفة": "Caliph",
    "الوالي": "Governor",

    # Religious & Scholarly
    "الإمام": "Imam",
    "الامام": "Imam",
    "الشيخ": "Sheikh",
    "الشيخة": "Sheikha",
    "شيخ الإسلام": "Sheikh Al-Islam",
    "سيد الشهداء": "Sayyid Al-Shuhada",
    "الشهيد": "Martyr",
    "شهداء الواجب": "Duty Martyrs",
    "شهداء الحد الجنوبي": "Southern Border Martyrs",
    "الشهداء": "Al-Shuhada",
    "السيدة": "Sayyidah",
    "سيدة": "Sayyidah",
    "أم المؤمنين": "Umm Al-Mu'minin",
    "ام المؤمنين": "Umm Al-Mu'minin",
    "سيف الله": "Saifullah",
    "سيف الله المسلول": "Saifullah Al-Maslool",
    "ذو النورين": "Dhu Al-Nurayn",
    "ذي النورين": "Dhu Al-Nurayn",
    "ذات النطاقين": "Dhat Al-Nitaqayn",
    "الصديق": "Al-Siddiq",
    "الفاروق": "Al-Farooq",
    "الطيار": "Al-Tayyar",
    "الخلفاء الراشدين": "Rightly Guided Caliphs",
    "الخلفاء الراشدون": "Rightly Guided Caliphs",
}

# Eulogies / Pious devotional phrases to remove from formal geographic names
EULOGIES = [
    re.compile(r"\bرضي\s+الله\s+(عنه|عنها|عنهم|عنهما)\b"),
    re.compile(r"\bرضوان\s+الله\s+عليهم?\b"),
    re.compile(r"\bصلى\s+الله\s+عليه\s+وسلم\b"),
    re.compile(r"\bعليه\s+(الصلاة\s+و)?السلام\b"),
    re.compile(r"\bعليهم\s+(الصلاة\s+و)?السلام\b"),
    re.compile(r"\bرحمه\s+الله\b"),
    re.compile(r"\bرحمها\s+الله\b"),
    re.compile(r"\bرحمهم\s+الله\b"),
    re.compile(r"\bغفر\s+الله\s+له\b"),
    re.compile(r"\bعفا\s+الله\s+عنه\b"),
    re.compile(r"\bأسكنه\s+فسيح\s+جناته\b"),
    re.compile(r"\bكرم\s+الله\s+وجهه\b"),
    re.compile(r"\bحفظه\s+الله\b"),
    re.compile(r"\bوفقه\s+الله\b"),
    re.compile(r"\bأيده\s+الله\b"),
    re.compile(r"\bقدس\s+سره\b"),
    re.compile(r"\bتبارك\s+وتعالى\b"),
    re.compile(r"\bعز\s+وجل\b"),
    re.compile(r"\bسبحانه\s+وتعالى\b"),
]

# ---------------------------------------------------------------------------
# 3. Connectives, Patronymics & Particles
# ---------------------------------------------------------------------------
PATRONYMICS = {
    "بن": "bin",
    "ابن": "Ibn",
    "بنت": "bint",
    "أبو": "Abu",
    "ابو": "Abu",
    "أبي": "Abi",
    "ابي": "Abi",
    "أم": "Umm",
    "ام": "Umm",
    "آل": "Al",
    "ذو": "Dhu",
    "ذي": "Dhi",
    "ذات": "Dhat",
    "أهل": "Ahl",
    "اهل": "Ahl",
    "أولاد": "Awlad",
    "بني": "Bani",
    "بنو": "Banu",
}

# ---------------------------------------------------------------------------
# 4. Divine Names (The 99 Attributes of Allah)
# ---------------------------------------------------------------------------
DIVINE_NAMES = {
    "الله": "Allah",
    "الرحمن": "Al-Rahman",
    "الرحيم": "Al-Raheem",
    "الملك": "Al-Malik",
    "القدوس": "Al-Quddus",
    "السلام": "Al-Salam",
    "المؤمن": "Al-Mu'min",
    "المهيمن": "Al-Muhaymin",
    "العزيز": "Al-Aziz",
    "الجبار": "Al-Jabbar",
    "المتكبر": "Al-Mutakabbir",
    "الخالق": "Al-Khaliq",
    "البارئ": "Al-Bari",
    "المصور": "Al-Musawwir",
    "الغفار": "Al-Ghaffar",
    "القهار": "Al-Qahhar",
    "الوهاب": "Al-Wahhab",
    "الرزاق": "Al-Razzaq",
    "الفتاح": "Al-Fattah",
    "العليم": "Al-Aleem",
    "القابض": "Al-Qabid",
    "الباسط": "Al-Basit",
    "الخافض": "Al-Khafid",
    "الرافع": "Al-Rafi",
    "المعز": "Al-Mu'izz",
    "المذل": "Al-Mudhill",
    "السميع": "Al-Samee",
    "البصير": "Al-Baseer",
    "الحكم": "Al-Hakam",
    "العدل": "Al-Adl",
    "اللطيف": "Al-Latif",
    "الخبير": "Al-Khabeer",
    "الحليم": "Al-Haleem",
    "العظيم": "Al-Azeem",
    "الغفور": "Al-Ghafoor",
    "الشكور": "Al-Shakoor",
    "العلي": "Al-Ali",
    "الكبير": "Al-Kabeer",
    "الحفيظ": "Al-Hafeez",
    "المقيت": "Al-Muqeet",
    "الحسيب": "Al-Haseeb",
    "الجليل": "Al-Jaleel",
    "الكريم": "Al-Kareem",
    "الرقيب": "Al-Raqeeb",
    "المجيب": "Al-Mujeeb",
    "الواسع": "Al-Wasi",
    "الحكيم": "Al-Hakeem",
    "الودود": "Al-Wadood",
    "المجيد": "Al-Majeed",
    "الباعث": "Al-Ba'ith",
    "الشهيد": "Al-Shaheed",
    "الحق": "Al-Haqq",
    "الوكيل": "Al-Wakeel",
    "القوي": "Al-Qawi",
    "المتين": "Al-Mateen",
    "الولي": "Al-Wali",
    "الحميد": "Al-Hameed",
    "المحصي": "Al-Muhsi",
    "المبدئ": "Al-Mubdi",
    "المعيد": "Al-Mu'id",
    "المحيي": "Al-Muhyi",
    "المميت": "Al-Mumeet",
    "الحي": "Al-Hayy",
    "القيوم": "Al-Qayyoom",
    "الواجد": "Al-Wajid",
    "الماجد": "Al-Majid",
    "الواحد": "Al-Wahid",
    "الأحد": "Al-Ahad",
    "الاحد": "Al-Ahad",
    "الصمد": "Al-Samad",
    "القادر": "Al-Qadir",
    "المقتدر": "Al-Muqtadir",
    "المقدم": "Al-Muqaddim",
    "المؤخر": "Al-Mu'akhkhir",
    "الأول": "Al-Awwal",
    "الاول": "Al-Awwal",
    "الآخر": "Al-Akhir",
    "الاخر": "Al-Akhir",
    "الظاهر": "Al-Zahir",
    "الباطن": "Al-Batin",
    "المتعالي": "Al-Muta'ali",
    "البر": "Al-Birr",
    "التواب": "Al-Tawwab",
    "المنتقم": "Al-Muntaqim",
    "العفو": "Al-Afuww",
    "الرؤوف": "Al-Ra'oof",
    "المقسط": "Al-Muqsit",
    "الجامع": "Al-Jami",
    "الغني": "Al-Ghani",
    "المغني": "Al-Mughni",
    "المانع": "Al-Mani",
    "الضار": "Al-Darr",
    "النافع": "Al-Nafi",
    "النور": "Al-Noor",
    "الهادي": "Al-Hadi",
    "البديع": "Al-Badi",
    "الباقي": "Al-Baqi",
    "الوارث": "Al-Warith",
    "الرشيد": "Al-Rasheed",
    "الصبور": "Al-Saboor",
}

# The Abdul- forms for Divine Names
ABD_MAP = {}
for ar_name, en_trans in DIVINE_NAMES.items():
    if ar_name == "الله":
        ABD_MAP["الله"] = "Abdullah"
        ABD_MAP["لله"] = "Abdullah"
        continue
    core = en_trans.replace("Al-", "").replace("'", "")
    ABD_MAP[ar_name] = f"Abdul{core.lower()}"
    stem_ar = ar_name[2:] if ar_name.startswith("ال") else ar_name
    ABD_MAP[stem_ar] = f"Abdul{core.lower()}"

# Special high-frequency compounds
ABD_SPECIAL = {
    "عبدالعزيز": "Abdulaziz",
    "عبد العزيز": "Abdulaziz",
    "عبدالله": "Abdullah",
    "عبد الله": "Abdullah",
    "عبدالرحمن": "Abdulrahman",
    "عبد الرحمن": "Abdulrahman",
    "عبدالرحيم": "Abdulraheem",
    "عبد الرحيم": "Abdulraheem",
    "عبدالملك": "Abdulmalik",
    "عبد الملك": "Abdulmalik",
    "عبدالمحسن": "Abdulmohsen",
    "عبد المحسن": "Abdulmohsen",
    "عبداللطيف": "Abdullatif",
    "عبد اللطيف": "Abdullatif",
    "عبدالوهاب": "Abdulwahhab",
    "عبد الوهاب": "Abdulwahhab",
    "عبدالصمد": "Abdulsamad",
    "عبد الصمد": "Abdulsamad",
    "عبدالسلام": "Abdulsalam",
    "عبد السلام": "Abdulsalam",
    "عبدالكريم": "Abdulkarim",
    "عبد الكريم": "Abdulkarim",
    "عبدالمجيد": "Abdulmajeed",
    "عبد المجيد": "Abdulmajeed",
    "عبدالحكيم": "Abdulhakeem",
    "عبد الحكيم": "Abdulhakeem",
    "عبدالفتاح": "Abdulfattah",
    "عبد الفتاح": "Abdulfattah",
    "عبدالرزاق": "Abdulrazzaq",
    "عبد الرزاق": "Abdulrazzaq",
    "عبدالعليم": "Abdulaleem",
    "عبد العليم": "Abdulaleem",
    "عبدالحميد": "Abdulhameed",
    "عبد الحميد": "Abdulhameed",
    "عبدالقادر": "Abdulqadir",
    "عبد القادر": "Abdulqadir",
    "عبدالغفور": "Abdulghafur",
    "عبد الغفور": "Abdulghafur",
    "عبدالخالق": "Abdulkhaliq",
    "عبد الخالق": "Abdulkhaliq",
    "عبدالقدوس": "Abdulquddus",
    "عبد القدوس": "Abdulquddus",
    "عبدالهادي": "Abdulhadi",
    "عبد الهادي": "Abdulhadi",
    "عبدالباسط": "Abdulbasit",
    "عبد الباسط": "Abdulbasit",
    "عبدالجبار": "Abduljabbar",
    "عبد الجبار": "Abduljabbar",
    "عبدالمطلب": "Abdulmuttalib",
    "عبد المطلب": "Abdulmuttalib",
    "عبدالمنان": "Abdulmannan",
    "عبد المنان": "Abdulmannan",
    "عبدالحي": "Abdulhayy",
    "عبد الحي": "Abdulhayy",
    "عبدالقيوم": "Abdulqayyum",
    "عبد القيوم": "Abdulqayyum",
    "عبدالعظيم": "Abdulazeem",
    "عبد العظيم": "Abdulazeem",
    "عبدالغني": "Abdulghani",
    "عبد الغني": "Abdulghani",
    "عبدالواحد": "Abdulwahid",
    "عبد الواحد": "Abdulwahid",
    "عبدالأحد": "Abdulahad",
    "عبد الأحد": "Abdulahad",
    "عبدالستار": "Abdulsattar",
    "عبد الستار": "Abdulsattar",
    "عبدالصبور": "Abdulsaboor",
    "عبد الصبور": "Abdulsaboor",
    "عبدالباري": "Abdulbari",
    "عبد الباري": "Abdulbari",
    "عبدالرؤوف": "Abdulraouf",
    "عبد الرؤوف": "Abdulraouf",
    "عبدالإله": "Abdulilah",
    "عبد الإله": "Abdulilah",
    "عبدالاله": "Abdulilah",
    "عبد الاله": "Abdulilah",
    "عبدالمولى": "Abdulmawla",
    "عبد المولى": "Abdulmawla",
}

# ---------------------------------------------------------------------------
# 5. Dictionary of Known Proper Names, Concepts, Places & Benefactors
# ---------------------------------------------------------------------------
KNOWN_VOCABULARY = {
    # Prophets & Messengers
    "محمد": "Muhammad",
    "إبراهيم": "Ibrahim", "ابراهيم": "Ibrahim",
    "موسى": "Musa", "عيسى": "Isa", "نوح": "Nuh", "آدم": "Adam", "ادم": "Adam",
    "هود": "Hud", "صالح": "Salih", "لوط": "Lut",
    "إسماعيل": "Ismail", "اسماعيل": "Ismail",
    "إسحاق": "Ishaq", "اسحاق": "Ishaq",
    "يعقوب": "Yaqub", "يوسف": "Yusuf", "أيوب": "Ayyub", "ايوب": "Ayyub",
    "شعيب": "Shuaib", "هارون": "Harun", "داود": "Dawud", "داوود": "Dawud",
    "سليمان": "Sulaiman", "يونس": "Yunus", "إلياس": "Ilyas", "الياس": "Ilyas",
    "اليسع": "Al-Yasa", "زكريا": "Zakariya", "يحيى": "Yahya",

    # Companions (Sahabah) & Early Caliphs
    "أبو بكر": "Abu Bakr", "ابو بكر": "Abu Bakr",
    "أبو بكر الصديق": "Abu Bakr Al-Siddiq", "ابو بكر الصديق": "Abu Bakr Al-Siddiq",
    "بكر": "Bakr", "البكر": "Al-Bakr",
    "عمر": "Omar", "الخطاب": "Al-Khattab", "ابن الخطاب": "Ibn Al-Khattab",
    "عمر بن الخطاب": "Omar bin Al-Khattab",
    "عثمان": "Othman", "عفان": "Affan", "ابن عفان": "Ibn Affan",
    "عثمان بن عفان": "Othman bin Affan",
    "علي": "Ali", "طالب": "Talib", "أبي طالب": "Abi Talib", "ابي طالب": "Abi Talib",
    "علي بن أبي طالب": "Ali bin Abi Talib", "علي بن ابي طالب": "Ali bin Abi Talib",
    "خالد": "Khalid", "الوليد": "Al-Waleed", "وليد": "Waleed",
    "خالد بن الوليد": "Khalid bin Al-Waleed",
    "بلال": "Bilal", "رباح": "Rabah", "بلال بن رباح": "Bilal bin Rabah",
    "حمزة": "Hamza", "حمزة بن عبد المطلب": "Hamza bin Abdulmuttalib", "حمزة بن عبدالمطلب": "Hamza bin Abdulmuttalib",
    "سعد": "Saad", "سعيد": "Saeed",
    "سعد بن أبي وقاص": "Saad bin Abi Waqqas", "سعد بن ابي وقاص": "Saad bin Abi Waqqas",
    "وقاص": "Waqqas", "أبي وقاص": "Abi Waqqas", "ابي وقاص": "Abi Waqqas",
    "سعد بن معاذ": "Saad bin Muadh", "معاذ": "Muadh", "جبل": "Jabal",
    "معاذ بن جبل": "Muadh bin Jabal",
    "مصعب": "Musab", "عمير": "Umair", "مصعب بن عمير": "Musab bin Umair",
    "طلحة": "Talha", "عبيد الله": "Ubaidullah", "طلحة بن عبيد الله": "Talha bin Ubaidullah",
    "الزبير": "Al-Zubair", "العوام": "Al-Awwam", "الزبير بن العوام": "Al-Zubair bin Al-Awwam",
    "أبو عبيدة": "Abu Ubaidah", "ابو عبيدة": "Abu Ubaidah", "الجراح": "Al-Jarrah",
    "أبو عبيدة بن الجراح": "Abu Ubaidah bin Al-Jarrah",
    "أبو هريرة": "Abu Hurairah", "ابو هريرة": "Abu Hurairah",
    "أبو ذر": "Abu Dharr", "ابو ذر": "Abu Dharr", "أبي ذر": "Abu Dharr", "ابي ذر": "Abu Dharr",
    "الغفاري": "Al-Ghifari", "ذر": "Dharr",
    "أبو ذر الغفاري": "Abu Dharr Al-Ghifari", "ابو ذر الغفاري": "Abu Dharr Al-Ghifari",
    "أبي ذر الغفاري": "Abu Dharr Al-Ghifari", "ابي ذر الغفاري": "Abu Dharr Al-Ghifari",
    "سلمان": "Salman", "الفارسي": "Al-Farsi", "سلمان الفارسي": "Salman Al-Farsi",
    "صهيب": "Suhaib", "الرومي": "Al-Rumi", "صهيب الرومي": "Suhaib Al-Rumi",
    "عمار": "Ammar", "ياسر": "Yasser", "عمار بن ياسر": "Ammar bin Yasser",
    "حذيفة": "Hudhaifah", "اليمان": "Al-Yaman", "حذيفة بن اليمان": "Hudhaifah bin Al-Yaman",
    "أنس": "Anas", "انس": "Anas", "مالك": "Malik", "أنس بن مالك": "Anas bin Malik", "انس بن مالك": "Anas bin Malik",
    "أسامة": "Osama", "اسامة": "Osama", "زيد": "Zaid", "أسامة بن زيد": "Osama bin Zaid",
    "زيد بن حارثة": "Zaid bin Harithah", "حارثة": "Harithah",
    "زيد بن ثابت": "Zaid bin Thabit", "ثابت": "Thabit", "حسان": "Hassan",
    "حسان بن ثابت": "Hassan bin Thabit", "جعفر": "Jafar", "جعفر الطيار": "Jafar Al-Tayyar",
    "الحسن": "Al-Hassan", "حسن": "Hassan", "الحسين": "Al-Hussein", "حسين": "Hussein",
    "عبد الله بن عباس": "Abdullah bin Abbas", "ابن عباس": "Ibn Abbas", "عباس": "Abbas",
    "عبد الله بن عمر": "Abdullah bin Omar", "ابن عمر": "Ibn Omar",
    "عبد الله بن مسعود": "Abdullah bin Masud", "ابن مسعود": "Ibn Masud", "مسعود": "Masud",
    "عبدالله بن مسعود": "Abdullah bin Masud",
    "عبد الرحمن بن عوف": "Abdulrahman bin Awf", "عبدالرحمن بن عوف": "Abdulrahman bin Awf", "عوف": "Awf",
    "عمرو بن العاص": "Amr bin Al-Aas", "عمرو": "Amr", "العاص": "Al-Aas",
    "معاوية": "Muawiyah", "سفيان": "Sufyan", "أبي سفيان": "Abi Sufyan",
    "الأرقم": "Al-Arqam", "الارقم": "Al-Arqam",
    "القعقاع": "Al-Qa'qa", "عكاشة": "Ukashah", "عكرمة": "Ikrimah",
    "البراء": "Al-Bara", "تميم الداري": "Tamim Al-Dari",
    "طارق": "Tariq", "زياد": "Ziyad", "طارق بن زياد": "Tariq bin Ziyad",
    "المغيرة": "Al-Mughirah", "شعبة": "Shu'bah", "المغيرة بن شعبة": "Al-Mughirah bin Shu'bah",

    # Mothers of the Believers & Pious Women
    "خديجة": "Khadijah", "خديجة بنت خويلد": "Khadijah bint Khuwaylid",
    "عائشة": "Aisha", "فاطمة": "Fatima", "فاطمة الزهراء": "Fatima Al-Zahra",
    "الزهراء": "Al-Zahra",
    "مريم": "Maryam", "آسية": "Asiya", "اسية": "Asiya",
    "زينب": "Zainab", "رقية": "Ruqayyah", "حفصة": "Hafsah",
    "أم كلثوم": "Umm Kulthum", "ام كلثوم": "Umm Kulthum",
    "أم سلمة": "Umm Salamah", "ام سلمة": "Umm Salamah",
    "أسماء بنت أبي بكر": "Asma bint Abi Bakr", "أسماء": "Asma", "اسماء": "Asma",
    "سارة": "Sarah", "هاجر": "Hajar", "سمية": "Sumayyah",
    "الخنساء": "Al-Khansa",

    # Renowned Imams & Scholars
    "الشافعي": "Al-Shafi'i", "الإمام الشافعي": "Imam Al-Shafi'i", "الامام الشافعي": "Imam Al-Shafi'i",
    "أحمد بن حنبل": "Ahmad bin Hanbal", "احمد بن حنبل": "Ahmad bin Hanbal", "ابن حنبل": "Ibn Hanbal",
    "أبو حنيفة": "Abu Hanifa", "ابو حنيفة": "Abu Hanifa",
    "مالك بن أنس": "Malik bin Anas", "الإمام مالك": "Imam Malik",
    "البخاري": "Al-Bukhari", "الإمام البخاري": "Imam Al-Bukhari",
    "مسلم": "Muslim", "الإمام مسلم": "Imam Muslim",
    "النووي": "Al-Nawawi", "الطبري": "Al-Tabari", "القرطبي": "Al-Qurtubi",
    "ابن تيمية": "Ibn Taymiyyah", "ابن القيم": "Ibn Al-Qayyim",
    "ابن كثير": "Ibn Kathir", "ابن حجر": "Ibn Hajar",
    "محمد بن عبد الوهاب": "Muhammad bin Abdulwahhab", "محمد بن عبدالوهاب": "Muhammad bin Abdulwahhab",
    "ابن باز": "Ibn Baz", "بن باز": "bin Baz",
    "ابن عثيمين": "Ibn Uthaymeen", "الشنقيطي": "Al-Shanqiti",
    "الألباني": "Al-Albani", "الالباني": "Al-Albani",

    # Saudi Royal Family & Leaders
    "سعود": "Saud", "فيصل": "Faisal", "فهد": "Fahd",
    "سلطان": "Sultan", "نايف": "Nayef", "سلمان": "Salman",
    "تركي": "Turki", "بندر": "Bandar", "مشعل": "Mishaal",
    "مقرن": "Muqrin", "طلال": "Talal", "نواف": "Nawaf",
    "منصور": "Mansour", "مساعد": "Musaed", "أحمد": "Ahmad", "احمد": "Ahmad",
    "سطام": "Sattam", "متعب": "Mutaib", "ممدوح": "Mamdouh",
    "محمد بن سلمان": "Muhammad bin Salman",
    "محمد بن سعود": "Muhammad bin Saud",
    "تركي بن عبد الله": "Turki bin Abdullah", "تركي بن عبدالله": "Turki bin Abdullah",
    "عبد العزيز آل سعود": "Abdulaziz Al Saud", "عبدالعزيز آل سعود": "Abdulaziz Al Saud",
    "خالد الفيصل": "Khalid Al-Faisal", "سعود الفيصل": "Saud Al-Faisal",
    "تركي الفيصل": "Turki Al-Faisal",

    # Philanthropists, Benefactors & Stations
    "الراجحي": "Al-Rajhi", "سليمان الراجحي": "Sulaiman Al-Rajhi",
    "صالح الراجحي": "Saleh Al-Rajhi", "عائشة الراجحي": "Aisha Al-Rajhi",
    "الشربتلي": "Al-Sharbatly", "حسن الشربتلي": "Hassan Al-Sharbatly",
    "الكعكي": "Al-Kaaki", "بقشان": "Bugshan", "بن لادن": "Bin Laden",
    "العبيكان": "Al-Obeikan", "الدخيل": "Al-Dakheel",
    "الموسى": "Al-Mousa", "الجفالي": "Al-Juffali",
    "الدريس": "Al-Drees", "دريس": "Drees", "الساسكو": "Sasco", "ساسكو": "Sasco",
    "السهلي": "Al-Sahli", "النفيعي": "Al-Nufaie", "العمري": "Al-Omari",

    # Historic Places, Battles, Landmarks & Concepts
    "قباء": "Quba", "القبلتين": "Al-Qiblatain", "الخيف": "Al-Khaif", "نمرة": "Namirah",
    "المشعر الحرام": "Al-Mash'ar Al-Haram", "التنعيم": "Al-Taneem", "البيعة": "Al-Baya'ah",
    "بدر": "Badr", "أحد": "Uhud", "احد": "Uhud", "حنين": "Hunain",
    "تبوك": "Tabuk", "خيبر": "Khaibar", "الخندق": "Al-Khandaq", "مؤتة": "Mutah",
    "اليرموك": "Al-Yarmouk", "القادسية": "Al-Qadisiyyah", "حطين": "Hittin",
    "عين جالوت": "Ain Jalut",
    "الصفا": "Al-Safa", "المروة": "Al-Marwah", "زمزم": "Zamzam",
    "حراء": "Hira", "ثور": "Thawr", "الطور": "Al-Toor",
    "طيبة": "Taybah", "يثرب": "Yathrib",
    "مكة": "Makkah", "المدينة": "Al-Madinah", "القدس": "Al-Quds", "الأقصى": "Al-Aqsa", "الاقصى": "Al-Aqsa",
    "الأندلس": "Al-Andalus", "الاندلس": "Al-Andalus", "قرطبة": "Cordoba", "غرناطة": "Granada",
    "الوادي": "Al-Wadi", "النخيل": "Al-Nakheel", "الحارة": "Al-Harah", "الحاره": "Al-Harah",
    "الصناعية": "Al-Sina'iyah", "صناعية": "Al-Sina'iyah",

    # Islamic Concepts & Virtues
    "الهدى": "Al-Huda", "التقوى": "Al-Taqwa", "الفتح": "Al-Fath",
    "الإخلاص": "Al-Ikhlas", "الاخلاص": "Al-Ikhlas",
    "الفردوس": "Al-Firdaws", "الكوثر": "Al-Kawthar", "الريان": "Al-Rayyan",
    "التوحيد": "Al-Tawhid", "البركة": "Al-Barakah", "الفرقان": "Al-Furqan",
    "الإيمان": "Al-Iman", "الايمان": "Al-Iman",
    "الإحسان": "Al-Ihsan", "الاحسان": "Al-Ihsan",
    "الجمعة": "Al-Jummah", "العيد": "Al-Eid",
    "الوالدين": "Al-Walidayn", "بر الوالدين": "Birr Al-Walidayn",
    "الخير": "Al-Khair", "خير": "Khair",
    "البر": "Al-Birr", "بر": "Birr",
    "الرحمة": "Al-Rahmah", "رحمة": "Rahmah", "الرحمه": "Al-Rahmah",
    "المغفرة": "Al-Maghfirah", "الرضوان": "Al-Ridwan", "رضوان": "Ridwan",
    "النعيم": "Al-Naeem", "الجنة": "Al-Jannah", "الفلاح": "Al-Falah",
    "الصالحين": "Al-Salihin", "المتقين": "Al-Muttaqin", "المحسنين": "Al-Muhsinin",
    "الصابرين": "Al-Sabirin", "المهاجرين": "Al-Muhajirin", "الأنصار": "Al-Ansar", "الانصار": "Al-Ansar",
    "الأبرار": "Al-Abrar", "الابرار": "Al-Abrar",
    "عباد الرحمن": "Ibad Al-Rahman", "رياض الصالحين": "Riyad Al-Salihin",
    "الصحابة": "Al-Sahabah", "الضياء": "Al-Diya", "ضياء": "Diya",
    "البينة": "Al-Bayyinah", "البيان": "Al-Bayan", "الهداية": "Al-Hidayah",
    "الأمان": "Al-Aman", "الامان": "Al-Aman", "السكينة": "Al-Sakinah",
    "التعاون": "Al-Taawun", "التوبة": "Al-Tawbah", "الاستقامة": "Al-Istiqamah",
    "المحطة": "Al-Mahattah", "محطة": "Al-Mahattah", "الحي": "Al-Hayy", "السوق": "Al-Souq",
    "النصر": "Al-Nasr", "العزة": "Al-Izzah", "الكرامة": "Al-Karamah", "المجد": "Al-Majd",
    "الحمد": "Al-Hamd", "الأعلى": "Al-A'la", "الاعلى": "Al-A'la",
    "خليل": "Khalil", "توفيق": "Tawfiq", "محمود": "Mahmoud",

    # Generic or Descriptive Tags often in OSM
    "أهلي": "Ahli", "اهلي": "Ahli",
    "محلي": "Local",
    "مؤقت": "Temporary",
    "صغير": "Small",
    "كبير": "Grand",
    "الكبير": "Al-Kabeer",
    "رجال": "Men", "الرجال": "Men",
    "نساء": "Women", "النساء": "Women",

    # Endowments, Family Relations & Historic Figures
    "والدة": "Walidat", "والد": "Walid",
    "صلاح الدين": "Salah Al-Din", "الأيوبي": "Al-Ayyubi",
    "صلاح الدين الأيوبي": "Salah Al-Din Al-Ayyubi",
    "أويس القرني": "Owais Al-Qarni", "أويس": "Owais",
    "الهجرة": "Al-Hijrah", "هجرة": "Hijrah",
    "البابطين": "Al-Babtain", "بابطين": "Babtain",
    "السدحان": "Al-Sadhan", "الشميسي": "Al-Shemaisi",
    "الفوطة": "Al-Foutah", "الغنام": "Al-Ghannam",
    "المبيريك": "Al-Mubaireek", "السبعان": "Al-Sabaan",
    "المرشد": "Al-Murshid", "الحديقة": "Al-Hadeeqah",
    "جسر الملك فهد": "King Fahd Causeway",
    "جسر": "Bridge",

    # Major Saudi Tribes & Surnames
    "القحطاني": "Al-Qahtani", "قحطان": "Qahtan",
    "السبيعي": "Al-Subaie", "سبيع": "Subaie",
    "العتيبي": "Al-Otaibi", "عتيبة": "Otaibah",
    "الدوسري": "Al-Dossari", "دوسر": "Dossari",
    "الغامدي": "Al-Ghamdi", "غامد": "Ghamd",
    "الزهراني": "Al-Zahrani", "زهران": "Zahran",
    "الحربي": "Al-Harbi", "حرب": "Harb",
    "المطيري": "Al-Mutairi", "مطير": "Mutair",
    "الشهري": "Al-Shehri", "بني شهر": "Bani Shehr",
    "القرني": "Al-Qarni", "بلقرن": "Balqarn",
    "العسيري": "Al-Asiri", "عسير": "Asir",
    "المالكي": "Al-Malki", "بني مالك": "Bani Malik",
    "الشمري": "Al-Shammari", "شمر": "Shammar",
    "العنزي": "Al-Anazi", "عنزة": "Anazah",
    "الخالدي": "Al-Khalidi", "بني خالد": "Bani Khalid",
    "البقمي": "Al-Baqami", "السلمي": "Al-Sulami",
    "الجهني": "Al-Juhani", "البلوي": "Al-Balawi",
    "الحازمي": "Al-Hazmi", "التميمي": "Al-Tamimi",
}

WAW_ROOT_STARTS = ("والد", "وائل", "واحة", "واسط", "وافي", "واصل", "وادي", "وقاص", "وجدي", "وحيد", "وديع", "وردة", "وفاء", "وثيق")

# ---------------------------------------------------------------------------
# 6. Character Transliteration Table (UNGEGN / GASGI Standard)
# ---------------------------------------------------------------------------
CHAR_MAP = {
    "ء": "'", "أ": "A", "إ": "I", "آ": "Aa", "ٱ": "A", "ا": "a",
    "ب": "b", "ت": "t", "ث": "th", "ج": "j", "ح": "h", "خ": "kh",
    "د": "d", "ذ": "dh", "ر": "r", "ز": "z", "س": "s", "ش": "sh",
    "ص": "s", "ض": "d", "ط": "t", "ظ": "dh", "ع": "a", "غ": "gh",
    "ف": "f", "ق": "q", "ك": "k", "ل": "l", "م": "m", "ن": "n",
    "ه": "h", "و": "w", "ي": "y", "ى": "a", "ة": "ah", "ؤ": "'", "ئ": "'"
}

_RE_TASHKEEL = re.compile(r"[ً-ٰٟ]")
_RE_TATWEEL = re.compile(r"ـ")


def clean_arabic(text: str) -> str:
    """Removes diacritics, tatweel, pious eulogies, and normalizes spacing."""
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", str(text).strip())
    s = _RE_TASHKEEL.sub("", s)
    s = _RE_TATWEEL.sub("", s)

    # Normalize medial alef maqsura (Persian/Urdu keyboard typo) to yaa
    s = re.sub(r"ى(?=[ء-ي])", "ي", s)

    # Remove pious eulogies
    for eulogy_re in EULOGIES:
        s = eulogy_re.sub("", s)

    return re.sub(r"\s+", " ", s).strip()


def reconstruct_arabic_morphology(stem: str) -> str:
    """
    Applies Arabic morphological pattern rules (علم الصرف) to correctly
    vowelize trilateral / quadrilateral patterns for Out-Of-Vocabulary words.
    """
    n = len(stem)
    if n < 3:
        return "".join(CHAR_MAP.get(c, c) for c in stem).capitalize()

    # 1. Pattern تَفْعِيل (Taf'eel / Taf'il): e.g. توفيق (Tawfiq), تيسير (Tayseer), تحسين (Tahseen)
    if n == 5 and stem.startswith("ت") and stem[3] == "ي":
        c1 = CHAR_MAP.get(stem[1], stem[1])
        c2 = CHAR_MAP.get(stem[2], stem[2])
        c3 = CHAR_MAP.get(stem[4], stem[4])
        if stem[1] == "و":
            return f"Taw{c2}iq" if stem[4] == "ق" else f"Taw{c2}id"
        return f"Ta{c1}{c2}in" if stem[4] == "ن" else f"Ta{c1}{c2}eer"

    # 2. Pattern مَفْعُول (Maf'oul): e.g. محمود (Mahmoud), منصور (Mansour), مسرور (Masrour)
    if n == 5 and stem.startswith("م") and stem[3] == "و":
        c1 = CHAR_MAP.get(stem[1], stem[1])
        c2 = CHAR_MAP.get(stem[2], stem[2])
        c3 = CHAR_MAP.get(stem[4], stem[4])
        return f"Ma{c1}{c2}ou{c3}".capitalize()

    # 3. Pattern فَعِيل (Fa'eel / Fa'il): e.g. كريم (Karim), خليل (Khalil), لطيف (Latif), جميل (Jamil), سعيد (Saeed), حكيم (Hakeem), عظيم (Azeem), شهيد (Shaheed)
    if n == 4 and stem[2] == "ي":
        c1 = CHAR_MAP.get(stem[0], stem[0])
        c2 = CHAR_MAP.get(stem[1], stem[1])
        c3 = CHAR_MAP.get(stem[3], stem[3])
        return f"{c1}a{c2}i{c3}".capitalize()

    # 4. Pattern فَعُول (Fa'oul): e.g. صبور (Sabour), شكور (Shakour), غفور (Ghafour)
    if n == 4 and stem[2] == "و":
        c1 = CHAR_MAP.get(stem[0], stem[0])
        c2 = CHAR_MAP.get(stem[1], stem[1])
        c3 = CHAR_MAP.get(stem[3], stem[3])
        return f"{c1}a{c2}ou{c3}".capitalize()

    # 5. Pattern فَاعِل (Fa'il): e.g. صالح (Salih), طارق (Tariq), ناصر (Nasir), ماجد (Majid), ثابت (Thabit), سالم (Salim)
    if n == 4 and stem[1] == "ا":
        c1 = CHAR_MAP.get(stem[0], stem[0])
        c2 = CHAR_MAP.get(stem[2], stem[2])
        c3 = CHAR_MAP.get(stem[3], stem[3])
        return f"{c1}a{c2}i{c3}".capitalize()

    # 6. Pattern فَعْلَان (Fa'lan): e.g. عمران (Imran), عدنان (Adnan), حمدان (Hamdan), رضوان (Ridwan)
    if n >= 5 and stem.endswith("ان"):
        prefix = stem[:-2]
        if len(prefix) == 3:
            c1 = CHAR_MAP.get(prefix[0], prefix[0])
            c2 = CHAR_MAP.get(prefix[1], prefix[1])
            c3 = CHAR_MAP.get(prefix[2], prefix[2])
            return f"{c1}a{c2}{c3}an".capitalize()

    # 7. Pattern فَعِيلَة (Fa'eelah / Taybah): e.g. طيبة (Taybah), جميلة (Jameelah), كريمة (Karimah)
    if n == 5 and stem[2] == "ي" and stem.endswith(("ة", "ه")):
        c1 = CHAR_MAP.get(stem[0], stem[0])
        c2 = CHAR_MAP.get(stem[1], stem[1])
        return f"{c1}a{c2}bah" if stem[3] == "ب" else f"{c1}a{c2}ee{CHAR_MAP.get(stem[3], stem[3])}ah".capitalize()

    # 8. Pattern فَعْل (Fa'l / Triliteral Root): e.g. بدر (Badr), فهد (Fahd), سعد (Saad), حمد (Hamad), نصر (Nasr)
    if n == 3:
        c1 = CHAR_MAP.get(stem[0], stem[0])
        c2 = CHAR_MAP.get(stem[1], stem[1])
        c3 = CHAR_MAP.get(stem[2], stem[2])
        if stem[1] in ("ا", "و", "ي"):
            vowel = "a" if stem[1] == "ا" else ("ou" if stem[1] == "و" else "i")
            return f"{c1}{vowel}{c3}".capitalize()
        if stem == "أحد" or stem == "احد":
            return "Uhud"
        return f"{c1}a{c2}{c3}".capitalize()

    # Fallback letter-by-letter with vowel awareness
    out = []
    i = 0
    while i < n:
        c = stem[i]
        if c == "و" and 0 < i < n - 1 and stem[i-1] not in ("ا", "و", "ي") and stem[i+1] not in ("ا", "و", "ي"):
            out.append("ou")
        elif c == "ي" and 0 < i < n - 1 and stem[i-1] not in ("ا", "و", "ي") and stem[i+1] not in ("ا", "و", "ي"):
            out.append("i")
        elif c == "ي" and i == n - 1:
            out.append("i")
        elif c in CHAR_MAP:
            out.append(CHAR_MAP[c])
        else:
            out.append(c)
        i += 1

    return "".join(out).capitalize()


def transliterate_word(word: str) -> str:
    """Transliterates a single Arabic word according to UNGEGN / GASGI standards."""
    if not word:
        return ""

    if word in KNOWN_VOCABULARY:
        return KNOWN_VOCABULARY[word]
    if word in DIVINE_NAMES:
        return DIVINE_NAMES[word]
    if word in ABD_SPECIAL:
        return ABD_SPECIAL[word]
    if word in HONORIFICS_MAP:
        return HONORIFICS_MAP[word]
    if word in PATRONYMICS:
        return PATRONYMICS[word]

    # Orthographic variants: taa marbuta / haa
    if word.endswith("ه") and (word[:-1] + "ة") in KNOWN_VOCABULARY:
        return KNOWN_VOCABULARY[word[:-1] + "ة"]
    if word.endswith("ة") and (word[:-1] + "ه") in KNOWN_VOCABULARY:
        return KNOWN_VOCABULARY[word[:-1] + "ه"]

    has_al = False
    stem = word
    if word.startswith("ال") and len(word) > 3:
        has_al = True
        stem = word[2:]

    if stem in KNOWN_VOCABULARY:
        res = KNOWN_VOCABULARY[stem]
        return f"Al-{res}" if has_al and not res.startswith("Al-") else res
    if stem in DIVINE_NAMES:
        res = DIVINE_NAMES[stem]
        return f"Al-{res}" if has_al and not res.startswith("Al-") else res

    # Check normalized alef variants
    norm_stem = stem.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    if norm_stem in KNOWN_VOCABULARY:
        res = KNOWN_VOCABULARY[norm_stem]
        return f"Al-{res}" if has_al and not res.startswith("Al-") else res

    # Check taa marbuta variants on stem
    if norm_stem.endswith("ه") and (norm_stem[:-1] + "ة") in KNOWN_VOCABULARY:
        res = KNOWN_VOCABULARY[norm_stem[:-1] + "ة"]
        return f"Al-{res}" if has_al and not res.startswith("Al-") else res

    reconstructed = reconstruct_arabic_morphology(stem)
    if has_al:
        return f"Al-{reconstructed}"
    return reconstructed


def classify_mosque_type(name: str) -> str:
    """
    Classifies mosque type from Arabic name:
    'jamea' (Grand Mosque / Friday prayers),
    'mosque' (Standard 5-time neighborhood mosque),
    'musalla' (Prayer room, seasonal or transit facility),
    'non_religious' (False positive entity like schools/hospitals).
    """
    cleaned = clean_arabic(name)
    words = cleaned.split()
    if not words:
        return "mosque"

    non_religious_terms = {"مدرسة", "جامعة", "كلية", "مستشفى", "مستوصف", "جمعية", "نادي", "مؤسسة"}
    if any(w in non_religious_terms for w in words):
        return "non_religious"

    first = words[0]
    if first == "جامع" or "الجامع" in words:
        return "jamea"
    if first in ("مصلى", "مصلّى", "المصلى") or "مصلى" in words:
        return "musalla"
    return "mosque"


def transliterate_mosque_name(arabic_name: str) -> dict:
    """
    Translates/transliterates an Arabic mosque name to English according to
    Saudi Geographic Naming Standards (UNGEGN/GASGI).

    Examples:
      - 'جامع الملك فهد' -> 'King Fahd Grand Mosque'
      - 'مسجد التقوى' -> 'Al-Taqwa Mosque'
      - 'جامع الشيخ عبد العزيز الراجحي' -> 'Sheikh Abdulaziz Al-Rajhi Grand Mosque'
      - 'مسجد بلال بن رباح' -> 'Bilal bin Rabah Mosque'
      - 'مصلى العيد' -> 'Al-Eid Musalla'
      - 'مسجد الهدى والتقوى' -> 'Al-Huda and Al-Taqwa Mosque'
      - 'مسجد عمر بن الخطاب رضي الله عنه' -> 'Omar bin Al-Khattab Mosque'

    Returns:
      {
        'name_ar': str,
        'name_en': str,
        'type': 'jamea' | 'mosque' | 'musalla' | 'non_religious',
        'confidence': float (0.0 to 1.0)
      }
    """
    cleaned = clean_arabic(arabic_name)
    if not cleaned:
        return {"name_ar": "", "name_en": "", "type": "mosque", "confidence": 0.0}

    mosque_type = classify_mosque_type(cleaned)
    if mosque_type == "non_religious":
        return {"name_ar": cleaned, "name_en": "", "type": "non_religious", "confidence": 0.0}

    tokens = cleaned.split()
    first_word = tokens[0]

    # Determine mosque title suffix
    suffix = "Mosque"
    if first_word in TITLE_MAP:
        suffix = TITLE_MAP[first_word]
        name_tokens = tokens[1:]
    elif tokens[0] in ("جامع", "مسجد", "مصلى", "مصلّى", "روضة"):
        suffix = TITLE_MAP.get(tokens[0], "Mosque")
        name_tokens = tokens[1:]
    else:
        suffix = "Grand Mosque" if mosque_type == "jamea" else "Mosque"
        name_tokens = tokens

    # If the name is solely 'مسجد' or 'جامع' with no further tokens
    if not name_tokens:
        return {"name_ar": cleaned, "name_en": suffix, "type": mosque_type, "confidence": 0.5}

    # Pre-process tokens: split conjunction 'و' attached to words (excluding words with root 'و')
    split_tokens = []
    for t in name_tokens:
        if t.startswith("و") and not any(t.startswith(p) for p in WAW_ROOT_STARTS):
            if len(t) > 3 and (t.startswith("وال") or t.startswith("وإ") or t.startswith("وأ")):
                split_tokens.append("and")
                split_tokens.append(t[1:])
            elif t == "و":
                split_tokens.append("and")
            else:
                split_tokens.append(t)
        else:
            split_tokens.append(t)

    name_tokens = split_tokens
    processed_parts = []
    i = 0
    num_known = 0
    total_tokens = len(name_tokens)

    while i < len(name_tokens):
        current = name_tokens[i]

        if current == "and":
            processed_parts.append("and")
            num_known += 1
            i += 1
            continue

        # Check 4-token phrases
        if i + 3 < len(name_tokens):
            four_word = f"{current} {name_tokens[i+1]} {name_tokens[i+2]} {name_tokens[i+3]}"
            if four_word in HONORIFICS_MAP:
                processed_parts.append(HONORIFICS_MAP[four_word])
                num_known += 4
                i += 4
                continue

        # Check 3-token phrases
        if i + 2 < len(name_tokens):
            three_word = f"{current} {name_tokens[i+1]} {name_tokens[i+2]}"
            if three_word in HONORIFICS_MAP:
                processed_parts.append(HONORIFICS_MAP[three_word])
                num_known += 3
                i += 3
                continue
            if three_word in KNOWN_VOCABULARY:
                processed_parts.append(KNOWN_VOCABULARY[three_word])
                num_known += 3
                i += 3
                continue

        # Check 2-token compound phrases
        if i + 1 < len(name_tokens):
            two_word = f"{current} {name_tokens[i+1]}"
            if two_word in ABD_SPECIAL:
                processed_parts.append(ABD_SPECIAL[two_word])
                num_known += 2
                i += 2
                continue
            if two_word in HONORIFICS_MAP:
                processed_parts.append(HONORIFICS_MAP[two_word])
                num_known += 2
                i += 2
                continue
            if two_word in KNOWN_VOCABULARY:
                processed_parts.append(KNOWN_VOCABULARY[two_word])
                num_known += 2
                i += 2
                continue

        # Check compound "عبد" + Name
        if current in ("عبد", "العبد") and i + 1 < len(name_tokens):
            next_word = name_tokens[i+1]
            if next_word in ABD_MAP:
                processed_parts.append(ABD_MAP[next_word])
                num_known += 2
                i += 2
                continue
            core = next_word[2:] if next_word.startswith("ال") else next_word
            trans_core = transliterate_word(core)
            processed_parts.append(f"Abdul{trans_core.lower()}")
            num_known += 2
            i += 2
            continue

        # Single word lookups
        if current in ABD_SPECIAL:
            processed_parts.append(ABD_SPECIAL[current])
            num_known += 1
        elif current in HONORIFICS_MAP:
            processed_parts.append(HONORIFICS_MAP[current])
            num_known += 1
        elif current in PATRONYMICS:
            patron = PATRONYMICS[current]
            if patron == "bin" and not processed_parts:
                patron = "Bin"
            processed_parts.append(patron)
            num_known += 1
        elif current in KNOWN_VOCABULARY:
            processed_parts.append(KNOWN_VOCABULARY[current])
            num_known += 1
        elif current in DIVINE_NAMES:
            processed_parts.append(DIVINE_NAMES[current])
            num_known += 1
        else:
            trans = transliterate_word(current)
            processed_parts.append(trans)
            if trans and not any(ord(c) > 127 for c in trans):
                num_known += 0.85

        i += 1

    core_name = " ".join(processed_parts).strip()

    # Special handling for musalla with men / women
    if suffix == "Musalla":
        if "Men" in core_name:
            full_name_en = core_name.replace("Men", "Men's Musalla").strip()
            return {"name_ar": cleaned, "name_en": full_name_en, "type": mosque_type, "confidence": 0.98}
        if "Women" in core_name:
            full_name_en = core_name.replace("Women", "Women's Musalla").strip()
            return {"name_ar": cleaned, "name_en": full_name_en, "type": mosque_type, "confidence": 0.98}

    if any(core_name.lower().endswith(s.lower()) for s in ("Mosque", "Grand Mosque", "Musalla", "Rawdah", "Complex", "Center")):
        full_name_en = core_name
    elif suffix.lower() not in core_name.lower():
        full_name_en = f"{core_name} {suffix}".strip()
    else:
        full_name_en = core_name.strip()

    ratio = num_known / max(total_tokens, 1)
    if ratio >= 0.95:
        confidence = 0.98
    elif ratio >= 0.80:
        confidence = 0.95
    elif ratio >= 0.60:
        confidence = 0.88
    else:
        confidence = max(0.60, round(ratio, 2))

    return {
        "name_ar": cleaned,
        "name_en": full_name_en,
        "type": mosque_type,
        "confidence": confidence,
    }
