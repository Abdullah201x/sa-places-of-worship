#!/usr/bin/env python3
"""
Manara Live Replicator (Coolify service `manara-live`).

Continuously streams minutely replication diffs from OpenStreetMap,
identifies changes affecting places of worship across Saudi Arabia,
evaluates change flags, and writes to `change_events` (source = 'live')
and `replication_state` in PostgreSQL.

Maintains a tiny memory footprint (<192 MiB) and respects OSMF policies:
- Sets polite User-Agent
- Follows redirects to OSMF mirrors
- Backs off exponentially on HTTP 429/503
- Drops `user` and `uid`, keeping only `changeset`
"""

import gzip
import io
import math
import os
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Any

from change_rules import compute_tag_diff, evaluate_change_flags
from common import configure_utf8_output, normalize_arabic
from worship_tags import is_worship_tagged

configure_utf8_output()

DEFAULT_REPLICATION_URL = "https://planet.openstreetmap.org/replication/minute"
USER_AGENT = "Manara/1.0 (+https://manara.saudiosm.org)"

# Saudi Arabia approximate bounding box for fast pre-filtering
SA_BBOX = (34.5, 16.0, 55.7, 32.2)  # min_lon, min_lat, max_lon, max_lat


def parse_state_txt(content: str) -> dict[str, Any]:
    """
    Parses OpenStreetMap replication state.txt file.
    Example:
      sequenceNumber=6543210
      timestamp=2026-10-30T00\\:01\\:00Z
    """
    data = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().replace(r"\:", ":")
            if k == "sequenceNumber":
                data["sequence"] = int(v)
            elif k == "timestamp":
                data["timestamp"] = v
    return data


def format_sequence_path(seq: int) -> str:
    """
    Formats a sequence number into the standard 9-digit 3-tier path:
    e.g. 6123456 -> '006/123/456'
    """
    s = f"{seq:09d}"
    return f"{s[0:3]}/{s[3:6]}/{s[6:9]}"


def build_diff_url(base_url: str, seq: int) -> str:
    """Builds the full URL for a sequence .osc.gz diff."""
    base = base_url.rstrip("/")
    path = format_sequence_path(seq)
    return f"{base}/{path}.osc.gz"


def is_in_sa_bbox(lat: float, lon: float) -> bool:
    """Fast bounding box test for Saudi Arabia."""
    min_lon, min_lat, max_lon, max_lat = SA_BBOX
    return min_lon <= lon <= max_lon and min_lat <= lat <= max_lat


def load_known_places(conn) -> dict[tuple[str, int], dict[str, Any]]:
    """
    Loads the known-places cache: (osm_type, osm_id) -> {"lat", "lon", "region_code", "tags"} for the
    ~14k places in the daily dataset plus live-created ones. Enables tag diffing,
    worship-tag removal detection, and deletion recognition.
    """
    known: dict[tuple[str, int], dict[str, Any]] = {}
    with conn.cursor() as cur:
        for table in ("places", "live_places"):
            try:
                cur.execute(
                    f"SELECT osm_type, osm_id, ST_Y(geom) AS lat, ST_X(geom) AS lon, region_code, tags FROM {table} WHERE geom IS NOT NULL;"
                )
                for row in cur.fetchall():
                    if isinstance(row, dict):
                        osm_type = row["osm_type"]
                        osm_id = int(row["osm_id"])
                        lat = row["lat"]
                        lon = row["lon"]
                        region_code = row.get("region_code")
                        tags_val = row.get("tags")
                    else:
                        osm_type = row[0]
                        osm_id = int(row[1])
                        lat = row[2]
                        lon = row[3]
                        region_code = row[4] if len(row) > 4 else None
                        tags_val = row[5] if len(row) > 5 else {}

                    if isinstance(tags_val, str):
                        try:
                            import json
                            tags_val = json.loads(tags_val)
                        except Exception:
                            tags_val = {}
                    place_info = {"lat": lat, "lon": lon}
                    if region_code:
                        place_info["region_code"] = region_code
                    if tags_val:
                        place_info["tags"] = tags_val
                    known[(osm_type, osm_id)] = place_info
            except Exception as e:
                print(f"[WARN] Could not load known places from {table}: {e}")
    return known


