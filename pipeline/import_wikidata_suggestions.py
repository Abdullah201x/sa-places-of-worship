"""
Builds suggested_mosques_sa.geojson: Saudi mosques that exist in Wikidata but
not in OpenStreetMap, taken from the "osm x wikidata" project's data/sa.json.

These are suggestions for mappers to verify and add by hand, not an import:
nothing here is uploaded to OSM directly.

Key improvements over raw Wikidata extraction:
1. Distance Filter: Drops any suggestion closer than --min-distance (default 100 m)
   to an existing OSM place of worship in places_of_worship_sa.geojson.
2. Disambiguation Number Cleaning: Wikidata batch imports append serial suffixes
   (e.g. "جامع الرمال 1", "King Abdulaziz Grand Mosque 5") to guarantee label uniqueness.
   This script strips those suffixes while preserving the true mosque name.
3. True Generic / Unnamed Flagging: Only marks mosques as unnamed if the remaining
   name after cleaning is empty or a bare generic word ("مسجد", "جامع", "مصلى", "mosque", "masjid").
4. False Positive Filtering: Drops non-mosque entities accidentally classified as Q32815
   in Wikidata (e.g. universities, stadiums, neighborhoods, hospitals, schools).
5. Compact Precision: Rounds coordinates to 5 decimal places (~1.1 m accuracy)
   to produce an optimized GeoJSON payload.
"""

import argparse
import json
import math
import os
import re
import sys
from collections import defaultdict

from common import (BASE_DIR, RE_MOSQUE_NAME, RE_MOSQUE_NAME_EN, configure_utf8_output,
                    is_generic_mosque_name, update_summary, write_json)

configure_utf8_output()

PLACES_PATH = os.path.join(BASE_DIR, "places_of_worship_sa.geojson")
OUTPUT_PATH = os.path.join(BASE_DIR, "suggested_mosques_sa.geojson")

CAT_WORSHIP = 6
STATUS_MISSING = 0
P31_MOSQUE = "Q32815"

GRID_DEG = 0.01  # ~1.1 km grid cell for spatial indexing

# Regex for non-mosque false positives in Wikidata that erroneously got Q32815
NON_MOSQUE_PATTERNS = [
    re.compile(r"^(جامعة|كلية|مستشفى|مدرسة|ملعب|مطار|شارع|طريق|حي|بلدية|إمارة|مركز شرطة|مواقف|مقبرة|بئر|سوق|حديقة|مكتبة|دوار|محطة)\s", re.I),
    re.compile(r"^(University|College|Hospital|School|Stadium|Airport|Street|Road|Park|Cemetery)\b", re.I),
]

# Natural features (GeoNames-style imports) whose names merely contain a
# mosque word, e.g. "فيضة ام مسجد" (a depression called Umm Masjid).
LANDFORM_PREFIX = re.compile(
    r"^(فيضة|فيضه|شعيب|شعيبة|وادي|جبل|خشم|ريع|قلت|نفود|عرق|حزم|ضلع|نقرة|خبراء|خبرا|روضة)\s"
)

DISAMBIG_REGEX = re.compile(r"\s+[0-9٠-٩]+$")


