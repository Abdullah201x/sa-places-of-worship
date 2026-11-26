import pytest
import sys
import os

pipeline_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "pipeline"))
if pipeline_dir not in sys.path:
    sys.path.insert(0, pipeline_dir)

from detect_changes import diff_places, calculate_distance_m


def test_calculate_distance():
    # Riyadh center to another point ~1.1 km away
    d = calculate_distance_m(24.7136, 46.6753, 24.7236, 46.6753)
    assert 1000 < d < 1200


def test_diff_places_created():
    old_places = []
    new_places = [
        {
            "osm_type": "node",
            "osm_id": 1001,
            "version": 1,
            "name": "مسجد الهدى",
            "name_norm": "مسجد الهدى",
            "tags": {"amenity": "place_of_worship", "name": "مسجد الهدى"},
            "coords": [46.67, 24.71],
            "region_code": "SA-01",
        }
    ]

    events = diff_places(old_places, new_places, "v2", "v1")
    assert len(events) == 1
    ev = events[0]
    assert ev["kind"] == "created"
    assert ev["osm_id"] == 1001
    assert ev["version_after"] == 1
    assert ev["name"] == "مسجد الهدى"


def test_diff_places_modified():
    old_places = [
        {
            "osm_type": "way",
            "osm_id": 2002,
            "version": 2,
            "name": "مسجد النور",
            "name_norm": "مسجد النور",
            "tags": {"building": "mosque", "name": "مسجد النور"},
            "coords": [46.68, 24.72],
            "region_code": "SA-01",
        }
    ]
    new_places = [
        {
            "osm_type": "way",
            "osm_id": 2002,
            "version": 3,
            "name": "مسجد النور",
            "name_norm": "مسجد النور",
            "tags": {"building": "yes", "name": "مسجد النور"},  # Downgraded building
            "coords": [46.68, 24.72],
            "region_code": "SA-01",
        }
    ]

    events = diff_places(old_places, new_places, "v2", "v1")
    assert len(events) == 1
    ev = events[0]
    assert ev["kind"] == "modified"
    assert ev["version_before"] == 2
    assert ev["version_after"] == 3
    assert "building-downgraded" in ev["flags"]
    assert "building" in ev["tag_diff"]["modified"]


def test_diff_places_deleted_named():
    old_places = [
        {
            "osm_type": "node",
            "osm_id": 3003,
            "version": 4,
            "name": "جامع الملك عبدالعزيز",
            "name_norm": "جامع الملك عبدالعزيز",
            "tags": {"amenity": "place_of_worship", "name": "جامع الملك عبدالعزيز"},
            "coords": [46.69, 24.73],
            "region_code": "SA-01",
        }
    ]
    new_places = []

    events = diff_places(old_places, new_places, "v2", "v1")
    assert len(events) == 1
    ev = events[0]
    assert ev["kind"] == "deleted"
    assert ev["osm_id"] == 3003
    assert "deleted-named-mosque" in ev["flags"]


def test_diff_places_upgraded_node_to_way():
    # An old node is removed, but a new way subsumes it with poi_node_id
    old_places = [
        {
            "osm_type": "node",
            "osm_id": 4004,
            "version": 1,
            "name": "مسجد الرحمة",
            "name_norm": "مسجد الرحمة",
            "tags": {"amenity": "place_of_worship", "name": "مسجد الرحمة"},
            "coords": [46.70, 24.74],
            "region_code": "SA-01",
        }
    ]
    new_places = [
        {
            "osm_type": "way",
            "osm_id": 5005,
            "version": 1,
            "poi_node_id": 4004,  # Subsumes node 4004
            "name": "مسجد الرحمة",
            "name_norm": "مسجد الرحمة",
            "tags": {"building": "mosque", "amenity": "place_of_worship", "name": "مسجد الرحمة"},
            "coords": [46.70, 24.74],
            "region_code": "SA-01",
        }
    ]

    events = diff_places(old_places, new_places, "v2", "v1")
    assert len(events) == 1
    ev = events[0]
    assert ev["kind"] == "upgraded"
    assert ev["osm_id"] == 5005
    assert ev["prev_ref"] == "node/4004"
    # Node 4004 should NOT generate a false "deleted-named-mosque" event
    assert not any(e["kind"] == "deleted" and e["osm_id"] == 4004 for e in events)
