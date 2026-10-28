import os
import sys
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from app.main import app
from app.transliteration import transliterate_mosque_name, classify_mosque_type


def test_classify_mosque_type():
    assert classify_mosque_type("جامع الملك فهد") == "jamea"
    assert classify_mosque_type("مسجد الهدى") == "mosque"
    assert classify_mosque_type("مصلى العيد") == "musalla"
    assert classify_mosque_type("مدرسة ابن خلدون") == "non_religious"
    assert classify_mosque_type("مستشفى الملك فيصل") == "non_religious"


def test_transliterate_royal_mosques():
    res1 = transliterate_mosque_name("جامع الملك فهد")
    assert res1["name_en"] == "King Fahd Grand Mosque"
    assert res1["type"] == "jamea"
    assert res1["confidence"] >= 0.90

    res2 = transliterate_mosque_name("مسجد الأمير سلطان بن عبد العزيز")
    assert "Prince Sultan bin Abdulaziz Mosque" in res2["name_en"]
    assert res2["type"] == "mosque"

    res_custodian = transliterate_mosque_name("جامع خادم الحرمين الشريفين")
    assert res_custodian["name_en"] == "Custodian of the Two Holy Mosques Grand Mosque"
    assert res_custodian["confidence"] >= 0.95

    res_salman = transliterate_mosque_name("جامع الملك سلمان بن عبدالعزيز")
    assert res_salman["name_en"] == "King Salman bin Abdulaziz Grand Mosque"


def test_transliterate_divine_attributes_and_abdul():
    res = transliterate_mosque_name("مسجد التقوى")
    assert res["name_en"] == "Al-Taqwa Mosque"

    res_rahji = transliterate_mosque_name("جامع الراجحي")
    assert res_rahji["name_en"] == "Al-Rajhi Grand Mosque"

    res_latif = transliterate_mosque_name("جامع عبد اللطيف")
    assert res_latif["name_en"] == "Abdullatif Grand Mosque"

    res_samad = transliterate_mosque_name("جامع عبد الصمد")
    assert res_samad["name_en"] == "Abdulsamad Grand Mosque"

    res_wahhab = transliterate_mosque_name("جامع عبد الوهاب")
    assert res_wahhab["name_en"] == "Abdulwahhab Grand Mosque"

    res_mohsen = transliterate_mosque_name("جامع عبد المحسن")
    assert res_mohsen["name_en"] == "Abdulmohsen Grand Mosque"


def test_transliterate_companions_and_caliphs():
    res = transliterate_mosque_name("مسجد بلال بن رباح")
    assert res["name_en"] == "Bilal bin Rabah Mosque"

    res_bakr = transliterate_mosque_name("مسجد أبو بكر الصديق")
    assert res_bakr["name_en"] == "Abu Bakr Al-Siddiq Mosque"

    res_omar = transliterate_mosque_name("مسجد عمر بن الخطاب")
    assert res_omar["name_en"] == "Omar bin Al-Khattab Mosque"

    res_othman = transliterate_mosque_name("مسجد عثمان بن عفان")
    assert res_othman["name_en"] == "Othman bin Affan Mosque"

    res_ali = transliterate_mosque_name("مسجد علي بن أبي طالب")
    assert res_ali["name_en"] == "Ali bin Abi Talib Mosque"

    res_khalid = transliterate_mosque_name("مسجد خالد بن الوليد")
    assert res_khalid["name_en"] == "Khalid bin Al-Waleed Mosque"

    res_saad = transliterate_mosque_name("مسجد سعد بن أبي وقاص")
    assert res_saad["name_en"] == "Saad bin Abi Waqqas Mosque"

    res_dharr = transliterate_mosque_name("مسجد أبي ذر الغفاري")
    assert res_dharr["name_en"] == "Abu Dharr Al-Ghifari Mosque"

    res_nurayn = transliterate_mosque_name("مسجد ذي النورين")
    assert res_nurayn["name_en"] == "Dhu Al-Nurayn Mosque"


def test_transliterate_pious_eulogies_stripped():
    res_omar_eulogy = transliterate_mosque_name("مسجد عمر بن الخطاب رضي الله عنه")
    assert res_omar_eulogy["name_en"] == "Omar bin Al-Khattab Mosque"
    assert res_omar_eulogy["confidence"] >= 0.95

    res_ali_eulogy = transliterate_mosque_name("مسجد علي بن أبي طالب كرم الله وجهه")
    assert res_ali_eulogy["name_en"] == "Ali bin Abi Talib Mosque"

    res_abdullah_eulogy = transliterate_mosque_name("جامع الملك عبد الله رحمه الله")
    assert res_abdullah_eulogy["name_en"] == "King Abdullah Grand Mosque"


