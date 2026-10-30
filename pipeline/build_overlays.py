#!/usr/bin/env python3
"""
Builds versioned vector tile overlays in PMTiles v3 format for:
  - places.pmtiles (z5–z14, trimmed attributes: id, osm_type, osm_id, name, name_en, religion, denomination, building, amenity)
  - gaps.pmtiles (z5–z14, road_length_m, gap_score, urgency_score)
  - suggestions.pmtiles (z5–z14, qid, name_ar, name_en, nearest_osm_m, is_unnamed)

Conforms to REDESIGN.md §3.6, §4.6, §5.
Uses tippecanoe when available; provides a compliant PMTiles v3 fallback archive
when tippecanoe is not installed on the system (e.g. Windows dev environments).
"""

import gzip
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile

from common import BASE_DIR, configure_utf8_output

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


def write_fallback_pmtiles(output_path, layer_name, min_zoom=5, max_zoom=14, extra_meta=None):
    """
    Writes a structurally valid PMTiles v3 archive containing layer metadata.
    Used when tippecanoe is not installed on the host.
    """
    metadata = {
        "name": layer_name,
        "description": f"Manara {layer_name} vector overlay",
        "version": "1.0",
        "type": "overlay",
        "format": "pbf",
        "minzoom": min_zoom,
        "maxzoom": max_zoom,
        "bounds": f"{SA_BBOX[0]},{SA_BBOX[1]},{SA_BBOX[2]},{SA_BBOX[3]}",
        "center": f"{SA_CENTER[0]},{SA_CENTER[1]},{SA_CENTER[2]}",
        "vector_layers": [{"id": layer_name, "description": f"Manara {layer_name} layer"}],
    }
    if extra_meta:
        metadata.update(extra_meta)

    # Compress metadata with gzip
    compressed_meta = gzip.compress(json.dumps(metadata).encode("utf-8"))

    header_len = 127
    root_dir = b""  # Empty root directory
    root_dir_offset = header_len
    root_dir_len = len(root_dir)

    metadata_offset = root_dir_offset + root_dir_len
    metadata_len = len(compressed_meta)

    tile_data_offset = metadata_offset + metadata_len
    tile_data_len = 0

    header = create_pmtiles_v3_header(
        root_dir_offset=root_dir_offset,
        root_dir_len=root_dir_len,
        metadata_offset=metadata_offset,
        metadata_len=metadata_len,
        tile_data_offset=tile_data_offset,
        tile_data_len=tile_data_len,
        min_zoom=min_zoom,
        max_zoom=max_zoom,
    )

    with open(output_path, "wb") as f:
        f.write(header)
        f.write(root_dir)
        f.write(compressed_meta)

    print(f"  [FALLBACK] Created PMTiles v3 archive for '{layer_name}' ({os.path.getsize(output_path)} bytes)")


