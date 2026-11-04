#!/usr/bin/env python3
"""
Detects changes between consecutive daily Manara datasets.

Generates change events (created, modified, deleted, upgraded),
evaluates change flags (name-removed, religion-changed, deleted-named-mosque, etc.),
and records them in the `change_events` table (source = 'daily').
Also reconciles with minutely live replication events.
"""

import json
import math
import os
import sys
import time
from typing import Any

from change_rules import compute_tag_diff, evaluate_change_flags
from common import (
    BASE_DIR,
    configure_utf8_output,
    normalize_arabic,
    read_summary,
)

configure_utf8_output()

DATABASE_URL = os.environ.get("MANARA_DATABASE_URL") or os.environ.get("DATABASE_URL")


def calculate_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in metres."""
    r = 6371000.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(d_lon / 2) ** 2)
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def diff_places(
    old_places: list[dict[str, Any]],
    new_places: list[dict[str, Any]],
    dataset_version: str = "",
    prev_dataset_version: str = "",
    old_issues_by_place: dict[tuple[str, int], set[str]] | None = None,
    new_issues_by_place: dict[tuple[str, int], set[str]] | None = None,
) -> list[dict[str, Any]]:
    """
    Pure differential analysis between two place snapshots.
    Each place dict has keys:
      osm_type, osm_id, version, name, name_norm, name_en,
      religion, denomination, building, amenity, poi_node_id,
      tags, coords (lon, lat), region_code.
    """
    old_map = {f"{p.get('osm_type')}/{p.get('osm_id')}": p for p in old_places}
    new_map = {f"{p.get('osm_type')}/{p.get('osm_id')}": p for p in new_places}

    old_issues = old_issues_by_place or {}
    new_issues = new_issues_by_place or {}

    old_keys = set(old_map.keys())
    new_keys = set(new_map.keys())

    events = []

    # 1. Detect New & Upgraded Places
    # Map old nodes by id for quick upgrade lookup
    old_nodes_by_id = {
        p.get("osm_id"): p
        for p in old_places
        if p.get("osm_type") == "node"
    }

    for ref in new_keys - old_keys:
        new_p = new_map[ref]
        new_tags = new_p.get("tags") or {}
        new_coords = new_p.get("coords") or [0.0, 0.0]

        # Check for upgrade: way that subsumed a deleted POI node
        poi_node_id = new_p.get("poi_node_id")
        upgraded_from = None
        if poi_node_id and poi_node_id in old_nodes_by_id and f"node/{poi_node_id}" not in new_map:
            upgraded_from = f"node/{poi_node_id}"

        # Potential duplicate check (<50m to another old place with matching normalized name)
        is_pot_dup = False
        new_norm = new_p.get("name_norm", "")
        if new_norm and len(new_norm) > 2:
            for op in old_places:
                if op.get("name_norm") == new_norm:
                    op_coords = op.get("coords") or [0.0, 0.0]
                    if calculate_distance_m(new_coords[1], new_coords[0], op_coords[1], op_coords[0]) < 50.0:
                        is_pot_dup = True
                        break

        kind = "upgraded" if upgraded_from else "created"
        flags = evaluate_change_flags(
            old_tags={},
            new_tags=new_tags,
            is_deleted=False,
            is_upgraded=bool(upgraded_from),
            is_outside_boundary=not bool(new_p.get("region_code")),
            is_potential_duplicate=is_pot_dup,
            normalized_name=new_p.get("name_norm", ""),
            normalized_name_ar=normalize_arabic(new_tags.get("name:ar", "")),
        )

        events.append({
            "source": "daily",
            "kind": kind,
            "osm_type": new_p.get("osm_type"),
            "osm_id": new_p.get("osm_id"),
            "prev_ref": upgraded_from,
            "dataset_version": dataset_version,
            "prev_dataset_version": prev_dataset_version,
            "version_before": None,
            "version_after": new_p.get("version"),
            "name": new_p.get("name") or new_p.get("name_en") or "",
            "region_code": new_p.get("region_code"),
            "coords": new_coords,
            "tag_diff": compute_tag_diff({}, new_tags),
            "flags": flags,
        })

    # 2. Detect Modified Places
    for ref in old_keys & new_keys:
        old_p = old_map[ref]
        new_p = new_map[ref]

        old_tags = old_p.get("tags") or {}
        new_tags = new_p.get("tags") or {}
        old_ver = old_p.get("version")
        new_ver = new_p.get("version")

        old_coords = old_p.get("coords") or [0.0, 0.0]
        new_coords = new_p.get("coords") or [0.0, 0.0]
        dist_m = calculate_distance_m(old_coords[1], old_coords[0], new_coords[1], new_coords[0])
        is_moved_far = dist_m > 200.0

        place_key = (new_p.get("osm_type"), new_p.get("osm_id"))
        resolved_rules = list(old_issues.get(place_key, set()) - new_issues.get(place_key, set()))

        tag_diff = compute_tag_diff(old_tags, new_tags)
        is_ver_changed = (old_ver is not None and new_ver is not None and new_ver != old_ver)

        if tag_diff or is_ver_changed or is_moved_far:
            flags = evaluate_change_flags(
                old_tags=old_tags,
                new_tags=new_tags,
                is_deleted=False,
                is_outside_boundary=not bool(new_p.get("region_code")),
                is_moved_far=is_moved_far,
                normalized_name=new_p.get("name_norm", ""),
                normalized_name_ar=normalize_arabic(new_tags.get("name:ar", "")),
                resolved_issues=resolved_rules,
            )

            events.append({
                "source": "daily",
                "kind": "modified",
                "osm_type": new_p.get("osm_type"),
                "osm_id": new_p.get("osm_id"),
                "prev_ref": None,
                "dataset_version": dataset_version,
                "prev_dataset_version": prev_dataset_version,
                "version_before": old_ver,
                "version_after": new_ver,
                "name": new_p.get("name") or new_p.get("name_en") or "",
                "region_code": new_p.get("region_code"),
                "coords": new_coords,
                "tag_diff": tag_diff,
                "flags": flags,
            })

    # 3. Detect Deleted Places
    # An old node upgraded to a way was already marked upgraded above
    upgraded_node_refs = {
        e["prev_ref"] for e in events if e["kind"] == "upgraded" and e.get("prev_ref")
    }

    for ref in old_keys - new_keys:
        if ref in upgraded_node_refs:
            continue  # Node was legitimately upgraded to building outline

        old_p = old_map[ref]
        old_tags = old_p.get("tags") or {}
        flags = evaluate_change_flags(
            old_tags=old_tags,
            new_tags={},
            is_deleted=True,
            is_upgraded=False,
            normalized_name=old_p.get("name_norm", ""),
        )

        events.append({
            "source": "daily",
            "kind": "deleted",
            "osm_type": old_p.get("osm_type"),
            "osm_id": old_p.get("osm_id"),
            "prev_ref": None,
            "dataset_version": dataset_version,
            "prev_dataset_version": prev_dataset_version,
            "version_before": old_p.get("version"),
            "version_after": None,
            "name": old_p.get("name") or old_p.get("name_en") or "",
            "region_code": old_p.get("region_code"),
            "coords": old_p.get("coords") or [0.0, 0.0],
            "tag_diff": compute_tag_diff(old_tags, {}),
            "flags": flags,
        })

    return events


def save_change_events_to_db(conn, events: list[dict[str, Any]], pbf_timestamp: str | None = None):
    """
    Inserts change events into `change_events` and reconciles with live events.
    """
    if not events:
        return

    insert_sql = """
    INSERT INTO change_events (
        source, confirmed, osm_timestamp, observed_at, dataset_version,
        prev_dataset_version, osm_type, osm_id, prev_ref, kind, flags,
        geom, region_code, name, tag_diff, version_before, version_after
    ) VALUES (
        %s, %s, %s, NOW(), %s,
        %s, %s, %s, %s, %s, %s,
        ST_SetSRID(ST_Point(%s, %s), 4326), %s, %s, %s, %s, %s
    )
    ON CONFLICT DO NOTHING;
    """

    with conn.transaction():
        with conn.cursor() as cur:
            for ev in events:
                coords = ev.get("coords") or [0.0, 0.0]
                cur.execute(insert_sql, (
                    ev["source"],
                    True,  # Daily events are confirmed ground truth
                    pbf_timestamp,
                    ev.get("dataset_version"),
                    ev.get("prev_dataset_version"),
                    ev["osm_type"],
                    ev["osm_id"],
                    ev.get("prev_ref"),
                    ev["kind"],
                    json.dumps(ev.get("flags") or []),
                    coords[0],
                    coords[1],
                    ev.get("region_code"),
                    ev.get("name", ""),
                    json.dumps(ev.get("tag_diff") or {}),
                    ev.get("version_before"),
                    ev.get("version_after"),
                ))

            # Reconcile with live replication events
            # 1. Confirm live events that match observed changes
            cur.execute("""
            UPDATE change_events c_live
            SET confirmed = TRUE
            FROM change_events c_daily
            WHERE c_live.source = 'live'
              AND c_daily.source = 'daily'
              AND c_live.osm_type = c_daily.osm_type
              AND c_live.osm_id = c_daily.osm_id
              AND (c_live.version_after = c_daily.version_after OR c_daily.kind = 'deleted');
            """)

            # 2. Reconcile same-day reverts
            # If an object had a live event, but the daily diff saw NO net change
            # and it is not in c_daily, mark reverted_same_day (guarded by pbf_timestamp)
            cur.execute("""
            UPDATE change_events c_live
            SET reverted_same_day = TRUE
            WHERE c_live.source = 'live'
              AND c_live.confirmed = FALSE
              AND (%s::timestamptz IS NULL OR c_live.observed_at <= %s::timestamptz)
              AND c_live.observed_at >= NOW() - INTERVAL '48 hours'
              AND NOT EXISTS (
                  SELECT 1 FROM change_events c_daily
                  WHERE c_daily.source = 'daily'
                    AND c_daily.osm_type = c_live.osm_type
                    AND c_daily.osm_id = c_live.osm_id
              );
            """, (pbf_timestamp, pbf_timestamp))

    print(f"  [OK] Saved {len(events)} change events to database and reconciled live events.")


def detect_and_record_daily_changes(conn, data_dir=BASE_DIR):
    """
    Diffs current `places` against `places_staging` and records `change_events`.
    Called inside load_db.py right before the atomic table swap.
    """
    summary = read_summary()
    dataset_version = "v" + summary.get("updated_at", "").replace("-", "").replace(":", "")
    pbf_timestamp = summary.get("pbf_timestamp")
    if not pbf_timestamp and summary.get("pbf_date"):
        pbf_timestamp = f"{summary.get('pbf_date')}T00:00:00Z"

    with conn.cursor() as cur:
        # Get previous dataset version
        cur.execute("SELECT version FROM dataset_versions ORDER BY published_at DESC LIMIT 1;")
        prev_row = cur.fetchone()
        prev_version = prev_row[0] if (prev_row and isinstance(prev_row, tuple)) else (prev_row.get("version", "") if isinstance(prev_row, dict) else "")

        # Fetch old places from places
        cur.execute("""
            SELECT osm_type, osm_id, version, name, name_norm, name_en,
                   religion, denomination, building, amenity, poi_node_id,
                   tags, ST_X(geom) AS lon, ST_Y(geom) AS lat, region_code
            FROM places;
        """)
        old_rows = cur.fetchall()
        old_places = []
        for r in old_rows:
            d = dict(r) if isinstance(r, dict) else {
                "osm_type": r[0], "osm_id": r[1], "version": r[2], "name": r[3],
                "name_norm": r[4], "name_en": r[5], "religion": r[6], "denomination": r[7],
                "building": r[8], "amenity": r[9], "poi_node_id": r[10],
                "tags": r[11] if isinstance(r[11], dict) else (json.loads(r[11]) if r[11] else {}),
                "lon": r[12], "lat": r[13], "region_code": r[14],
            }
            d["coords"] = [d.pop("lon", 0.0) or 0.0, d.pop("lat", 0.0) or 0.0]
            old_places.append(d)

        # Fetch new places from places_staging
        cur.execute("""
            SELECT osm_type, osm_id, version, name, name_norm, name_en,
                   religion, denomination, building, amenity, poi_node_id,
                   tags, ST_X(geom) AS lon, ST_Y(geom) AS lat, region_code
            FROM places_staging;
        """)
        new_rows = cur.fetchall()
        new_places = []
        for r in new_rows:
            d = dict(r) if isinstance(r, dict) else {
                "osm_type": r[0], "osm_id": r[1], "version": r[2], "name": r[3],
                "name_norm": r[4], "name_en": r[5], "religion": r[6], "denomination": r[7],
                "building": r[8], "amenity": r[9], "poi_node_id": r[10],
                "tags": r[11] if isinstance(r[11], dict) else (json.loads(r[11]) if r[11] else {}),
                "lon": r[12], "lat": r[13], "region_code": r[14],
            }
            d["coords"] = [d.pop("lon", 0.0) or 0.0, d.pop("lat", 0.0) or 0.0]
            new_places.append(d)

        # Issues before vs after
        cur.execute("SELECT rule_id, osm_type, osm_id FROM issues;")
        old_issues_raw = cur.fetchall()
        old_issues_by_place = {}
        for r in old_issues_raw:
            k = (r["osm_type"], r["osm_id"]) if isinstance(r, dict) else (r[1], r[2])
            rule = r["rule_id"] if isinstance(r, dict) else r[0]
            old_issues_by_place.setdefault(k, set()).add(rule)

        cur.execute("SELECT rule_id, osm_type, osm_id FROM issues_staging;")
        new_issues_raw = cur.fetchall()
        new_issues_by_place = {}
        for r in new_issues_raw:
            k = (r["osm_type"], r["osm_id"]) if isinstance(r, dict) else (r[1], r[2])
            rule = r["rule_id"] if isinstance(r, dict) else r[0]
            new_issues_by_place.setdefault(k, set()).add(rule)

    events = diff_places(
        old_places,
        new_places,
        dataset_version=dataset_version,
        prev_dataset_version=prev_version,
        old_issues_by_place=old_issues_by_place,
        new_issues_by_place=new_issues_by_place,
    )
    save_change_events_to_db(conn, events, pbf_timestamp=pbf_timestamp)
    return events


def main():
    if not DATABASE_URL:
        sys.exit("[SKIP] No DATABASE_URL or MANARA_DATABASE_URL set.")
    try:
        import psycopg
        from psycopg.rows import dict_row
        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=True)
    except Exception as e:
        sys.exit(f"Could not connect to database: {e}")

    try:
        events = detect_and_record_daily_changes(conn)
        print(f"Daily change detection completed: {len(events)} events processed.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
