import gzip
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pipeline"))

from build_overlays import (
    create_pmtiles_v3_header,
    write_fallback_pmtiles,
    build_all_overlays,
)


def test_create_pmtiles_v3_header():
    header = create_pmtiles_v3_header()
    assert len(header) == 127
    assert header.startswith(b"PMTiles\x03")


def test_write_fallback_pmtiles(tmp_path):
    output_path = tmp_path / "test.pmtiles"
    write_fallback_pmtiles(str(output_path), "test_layer", min_zoom=6, max_zoom=12)

    assert output_path.exists()
    assert output_path.stat().st_size > 127

    with open(output_path, "rb") as f:
        magic = f.read(8)
        assert magic == b"PMTiles\x03"

        # Read remaining header
        f.seek(127)
        # Root dir is empty (len 0), next is gzip metadata
        gz_data = f.read()
        decompressed = gzip.decompress(gz_data)
        meta = json.loads(decompressed.decode("utf-8"))

        assert meta["name"] == "test_layer"
        assert meta["minzoom"] == 6
        assert meta["maxzoom"] == 12
        assert meta["vector_layers"][0]["id"] == "test_layer"


def test_build_all_overlays_with_fallback(tmp_path):
    # Create mock inputs
    places_file = tmp_path / "places_of_worship_sa.geojson"
    places_file.write_text(json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8")

    gaps_file = tmp_path / "worship_gaps_sa.json"
    gaps_file.write_text(json.dumps({"grid_size": 0.004, "cells": []}), encoding="utf-8")

    sug_file = tmp_path / "suggested_mosques_sa.geojson"
    sug_file.write_text(json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8")

    ok = build_all_overlays(data_dir=str(tmp_path))
    assert ok is True

    assert (tmp_path / "places.pmtiles").exists()
    assert (tmp_path / "gaps.pmtiles").exists()
    assert (tmp_path / "suggestions.pmtiles").exists()
