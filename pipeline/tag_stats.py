"""
pipeline/tag_stats.py - Generates tag usage statistics for Saudi places of worship.

Counts tag and key usage, co-occurrences, and percentages for places of worship
in Saudi Arabia. Writes `tag_stats_sa.json` and compiled `tags.json` (for the static
tag directory and UI) and records a snapshot into the `tag_usage_history` database table.

Usage:
    python pipeline/tag_stats.py [--geojson PATH] [--pbf PATH] [--out PATH] [--no-db]
"""

import argparse
import datetime
import glob
import json
import os
import sys
from collections import Counter, defaultdict

try:
    import yaml
except ImportError:
    yaml = None

try:
    from common import (BASE_DIR, CODE_DIR, configure_utf8_output, find_pbf, is_worship_tagged,
                        load_boundary, write_json)
except ImportError:
    from pipeline.common import (BASE_DIR, CODE_DIR, configure_utf8_output, find_pbf, is_worship_tagged,
                                 load_boundary, write_json)

configure_utf8_output()

TRACKED_KEYS = [
    "amenity", "religion", "denomination", "building",
    "name", "name:ar", "name:en",
    "female", "wheelchair", "capacity", "opening_hours", "addr:city", "wikidata"
]

TRACKED_TAGS = [
    ("amenity", "place_of_worship"),
    ("religion", "muslim"),
    ("building", "mosque"),
    ("building", "yes"),
    ("denomination", "sunni"),
    ("denomination", "shia"),
    ("denomination", "unknown"),
    ("female", "yes"),
    ("female", "no"),
    ("female", "dedicated"),
    ("wheelchair", "yes"),
    ("wheelchair", "limited"),
    ("wheelchair", "no"),
]


def props_to_tags(props):
    """Normalize properties from GeoJSON into canonical OSM tags dict."""
    tags = {}
    for k, v in props.items():
        if v is None or v == "":
            continue
        if k in ("osm_id", "geom_type", "version", "edited_at", "edited_by",
                 "region_id", "ml_anomaly", "footprint_area", "poi_node_id"):
            continue
        if k == "name_en":
            tags["name:en"] = str(v).strip()
        elif k == "name_original":
            tags["name:ar"] = str(v).strip()
        elif k == "name_en_original":
            tags["name:en_original"] = str(v).strip()
        elif k == "addr_city":
            tags["addr:city"] = str(v).strip()
        else:
            tags[k] = str(v).strip()
    return tags


def compute_tag_stats(places_tags_iter, total_places=None, as_of=None, dataset_version=None):
    """
    Computes tag usage counts, co-occurrences, and percentages.
    
    places_tags_iter: iterable of dicts of tags, or list of tag dicts.
    """
    tags_list = list(places_tags_iter)
    total = total_places if total_places is not None else len(tags_list)
    if total == 0:
        total = 1  # avoid ZeroDivisionError

    key_counts = Counter()
    tag_counts = Counter()
    key_with_keys = defaultdict(Counter)
    tag_with_keys = defaultdict(Counter)

    for tags in tags_list:
        present_keys = set(tags.keys())
        for k in present_keys:
            key_counts[k] += 1
            for other in present_keys:
                if other != k:
                    key_with_keys[k][other] += 1

        for k, v in tags.items():
            tag_str = f"{k}={v}"
            tag_counts[tag_str] += 1
            for other in present_keys:
                if other != k:
                    tag_with_keys[tag_str][other] += 1

    # Structure keys output
    keys_out = {}
    for k in sorted(TRACKED_KEYS):
        cnt = key_counts.get(k, 0)
        co_occur = {
            other: key_with_keys[k][other]
            for other in sorted(key_with_keys[k], key=lambda x: key_with_keys[k][x], reverse=True)[:10]
        }
        keys_out[k] = {
            "count": cnt,
            "percentage": round((cnt / total) * 100, 2),
            "with_key": co_occur
        }

    # Structure tags output
    tags_out = {}
    for k, v in TRACKED_TAGS:
        tag_str = f"{k}={v}"
        cnt = tag_counts.get(tag_str, 0)
        co_occur = {
            other: tag_with_keys[tag_str][other]
            for other in sorted(tag_with_keys[tag_str], key=lambda x: tag_with_keys[tag_str][x], reverse=True)[:10]
        }
        tags_out[tag_str] = {
            "key": k,
            "value": v,
            "count": cnt,
            "percentage": round((cnt / total) * 100, 2),
            "with_key": co_occur
        }

    as_of_stamp = as_of or datetime.datetime.now(datetime.timezone.utc).isoformat()
    version_str = dataset_version or as_of_stamp[:10].replace("-", "")

    return {
        "dataset_version": version_str,
        "as_of": as_of_stamp,
        "total_places": len(tags_list),
        "keys": keys_out,
        "tags": tags_out
    }


