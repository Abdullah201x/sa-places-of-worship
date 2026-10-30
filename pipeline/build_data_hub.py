#!/usr/bin/env python3
"""
Generates the Data Hub manifest (manifest.json) and tabular CSV exports
for Saudi places of worship, coverage gaps, and Wikidata suggestions.

Conforms to REDESIGN.md §4.6 DataManifest specifications.
Licence: ODbL-1.0
Attribution: © OpenStreetMap contributors
"""

import csv
import hashlib
import json
import os
import sys

from common import BASE_DIR, configure_utf8_output, read_summary

configure_utf8_output()

DATA_DIR = os.environ.get("MANARA_DATA_DIR", BASE_DIR)


def sha256_file(filepath):
    """Calculates SHA-256 hexadecimal digest of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def generate_places_csv(geojson_path, csv_path):
    """Converts places_of_worship_sa.geojson to a clean CSV export."""
    if not os.path.exists(geojson_path):
        return 0

    with open(geojson_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    features = data.get("features", [])
    count = 0

    with open(csv_path, "w", encoding="utf-8-sig", newline="") as out:
        writer = csv.writer(out)
        writer.writerow([
            "id", "osm_type", "osm_id", "name", "name_norm", "name_en",
            "religion", "denomination", "building", "amenity",
            "lon", "lat", "region_code"
        ])
        for feat in features:
            props = feat.get("properties", {})
            geom = feat.get("geometry", {})
            coords = geom.get("coordinates", [None, None])
            writer.writerow([
                feat.get("id", ""),
                props.get("osm_type", ""),
                props.get("osm_id", ""),
                props.get("name", ""),
                props.get("name_norm", ""),
                props.get("name_en", ""),
                props.get("religion", ""),
                props.get("denomination", ""),
                props.get("building", ""),
                props.get("amenity", ""),
                coords[0] if len(coords) > 0 else "",
                coords[1] if len(coords) > 1 else "",
                props.get("region_code", "")
            ])
            count += 1
    return count


def generate_gaps_csv(gaps_json_path, csv_path):
    """Converts worship_gaps_sa.json to a clean CSV export."""
    if not os.path.exists(gaps_json_path):
        return 0

    with open(gaps_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    cells = data.get("cells", []) if isinstance(data, dict) else data
    grid_size = float(data.get("grid_size", 0.004)) if isinstance(data, dict) else 0.004

    count = 0
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as out:
        writer = csv.writer(out)
        writer.writerow(["grid_x", "grid_y", "lon", "lat", "road_length_m", "gap_score", "urgency_score"])
        for row in cells:
            if len(row) >= 4:
                gx, gy, road_len, score = row[0], row[1], row[2], row[3]
                urgency = row[4] if len(row) > 4 else 0.0
                lon = round((float(gx) + 0.5) * grid_size, 6)
                lat = round((float(gy) + 0.5) * grid_size, 6)
                writer.writerow([gx, gy, lon, lat, road_len, score, urgency])
                count += 1
    return count


def generate_suggestions_csv(geojson_path, csv_path):
    """Converts suggested_mosques_sa.geojson to a clean CSV export."""
    if not os.path.exists(geojson_path):
        return 0

    with open(geojson_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    features = data.get("features", [])
    count = 0

    with open(csv_path, "w", encoding="utf-8-sig", newline="") as out:
        writer = csv.writer(out)
        writer.writerow(["wikidata_id", "name_ar", "name_en", "nearest_osm_m", "is_unnamed", "lon", "lat"])
        for feat in features:
            props = feat.get("properties", {})
            geom = feat.get("geometry", {})
            coords = geom.get("coordinates", [None, None])
            writer.writerow([
                props.get("wikidata_id", props.get("qid", "")),
                props.get("name_ar", ""),
                props.get("name_en", ""),
                props.get("nearest_osm_m", ""),
                props.get("is_unnamed", False),
                coords[0] if len(coords) > 0 else "",
                coords[1] if len(coords) > 1 else ""
            ])
            count += 1
    return count


OVERPASS_PRESETS = [
    {
        "id": "places_of_worship_sa",
        "label": {
            "ar": "جميع بيوت ومصليات العبادة في المملكة",
            "en": "All Places of Worship in Saudi Arabia"
        },
        "query": "[out:json][timeout:90];\narea[\"ISO3166-1\"=\"SA\"]->.searchArea;\n(\n  nwr[\"amenity\"=\"place_of_worship\"](area.searchArea);\n);\nout center tags;"
    },
    {
        "id": "unnamed_mosques",
        "label": {
            "ar": "مساجد ومصليات غير محددة الاسم",
            "en": "Unnamed Mosques & Prayer Rooms"
        },
        "query": "[out:json][timeout:60];\narea[\"ISO3166-1\"=\"SA\"]->.searchArea;\n(\n  nwr[\"amenity\"=\"place_of_worship\"][\"!name\"](area.searchArea);\n);\nout center tags;"
    },
    {
        "id": "missing_name_en",
        "label": {
            "ar": "مساجد تفتقر لاسم لاتيني (name:en)",
            "en": "Mosques Missing English Names (name:en)"
        },
        "query": "[out:json][timeout:60];\narea[\"ISO3166-1\"=\"SA\"]->.searchArea;\n(\n  nwr[\"amenity\"=\"place_of_worship\"][\"name\"][\"!name:en\"](area.searchArea);\n);\nout center tags;"
    },
    {
        "id": "building_yes_mosques",
        "label": {
            "ar": "مساجد موسومة building=yes",
            "en": "Mosques Tagged building=yes"
        },
        "query": "[out:json][timeout:60];\narea[\"ISO3166-1\"=\"SA\"]->.searchArea;\n(\n  nwr[\"amenity\"=\"place_of_worship\"][\"building\"=\"yes\"](area.searchArea);\n);\nout center tags;"
    },
    {
        "id": "mosque_outlines_nodes",
        "label": {
            "ar": "مساجد مرسومة كنقاط فقط وليست مباني",
            "en": "Mosques Mapped Only as Nodes"
        },
        "query": "[out:json][timeout:60];\narea[\"ISO3166-1\"=\"SA\"]->.searchArea;\n(\n  node[\"amenity\"=\"place_of_worship\"][\"!building\"](area.searchArea);\n);\nout;"
    }
]


def build_manifest(data_dir=DATA_DIR):
    """Builds manifest.json in the data directory."""
    summary_file = os.path.join(data_dir, "summary.json")
    if os.path.exists(summary_file):
        try:
            with open(summary_file, "r", encoding="utf-8") as f:
                summary = json.load(f)
        except Exception:
            summary = read_summary()
    else:
        summary = read_summary()
    updated_at = summary.get("updated_at") or "2026-10-30T00:00:00Z"
    pbf_date = summary.get("pbf_date") or "2026-10-27"
    dataset_version = "v" + updated_at.replace("-", "").replace(":", "")

    # 1. Generate tabular CSV files alongside GeoJSON
    places_geojson = os.path.join(data_dir, "places_of_worship_sa.geojson")
    places_csv = os.path.join(data_dir, "places_of_worship_sa.csv")
    places_count = generate_places_csv(places_geojson, places_csv)

    gaps_json = os.path.join(data_dir, "worship_gaps_sa.json")
    gaps_csv = os.path.join(data_dir, "worship_gaps_sa.csv")
    gaps_count = generate_gaps_csv(gaps_json, gaps_csv)

    sug_geojson = os.path.join(data_dir, "suggested_mosques_sa.geojson")
    sug_csv = os.path.join(data_dir, "suggested_mosques_sa.csv")
    sug_count = generate_suggestions_csv(sug_geojson, sug_csv)

    boundary_geojson = os.path.join(data_dir, "sa_boundary.geojson")
    regions_geojson = os.path.join(data_dir, "sa_regions.geojson")

    # 2. Build files catalog
    file_configs = [
        {
            "id": "places-sa-geojson",
            "scope": "SA",
            "layer": "places",
            "format": "geojson",
            "filename": "places_of_worship_sa.geojson",
            "features": places_count or summary.get("datasets", {}).get("places", {}).get("count", 0),
        },
        {
            "id": "places-sa-csv",
            "scope": "SA",
            "layer": "places",
            "format": "csv",
            "filename": "places_of_worship_sa.csv",
            "features": places_count,
        },
        {
            "id": "gaps-sa-json",
            "scope": "SA",
            "layer": "gaps",
            "format": "geojson",
            "filename": "worship_gaps_sa.json",
            "features": gaps_count or summary.get("datasets", {}).get("gaps", {}).get("count", 0),
        },
        {
            "id": "gaps-sa-csv",
            "scope": "SA",
            "layer": "gaps",
            "format": "csv",
            "filename": "worship_gaps_sa.csv",
            "features": gaps_count,
        },
        {
            "id": "suggestions-sa-geojson",
            "scope": "SA",
            "layer": "suggestions",
            "format": "geojson",
            "filename": "suggested_mosques_sa.geojson",
            "features": sug_count or summary.get("datasets", {}).get("suggestions", {}).get("count", 0),
        },
        {
            "id": "suggestions-sa-csv",
            "scope": "SA",
            "layer": "suggestions",
            "format": "csv",
            "filename": "suggested_mosques_sa.csv",
            "features": sug_count,
        },
        {
            "id": "boundary-sa-geojson",
            "scope": "SA",
            "layer": "boundary",
            "format": "geojson",
            "filename": "sa_boundary.geojson",
            "features": 1,
        },
        {
            "id": "regions-sa-geojson",
            "scope": "SA",
            "layer": "regions",
            "format": "geojson",
            "filename": "sa_regions.geojson",
            "features": summary.get("datasets", {}).get("regions", {}).get("count", 13),
        },
    ]

    files_list = []
    for cfg in file_configs:
        filepath = os.path.join(data_dir, cfg["filename"])
        if os.path.exists(filepath):
            files_list.append({
                "id": cfg["id"],
                "scope": cfg["scope"],
                "layer": cfg["layer"],
                "format": cfg["format"],
                "path": cfg["filename"],
                "bytes": os.path.getsize(filepath),
                "sha256": sha256_file(filepath),
                "features": cfg["features"],
            })

    manifest = {
        "dataset_version": dataset_version,
        "pbf_date": pbf_date,
        "licence": "ODbL-1.0",
        "attribution": "© OpenStreetMap contributors",
        "files": files_list,
        "overpass_presets": OVERPASS_PRESETS,
    }

    manifest_path = os.path.join(data_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"[OK] Generated {manifest_path} with {len(files_list)} catalogued files.")
    return manifest


if __name__ == "__main__":
    build_manifest()
