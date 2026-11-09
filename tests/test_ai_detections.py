"""Satellite AI detections: private to MANARA_SUGGESTIONS_ALLOWLIST, reviewable, synced by app.ai_sync."""
import os
import sys
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from app.ai_sync import _polygon_wkt, export_reviews, import_detections  # noqa: E402
from app.auth import get_current_user  # noqa: E402
from app.database import get_db  # noqa: E402
from app.main import app  # noqa: E402

ME = {"osm_uid": 42, "display_name": "Reviewer", "is_admin": False}
CSRF = {"X-Manara-CSRF": "1", "Origin": "https://manara.saudiosm.org"}
ROW = {
    "detection_id": "ai_det_00088", "confidence": 0.71, "dual_provider": True, "region_code": "SA-01",
    "region_name": "Riyadh", "qibla_bearing": 244.1, "est_area_m2": 640.0, "model": "best_v5_obb.pt",
    "lon": 46.7, "lat": 24.7, "footprint": '{"type":"Polygon","coordinates":[[[46.7,24.7],[46.70,24.71],[46.71,24.71],[46.7,24.7]]]}',
    "n_positive": 1, "n_negative": 0, "n_unsure": 0, "my_verdict": "positive",
}


@pytest.fixture
def db():
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchall.return_value = [ROW]
    cur.fetchone.side_effect = [{"?column?": 1}, {"n_positive": 0, "n_negative": 1, "n_unsure": 0}]
    return conn, cur


@pytest.fixture
def client(db, monkeypatch):
    monkeypatch.setenv("MANARA_SUGGESTIONS_ALLOWLIST", "42")

    def override_get_db():
        yield db[0]

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


def login(user=ME):
    app.dependency_overrides[get_current_user] = lambda: dict(user)


def test_anonymous_gets_401(client):
    assert client.get("/api/v1/ai/detections").status_code == 401
    assert client.put("/api/v1/ai/detections/ai_det_00088/review", json={"verdict": "positive"},
                      headers=CSRF).status_code == 401


def test_user_not_on_allowlist_gets_403(client):
    login({**ME, "osm_uid": 7})
    assert client.get("/api/v1/ai/detections").status_code == 403
    assert client.put("/api/v1/ai/detections/ai_det_00088/review", json={"verdict": "positive"},
                      headers=CSRF).status_code == 403


def test_list_returns_geojson_with_tallies_and_own_verdict(client):
    login()
    r = client.get("/api/v1/ai/detections")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "private, no-store"
    f = r.json()["features"][0]
    assert f["geometry"]["coordinates"] == [46.7, 24.7]
    assert f["properties"]["id"] == "ai_det_00088"
    assert f["properties"]["dual"] is True
    assert f["properties"]["my_verdict"] == "positive"
    assert f["properties"]["n_positive"] == 1


def test_review_upserts_and_returns_tally(client, db):
    login()
    r = client.put("/api/v1/ai/detections/ai_det_00088/review", json={"verdict": "negative"}, headers=CSRF)
    assert r.status_code == 200, r.text
    assert r.json() == {"id": "ai_det_00088", "my_verdict": "negative", "n_positive": 0, "n_negative": 1, "n_unsure": 0}
    sql = [c.args[0] for c in db[1].execute.call_args_list]
    assert any("ON CONFLICT (detection_id, osm_uid)" in s for s in sql)
    insert_args = next(c.args[1] for c in db[1].execute.call_args_list if "INSERT INTO ai_detection_reviews" in c.args[0])
    assert insert_args == ("ai_det_00088", 42, "negative")


def test_review_requires_csrf(client):
    login()
    r = client.put("/api/v1/ai/detections/ai_det_00088/review", json={"verdict": "positive"})
    assert r.status_code == 403


@pytest.mark.parametrize("verdict", ["yes", "", "POSITIVE", None])
def test_review_rejects_unknown_verdicts(client, verdict):
    login()
    r = client.put("/api/v1/ai/detections/ai_det_00088/review", json={"verdict": verdict}, headers=CSRF)
    assert r.status_code == 422


@pytest.mark.parametrize("bad_id", ["x", "ai_det_", "ai_det_1;drop", "ai_det_123456789"])
def test_review_rejects_malformed_ids(client, bad_id):
    login()
    r = client.put(f"/api/v1/ai/detections/{bad_id}/review", json={"verdict": "positive"}, headers=CSRF)
    assert r.status_code in (404, 422)


def test_review_of_unknown_detection_is_404(client, db):
    login()
    db[1].fetchone.side_effect = [None]
    r = client.put("/api/v1/ai/detections/ai_det_00001/review", json={"verdict": "positive"}, headers=CSRF)
    assert r.status_code == 404


def test_polygon_wkt_closes_ring_and_rejects_degenerate():
    assert _polygon_wkt([[1, 2], [3, 4], [5, 6]]) == "POLYGON((1.0 2.0, 3.0 4.0, 5.0 6.0, 1.0 2.0))"
    assert _polygon_wkt([[1, 2], [3, 4]]) is None
    assert _polygon_wkt(None) is None


# --- Real PostGIS round trip (runs in CI, where MANARA_DATABASE_URL points at a throwaway DB) ---

DB_URL = os.environ.get("MANARA_DATABASE_URL")


@pytest.mark.skipif(not DB_URL, reason="needs MANARA_DATABASE_URL (PostGIS)")
def test_sync_round_trip_on_postgis():
    import psycopg
    from psycopg.rows import dict_row

    from app.schema import init_app_tables

    det = {"id": "ai_det_99001", "lat": 24.7, "lon": 46.7, "confidence": 0.8, "dual": True,
           "footprint": [[46.7, 24.7], [46.7001, 24.7], [46.7001, 24.7001], [46.7, 24.7001]],
           "region_code": "SA-01", "region_name": "Riyadh", "qibla": 244.0, "area_m2": 120.0,
           "model": "best_v5_obb.pt"}
    with psycopg.connect(DB_URL, row_factory=dict_row, autocommit=True) as conn:
        init_app_tables(conn)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM ai_detections WHERE detection_id LIKE 'ai_det_99%%'")
            cur.execute("INSERT INTO users (osm_uid, display_name) VALUES (990001, 't') ON CONFLICT DO NOTHING")
        try:
            out = import_detections(conn, {"detections": [det, {**det, "id": "ai_det_99002", "footprint": None}]})
            assert out["upserted"] == 2
            with conn.cursor() as cur:
                cur.execute("INSERT INTO ai_detection_reviews (detection_id, osm_uid, verdict) "
                            "VALUES ('ai_det_99001', 990001, 'positive')")
            # second upload drops 99002 -> retired, 99001 keeps its review
            out = import_detections(conn, {"detections": [det]})
            assert out["retired"] >= 1
            with conn.cursor() as cur:
                cur.execute("SELECT retired_at IS NOT NULL AS gone FROM ai_detections WHERE detection_id = 'ai_det_99002'")
                assert cur.fetchone()["gone"] is True
            rev = export_reviews(conn)
            assert rev["ai_det_99001"]["n_positive"] == 1
        finally:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM ai_detections WHERE detection_id LIKE 'ai_det_99%%'")
                cur.execute("DELETE FROM users WHERE osm_uid = 990001")