def find_source(base_dir=None):
    if base_dir is None:
        base_dir = BASE_DIR
    candidates = [
        os.path.abspath(os.path.join(base_dir, "..", "osm x wikidata", "data", "sa.json")),
        os.path.abspath(os.path.join(base_dir, "..", "osm-x-wikidata", "data", "sa.json")),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def distance_m(lat1, lon1, lat2, lon2):
    # Equirectangular approximation; accurate to well under 1% at local ranges.
    x = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    y = math.radians(lat2 - lat1)
    return math.hypot(x, y) * 6371000


def is_non_mosque_entity(name_ar, name_en):
    """Filters out non-mosque entities (landforms, universities, stadiums,
    hospitals, neighborhoods, streets, cemeteries...) that were mistakenly given P31:Q32815 in Wikidata."""
    names = [n.strip() for n in (name_ar, name_en) if n and n.strip()]

    # Landforms first: a mosque word inside a landform's name is just part of
    # its place name, so it must not count as evidence of a mosque.
    if any(LANDFORM_PREFIX.match(n) for n in names):
        return True

    # Non-mosque head nouns must be evaluated before substring mosque checks
    if any(pat.search(n) for pat in NON_MOSQUE_PATTERNS for n in names):
        return True

    # A whole-word mosque term (not جامعة) in either label means a mosque.
    if any(RE_MOSQUE_NAME.search(n) or RE_MOSQUE_NAME_EN.search(n) for n in names):
        return False

    return False


def clean_name(raw_name):
    """Strips Wikidata disambiguation serial suffixes (e.g. 'جامع الرمال 1' -> 'جامع الرمال')."""
    if not raw_name:
        return ""
    cleaned = DISAMBIG_REGEX.sub("", raw_name.strip()).strip()
    return cleaned


def build_grid(places):
    grid = defaultdict(list)
    for f in places:
        coords = f["geometry"]["coordinates"]
        lon, lat = coords[0], coords[1]
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
    return best


def main():
    parser = argparse.ArgumentParser(description="Build Wikidata mosque suggestions missing from OSM.")
    parser.add_argument("--source", default=None, help="Path to osm x wikidata data/sa.json (auto-detected if omitted).")
    parser.add_argument("--min-distance", type=float, default=100.0,
                        help="Drop suggestions closer than this many metres to an existing OSM place of worship (default 100).")
    args = parser.parse_args()

    # On the server run.py downloads sa.json and passes it in the environment.
    source = args.source or os.environ.get("MANARA_WIKIDATA_SOURCE") or find_source()
    if not source or not os.path.exists(source):
        sys.exit("Could not find osm x wikidata data/sa.json. Pass --source.")
    if not os.path.exists(PLACES_PATH):
        sys.exit(f"{PLACES_PATH} not found. Run extract_places.py first.")

    print(f"Reading source: {source}")
    with open(source, "r", encoding="utf-8") as f:
        items = json.load(f)["items"]
    print(f"Reading existing places: {PLACES_PATH}")
    with open(PLACES_PATH, "r", encoding="utf-8") as f:
        places = json.load(f)["features"]

    known_qids = set()
    for feat in places:
        props = feat.get("properties", {})
        qid_tag = props.get("wikidata")
        if qid_tag:
            for q in str(qid_tag).split(";"):
                q_clean = q.strip()
                if q_clean:
                    known_qids.add(q_clean)

    print(f"Loaded {len(known_qids):,} already-mapped Wikidata QIDs to suppress.")

    print(f"Building spatial grid for {len(places):,} OSM places...")
    grid = build_grid(places)

    missing = [i for i in items if i[3] == CAT_WORSHIP and i[4] == STATUS_MISSING and i[7] == P31_MOSQUE]
    candidate_features = []
    dropped_known_qid = 0
    dropped_near = 0
    dropped_non_mosque = 0
    named_count = 0
    unnamed_count = 0

    for item in missing:
        qid_num, lat, lon = item[0], item[1], item[2]
        qid_str = f"Q{qid_num}"
        if qid_str in known_qids:
            dropped_known_qid += 1
            continue

        name_ar_raw = (item[5] or "").strip()
        name_en_raw = (item[6] or "").strip()

        if is_non_mosque_entity(name_ar_raw, name_en_raw):
            dropped_non_mosque += 1
            continue

        nearest = nearest_distance(grid, lat, lon)
        if nearest is not None and nearest < args.min_distance:
            dropped_near += 1
            continue

        # Clean trailing disambiguation numbers while preserving real names
        clean_ar = clean_name(name_ar_raw)
        clean_en = clean_name(name_en_raw)

        has_valid_ar = not is_generic_mosque_name(clean_ar)
        has_valid_en = not is_generic_mosque_name(clean_en)

        is_unnamed = not (has_valid_ar or has_valid_en)
        if is_unnamed:
            unnamed_count += 1
        else:
            named_count += 1

        candidate_features.append({
            "type": "Feature",
            "properties": {
                "qid": qid_str,
                "name_ar": clean_ar if has_valid_ar else (name_ar_raw if name_ar_raw else ""),
                "name_en": clean_en if has_valid_en else (name_en_raw if name_en_raw else ""),
                "nearest_osm_m": round(nearest) if nearest is not None else None,
                "is_unnamed": is_unnamed,
            },
            "geometry": {
                "type": "Point",
                "coordinates": [round(lon, 5), round(lat, 5)]
            },
        })

    # Intra-Wikidata spatial deduplication (< 25m)
    dedup_grid = defaultdict(list)
    features = []
    dropped_duplicate_wikidata = 0
    for f in candidate_features:
        coords = f["geometry"]["coordinates"]
        lon, lat = coords[0], coords[1]
        gx, gy = int(lat // 0.005), int(lon // 0.005)
        is_dup = False
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for prev_lat, prev_lon in dedup_grid.get((gx + dx, gy + dy), ()):
                    if distance_m(lat, lon, prev_lat, prev_lon) < 25.0:
                        is_dup = True
                        break
                if is_dup:
                    break
            if is_dup:
                break
        if is_dup:
            dropped_duplicate_wikidata += 1
            if not f["properties"]["is_unnamed"]:
                named_count -= 1
            else:
                unnamed_count -= 1
            continue
        dedup_grid[(gx, gy)].append((lat, lon))
        features.append(f)

    collection = {
        "type": "FeatureCollection",
        "metadata": {
            "total_suggestions": len(features),
            "named_suggestions": named_count,
            "unnamed_suggestions": unnamed_count,
            "min_distance_m": args.min_distance,
        },
        "features": features
    }

    write_json(OUTPUT_PATH, collection)
    update_summary("suggestions", {
        "count": len(features),
        "named": named_count,
        "unnamed": unnamed_count,
    })

    print(f"Wikidata mosques missing in OSM: {len(missing):,}")
    print(f"Dropped already-mapped QIDs: {dropped_known_qid:,}")
    print(f"Dropped non-mosque entities: {dropped_non_mosque:,}")
    print(f"Dropped duplicate Wikidata entries (<25m): {dropped_duplicate_wikidata:,}")
    print(f"Dropped (< {args.min_distance:.0f} m from an OSM place of worship): {dropped_near:,}")
    print(f"Suggestions written: {len(features):,}")
    print(f"  - Named mosques (cleaned & verified): {named_count:,} ({named_count / len(features) * 100:.1f}%)")
    print(f"  - Unnamed/generic mosques: {unnamed_count:,} ({unnamed_count / len(features) * 100:.1f}%)")
    print(f"Output: {OUTPUT_PATH} ({os.path.getsize(OUTPUT_PATH) / 1024 / 1024:.2f} MB)")


if __name__ == "__main__":
    main()