def compile_tags_json(tags_dir, stats, out_path):
    """Compiles content/tags/*.yaml merged with usage_sa into /data/tags.json."""
    if not yaml:
        print("yaml module not available; writing empty tags.json")
        write_json(out_path, [])
        return []

    tag_files = glob.glob(os.path.join(tags_dir, "*.yaml"))
    tag_docs = []
    for p in sorted(tag_files):
        with open(p, "r", encoding="utf-8") as f:
            doc = yaml.safe_load(f)
        k = doc.get("key")
        v = doc.get("value")
        if v:
            tag_key = f"{k}={v}"
            tag_info = stats.get("tags", {}).get(tag_key)
        else:
            tag_info = stats.get("keys", {}).get(k)

        if tag_info:
            doc["usage_sa"] = {
                "count": tag_info.get("count", 0),
                "percentage": tag_info.get("percentage", 0.0),
                "with_key": tag_info.get("with_key", {}),
                "as_of": stats.get("as_of")
            }
        tag_docs.append(doc)

    write_json(out_path, tag_docs)
    return tag_docs


def load_from_geojson(geojson_path):
    """Loads place tags from places_of_worship_sa.geojson."""
    with open(geojson_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    for feat in data.get("features", []):
        yield props_to_tags(feat.get("properties", {}))


def record_stats_to_db(stats, db_url=None):
    """Inserts or updates rows in the tag_usage_history table."""
    url = db_url or os.environ.get("MANARA_DB_URL") or os.environ.get("DATABASE_URL")
    if not url:
        return False

    try:
        import psycopg2
        import psycopg2.extras
    except ImportError:
        print("psycopg2 not installed; skipping database record")
        return False

    version = stats["dataset_version"]
    total = stats["total_places"]

    rows = []
    # Key-level rows (tag_value = None)
    for k, info in stats["keys"].items():
        rows.append((
            version,
            k,
            None,
            info["count"],
            total,
            json.dumps(info["with_key"])
        ))

    # Tag-level rows (tag_value = val)
    for tag_str, info in stats["tags"].items():
        rows.append((
            version,
            info["key"],
            info["value"],
            info["count"],
            total,
            json.dumps(info["with_key"])
        ))

    try:
        with psycopg2.connect(url) as conn:
            with conn.cursor() as cur:
                psycopg2.extras.execute_values(
                    cur,
                    """
                    INSERT INTO tag_usage_history (
                        dataset_version, tag_key, tag_value, count, total_places, with_keys
                    ) VALUES %s
                    ON CONFLICT (dataset_version, tag_key, tag_value)
                    DO UPDATE SET
                        count = EXCLUDED.count,
                        total_places = EXCLUDED.total_places,
                        with_keys = EXCLUDED.with_keys,
                        recorded_at = NOW();
                    """,
                    rows
                )
            conn.commit()
        print(f"Recorded {len(rows)} tag usage metrics to tag_usage_history")
        return True
    except Exception as e:
        print(f"Warning: Failed to record tag stats to database: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Generate Saudi places of worship tag statistics")
    parser.add_argument("--geojson", help="Path to places_of_worship_sa.geojson")
    parser.add_argument("--pbf", help="Path to GCC osm.pbf extract")
    parser.add_argument("--out", help="Path to output tag_stats_sa.json")
    parser.add_argument("--tags-dir", help="Path to content/tags")
    parser.add_argument("--tags-out", help="Path to output tags.json")
    parser.add_argument("--no-db", action="store_true", help="Skip database write")
    args = parser.parse_args()

    geojson_path = args.geojson or os.path.join(BASE_DIR, "places_of_worship_sa.geojson")
    out_path = args.out or os.path.join(BASE_DIR, "tag_stats_sa.json")
    tags_dir = args.tags_dir or os.environ.get("MANARA_TAGS_DIR")
    if not tags_dir:
        for candidate in [
            os.path.join(CODE_DIR, "content", "tags"),
            os.path.join(CODE_DIR, "..", "content", "tags"),
            os.path.join(BASE_DIR, "content", "tags"),
        ]:
            if os.path.isdir(candidate):
                tags_dir = candidate
                break
    tags_out = args.tags_out or os.path.join(BASE_DIR, "tags.json")

    if not os.path.exists(geojson_path):
        print(f"Error: {geojson_path} not found.")
        sys.exit(1)

    print(f"Computing tag statistics from {geojson_path}...")
    tags_iter = list(load_from_geojson(geojson_path))
    stats = compute_tag_stats(tags_iter)

    write_json(out_path, stats)
    print(f"Wrote {out_path} ({stats['total_places']} places of worship processed)")

    if tags_dir and os.path.exists(tags_dir):
        docs = compile_tags_json(tags_dir, stats, tags_out)
        print(f"Wrote {tags_out} ({len(docs)} tag documents compiled with live usage stats)")
    else:
        write_json(tags_out, [])
        print(f"Wrote empty {tags_out} (tags_dir not found)")

    if not args.no_db:
        record_stats_to_db(stats)


if __name__ == "__main__":
    main()
