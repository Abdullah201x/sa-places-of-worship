import json
import os
import subprocess
import sys
import pytest

root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(root, "backend"))

from app.transliteration import transliterate_mosque_name, classify_mosque_type

TEST_NAMES = [
    # Royal & Leadership
    "جامع الملك فهد",
    "جامع الملك سلمان بن عبدالعزيز",
    "جامع خادم الحرمين الشريفين",
    "مسجد الأمير سلطان بن عبد العزيز",
    "مسجد الملك فيصل",
    "مسجد الأمير نايف",
    "جامع الملك عبد الله",
    "مسجد الأمير مقرن بن عبد العزيز",
    
    # Companions & Caliphs
    "مسجد بلال بن رباح",
    "مسجد أبو بكر الصديق",
    "مسجد عمر بن الخطاب",
    "مسجد عثمان بن عفان",
    "مسجد علي بن أبي طالب",
    "مسجد خالد بن الوليد",
    "مسجد سعد بن أبي وقاص",
    "مسجد أبي ذر الغفاري",
    "مسجد ذي النورين",
    "مسجد حمزة بن عبد المطلب",
    "مسجد معاذ بن جبل",
    "مسجد مصعب بن عمير",
    "مسجد عمار بن ياسر",
    "مسجد سلمان الفارسي",
    "مسجد طلحة بن عبيد الله",
    "مسجد الزبير بن العوام",
    
    # Pious Eulogies (Parenthesized & Bare)
    "مسجد عمر بن الخطاب (رضي الله عنه)",
    "مسجد علي بن أبي طالب (كرم الله وجهه)",
    "جامع الملك عبد الله (رحمه الله)",
    "مسجد عمر بن الخطاب رضي الله عنه",
    "مسجد علي بن أبي طالب كرم الله وجهه",
    "جامع الملك عبد الله رحمه الله",
    "مسجد عائشة (رضي الله عنها)",
    "مسجد فاطمة الزهراء (رضي الله عنها)",
    
    # Divine Names & Abdul- compounds
    "مسجد التقوى",
    "جامع الراجحي",
    "جامع عبد اللطيف",
    "جامع عبد الصمد",
    "جامع عبد الوهاب",
    "جامع عبد المحسن",
    "جامع عبد الرحمن",
    "مسجد عبد العزيز",
    "مسجد عبد الكريم",
    "مسجد عبد السلام",
    "مسجد عبد الملك",
    "مسجد عبد الحكيم",
    "مسجد عبد الباسط",
    "مسجد عبد الجبار",
    "مسجد عبد الغفور",
    
    # Conjunctions & Root Waw
    "مسجد الهدى والتقوى",
    "مسجد الصفا والمروة",
    "مسجد النور والضياء",
    "مسجد والدة عبدالله المرشد",
    "مسجد وائل بن حجر",
    "مسجد واحة الإيمان",
    
    # Musallas & Types
    "مصلى العيد",
    "مصلى رجال",
    "مصلى نساء",
    "روضة الأبرار",
    "مجمع الصالحين",
    "مركز التوحيد",
    
    # Morphological Patterns & Historical Places
    "مسجد توفيق",
    "مسجد محمود",
    "مسجد منصور",
    "مسجد صبور",
    "مسجد كريم",
    "مسجد بدر",
    "مسجد فهد",
    "مسجد أحد",
    "مسجد طيبة",
    "مسجد حطين",
    "مسجد اليرموك",
    "مسجد القادسية",
    "مسجد الأندلس",
    "مسجد خيبر",
    "مسجد قباء",
    "مسجد القبلتين",
    
    # Non-Religious (False Positives to suppress)
    "مدرسة ابن خلدون",
    "مستشفى الملك فيصل",
    "جامعة الملك سعود",
    "كلية الشريعة",
    "جمعية البر الخيرية",
    "نادي الشباب",
    "مؤسسة الراجحي الخيرية",
    "شارع مسجد قباء",
    "مقبرة الشهداء"
]


def run_node_transliterations(names: list[str]) -> dict[str, str]:
    """Runs the JavaScript transliteration engine in Node and returns {name_ar: name_en}."""
    js_code = """
    import { ArabicText } from './frontend/src/arabic.js';
    import fs from 'fs';

    const inputData = fs.readFileSync(0, 'utf-8');
    const names = JSON.parse(inputData);
    const results = {};
    for (const name of names) {
        results[name] = ArabicText.suggestEnglishName(name);
    }
    process.stdout.write(JSON.stringify(results));
    """
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", js_code],
        input=json.dumps(names, ensure_ascii=False),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        cwd=root,
        check=True
    )
    return json.loads(proc.stdout)


def test_python_node_transliteration_parity():
    """Verifies that Python and JS engines produce identical English names for all test vectors."""
    node_results = run_node_transliterations(TEST_NAMES)
    
    mismatches = []
    for name in TEST_NAMES:
        py_res = transliterate_mosque_name(name)["name_en"]
        node_res = node_results.get(name, "")
        if py_res != node_res:
            mismatches.append(f"Name '{name}': Python='{py_res}' vs Node='{node_res}'")
            
    assert not mismatches, "\n".join(mismatches)


def test_parenthesized_eulogy_stripping():
    """Verifies parenthesized eulogies are cleanly stripped without empty parens in both."""
    sample = "مسجد عمر بن الخطاب (رضي الله عنه)"
    py_res = transliterate_mosque_name(sample)
    assert py_res["name_en"] == "Omar bin Al-Khattab Mosque"
    assert "()" not in py_res["name_en"]
    assert "(" not in py_res["name_en"]

    sample2 = "جامع الملك عبد الله (رحمه الله)"
    py_res2 = transliterate_mosque_name(sample2)
    assert py_res2["name_en"] == "King Abdullah Grand Mosque"
    assert "()" not in py_res2["name_en"]


def test_non_religious_suppression():
    """Verifies non-religious civic infrastructure returns empty string in both."""
    non_religious = ["مدرسة ابن خلدون", "مستشفى الملك فيصل", "شارع مسجد قباء"]
    for name in non_religious:
        py_res = transliterate_mosque_name(name)
        assert py_res["name_en"] == "", f"Expected empty for '{name}', got '{py_res['name_en']}'"
        assert py_res["type"] == "non_religious"
