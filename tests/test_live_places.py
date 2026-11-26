import os
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))

from app.main import app  # noqa: E402
from app.database import get_db  # noqa: E402
from app.routers.edits import (  # noqa: E402
    MAX_LIVE_UPSERTS_PER_CHANGESET,
    parse_osmchange_live,
    write_live_changes,
)
from app.worship_tags import is_worship_tagged as backend_is_worship_tagged  # noqa: E402
from worship_tags import is_worship_tagged as pipeline_is_worship_tagged  # noqa: E402
from live_replicator import record_live_events, sync_live_place  # noqa: E402


# --- worship predicate parity -------------------------------------------------

TAG_CASES = [
    {},
    None,
    {"amenity": "place_of_worship"},
    {"amenity": "mosque"},
    {"building": "mosque"},
    {"amenity": "restaurant"},
    {"building": "church"},
    {"amenity": "place_of_worship", "religion": "christian"},
]


@pytest.mark.parametrize("tags", TAG_CASES)
def test_is_worship_tagged_parity(tags):
    assert backend_is_worship_tagged(tags) == pipeline_is_worship_tagged(tags)


# --- OSMChange live parsing ---------------------------------------------------

OSMCHANGE = """<osmChange version="0.6">
  <create>
    <node id="1" version="1" timestamp="2026-11-26T10:00:00Z" uid="9" user="x" lat="24.7" lon="46.7">
      <tag k="amenity" v="place_of_worship"/><tag k="religion" v="muslim"/>
    </node>
    <node id="2" version="1" lat="24.7" lon="46.7"><tag k="amenity" v="cafe"/></node>
    <way id="3" version="1"><tag k="amenity" v="place_of_worship"/></way>
  </create>
  <modify>
    <node id="4" version="3" timestamp="2026-11-26T10:01:00Z" lat="24.8" lon="46.8"><tag k="shop" v="bakery"/></node>
    <node id="5" version="2" lat="24.9" lon="46.9"><tag k="building" v="mosque"/></node>
  </modify>
  <delete>
    <node id="6" version="4" timestamp="2026-11-26T10:02:00Z"/>
  </delete>
</osmChange>"""


def test_parse_osmchange_live():
    by_id = {c["osm_id"]: c for c in parse_osmchange_live(OSMCHANGE)}
    assert set(by_id) == {1, 4, 5, 6}  # cafe create and the way are ignored

    assert by_id[1]["deleted"] is False
    assert (by_id[1]["lat"], by_id[1]["lon"], by_id[1]["version"]) == (24.7, 46.7, 1)
    assert by_id[1]["timestamp"] == "2026-11-26T10:00:00Z"
    assert by_id[1]["tags"]["religion"] == "muslim"
    assert "uid" not in by_id[1] and "user" not in by_id[1]

    assert by_id[4]["deleted"] is True  # modify that stripped the worship tags
    assert by_id[5]["deleted"] is False and by_id[5]["timestamp"] is None
    assert by_id[6]["deleted"] is True and by_id[6]["version"] == 4


def test_parse_osmchange_live_garbage_is_empty():
    assert parse_osmchange_live("not xml") == []


def test_write_live_changes_caps_a_bulk_changeset():
    conn = MagicMock()
    cur = MagicMock()
    changes = [
        {"osm_type": "node", "osm_id": i, "version": 1, "lat": 24.7, "lon": 46.7,
         "tags": {"amenity": "mosque"}, "deleted": False, "timestamp": None}
        for i in range(MAX_LIVE_UPSERTS_PER_CHANGESET + 25)
    ]
    assert write_live_changes(conn, cur, 123, changes) == MAX_LIVE_UPSERTS_PER_CHANGESET
    assert cur.execute.call_count == MAX_LIVE_UPSERTS_PER_CHANGESET
    sql, params = cur.execute.call_args_list[0].args
    assert "manara_upsert_live_place" in sql and "'manara'" in sql
    assert params[0] == "node" and params[-1] == 123


def test_write_live_changes_failure_does_not_raise():
    conn = MagicMock()
    cur = MagicMock()
    cur.execute.side_effect = RuntimeError("boom")
    change = {"osm_type": "node", "osm_id": 1, "version": 1, "lat": 1.0, "lon": 2.0,
              "tags": {}, "deleted": False, "timestamp": None}
    assert write_live_changes(conn, cur, 1, [change]) == 0