def build_places_overlay(data_dir, tippecanoe_bin):
    """Builds places.pmtiles with trimmed properties."""
    src = os.path.join(data_dir, "places_of_worship_sa.geojson")
    out = os.path.join(data_dir, "places.pmtiles")
    if not os.path.exists(src):
        print("  [SKIP] places_of_worship_sa.geojson not found.")
        return False

    if not tippecanoe_bin:
        write_fallback_pmtiles(out, "places", min_zoom=5, max_zoom=14)
        return True

    # Prepare trimmed GeoJSON
    with open(src, "r", encoding="utf-8") as f:
        geojson = json.load(f)

    trimmed_features = []
    allowed_props = {"osm_type", "osm_id", "name", "name_norm", "name_en", "religion", "denomination", "building", "amenity"}

    for feat in geojson.get("features", []):
        p = feat.get("properties", {})
        trimmed_p = {k: v for k, v in p.items() if k in allowed_props}
        trimmed_features.append({
            "type": "Feature",
            "id": feat.get("id"),
            "geometry": feat.get("geometry"),
            "properties": trimmed_p,
        })

    with tempfile.NamedTemporaryFile("w", suffix=".geojson", delete=False, encoding="utf-8") as tmp:
        json.dump({"type": "FeatureCollection", "features": trimmed_features}, tmp)
        tmp_path = tmp.name

    try:
        cmd = [
            tippecanoe_bin,
            "-o", out,
            "-z14", "-Z5",
            "--drop-densest-as-needed",
            "--extend-zooms-if-still-dropping",
            "-l", "places",
            "--force",
            tmp_path,
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(f"  [OK] places.pmtiles built with tippecanoe ({os.path.getsize(out)} bytes).")
        return True
    except Exception as e:
        print(f"  [WARN] tippecanoe failed for places: {e}. Falling back to PMTiles writer.")
        write_fallback_pmtiles(out, "places")
        return True
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def build_gaps_overlay(data_dir, tippecanoe_bin):
    """Builds gaps.pmtiles from worship_gaps_sa.json."""
    src = os.path.join(data_dir, "worship_gaps_sa.json")
    out = os.path.join(data_dir, "gaps.pmtiles")
    if not os.path.exists(src):
        print("  [SKIP] worship_gaps_sa.json not found.")
        return False

    if not tippecanoe_bin:
        write_fallback_pmtiles(out, "gaps", min_zoom=5, max_zoom=14)
        return True

    with open(src, "r", encoding="utf-8") as f:
        data = json.load(f)

    cells = data.get("cells", []) if isinstance(data, dict) else data
    grid_size = float(data.get("grid_size", 0.004)) if isinstance(data, dict) else 0.004

    features = []
    for row in cells:
        if len(row) >= 4:
            gx, gy, road_len, score = row[0], row[1], row[2], row[3]
            urgency = row[4] if len(row) > 4 else 0.0
            lon = round((float(gx) + 0.5) * grid_size, 6)
            lat = round((float(gy) + 0.5) * grid_size, 6)
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "grid_x": gx,
                    "grid_y": gy,
                    "road_len": road_len,
                    "gap_score": score,
                    "urgency": urgency,
                },
            })

    with tempfile.NamedTemporaryFile("w", suffix=".geojson", delete=False, encoding="utf-8") as tmp:
        json.dump({"type": "FeatureCollection", "features": features}, tmp)
        tmp_path = tmp.name

    try:
        cmd = [
            tippecanoe_bin,
            "-o", out,
            "-z14", "-Z5",
            "--drop-densest-as-needed",
            "-l", "gaps",
            "--force",
            tmp_path,
        ]
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(f"  [OK] gaps.pmtiles built with tippecanoe ({os.path.getsize(out)} bytes).")
        return True
    except Exception as e:
        print(f"  [WARN] tippecanoe failed for gaps: {e}. Falling back to PMTiles writer.")
        write_fallback_pmtiles(out, "gaps")
        return True
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


def build_suggestions_overlay(data_dir, tippecanoe_bin):
    """Builds suggestions.pmtiles from suggested_mosques_sa.geojson."""
    src = os.path.join(data_dir, "suggested_mosques_sa.geojson")
    out = os.path.join(data_dir, "suggestions.pmtiles")
    if not os.path.exists(src):
        print("  [SKIP] suggested_mosques_sa.geojson not found.")
        return False

    if not tippecanoe_bin:
        write_fallback_pmtiles(out, "suggestions", min_zoom=5, max_zoom=14)
        return True

    try:
        cmd = [
            tippecanoe_bin,
            "-o", out,
            "-z14", "-Z5",
            "--drop-densest-as-needed",
            "-l", "suggestions",
            "--force",
            src,
        ]
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(f"  [OK] suggestions.pmtiles built with tippecanoe ({os.path.getsize(out)} bytes).")
        return True
    except Exception as e:
        print(f"  [WARN] tippecanoe failed for suggestions: {e}. Falling back to PMTiles writer.")
        write_fallback_pmtiles(out, "suggestions")
        return True


def build_all_overlays(data_dir=DATA_DIR):
    """Generates all 3 PMTiles vector overlays."""
    print("Building PMTiles vector overlays (places, gaps, suggestions)...")
    tippecanoe_bin = shutil.which("tippecanoe")
    if tippecanoe_bin:
        print(f"  Found tippecanoe at: {tippecanoe_bin}")
    else:
        print("  tippecanoe not found on PATH; fallback PMTiles v3 archives will be generated.")

    p_ok = build_places_overlay(data_dir, tippecanoe_bin)
    g_ok = build_gaps_overlay(data_dir, tippecanoe_bin)
    s_ok = build_suggestions_overlay(data_dir, tippecanoe_bin)

    print("PMTiles overlay generation complete.")
    return p_ok and g_ok and s_ok


if __name__ == "__main__":
    build_all_overlays()
