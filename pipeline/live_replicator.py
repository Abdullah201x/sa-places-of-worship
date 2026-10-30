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
    Loads the known-places cache: (osm_type, osm_id) -> {"lat", "lon"} for the
    ~14k places in the daily dataset plus live-created ones. Only these objects
    can be recognised when they are deleted, since diffs carry no tags for
    deletions, and ways/relations in the diff have no coordinates of their own.
    """
    known: dict[tuple[str, int], dict[str, Any]] = {}
    with conn.cursor() as cur:
        for table in ("places", "live_places"):
            cur.execute(
                f"SELECT osm_type, osm_id, ST_Y(geom) AS lat, ST_X(geom) AS lon FROM {table} WHERE geom IS NOT NULL;"
            )
            for row in cur.fetchall():
                if isinstance(row, dict):
                    osm_type, osm_id, lat, lon = row["osm_type"], row["osm_id"], row["lat"], row["lon"]
                else:
                    osm_type, osm_id, lat, lon = row
                known[(osm_type, int(osm_id))] = {"lat": lat, "lon": lon}
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

            # Evaluate change flags
            flags = evaluate_change_flags(
                old_tags={},
                new_tags=tags,
                is_deleted=(kind == "deleted"),
                normalized_name=name_norm,
                normalized_name_ar=normalize_arabic(tags.get("name:ar", "")),
            )

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
                "tags": tags,
                "flags": flags,
            })

    return events


def record_live_events(conn, seq: int, osm_timestamp: str, events: list[dict[str, Any]]):
    """
    Atomically records live change events and updates replication_state.
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
                    import_json(ev.get("tags") or {}),
                    ev.get("name", ""),
                    ev.get("version_before"),
                    ev.get("version_after"),
                ]
                if lat is not None and lon is not None:
                    params.extend([lon, lat])

                insert_sql = f"""
                INSERT INTO change_events (
                    source, confirmed, osm_timestamp, observed_at, changeset_id,
                    replication_seq, osm_type, osm_id, kind, flags,
                    tag_diff, name, version_before, version_after, geom
                ) VALUES (
                    %s, %s, %s, NOW(), %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, {geom_sql}
                );
                """
                cur.execute(insert_sql, params)

            # Update replication_state
            cur.execute("""
            INSERT INTO replication_state (id, sequence, osm_timestamp, processed_at)
            VALUES (1, %s, %s, NOW())
            ON CONFLICT (id) DO UPDATE SET
                sequence = EXCLUDED.sequence,
                osm_timestamp = EXCLUDED.osm_timestamp,
                processed_at = NOW();
            """, (seq, osm_timestamp))


def import_json(val: Any) -> str:
    import json
    return json.dumps(val)