# --- replicator -> SQL function -----------------------------------------------

def _event(kind, tags, **extra):
    return {"source": "live", "kind": kind, "osm_type": "node", "osm_id": 7, "version": 2,
            "version_after": 2, "version_before": 1, "changeset_id": 55, "name": "",
            "lat": 24.7, "lon": 46.7, "tags": tags, "flags": [], "timestamp": "2026-11-26T10:00:00Z", **extra}


def _args(cur):
    return cur.execute.call_args.args[1]


def test_sync_live_place_upserts_worship_node():
    cur = MagicMock()
    sync_live_place(cur, _event("created", {"amenity": "mosque"}), "2026-11-26T11:00:00Z")
    args = _args(cur)
    assert args[:3] == ("node", 7, 2)
    assert (args[3], args[4]) == (46.7, 24.7)  # lon, lat
    assert args[6] is False
    assert args[7] == "2026-11-26T10:00:00Z"  # the element's own timestamp


def test_sync_live_place_tombstones_stripped_modify_and_delete():
    for ev in (_event("modified", {"shop": "bakery"}), _event("deleted", {})):
        cur = MagicMock()
        sync_live_place(cur, ev, "2026-11-26T11:00:00Z")
        args = _args(cur)
        assert args[6] is True and args[3] is None and args[4] is None


def test_sync_live_place_ignores_unlocated_and_non_worship_creates():
    cur = MagicMock()
    sync_live_place(cur, _event("created", {"amenity": "mosque"}, lat=None, lon=None), "t")
    sync_live_place(cur, _event("created", {"amenity": "cafe"}), "t")
    cur.execute.assert_not_called()


def test_record_live_events_syncs_only_when_enabled():
    def run(flag):
        conn = MagicMock()
        cur = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cur
        record_live_events(conn, 1, "2026-11-26T11:00:00Z", [_event("created", {"amenity": "mosque"})],
                           sync_live_places=flag)
        return [c.args[0] for c in cur.execute.call_args_list]

    assert not any("manara_upsert_live_place" in s for s in run(False))
    assert any("manara_upsert_live_place" in s for s in run(True))


# --- GET /api/v1/places/live ---------------------------------------------------

@pytest.fixture
def live_client():
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur

    def override_get_db():
        yield conn

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c, cur
    app.dependency_overrides.clear()


def _row(osm_id, deleted=False):
    ts = datetime(2026, 11, 26, 10, 0, tzinfo=timezone.utc)
    return {"osm_type": "node", "osm_id": osm_id, "version": 1, "deleted": deleted,
            "lon": 46.7, "lat": 24.7, "region_code": "SA-01",
            "tags": {"amenity": "mosque"}, "osm_timestamp": ts, "seen_at": ts}


def test_live_places_splits_features_and_removed(live_client):
    client, cur = live_client
    cur.fetchall.return_value = [_row(1), _row(2, deleted=True)]
    res = client.get("/api/v1/places/live", params={"since": "2026-11-25T00:00:00Z"})
    assert res.status_code == 200
    body = res.json()
    assert [f["properties"]["osm_id"] for f in body["features"]] == [1]
    assert body["features"][0]["properties"]["tags"] == {"amenity": "mosque"}
    assert body["features"][0]["geometry"]["coordinates"] == [46.7, 24.7]
    assert body["removed"] == [{"osm_type": "node", "osm_id": 2}]
    assert "max-age=30" in res.headers["cache-control"]
    params = cur.execute.call_args.args[1]
    assert params["since"] == datetime(2026, 11, 25, tzinfo=timezone.utc)