def test_transliterate_conjunctions():
    res_huda_taqwa = transliterate_mosque_name("مسجد الهدى والتقوى")
    assert res_huda_taqwa["name_en"] == "Al-Huda and Al-Taqwa Mosque"

    res_safa_marwa = transliterate_mosque_name("مسجد الصفا والمروة")
    assert res_safa_marwa["name_en"] == "Al-Safa and Al-Marwah Mosque"

    res_noor_diya = transliterate_mosque_name("مسجد النور والضياء")
    assert res_noor_diya["name_en"] == "Al-Noor and Al-Diya Mosque"

    # Waw as root letter, NOT a conjunction
    res_walidah = transliterate_mosque_name("مسجد والدة عبدالله المرشد")
    assert "Walidat Abdullah Al-Murshid Mosque" in res_walidah["name_en"]
    assert "and" not in res_walidah["name_en"].lower()


def test_transliterate_historic_landmarks():
    res_uhud = transliterate_mosque_name("مسجد أحد")
    assert res_uhud["name_en"] == "Uhud Mosque"

    res_badr = transliterate_mosque_name("مسجد بدر")
    assert res_badr["name_en"] == "Badr Mosque"

    res_hittin = transliterate_mosque_name("مسجد حطين")
    assert res_hittin["name_en"] == "Hittin Mosque"

    res_yarmouk = transliterate_mosque_name("مسجد اليرموك")
    assert res_yarmouk["name_en"] == "Al-Yarmouk Mosque"

    res_andalus = transliterate_mosque_name("مسجد الأندلس")
    assert res_andalus["name_en"] == "Al-Andalus Mosque"

    res_taybah = transliterate_mosque_name("مسجد طيبة")
    assert res_taybah["name_en"] == "Taybah Mosque"


def test_transliterate_morphological_patterns():
    # Taf'eel: Tawfiq
    res_tawfiq = transliterate_mosque_name("مسجد توفيق")
    assert "Tawfiq" in res_tawfiq["name_en"]

    # Maf'oul: Mahmoud / Mansour
    res_mahmoud = transliterate_mosque_name("مسجد محمود")
    assert "Mahmoud" in res_mahmoud["name_en"]

    res_mansour = transliterate_mosque_name("مسجد منصور")
    assert "Mansour" in res_mansour["name_en"]


def test_transliterate_musalla_and_descriptive():
    res_eid = transliterate_mosque_name("مصلى العيد")
    assert res_eid["name_en"] == "Al-Eid Musalla"
    assert res_eid["type"] == "musalla"

    res_men = transliterate_mosque_name("مصلى رجال")
    assert res_men["name_en"] == "Men's Musalla"

    res_women = transliterate_mosque_name("مصلى نساء")
    assert res_women["name_en"] == "Women's Musalla"

    res_temporary = transliterate_mosque_name("مسجد مؤقت")
    assert res_temporary["name_en"] == "Temporary Mosque"

    res_local = transliterate_mosque_name("مسجد محلي")
    assert res_local["name_en"] == "Local Mosque"


def test_transliterate_orthographic_resilience():
    # Taa marbuta as haa
    res_station = transliterate_mosque_name("مسجد المحطه")
    assert res_station["name_en"] == "Al-Mahattah Mosque"

    res_rahmah = transliterate_mosque_name("مسجد الرحمه")
    assert res_rahmah["name_en"] == "Al-Rahmah Mosque"

    # Alef normalization
    res_ibrahim = transliterate_mosque_name("مسجد ابراهيم")
    assert res_ibrahim["name_en"] == "Ibrahim Mosque"


def test_transliterate_endpoint():
    with TestClient(app) as client:
        res = client.get("/api/v1/transliterate", params={"name": "جامع الملك فهد"})
        assert res.status_code == 200
        data = res.json()
        assert data["name_en"] == "King Fahd Grand Mosque"
        assert data["type"] == "jamea"

        res_post = client.post("/api/v1/transliterate", json={"name": "مسجد التقوى"})
        assert res_post.status_code == 200
        data_post = res_post.json()
        assert data_post["name_en"] == "Al-Taqwa Mosque"
