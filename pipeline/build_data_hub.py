#!/usr/bin/env python3
"""
Generates the Data Hub manifest (manifest.json) and tabular CSV exports
for Saudi places of worship, coverage gaps, and Wikidata suggestions,
both at the national level and sliced for all 13 administrative provinces.

Conforms to REDESIGN.md §4.6 DataManifest specifications.
Licence: ODbL-1.0
Attribution: © OpenStreetMap contributors
"""

import csv
import hashlib
import json
import os
import sys

from common import BASE_DIR, configure_utf8_output, normalize_arabic, read_summary, write_json

configure_utf8_output()

DATA_DIR = os.environ.get("MANARA_DATA_DIR", BASE_DIR)

_OSM_TYPE_BY_GEOM = {"Point": "node", "Polygon": "way", "MultiPolygon": "relation", "Relation": "relation"}


def sha256_file(filepath):
    """Calculates SHA-256 hexadecimal digest of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def write_places_csv_features(features, csv_path):
    """Writes list of GeoJSON features to CSV with UTF-8 BOM."""
    os.makedirs(os.path.dirname(os.path.abspath(csv_path)), exist_ok=True)
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
            osm_type = props.get("osm_type") or _OSM_TYPE_BY_GEOM.get(props.get("geom_type", ""), "")
            osm_id = props.get("osm_id", "")
            feat_id = feat.get("id") or props.get("id") or (f"{osm_type}/{osm_id}" if osm_type and osm_id != "" else "")
            raw_name = props.get("name_original", "")
            writer.writerow([
                feat_id,
                osm_type,
                osm_id,
                props.get("name", ""),
                normalize_arabic(raw_name) if raw_name else "",
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


def generate_places_csv(geojson_path, csv_path):
    """Converts places_of_worship_sa.geojson to a clean CSV export."""
    if not os.path.exists(geojson_path):
        return 0

    with open(geojson_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    features = data.get("features", [])
    return write_places_csv_features(features, csv_path)


def write_gaps_csv_cells(cells, grid_size, csv_path):
    """Writes list of grid gap cells to CSV with UTF-8 BOM."""
    os.makedirs(os.path.dirname(os.path.abspath(csv_path)), exist_ok=True)
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


def generate_gaps_csv(gaps_json_path, csv_path):
    """Converts worship_gaps_sa.json to a clean CSV export."""
    if not os.path.exists(gaps_json_path):
        return 0

    with open(gaps_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    cells = data.get("cells", []) if isinstance(data, dict) else data
    grid_size = float(data.get("grid_size", 0.004)) if isinstance(data, dict) else 0.004
    return write_gaps_csv_cells(cells, grid_size, csv_path)


def write_suggestions_csv_features(features, csv_path):
    """Writes list of Wikidata suggestion features to CSV with UTF-8 BOM."""
    os.makedirs(os.path.dirname(os.path.abspath(csv_path)), exist_ok=True)
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


def generate_suggestions_csv(geojson_path, csv_path):
    """Converts suggested_mosques_sa.geojson to a clean CSV export."""
    if not os.path.exists(geojson_path):
        return 0

    with open(geojson_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    features = data.get("features", [])
    return write_suggestions_csv_features(features, csv_path)


def load_prepared_regions(data_dir=DATA_DIR):
    """Loads sa_regions.geojson as prepared shapely polygons, or [] if unavailable."""
    regions_path = os.path.join(data_dir, "sa_regions.geojson")
    if not os.path.exists(regions_path):
        return []

    try:
        from shapely.geometry import shape
        from shapely.prepared import prep
    except ImportError:
        print("[WARN] shapely not available; skipping region assignment")
        return []

    with open(regions_path, "r", encoding="utf-8") as f:
        reg_data = json.load(f)

    prepared_regions = []
    for feat in reg_data.get("features", []):
        props = feat.get("properties", {})
        code = props.get("code") or feat.get("id")
        if not code:
            continue
        geom = shape(feat.get("geometry"))
        prepared_regions.append({
            "code": code,
            "name": props.get("name", ""),
            "name_en": props.get("name_en", ""),
            "prep": prep(geom),
            "bounds": geom.bounds,
        })
    return prepared_regions


def make_point_classifier(prepared_regions):
    """Returns classify(lon, lat) -> region code, or None outside every region."""
    from shapely.geometry import Point

    def classify_point(lon, lat):
        pt = Point(lon, lat)
        for r in prepared_regions:
            minx, miny, maxx, maxy = r["bounds"]
            if minx <= lon <= maxx and miny <= lat <= maxy:
                if r["prep"].contains(pt):
                    return r["code"]
        return None

    return classify_point


def stamp_region_codes(data_dir=DATA_DIR):
    """
    Writes properties.region_code onto every feature of places_of_worship_sa.geojson.
    The frontend's QA view filters by region client-side, and the raw extract
    carries no region. Returns the number of features that got a region.
    """
    places_path = os.path.join(data_dir, "places_of_worship_sa.geojson")
    if not os.path.exists(places_path):
        return 0

    prepared_regions = load_prepared_regions(data_dir)
    if not prepared_regions:
        return 0
    classify_point = make_point_classifier(prepared_regions)

    with open(places_path, "r", encoding="utf-8") as f:
        places_data = json.load(f)

    stamped = 0
    for feat in places_data.get("features", []):
        coords = (feat.get("geometry") or {}).get("coordinates", [])
        if len(coords) < 2:
            continue
        props = feat.setdefault("properties", {})
        code = classify_point(coords[0], coords[1])
        if code:
            props["region_code"] = code
            stamped += 1
        else:
            props.pop("region_code", None)

    write_json(places_path, places_data)
    return stamped


def generate_regional_exports(data_dir=DATA_DIR):
    """
    Slices places, gaps, and suggestions into per-region datasets
    for Saudi Arabia's 13 administrative provinces (SA-01 to SA-14).
    Writes them into {data_dir}/by-region/
    Returns a list of file metadata dicts for manifest.json.
    """
    prepared_regions = load_prepared_regions(data_dir)
    if not prepared_regions:
        return []

    classify_point = make_point_classifier(prepared_regions)

    by_region_dir = os.path.join(data_dir, "by-region")
    os.makedirs(by_region_dir, exist_ok=True)

    files_list = []

    # 1. Places per region
    places_path = os.path.join(data_dir, "places_of_worship_sa.geojson")
    if os.path.exists(places_path):
        with open(places_path, "r", encoding="utf-8") as f:
            places_data = json.load(f)
        places_by_reg = {r["code"]: [] for r in prepared_regions}
        for feat in places_data.get("features", []):
            coords = feat.get("geometry", {}).get("coordinates", [])
            if len(coords) >= 2:
                reg_code = feat.get("properties", {}).get("region_code") or classify_point(coords[0], coords[1])
                if reg_code and reg_code in places_by_reg:
                    feat["properties"]["region_code"] = reg_code
                    places_by_reg[reg_code].append(feat)

        for code, feats in places_by_reg.items():
            if not feats:
                continue
            geo_fn = f"places_{code}.geojson"
            csv_fn = f"places_{code}.csv"
            geo_rel = f"by-region/{geo_fn}"
            csv_rel = f"by-region/{csv_fn}"
            geo_full = os.path.join(by_region_dir, geo_fn)
            csv_full = os.path.join(by_region_dir, csv_fn)

            write_json(geo_full, {"type": "FeatureCollection", "features": feats})
            write_places_csv_features(feats, csv_full)

            files_list.append({
                "id": f"places-{code}-geojson",
                "scope": code,
                "layer": "places",
                "format": "geojson",
                "path": geo_rel,
                "bytes": os.path.getsize(geo_full),
                "sha256": sha256_file(geo_full),
                "features": len(feats),
            })
            files_list.append({
                "id": f"places-{code}-csv",
                "scope": code,
                "layer": "places",
                "format": "csv",
                "path": csv_rel,
                "bytes": os.path.getsize(csv_full),
                "sha256": sha256_file(csv_full),
                "features": len(feats),
            })

    # 2. Gaps per region
    gaps_path = os.path.join(data_dir, "worship_gaps_sa.json")
    if os.path.exists(gaps_path):
        with open(gaps_path, "r", encoding="utf-8") as f:
            gaps_data = json.load(f)
        cells = gaps_data.get("cells", []) if isinstance(gaps_data, dict) else gaps_data
        grid_size = float(gaps_data.get("grid_size", 0.004)) if isinstance(gaps_data, dict) else 0.004
        gaps_by_reg = {r["code"]: [] for r in prepared_regions}
        for cell in cells:
            if len(cell) >= 2:
                lon = (float(cell[0]) + 0.5) * grid_size
                lat = (float(cell[1]) + 0.5) * grid_size
                reg_code = classify_point(lon, lat)
                if reg_code and reg_code in gaps_by_reg:
                    gaps_by_reg[reg_code].append(cell)

        for code, reg_cells in gaps_by_reg.items():
            if not reg_cells:
                continue
            json_fn = f"worship_gaps_{code}.json"
            csv_fn = f"worship_gaps_{code}.csv"
            json_rel = f"by-region/{json_fn}"
            csv_rel = f"by-region/{csv_fn}"
            json_full = os.path.join(by_region_dir, json_fn)
            csv_full = os.path.join(by_region_dir, csv_fn)

            write_json(json_full, {
                    "grid_size": grid_size,
                    "fields": ["grid_x", "grid_y", "road_length_m", "gap_score", "urgency_score"],
                    "cells": reg_cells
                })
            write_gaps_csv_cells(reg_cells, grid_size, csv_full)

            files_list.append({
                "id": f"gaps-{code}-json",
                "scope": code,
                "layer": "gaps",
                "format": "json",
                "path": json_rel,
                "bytes": os.path.getsize(json_full),
                "sha256": sha256_file(json_full),
                "features": len(reg_cells),
            })
            files_list.append({
                "id": f"gaps-{code}-csv",
                "scope": code,
                "layer": "gaps",
                "format": "csv",
                "path": csv_rel,
                "bytes": os.path.getsize(csv_full),
                "sha256": sha256_file(csv_full),
                "features": len(reg_cells),
            })

    # 3. Suggestions per region
    sugs_path = os.path.join(data_dir, "suggested_mosques_sa.geojson")
    if os.path.exists(sugs_path):
        with open(sugs_path, "r", encoding="utf-8") as f:
            sugs_data = json.load(f)
        sugs_by_reg = {r["code"]: [] for r in prepared_regions}
        for feat in sugs_data.get("features", []):
            coords = feat.get("geometry", {}).get("coordinates", [])
            if len(coords) >= 2:
                reg_code = classify_point(coords[0], coords[1])
                if reg_code and reg_code in sugs_by_reg:
                    sugs_by_reg[reg_code].append(feat)

        for code, feats in sugs_by_reg.items():
            if not feats:
                continue
            geo_fn = f"suggested_mosques_{code}.geojson"
            csv_fn = f"suggested_mosques_{code}.csv"
            geo_rel = f"by-region/{geo_fn}"
            csv_rel = f"by-region/{csv_fn}"
            geo_full = os.path.join(by_region_dir, geo_fn)
            csv_full = os.path.join(by_region_dir, csv_fn)

            write_json(geo_full, {"type": "FeatureCollection", "features": feats})
            write_suggestions_csv_features(feats, csv_full)

            files_list.append({
                "id": f"suggestions-{code}-geojson",
                "scope": code,
                "layer": "suggestions",
                "format": "geojson",
                "path": geo_rel,
                "bytes": os.path.getsize(geo_full),
                "sha256": sha256_file(geo_full),
                "features": len(feats),
            })
            files_list.append({
                "id": f"suggestions-{code}-csv",
                "scope": code,
                "layer": "suggestions",
                "format": "csv",
                "path": csv_rel,
                "bytes": os.path.getsize(csv_full),
                "sha256": sha256_file(csv_full),
                "features": len(feats),
            })

    return files_list


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

    # 0. Region codes must be on the places file before it is exported or catalogued
    stamp_region_codes(data_dir)

    # 1. Generate tabular CSV files alongside GeoJSON (National)
    places_geojson = os.path.join(data_dir, "places_of_worship_sa.geojson")
    places_csv = os.path.join(data_dir, "places_of_worship_sa.csv")
    places_count = generate_places_csv(places_geojson, places_csv)

    gaps_json = os.path.join(data_dir, "worship_gaps_sa.json")
    gaps_csv = os.path.join(data_dir, "worship_gaps_sa.csv")
    gaps_count = generate_gaps_csv(gaps_json, gaps_csv)

    sug_geojson = os.path.join(data_dir, "suggested_mosques_sa.geojson")
    sug_csv = os.path.join(data_dir, "suggested_mosques_sa.csv")
    sug_count = generate_suggestions_csv(sug_geojson, sug_csv)

    # 2. Build files catalog for National datasets
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
            "format": "json",
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
        {
            "id": "places-sa-pmtiles",
            "scope": "SA",
            "layer": "places",
            "format": "pmtiles",
            "filename": "places.pmtiles",
            "features": places_count or summary.get("datasets", {}).get("places", {}).get("count", 0),
        },
        {
            "id": "gaps-sa-pmtiles",
            "scope": "SA",
            "layer": "gaps",
            "format": "pmtiles",
            "filename": "gaps.pmtiles",
            "features": gaps_count or summary.get("datasets", {}).get("gaps", {}).get("count", 0),
        },
        {
            "id": "suggestions-sa-pmtiles",
            "scope": "SA",
            "layer": "suggestions",
            "format": "pmtiles",
            "filename": "suggestions.pmtiles",
            "features": sug_count or summary.get("datasets", {}).get("suggestions", {}).get("count", 0),
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

    # 3. Generate Per-Region Slices (13 Provinces)
    regional_files = generate_regional_exports(data_dir=data_dir)
    files_list.extend(regional_files)

    manifest = {
        "dataset_version": dataset_version,
        "pbf_date": pbf_date,
        "licence": "ODbL-1.0",
        "attribution": "© OpenStreetMap contributors",
        "files": files_list,
        "overpass_presets": OVERPASS_PRESETS,
    }

    manifest_path = os.path.join(data_dir, "manifest.json")
    write_json(manifest_path, manifest)

    print(f"[OK] Generated {manifest_path} with {len(files_list)} catalogued files.")
    return manifest


if __name__ == "__main__":
    build_manifest()
