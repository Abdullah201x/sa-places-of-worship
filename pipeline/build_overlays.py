#!/usr/bin/env python3
"""
Builds versioned vector tile overlays in PMTiles v3 format for:
  - places.pmtiles (z5–z14, trimmed attributes: id, osm_type, osm_id, name, name_en, religion, denomination, building, amenity)
  - gaps.pmtiles (z5–z14, road_length_m, gap_score, urgency_score)
  - suggestions.pmtiles (z5–z14, qid, name_ar, name_en, nearest_osm_m, is_unnamed)

Conforms to REDESIGN.md §3.6, §4.6, §5.
Uses tippecanoe when available. Otherwise (or if it fails) pmtiles_writer.py tiles
the points itself, so the overlays always contain real tiles.
"""

import json
import os
import shutil
import struct
import subprocess
import tempfile

from common import BASE_DIR, configure_utf8_output
from pmtiles_writer import write_pmtiles

configure_utf8_output()

DATA_DIR = os.environ.get("MANARA_DATA_DIR", BASE_DIR)

# Saudi Arabia bounding box & center
# [minLon, minLat, maxLon, maxLat]
SA_BBOX = [34.5, 16.3, 55.7, 32.2]
SA_CENTER = [45.0, 24.0, 6]  # [lon, lat, zoom]


def create_pmtiles_v3_header(
    root_dir_offset=127,
    root_dir_len=0,
    metadata_offset=127,
    metadata_len=0,
    leaf_dir_offset=0,
    leaf_dir_len=0,
    tile_data_offset=127,
    tile_data_len=0,
    num_addressed_tiles=0,
    num_tile_entries=0,
    num_tile_contents=0,
    min_zoom=5,
    max_zoom=14,
    min_lon=34.5,
    min_lat=16.3,
    max_lon=55.7,
    max_lat=32.2,
    center_zoom=6,
    center_lon=45.0,
    center_lat=24.0,
):
    """
    Constructs a 127-byte PMTiles v3 specification header.
    Spec: https://github.com/protomaps/PMTiles/blob/main/spec/v3/spec.md
    """
    magic = b"PMTiles\x03"  # 8 bytes

    # 11 uint64_t fields (88 bytes)
    offsets_and_counts = struct.pack(
        "<11Q",
        root_dir_offset,
        root_dir_len,
        metadata_offset,
        metadata_len,
        leaf_dir_offset,
        leaf_dir_len,
        tile_data_offset,
        tile_data_len,
        num_addressed_tiles,
        num_tile_entries,
        num_tile_contents,
    )

    # 4 flags: clustered (1), internal_compression (2=gzip), tile_compression (2=gzip), tile_type (1=mvt)
    flags = struct.pack("<4B", 1, 2, 2, 1)

    # Zoom bounds
    zooms = struct.pack("<2B", min_zoom, max_zoom)

    # Bounds: 4 * int32_t (scaled by 1e7)
    bounds = struct.pack(
        "<4i",
        int(min_lon * 1e7),
        int(min_lat * 1e7),
        int(max_lon * 1e7),
        int(max_lat * 1e7),
    )

    # Center: 1 * uint8_t zoom, 2 * int32_t (scaled by 1e7)
    center = struct.pack(
        "<B2i",
        center_zoom,
        int(center_lon * 1e7),
        int(center_lat * 1e7),
    )

    header = magic + offsets_and_counts + flags + zooms + bounds + center
    assert len(header) == 127, f"PMTiles v3 header must be exactly 127 bytes, got {len(header)}"
    return header


PLACE_PROPS = ("osm_type", "osm_id", "name", "name_norm", "name_en", "religion",
               "denomination", "building", "amenity")

# (min zoom, max zoom). Gap cells are 0.004 deg (~440 m), so z12 already shows
# every cell on its own; MapLibre overzooms the source beyond that.
ZOOMS = {"places": (5, 14), "gaps": (5, 12), "suggestions": (5, 14)}


def write_fallback_pmtiles(output_path, layer_name, min_zoom=5, max_zoom=14, extra_meta=None, points=()):
    """Writes a PMTiles v3 archive with the pure-Python tiler (see pmtiles_writer.py)."""
    n = write_pmtiles(
        output_path, layer_name, list(points), min_zoom, max_zoom,
        bounds=SA_BBOX, center=SA_CENTER, extra_meta=extra_meta,
        header_builder=create_pmtiles_v3_header,
    )
    print(f"  [FALLBACK] Wrote {n} tiles to '{layer_name}' ({os.path.getsize(output_path)} bytes)")


def osm_type_of(props):
    """OSM element type from extract_places.py's geom_type (same rule as osmTypeOf in app.js)."""
    geom_type = props.get("geom_type")
    if geom_type == "Point":
        return "node"
    return "relation" if geom_type == "Relation" else "way"


