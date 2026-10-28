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


def test_transliterate_divine_attributes():
    res = transliterate_mosque_name("مسجد التقوى")
    assert res["name_en"] == "Al-Taqwa Mosque"

    res_rahji = transliterate_mosque_name("جامع الراجحي")
    assert res_rahji["name_en"] == "Al-Rajhi Grand Mosque"


def test_transliterate_companions():
    res = transliterate_mosque_name("مسجد بلال بن رباح")
    assert res["name_en"] == "Bilal bin Rabah Mosque"


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

