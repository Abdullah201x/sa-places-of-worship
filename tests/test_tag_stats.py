"""
tests/test_tag_stats.py - Tests for tag usage statistics generator.
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline"))

from tag_stats import compute_tag_stats, props_to_tags


def test_props_to_tags():
    props = {
        "name": "جامع الملك فهد",
        "name_en": "King Fahd Mosque",
        "name_original": "جامع الملك فهد",
        "amenity": "place_of_worship",
        "religion": "muslim",
        "denomination": "sunni",
        "building": "mosque",
        "addr_city": "Riyadh",
        "osm_id": 12345,
        "geom_type": "Polygon",
    }
    tags = props_to_tags(props)
    assert tags["name"] == "جامع الملك فهد"
    assert tags["name:en"] == "King Fahd Mosque"
    assert tags["name:ar"] == "جامع الملك فهد"
    assert tags["amenity"] == "place_of_worship"
    assert tags["religion"] == "muslim"
    assert tags["denomination"] == "sunni"
    assert tags["building"] == "mosque"
    assert tags["addr:city"] == "Riyadh"
    assert "osm_id" not in tags
    assert "geom_type" not in tags


def test_compute_tag_stats():
    sample_places = [
        {
            "amenity": "place_of_worship",
            "religion": "muslim",
            "building": "mosque",
            "denomination": "sunni",
            "name": "جامع 1",
            "name:en": "Mosque 1",
            "wheelchair": "yes"
        },
        {
            "amenity": "place_of_worship",
            "religion": "muslim",
            "building": "yes",
            "denomination": "shia",
            "name": "جامع 2",
            "name:en": "Mosque 2"
        },
        {
            "amenity": "place_of_worship",
            "religion": "muslim",
            "building": "mosque",
            "denomination": "unknown",
            "name": "جامع 3"
        }
    ]

    stats = compute_tag_stats(sample_places, as_of="2026-10-30T00:00:00Z", dataset_version="20261030")

    assert stats["total_places"] == 3
    assert stats["dataset_version"] == "20261030"
    assert stats["as_of"] == "2026-10-30T00:00:00Z"

    # Keys check
    keys = stats["keys"]
    assert keys["amenity"]["count"] == 3
    assert keys["amenity"]["percentage"] == 100.0
    assert keys["wheelchair"]["count"] == 1
    assert round(keys["wheelchair"]["percentage"], 1) == 33.3

    # Tags check
    tags = stats["tags"]
    assert tags["amenity=place_of_worship"]["count"] == 3
    assert tags["amenity=place_of_worship"]["percentage"] == 100.0
    assert tags["building=mosque"]["count"] == 2
    assert round(tags["building=mosque"]["percentage"], 1) == 66.7
    assert tags["building=yes"]["count"] == 1
    assert round(tags["building=yes"]["percentage"], 1) == 33.3
    assert tags["denomination=sunni"]["count"] == 1
    assert tags["denomination=shia"]["count"] == 1
    assert tags["denomination=unknown"]["count"] == 1

    # Co-occurrence check
    assert "religion" in tags["building=mosque"]["with_key"]
    assert tags["building=mosque"]["with_key"]["religion"] == 2