def _load_places(data_dir):
    path = os.path.join(data_dir, "places_of_worship_sa.geojson")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        feats = json.load(f).get("features", [])
    pts = []
    for ft in feats:
        geom = ft.get("geometry") or {}
        if geom.get("type") != "Point":
            continue
        p = ft.get("properties") or {}
        lon, lat = geom["coordinates"][:2]
        props = {k: p[k] for k in PLACE_PROPS if k in p}
        props["osm_type"] = osm_type_of(p)
        pts.append((lon, lat, props, 0))
    return pts


def _load_gaps(data_dir):
    path = os.path.join(data_dir, "worship_gaps_sa.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    cells = data.get("cells", []) if isinstance(data, dict) else data
    grid = float(data.get("grid_size", 0.004)) if isinstance(data, dict) else 0.004
    pts = []
    for row in cells:
        if len(row) < 4:
            continue
        gx, gy, road_len, score = row[0], row[1], row[2], row[3]
        urgency = row[4] if len(row) > 4 else 0.0
        pts.append((
            round((float(gx) + 0.5) * grid, 6), round((float(gy) + 0.5) * grid, 6),
            {"grid_x": gx, "grid_y": gy, "road_len": road_len, "gap_score": score, "urgency": urgency},
            urgency,
        ))
    return pts


def _load_suggestions(data_dir):
    path = os.path.join(data_dir, "suggested_mosques_sa.geojson")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        feats = json.load(f).get("features", [])
    pts = []
    for ft in feats:
        geom = ft.get("geometry") or {}
        if geom.get("type") != "Point":
            continue
        p = ft.get("properties") or {}
        lon, lat = geom["coordinates"][:2]
        props = {k: p[k] for k in ("qid", "name_ar", "name_en", "nearest_osm_m", "is_unnamed") if k in p}
        # Named suggestions that are far from any mapped mosque matter most.
        prio = (0 if p.get("is_unnamed") else 1) * 1e6 + float(p.get("nearest_osm_m") or 0)
        pts.append((lon, lat, props, prio))
    return pts


LOADERS = {"places": _load_places, "gaps": _load_gaps, "suggestions": _load_suggestions}
SOURCES = {"places": "places_of_worship_sa.geojson", "gaps": "worship_gaps_sa.json",
           "suggestions": "suggested_mosques_sa.geojson"}


def _run_tippecanoe(tippecanoe_bin, out, layer, points, min_zoom, max_zoom):
    feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]}, "properties": props}
             for lon, lat, props, _prio in points]
    with tempfile.NamedTemporaryFile("w", suffix=".geojson", delete=False, encoding="utf-8") as tmp:
        json.dump({"type": "FeatureCollection", "features": feats}, tmp, ensure_ascii=False)
        tmp_path = tmp.name
    try:
        cmd = [tippecanoe_bin, "-o", out, f"-z{max_zoom}", f"-Z{min_zoom}", "--drop-densest-as-needed",
               "-l", layer, "--force", tmp_path]
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    finally:
        os.remove(tmp_path)


def build_overlay(data_dir, layer, tippecanoe_bin):
    """Builds <layer>.pmtiles from its source file. Returns False if the source is missing."""
    points = LOADERS[layer](data_dir)
    if points is None:
        print(f"  [SKIP] {SOURCES[layer]} not found.")
        return False
    out = os.path.join(data_dir, f"{layer}.pmtiles")
    min_zoom, max_zoom = ZOOMS[layer]

    if tippecanoe_bin:
        try:
            _run_tippecanoe(tippecanoe_bin, out, layer, points, min_zoom, max_zoom)
            print(f"  [OK] {layer}.pmtiles built with tippecanoe ({os.path.getsize(out)} bytes).")
            return True
        except Exception as e:
            print(f"  [WARN] tippecanoe failed for {layer}: {e}. Falling back to the Python tiler.")
    write_fallback_pmtiles(out, layer, min_zoom, max_zoom, points=points)
    return True


def build_all_overlays(data_dir=DATA_DIR):
    """Generates all 3 PMTiles vector overlays."""
    print("Building PMTiles vector overlays (places, gaps, suggestions)...")
    tippecanoe_bin = shutil.which("tippecanoe")
    if tippecanoe_bin:
        print(f"  Found tippecanoe at: {tippecanoe_bin}")
    else:
        print("  tippecanoe not found on PATH; using the built-in Python tiler.")

    results = [build_overlay(data_dir, layer, tippecanoe_bin) for layer in ("places", "gaps", "suggestions")]

    print("PMTiles overlay generation complete.")
    return all(results)


if __name__ == "__main__":
    build_all_overlays()
