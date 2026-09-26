"""
Builds suggested_mosques_sa.geojson: Saudi mosques that exist in Wikidata but
not in OpenStreetMap, taken from the "osm x wikidata" project's data/sa.json.

These are suggestions for mappers to verify and add by hand, not an import:
nothing here is uploaded to OSM. Mosques within --min-distance metres of an
existing OSM place of worship (places_of_worship_sa.geojson) are dropped as
likely duplicates.

Run after extract_places.py (it reads that script's output).
"""

import argparse
import json
import math
import os
import re
import sys
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PLACES_PATH = os.path.join(BASE_DIR, "places_of_worship_sa.geojson")
OUTPUT_PATH = os.path.join(BASE_DIR, "suggested_mosques_sa.geojson")

# osm x wikidata compact item tuple (see its pipeline/matcher.py):
# [0: qid_num, 1: lat, 2: lon, 3: cat_id, 4: status, 5: name_ar, 6: name_en, 7: p31, ...]
CAT_WORSHIP = 6
STATUS_MISSING = 0
P31_MOSQUE = "Q32815"

GRID_DEG = 0.01  # ~1.1 km; must be larger than the max distance we search

GENERIC_NAMES = {"مسجد", "جامع", "مصلى", "mosque", "masjid", "masjid mosque", "jami", "jame"}


def find_source(base_dir=None):
    if base_dir is None:
        base_dir = BASE_DIR
    candidates = [
        os.path.abspath(os.path.join(base_dir, "..", "osm x wikidata", "data", "sa.json")),
        os.path.abspath(os.path.join(base_dir, "..", "osm-x-wikidata", "data", "sa.json")),
        r"C:\Users\abdul\Desktop\osm x wikidata\data\sa.json",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def distance_m(lat1, lon1, lat2, lon2):
    # Equirectangular approximation; accurate to well under 1% at these ranges.
    x = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    y = math.radians(lat2 - lat1)
    return math.hypot(x, y) * 6371000


def is_low_quality_name(name_ar, name_en):
    """Flags names that look auto-generated: missing, a bare generic word, or
    ending in a serial number (e.g. "Masjid Mosque 9", "مسجد البلدية 11")."""
    names = [n.strip() for n in (name_ar, name_en) if n and n.strip()]
    if not names:
        return True
    for n in names:
        if n.lower() in GENERIC_NAMES or re.search(r"\s[0-9٠-٩]+$", n):
            return True
    return False


def build_grid(places):
    grid = defaultdict(list)
    for f in places:
        lon, lat = f["geometry"]["coordinates"][:2]
        grid[(int(lat // GRID_DEG), int(lon // GRID_DEG))].append((lat, lon))
    return grid


def nearest_distance(grid, lat, lon):
    gx, gy = int(lat // GRID_DEG), int(lon // GRID_DEG)
    best = None
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for plat, plon in grid.get((gx + dx, gy + dy), ()):
                d = distance_m(lat, lon, plat, plon)
                if best is None or d < best:
                    best = d
    return best  # None when nothing within ~1 km


def main():
    parser = argparse.ArgumentParser(description="Build Wikidata mosque suggestions missing from OSM.")
    parser.add_argument("--source", default=None, help="Path to osm x wikidata data/sa.json (auto-detected if omitted).")
    parser.add_argument("--min-distance", type=float, default=100.0,
                        help="Drop suggestions closer than this many metres to an existing OSM place of worship (default 100).")
    args = parser.parse_args()

    source = args.source or find_source()
    if not source or not os.path.exists(source):
        sys.exit("Could not find osm x wikidata data/sa.json. Pass --source.")
    if not os.path.exists(PLACES_PATH):
        sys.exit(f"{PLACES_PATH} not found. Run extract_places.py first.")

    with open(source, "r", encoding="utf-8") as f:
        items = json.load(f)["items"]
    with open(PLACES_PATH, "r", encoding="utf-8") as f:
        places = json.load(f)["features"]

    grid = build_grid(places)

    missing = [i for i in items if i[3] == CAT_WORSHIP and i[4] == STATUS_MISSING and i[7] == P31_MOSQUE]
    features = []
    dropped_near = 0
    low_quality = 0
    for item in missing:
        qid_num, lat, lon = item[0], item[1], item[2]
        name_ar, name_en = item[5], item[6]
        nearest = nearest_distance(grid, lat, lon)
        if nearest is not None and nearest < args.min_distance:
            dropped_near += 1
            continue
        lq = is_low_quality_name(name_ar, name_en)
        low_quality += lq
        features.append({
            "type": "Feature",
            "properties": {
                "qid": f"Q{qid_num}",
                "name_ar": name_ar,
                "name_en": name_en,
                "nearest_osm_m": round(nearest) if nearest is not None else None,
                "low_quality_name": lq,
            },
            "geometry": {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]},
        })

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, ensure_ascii=False, separators=(",", ":"))

    print(f"Source: {source}")
    print(f"Wikidata mosques missing in OSM: {len(missing):,}")
    print(f"Dropped (< {args.min_distance:.0f} m from an OSM place of worship): {dropped_near:,}")
    print(f"Suggestions written: {len(features):,} ({low_quality:,} with low-quality names)")
    print(f"Output: {OUTPUT_PATH} ({os.path.getsize(OUTPUT_PATH) / 1024 / 1024:.1f} MB)")


if __name__ == "__main__":
    main()