def _resolve_centroid(elem, diff_nodes: dict[int, tuple[float, float]]) -> tuple[float, float] | None:
    """Mean of the member nodes that appear in this diff, or None if none do."""
    if elem.tag.lower() == "way":
        refs = [int(nd.attrib["ref"]) for nd in elem.findall("nd") if nd.attrib.get("ref")]
    else:
        refs = [
            int(m.attrib["ref"]) for m in elem.findall("member")
            if m.attrib.get("type") == "node" and m.attrib.get("ref")
        ]
    coords = [diff_nodes[r] for r in refs if r in diff_nodes]
    if not coords:
        return None
    return (sum(c[0] for c in coords) / len(coords), sum(c[1] for c in coords) / len(coords))


def parse_osc_stream(
    xml_bytes: bytes,
    known_places: dict[tuple[str, int], dict[str, Any]] | None = None,
    pending: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """
    Parses OSM changeset diff XML (.osc) from uncompressed bytes.
    Extracts created, modified, and deleted worship places inside Saudi Arabia.
    Strictly drops `user` and `uid`.

    The minutely feed is planet-wide, so an object is only kept when it can be
    tied to Saudi Arabia:
    - objects in `known_places` (the dataset cache) are always kept, located by
      their cached position (needed for deletions, which carry no tags);
    - other worship-tagged nodes must be inside the SA bbox;
    - other worship-tagged ways/relations are located from nodes in the same
      diff; if that fails they are appended to `pending` (when given) for the
      daily run to confirm, and otherwise dropped.
    """
    known_places = known_places or {}
    events = []
    try:
        root = ET.fromstring(xml_bytes)
    except Exception as e:
        print(f"[WARN] Failed to parse OSC XML: {e}")
        return []

    # Node positions in this diff, used to place ways and relations
    diff_nodes: dict[int, tuple[float, float]] = {}
    for action_node in root:
        if action_node.tag.lower() not in ("create", "modify"):
            continue
        for elem in action_node:
            if elem.tag.lower() == "node" and elem.attrib.get("lat") is not None and elem.attrib.get("lon") is not None:
                diff_nodes[int(elem.attrib.get("id", 0))] = (float(elem.attrib["lat"]), float(elem.attrib["lon"]))

    # root contains children: <create>, <modify>, <delete>
    for action_node in root:
        action_tag = action_node.tag.lower()
        if action_tag not in ("create", "modify", "delete"):
            continue

        kind = "created" if action_tag == "create" else ("modified" if action_tag == "modify" else "deleted")

        for elem in action_node:
            osm_type = elem.tag.lower()  # node, way, relation
            if osm_type not in ("node", "way", "relation"):
                continue

            osm_id = int(elem.attrib.get("id", 0))
            version = int(elem.attrib.get("version", 1))
            changeset_id = int(elem.attrib.get("changeset", 0)) or None
            cached = known_places.get((osm_type, osm_id))

            # Collect tags
            tags = {}
            for tag_elem in elem.findall("tag"):
                k = tag_elem.attrib.get("k")
                v = tag_elem.attrib.get("v")
                if k and v:
                    tags[k] = v

            # Deletions have no tags, so only known places can be recognised.
            # Other objects must be worship-tagged, unless they are known
            # places (a known place losing its tags is still a change).
            if kind == "deleted":
                if not cached:
                    continue
            elif not is_worship_tagged(tags) and not cached:
                continue

            # Locate the object
            lat_str = elem.attrib.get("lat")
            lon_str = elem.attrib.get("lon")
            lat = float(lat_str) if lat_str is not None else None
            lon = float(lon_str) if lon_str is not None else None
            if lat is None or lon is None:
                if osm_type != "node":
                    centroid = _resolve_centroid(elem, diff_nodes) if kind != "deleted" else None
                    if centroid is not None:
                        lat, lon = centroid
                if (lat is None or lon is None) and cached:
                    lat, lon = cached["lat"], cached["lon"]

            if not cached:
                if lat is None or lon is None:
                    # A worship-tagged way/relation we can't place yet
                    if pending is not None and osm_type != "node":
                        pending.append({
                            "osm_type": osm_type,
                            "osm_id": osm_id,
                            "version": version,
                            "tags": tags,
                            "node_refs": [
                                int(nd.attrib["ref"]) for nd in elem.findall("nd") if nd.attrib.get("ref")
                            ],
                        })
                    continue
                if not is_in_sa_bbox(lat, lon):
                    continue

            name = tags.get("name") or tags.get("name:ar") or tags.get("name:en") or ""
            name_norm = normalize_arabic(name) if name else ""

            old_tags = cached.get("tags") or {} if cached else {}
            if kind == "modified":
                tag_diff = compute_tag_diff(old_tags, tags)
            elif kind == "deleted":
                tag_diff = compute_tag_diff(old_tags, {})
            else:
                tag_diff = compute_tag_diff({}, tags)

            # Evaluate change flags
            flags = evaluate_change_flags(
                old_tags=old_tags,
                new_tags=tags if kind != "deleted" else {},
                is_deleted=(kind == "deleted"),
                normalized_name=name_norm,
                normalized_name_ar=normalize_arabic(tags.get("name:ar", "")),
            )

            region_code = cached.get("region_code") if cached else None

            events.append({
                "source": "live",
                "kind": kind,
                "osm_type": osm_type,
                "osm_id": osm_id,
                "version_after": version if kind != "deleted" else None,
                "version_before": version - 1 if (version > 1 and kind == "modified") else None,
                "changeset_id": changeset_id,
                "name": name,
                "lat": lat,
                "lon": lon,
                "region_code": region_code,
                "tags": tags,
                "tag_diff": tag_diff,
                "flags": flags,
            })

    return events


def record_live_events(conn, seq: int, osm_timestamp: str, events: list[dict[str, Any]], sync_live_places: bool = False):
    """
    Atomically records live change events, optionally updates live_places, and updates replication_state.
    """
    with conn.transaction():
        with conn.cursor() as cur:
            for ev in events:
                lat = ev.get("lat")
                lon = ev.get("lon")
                geom_sql = "ST_SetSRID(ST_Point(%s, %s), 4326)" if (lat is not None and lon is not None) else "NULL"
                params = [
                    ev["source"],
                    False,  # confirmed later by daily run
                    osm_timestamp,
                    ev.get("changeset_id"),
                    seq,
                    ev["osm_type"],
                    ev["osm_id"],
                    ev["kind"],
                    import_json(ev.get("flags") or []),
                    import_json(ev.get("tag_diff") or {}),
                    ev.get("name", ""),
                    ev.get("version_before"),
                    ev.get("version_after"),
                    ev.get("region_code"),
                ]
                if lat is not None and lon is not None:
                    params.extend([lon, lat])

                insert_sql = f"""
                INSERT INTO change_events (
                    source, confirmed, osm_timestamp, observed_at, changeset_id,
                    replication_seq, osm_type, osm_id, kind, flags,
                    tag_diff, name, version_before, version_after, region_code, geom
                ) VALUES (
                    %s, %s, %s, NOW(), %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, {geom_sql}
                )
                ON CONFLICT DO NOTHING;
                """
                cur.execute(insert_sql, params)

                # Maintain live_places for fast lookups and freshness if requested
                if sync_live_places:
                    if ev["kind"] == "deleted":
                        cur.execute("DELETE FROM live_places WHERE osm_type = %s AND osm_id = %s;", (ev["osm_type"], ev["osm_id"]))
                    elif lat is not None and lon is not None and is_worship_tagged(ev.get("tags") or {}):
                        cur.execute("""
                        INSERT INTO live_places (osm_type, osm_id, version, geom, region_code, tags, seen_at)
                        VALUES (%s, %s, %s, ST_SetSRID(ST_Point(%s, %s), 4326), %s, %s::jsonb, NOW())
                        ON CONFLICT (osm_type, osm_id) DO UPDATE SET
                            version = EXCLUDED.version,
                            geom = EXCLUDED.geom,
                            region_code = EXCLUDED.region_code,
                            tags = EXCLUDED.tags,
                            seen_at = NOW();
                        """, (ev["osm_type"], ev["osm_id"], ev.get("version_after"), lon, lat, ev.get("region_code"), import_json(ev.get("tags") or {})))

            # Update replication_state
            cur.execute("""
            INSERT INTO replication_state (id, sequence, osm_timestamp, processed_at)
            VALUES (1, %s, %s, NOW())
            ON CONFLICT (id) DO UPDATE SET
                sequence = EXCLUDED.sequence,
                osm_timestamp = EXCLUDED.osm_timestamp,
                processed_at = NOW();
            """, (seq, osm_timestamp))


def fetch_replication_state(base_url: str = DEFAULT_REPLICATION_URL) -> dict[str, Any]:
    """Fetches and parses current state.txt from the replication feed."""
    import urllib.request
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}/state.txt",
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=15) as res:
        content = res.read().decode("utf-8")
    return parse_state_txt(content)


