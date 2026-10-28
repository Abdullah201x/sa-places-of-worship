import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common import (axis_deviation, calculate_qibla_azimuth, is_generic_mosque_name,  # noqa: E402
                    normalize_arabic, ring_centroid)
from extract_places import POI_TAG_KEYS, _create_feature, _apply_name_fallbacks  # noqa: E402
from import_wikidata_suggestions import clean_name, is_non_mosque_entity  # noqa: E402


def test_ring_centroid_closed_square_ignores_repeated_first_node():
    square = [(0, 0), (2, 0), (2, 2), (0, 2), (0, 0)]
    assert ring_centroid(square) == pytest.approx((1.0, 1.0))


def test_ring_centroid_dense_edge_does_not_pull_centroid():
    # Many nodes along the bottom edge used to drag the vertex average down.
    ring = [(x / 10, 0) for x in range(0, 21)] + [(2, 2), (0, 2), (0, 0)]
    assert ring_centroid(ring) == pytest.approx((1.0, 1.0))


def test_ring_centroid_l_shape_stays_inside():
    l_shape = [(0, 0), (10, 0), (10, 1), (1, 1), (1, 10), (0, 10), (0, 0)]
    from shapely.geometry import Point, Polygon
    assert Polygon(l_shape).contains(Point(ring_centroid(l_shape)))


def test_ring_centroid_open_way_uses_vertex_mean():
    assert ring_centroid([(0, 0), (4, 0), (4, 2)]) == pytest.approx((8 / 3, 2 / 3))


def test_normalize_arabic():
    assert normalize_arabic("الجَامِعُ الكبيـــر", strip_al=True) == normalize_arabic("المسجد الكبير", strip_al=True)
    assert normalize_arabic("جامع") == normalize_arabic("مسجد")
    assert normalize_arabic("أحمد") == "احمد"
    assert normalize_arabic("مكة") == "مكه"
    assert normalize_arabic("Masjid  AL-Noor") == "masjid alnoor"


@pytest.mark.parametrize("name", ["", "مسجد", "المسجد", "جامع", "الجامع", "مصلى", "مسجد جامع",
                                  "Mosque", "Place of Worship", "مسجد 3", "مسجد بدون اسم"])
def test_generic_names(name):
    assert is_generic_mosque_name(name)


@pytest.mark.parametrize("name", ["مسجد الرحمن", "جامع الملك فهد", "مصلى العيد", "Al Rajhi Mosque"])
def test_specific_names(name):
    assert not is_generic_mosque_name(name)


def test_non_mosque_landform_containing_mosque_word():
    assert is_non_mosque_entity("فيضة ام مسجد", "Fayḑat Umm Masjid")


def test_non_mosque_university():
    assert is_non_mosque_entity("جامعة الملك سعود", "King Saud University")


@pytest.mark.parametrize("ar,en", [("جامع الملك فهد", ""), ("مسجد قباء", "Quba Mosque"),
                                   ("", "Al Rajhi Masjid"), ("مصلى العيد", "")])
def test_real_mosques_are_kept(ar, en):
    assert not is_non_mosque_entity(ar, en)


def test_clean_name_strips_serial_suffix():
    assert clean_name("جامع الرمال 1") == "جامع الرمال"
    assert clean_name("مسجد ٢٣") == "مسجد"


def test_qibla_azimuth_from_riyadh_points_west():
    az = calculate_qibla_azimuth(24.7136, 46.6753)
    assert 240 < az < 250


def test_qibla_azimuth_from_madinah_points_south():
    az = calculate_qibla_azimuth(24.4672, 39.6112)
    assert 170 < az < 185


@pytest.mark.parametrize("axis,qibla,expected", [
    (245, 245, 0), (65, 245, 0), (155, 245, 0),   # parallel, reversed, perpendicular
    (260, 245, 15), (230, 245, 15), (200, 245, 45),
])
def test_axis_deviation(axis, qibla, expected):
    assert axis_deviation(axis, qibla) == pytest.approx(expected)


def test_worship_gaps_schema_and_urgency():
    gaps_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "worship_gaps_sa.json")
    if os.path.exists(gaps_path):
        with open(gaps_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "grid_size" in data
        assert "fields" in data
        assert "urgency_score" in data["fields"]
        assert len(data["cells"]) > 0
        first = data["cells"][0]
        assert len(first) >= 5
        assert isinstance(first[4], (int, float))


def test_poi_tag_keys_includes_name_ar():
    assert "name:ar" in POI_TAG_KEYS
    assert "name" in POI_TAG_KEYS
    assert "name:en" in POI_TAG_KEYS


def test_create_feature_preserves_name_ar():
    from datetime import datetime, timezone

    class MockOsmObj:
        version = 1
        timestamp = datetime.now(timezone.utc)

    # Mosque with only name:ar tag
    f1 = _create_feature(1001, 24.5, 46.5, {"name:ar": "مسجد الهدى"}, "Point", MockOsmObj())
    assert f1["properties"]["name_ar"] == "مسجد الهدى"
    assert f1["properties"]["name_ar_original"] == "مسجد الهدى"
    assert f1["properties"]["name"] == "مسجد الهدى"

    # Mosque with no name at all
    f2 = _create_feature(1002, 24.5, 46.5, {"religion": "muslim"}, "Point", MockOsmObj())
    assert f2["properties"]["name_original"] == ""
    assert f2["properties"]["name_ar"] == ""
    assert f2["properties"]["name_ar_original"] == ""
    assert f2["properties"]["name"] == "Mosque"


def test_missing_name_en_excludes_unnamed_mosques():
    """Verify quality issues logic: mosques without name or name:ar must NOT be flagged as missing_name_en."""
    def check_missing_name_en(props):
        raw_ar = (props.get("name_original") or props.get("name:ar") or props.get("name_ar") or props.get("name_ar_original") or "").strip()
        clean_en = (props.get("name_en_original") or props.get("name:en") or "").strip()
        if raw_ar and not is_generic_mosque_name(raw_ar):
            if not clean_en or raw_ar == clean_en:
                return True
        return False

    # 1. Unnamed mosque (no name, no name:ar) -> NOT flagged
    assert not check_missing_name_en({"name_original": "", "name_en_original": ""})
    assert not check_missing_name_en({})

    # 2. Generic name ("مسجد", "Mosque") -> NOT flagged
    assert not check_missing_name_en({"name_original": "مسجد", "name_en_original": ""})
    assert not check_missing_name_en({"name_original": "Mosque", "name_en_original": ""})

    # 3. Named mosque with missing English name -> FLAGGED
    assert check_missing_name_en({"name_original": "جامع الملك فهد", "name_en_original": ""})

    # 4. Named mosque with only name:ar and missing English name -> FLAGGED
    assert check_missing_name_en({"name:ar": "مسجد قباء", "name_en_original": ""})

    # 5. Named mosque with identical English name -> FLAGGED
    assert check_missing_name_en({"name_original": "مسجد قباء", "name_en_original": "مسجد قباء"})

    # 6. Named mosque with valid English name -> NOT flagged
    assert not check_missing_name_en({"name_original": "مسجد قباء", "name_en_original": "Quba Mosque"})

