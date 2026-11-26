import pytest
import sys
import os

# Add pipeline directory to sys.path
pipeline_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "pipeline"))
if pipeline_dir not in sys.path:
    sys.path.insert(0, pipeline_dir)

from worship_tags import is_worship_tagged, is_mosque, worship_religion, worship_denomination
from change_rules import CHANGE_FLAGS, compute_tag_diff, evaluate_change_flags


def test_worship_tags_predicate():
    # True cases
    assert is_worship_tagged({"amenity": "place_of_worship"}) is True
    assert is_worship_tagged({"amenity": "mosque"}) is True
    assert is_worship_tagged({"building": "mosque"}) is True
    assert is_worship_tagged({"building": "mosque", "amenity": "school"}) is True

    # False cases
    assert is_worship_tagged({}) is False
    assert is_worship_tagged(None) is False
    assert is_worship_tagged({"amenity": "restaurant"}) is False
    assert is_worship_tagged({"building": "yes"}) is False


def test_is_mosque():
    assert is_mosque({"amenity": "place_of_worship", "religion": "muslim"}) is True
    assert is_mosque({"amenity": "place_of_worship"}) is True  # default muslim in KSA
    assert is_mosque({"building": "mosque"}) is True
    assert is_mosque({"amenity": "place_of_worship", "religion": "christian"}) is False


def test_compute_tag_diff():
    old_tags = {"amenity": "place_of_worship", "name": "مسجد النور", "religion": "muslim"}
    new_tags = {"amenity": "place_of_worship", "name": "مسجد النور", "religion": "muslim", "name:en": "Al Noor Mosque"}

    diff = compute_tag_diff(old_tags, new_tags)
    assert diff == {"added": {"name:en": "Al Noor Mosque"}}

    # Modified and removed
    old_tags = {"building": "mosque", "name": "مسجد القديم"}
    new_tags = {"building": "yes"}
    diff = compute_tag_diff(old_tags, new_tags)
    assert "modified" in diff
    assert diff["modified"]["building"] == {"before": "mosque", "after": "yes"}
    assert "removed" in diff
    assert diff["removed"] == {"name": "مسجد القديم"}


def test_evaluate_change_flags_deleted_named():
    flags = evaluate_change_flags(
        old_tags={"name": "جامع الملك فهد", "amenity": "place_of_worship"},
        new_tags={},
        is_deleted=True,
        is_upgraded=False,
    )
    assert "deleted-named-mosque" in flags

    # If upgraded (e.g. node replaced by way outline), flag should NOT fire
    flags_upgraded = evaluate_change_flags(
        old_tags={"name": "جامع الملك فهد", "amenity": "place_of_worship"},
        new_tags={},
        is_deleted=True,
        is_upgraded=True,
    )
    assert "deleted-named-mosque" not in flags_upgraded


def test_evaluate_change_flags_name_removed():
    flags = evaluate_change_flags(
        old_tags={"name": "مسجد السلام", "amenity": "place_of_worship"},
        new_tags={"amenity": "place_of_worship"},
        is_deleted=False,
    )
    assert "name-removed" in flags


def test_evaluate_change_flags_religion_changed():
    flags = evaluate_change_flags(
        old_tags={"religion": "muslim", "amenity": "place_of_worship"},
        new_tags={"religion": "christian", "amenity": "place_of_worship"},
    )
    assert "religion-changed" in flags


def test_evaluate_change_flags_amenity_removed():
    flags = evaluate_change_flags(
        old_tags={"amenity": "place_of_worship", "building": "yes"},
        new_tags={"building": "yes"},
    )
    assert "amenity-removed" in flags


def test_evaluate_change_flags_building_downgraded():
    flags = evaluate_change_flags(
        old_tags={"building": "mosque"},
        new_tags={"building": "yes"},
    )
    assert "building-downgraded" in flags


def test_evaluate_change_flags_name_ar_mismatch():
    flags = evaluate_change_flags(
        old_tags={},
        new_tags={"name": "مسجد النور", "name:ar": "مسجد الهدى"},
        normalized_name="مسجد النور",
        normalized_name_ar="مسجد الهدى",
    )
    assert "name-ar-mismatch" in flags


def test_evaluate_change_flags_issue_fixed():
    flags = evaluate_change_flags(
        old_tags={"name": "مسجد"},
        new_tags={"name": "مسجد الفتح"},
        resolved_issues=["missing_name"],
    )
    assert "issue-fixed" in flags