def fetch_diff_bytes(base_url: str, seq: int) -> bytes:
    """Downloads and uncompresses a minutely .osc.gz replication diff."""
    import urllib.request
    url = build_diff_url(base_url, seq)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as res:
        compressed = res.read()
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as gz:
        return gz.read()


def run_replication_step(conn, known_places: dict, base_url: str = DEFAULT_REPLICATION_URL) -> int:
    """
    Runs one sequence catchup or advances to current. Returns number of events processed.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT sequence, osm_timestamp FROM replication_state WHERE id = 1;")
        row = cur.fetchone()

    remote_state = fetch_replication_state(base_url)
    remote_seq = remote_state.get("sequence")
    remote_ts = remote_state.get("timestamp")

    if not row or not row.get("sequence"):
        # Initialize at current remote sequence - 1 to start monitoring live
        init_seq = remote_seq - 1 if remote_seq else 0
        with conn.cursor() as cur:
            cur.execute("""
            INSERT INTO replication_state (id, sequence, osm_timestamp, processed_at)
            VALUES (1, %s, %s, NOW())
            ON CONFLICT (id) DO UPDATE SET sequence = EXCLUDED.sequence, osm_timestamp = EXCLUDED.osm_timestamp;
            """, (init_seq, remote_ts))
        print(f"  [INIT] Replication state initialized at sequence {init_seq} ({remote_ts}).")
        current_seq = init_seq
    else:
        current_seq = row["sequence"]

    if remote_seq is None or current_seq >= remote_seq:
        return 0

    target_seq = current_seq + 1
    xml_bytes = fetch_diff_bytes(base_url, target_seq)
    events = parse_osc_stream(xml_bytes, known_places=known_places)
    record_live_events(conn, target_seq, remote_ts or datetime.now(timezone.utc).isoformat(), events)

    # Update cache with newly processed events
    for ev in events:
        key = (ev["osm_type"], ev["osm_id"])
        if ev["kind"] == "deleted":
            known_places.pop(key, None)
        else:
            known_places[key] = {
                "lat": ev.get("lat"),
                "lon": ev.get("lon"),
                "region_code": ev.get("region_code"),
                "tags": ev.get("tags") or {},
            }

    print(f"  [OK] Processed sequence {target_seq}: {len(events)} worship change events.")
    return len(events)


def main():
    DATABASE_URL = os.environ.get("MANARA_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not DATABASE_URL:
        sys.exit("[SKIP] No DATABASE_URL or MANARA_DATABASE_URL set.")

    import argparse
    parser = argparse.ArgumentParser(description="Manara Live Minutely Replicator")
    parser.add_argument("--once", action="store_true", help="Process available sequences once and exit")
    parser.add_argument("--interval", type=int, default=60, help="Poll interval in seconds (default 60)")
    args = parser.parse_args()

    try:
        import psycopg
        from psycopg.rows import dict_row
        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=True)
    except Exception as e:
        sys.exit(f"Could not connect to database: {e}")

    try:
        print("Loading known places cache into memory...")
        known = load_known_places(conn)
        print(f"Known places loaded: {len(known)} entries (~{len(known)*300//1024} KB).")

        if args.once:
            run_replication_step(conn, known)
            return

        print(f"Starting live replication daemon (polling every {args.interval}s)...")
        consecutive_errors = 0
        while True:
            try:
                processed = run_replication_step(conn, known)
                consecutive_errors = 0
                time.sleep(args.interval if processed == 0 else 5)
            except KeyboardInterrupt:
                print("\nShutting down live replicator.")
                break
            except Exception as e:
                consecutive_errors += 1
                backoff = min(300, args.interval * (2 ** min(consecutive_errors, 5)))
                print(f"[ERROR] Live replication error: {e}. Backing off {backoff}s.")
                time.sleep(backoff)
    finally:
        conn.close()


def import_json(val: Any) -> str:
    import json
    return json.dumps(val)


if __name__ == "__main__":
    main()
