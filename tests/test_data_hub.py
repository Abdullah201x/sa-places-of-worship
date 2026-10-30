import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline"))

from build_data_hub import (
    sha256_file,
    generate_places_csv,
    generate_gaps_csv,
    generate_suggestions_csv,
    build_manifest,
    OVERPASS_PRESETS,
)


def test_sha256_file(tmp_path):
    f = tmp_path / "sample.txt"
    f.write_text("hello manara", encoding="utf-8")
    digest = sha256_file(str(f))
    assert len(digest) == 64
    assert isinstance(digest, str)


def test_generate_places_csv(tmp_path):
    geojson_path = tmp_path / "places_of_worship_sa.geojson"
    csv_path = tmp_path / "places_of_worship_sa.csv"

    sample_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "id": "node/12345",
                "properties": {
                    "osm_type": "node",
                    "osm_id": 12345,
                    "name": "مسجد النور",
                    "name_norm": "مسجد النور",
                    "name_en": "Al Noor Mosque",
                    "religion": "muslim",
                    "denomination": "sunni",
                    "building": "mosque",
                    "amenity": "place_of_worship",
                    "region_code": "SA-01"
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [46.6753, 24.7136]
                }
            }
        ]
    }
    geojson_path.write_text(json.dumps(sample_geojson), encoding="utf-8")

    count = generate_places_csv(str(geojson_path), str(csv_path))
    assert count == 1
    assert csv_path.exists()

    content = csv_path.read_text(encoding="utf-8-sig")
    lines = content.strip().splitlines()
    assert len(lines) == 2
    assert "osm_id" in lines[0]
    assert "12345" in lines[1]
    assert "Al Noor Mosque" in lines[1]


def test_generate_gaps_csv(tmp_path):
    gaps_json_path = tmp_path / "worship_gaps_sa.json"
    csv_path = tmp_path / "worship_gaps_sa.csv"

    sample_gaps = {
        "grid_size": 0.004,
        "fields": ["gx", "gy", "road_length_m", "gap_score", "urgency_score"],
        "cells": [
            [12500, 6500, 1500, 12.5, 45.0],
            [12501, 6501, 800, 8.2, 25.0],
        ]
    }
    gaps_json_path.write_text(json.dumps(sample_gaps), encoding="utf-8")

    count = generate_gaps_csv(str(gaps_json_path), str(csv_path))
    assert count == 2
    assert csv_path.exists()

    content = csv_path.read_text(encoding="utf-8-sig")
    lines = content.strip().splitlines()
    assert len(lines) == 3
    assert "grid_x" in lines[0]
    assert "12500" in lines[1]
    assert "45.0" in lines[1]


def test_generate_suggestions_csv(tmp_path):
    sug_geojson_path = tmp_path / "suggested_mosques_sa.geojson"
    csv_path = tmp_path / "suggested_mosques_sa.csv"

    sample_sug = {
        "type": "FeatureCollection",
        "features": [
            {
                "properties": {
                    "wikidata_id": "Q123456",
                    "name_ar": "مسجد قباء",
                    "name_en": "Quba Mosque",
                    "nearest_osm_m": 450,
                    "is_unnamed": False
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [39.6172, 24.4392]
                }
            }
        ]
    }
    sug_geojson_path.write_text(json.dumps(sample_sug), encoding="utf-8")

    count = generate_suggestions_csv(str(sug_geojson_path), str(csv_path))
    assert count == 1
    assert csv_path.exists()

    content = csv_path.read_text(encoding="utf-8-sig")
    lines = content.strip().splitlines()
    assert len(lines) == 2
    assert "Q123456" in lines[1]
    assert "Quba Mosque" in lines[1]


def test_build_manifest(tmp_path):
    # Setup minimal files
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(json.dumps({
        "updated_at": "2026-10-30T12:00:00Z",
        "pbf_date": "2026-10-29",
        "datasets": {"places": {"count": 10}}
    }), encoding="utf-8")

    manifest = build_manifest(data_dir=str(tmp_path))

    assert manifest["dataset_version"] == "v20261030T120000Z"
    assert manifest["pbf_date"] == "2026-10-29"
    assert manifest["licence"] == "ODbL-1.0"
    assert manifest["attribution"] == "© OpenStreetMap contributors"
    assert isinstance(manifest["files"], list)
    assert len(manifest["overpass_presets"]) >= 4

    manifest_file = tmp_path / "manifest.json"
    assert manifest_file.exists()
    loaded = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert loaded["dataset_version"] == manifest["dataset_version"]