def test_live_places_etag_gives_304(live_client):
    client, cur = live_client
    cur.fetchall.return_value = [_row(1)]
    first = client.get("/api/v1/places/live", params={"since": "2026-11-25T00:00:00Z"})
    again = client.get("/api/v1/places/live", params={"since": "2026-11-25T00:00:00Z"},
                       headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304
    # a different `since` is a different representation
    other = client.get("/api/v1/places/live", params={"since": "2026-11-24T00:00:00Z"},
                       headers={"If-None-Match": first.headers["etag"]})
    assert other.status_code == 200


def test_live_places_bad_since_falls_back_to_latest_snapshot(live_client):
    client, cur = live_client
    snapshot = datetime(2026, 11, 20, tzinfo=timezone.utc)
    cur.fetchone.return_value = {"pbf_timestamp": snapshot}
    cur.fetchall.return_value = []
    res = client.get("/api/v1/places/live", params={"since": "garbage"})
    assert res.status_code == 200
    assert cur.execute.call_args.args[1]["since"] == snapshot


# --- SQL function on real PostGIS (CI sets MANARA_DATABASE_URL) -----------------

DB_URL = os.environ.get("MANARA_DATABASE_URL")


@pytest.mark.skipif(not DB_URL, reason="needs MANARA_DATABASE_URL (PostGIS)")
def test_upsert_function_on_postgis():
    import psycopg
    from psycopg.rows import dict_row

    from app.database import run_migrations
    from app.schema import init_app_tables

    class Rollback(Exception):
        pass

    ts = "2026-11-26T10:00:00Z"

    def upsert(cur, osm_id, version, lon, lat, deleted=False, tags='{"amenity":"mosque"}'):
        cur.execute(
            "SELECT manara_upsert_live_place('node', %s, %s, %s, %s, %s::jsonb, %s, %s::timestamptz, 'manara', 1) AS ok",
            (osm_id, version, lon, lat, tags, deleted, ts),
        )
        return cur.fetchone()["ok"]

    def row(cur, osm_id):
        cur.execute("SELECT version, deleted, region_code FROM live_places WHERE osm_type='node' AND osm_id=%s", (osm_id,))
        return cur.fetchone()

    with psycopg.connect(DB_URL, row_factory=dict_row, autocommit=True) as conn:
        init_app_tables(conn)
        run_migrations(conn)
        try:
            with conn.transaction():
                with conn.cursor() as cur:
                    # Minimal tables if the pipeline has not created them; rolled back at the end.
                    cur.execute("""
                    CREATE TABLE IF NOT EXISTS regions (code VARCHAR(10) PRIMARY KEY, osm_id BIGINT NOT NULL,
                        name VARCHAR(255) NOT NULL, name_en VARCHAR(255) NOT NULL, geom GEOMETRY(Geometry, 4326) NOT NULL);
                    CREATE TABLE IF NOT EXISTS places (osm_type VARCHAR(16), osm_id BIGINT, poi_node_id BIGINT, geom GEOMETRY(Point, 4326));
                    DELETE FROM regions WHERE code = 'ZZTEST';
                    INSERT INTO regions (code, osm_id, name, name_en, geom)
                    VALUES ('ZZTEST', 1, 't', 't', ST_MakeEnvelope(46.0, 24.0, 47.0, 25.0, 4326));
                    DELETE FROM live_places WHERE osm_id BETWEEN 990000001 AND 990000009;
                    """)

                    # region lookup fills region_code; a point outside every region is rejected
                    assert upsert(cur, 990000001, 1, 46.5, 24.5) is True
                    assert row(cur, 990000001)["region_code"] is not None
                    assert upsert(cur, 990000002, 1, 0.5, 0.5) is False
                    assert row(cur, 990000002) is None

                    # an older version never overwrites a newer one
                    assert upsert(cur, 990000003, 5, 46.5, 24.5) is True
                    assert upsert(cur, 990000003, 4, 46.6, 24.6) is False
                    assert row(cur, 990000003)["version"] == 5

                    # tombstone, then a stale create stays a tombstone
                    assert upsert(cur, 990000003, 6, None, None, deleted=True, tags="{}") is True
                    assert upsert(cur, 990000003, 5, 46.5, 24.5) is False
                    assert row(cur, 990000003)["deleted"] is True

                    # tombstones for objects we have never seen are ignored
                    assert upsert(cur, 990000004, 2, None, None, deleted=True, tags="{}") is False
                    raise Rollback()
        except Rollback:
            pass


# --- pipeline pieces ------------------------------------------------------------

def test_parse_osc_stream_keeps_version_and_timestamp_and_no_user():
    from live_replicator import parse_osc_stream

    osc = b"""<osmChange version="0.6"><create>
      <node id="9" version="1" timestamp="2026-11-26T10:00:00Z" uid="1" user="u" changeset="5" lat="24.7" lon="46.7">
        <tag k="amenity" v="mosque"/></node></create></osmChange>"""
    (ev,) = parse_osc_stream(osc)
    assert ev["version"] == 1 and ev["timestamp"] == "2026-11-26T10:00:00Z"
    assert "user" not in ev and "uid" not in ev


def test_load_known_places_skips_tombstones():
    from live_replicator import load_known_places

    conn = MagicMock()
    cur = MagicMock()
    cur.fetchall.return_value = []
    conn.cursor.return_value.__enter__.return_value = cur
    load_known_places(conn)
    queries = [c.args[0] for c in cur.execute.call_args_list]
    live = next(q for q in queries if "FROM live_places" in q)
    assert "NOT COALESCE(deleted, FALSE)" in live
    assert "deleted" not in next(q for q in queries if "FROM places" in q)


@pytest.mark.parametrize("gx,gy,fx,fy", [(10750, 6125, 0.0, 0.0), (10750, 6125, 0.5, 0.5), (10750, 6125, 0.999, 0.31)])
def test_rep_offsets_rebuild_the_point_within_a_99th_of_a_cell(gx, gy, fx, fy):
    from calculate_gaps import rep_offsets

    g = 0.004
    lon, lat = (gx + fx) * g, (gy + fy) * g
    rx, ry = rep_offsets(lon, lat, gx, gy, g)
    assert 0 <= rx <= 99 and 0 <= ry <= 99
    assert abs((gx + rx / 99) * g - lon) <= g / 99
    assert abs((gy + ry / 99) * g - lat) <= g / 99


@pytest.mark.skipif(not DB_URL, reason="needs MANARA_DATABASE_URL (PostGIS)")
def test_prune_keeps_rows_newer_than_the_previous_snapshot():
    import psycopg
    from psycopg.rows import dict_row

    from app.schema import init_app_tables
    from app.database import run_migrations
    from load_db import PRUNE_LIVE_SQL

    class Rollback(Exception):
        pass

    with psycopg.connect(DB_URL, row_factory=dict_row, autocommit=True) as conn:
        init_app_tables(conn)
        run_migrations(conn)
        try:
            with conn.transaction():
                with conn.cursor() as cur:
                    cur.execute("""
                    CREATE TABLE IF NOT EXISTS dataset_versions (
                        version VARCHAR(64) PRIMARY KEY, pbf_date DATE, pbf_timestamp TIMESTAMPTZ,
                        published_at TIMESTAMPTZ NOT NULL DEFAULT NOW(), metadata JSONB);
                    DELETE FROM dataset_versions WHERE version LIKE 'zztest%';
                    DELETE FROM live_places WHERE osm_id BETWEEN 990000011 AND 990000019;
                    INSERT INTO dataset_versions (version, pbf_timestamp) VALUES
                        ('zztest-prev', '2099-01-01T00:00:00Z'), ('zztest-new', '2099-01-02T00:00:00Z');
                    INSERT INTO live_places (osm_type, osm_id, version, osm_timestamp) VALUES
                        ('node', 990000011, 1, '2098-12-31T00:00:00Z'),
                        ('node', 990000012, 1, '2099-01-01T12:00:00Z');
                    """)
                    cur.execute(PRUNE_LIVE_SQL)
                    cur.execute("SELECT osm_id FROM live_places WHERE osm_id BETWEEN 990000011 AND 990000019")
                    assert [r["osm_id"] for r in cur.fetchall()] == [990000012]
                    raise Rollback()
        except Rollback:
            pass


def test_way_candidates_and_centroid():
    from app.routers.edits import parse_osmchange_way_candidates, way_centroid_from_full

    xml = """<osmChange><modify>
      <way id="10" version="3"><tag k="building" v="mosque"/></way>
      <way id="11" version="1"><tag k="building" v="yes"/></way>
    </modify><delete><way id="12" version="2"/></delete></osmChange>"""
    assert [w["osm_id"] for w in parse_osmchange_way_candidates(xml)] == [10]

    full = """<osm><node id="1" lat="24.0" lon="46.0"/><node id="2" lat="24.2" lon="46.2"/>
      <way id="10"><nd ref="1"/><nd ref="2"/></way></osm>"""
    lat, lon = way_centroid_from_full(full)
    assert (round(lat, 6), round(lon, 6)) == (24.1, 46.1)
    assert way_centroid_from_full("<osm/>") is None
    assert way_centroid_from_full("garbage") is None
