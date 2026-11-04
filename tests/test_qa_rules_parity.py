import json
import os
import pytest

from common import BASE_DIR, is_generic_mosque_name


def test_qa_rules_json_exists_and_has_13_rules():
    qa_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "content", "qa_rules.json")
    assert os.path.exists(qa_path), "content/qa_rules.json must exist"

    with open(qa_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    rules = data.get("rules", [])
    assert len(rules) == 13, f"Expected 13 rules, got {len(rules)}"

    rule_ids = {r["id"] for r in rules}
    expected_ids = {
        "missing_amenity",
        "missing_name",
        "missing_name_en",
        "missing_denom",
        "building_yes",
        "size_too_small",
        "size_too_large",
        "mapped_as_node",
        "duplicate_poi",
        "stale_data",
        "outdated_tags",
        "ml_geometry_anomaly",
        "qibla_deviation",
    }
    assert rule_ids == expected_ids

    # Thresholds check
    thresholds = data.get("thresholds", {})
    assert thresholds.get("size_min_m2") == 50.0
    assert thresholds.get("size_max_m2") == 10000.0
    assert thresholds.get("qibla_dev_deg") == 20.0
    assert thresholds.get("stale_data_years") == 5
    assert thresholds.get("ml_anomaly_score") == -0.1


def test_generic_name_detection_prevents_mosque_name_en_inversion():
    """
    Ensure synthetic fallback 'Mosque' and generic names are detected as generic
    so that:
    1. They are flagged as missing_name.
    2. They are NOT flagged as missing_name_en (no fake request to translate 'Mosque').
    """
    assert is_generic_mosque_name("Mosque") is True
    assert is_generic_mosque_name("mosque") is True
    assert is_generic_mosque_name("مسجد") is True
    assert is_generic_mosque_name("جامع") is True
    assert is_generic_mosque_name("مصلى") is True
    assert is_generic_mosque_name("المسجد") is True
    assert is_generic_mosque_name("الجامع") is True
    assert is_generic_mosque_name("مسجد 3") is True
    assert is_generic_mosque_name("Place of Worship") is True

    # Real specific names should NOT be generic
    assert is_generic_mosque_name("جامع الراجحي") is False
    assert is_generic_mosque_name("مسجد قباء") is False
    assert is_generic_mosque_name("Al-Rahma Mosque") is False
