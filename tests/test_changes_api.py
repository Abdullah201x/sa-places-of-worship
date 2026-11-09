import os
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from app.main import app
from app.database import get_db


@pytest.fixture
def mock_db():
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    conn.transaction.return_value.__enter__.return_value = conn
    cur.fetchall.return_value = []
    cur.fetchone.return_value = None
    return conn, cur


@pytest.fixture
def client(mock_db):
    conn, _ = mock_db
    def override_get_db():
        yield conn

    app.dependency_overrides[get_db] = override_get_db
    c = TestClient(app)
    yield c, mock_db
    app.dependency_overrides.clear()


def test_get_changes_endpoint(client):
    c, (conn, cur) = client
    cur.fetchall.return_value = [
        {
            "id": 1,
            "source": "daily",
            "confirmed": True,
            "reverted_same_day": False,
            "osm_timestamp": datetime.now(timezone.utc),
            "observed_at": datetime.now(timezone.utc),
            "changeset_id": 123456,
            "replication_seq": None,
            "dataset_version": "v1",
            "osm_type": "node",
            "osm_id": 1001,
            "prev_ref": None,
            "kind": "created",
            "flags": ["deleted-named-mosque"],
            "lon": 46.7,
            "lat": 24.7,
            "region_code": "SA-01",
            "name": "مسجد النور",
            "tag_diff": {},
            "version_before": None,
            "version_after": 1,
            "triage_status": None,
            "triage_uid": None,
            "triage_note": None,
            "triaged_at": None,
        }
    ]

    res = c.get("/api/v1/changes")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] == 1
    assert data["latest_id"] == 1
    assert data["changes"][0]["name"] == "مسجد النور"
    assert "ETag" in res.headers


def test_triage_csrf_required(client):
    c, _ = client
    res = c.post("/api/v1/changes/999/triage", json={"status": "reviewed"})
    assert res.status_code == 403


def test_triage_unauthenticated(client):
    c, _ = client
    res = c.post("/api/v1/changes/999/triage", json={"status": "reviewed"}, headers={"X-Manara-CSRF": "1"})
    assert res.status_code == 401


def test_triage_authenticated_not_found(client):
    c, (conn, cur) = client
    # Session found, but change event not found
    cur.fetchone.side_effect = [
        {"osm_uid": 112233, "osm_username": "validator"},  # user session
        None,  # change_events lookup
    ]

    c.cookies.set("manara_session", "valid_token")
    res = c.post("/api/v1/changes/999999/triage", json={"status": "reviewed", "note": "Checked in JOSM"}, headers={"X-Manara-CSRF": "1"})
    assert res.status_code == 404


def test_triage_authenticated_success(client):
    c, (conn, cur) = client
    cur.fetchone.side_effect = [
        {"osm_uid": 445566, "osm_username": "qa_mapper"},  # user session
        {"id": 777},  # change_events lookup
        {  # insert returning
            "change_id": 777,
            "status": "reviewed",
            "osm_uid": 445566,
            "note": "Approved place",
            "triaged_at": datetime.now(timezone.utc),
        },
    ]

    c.cookies.set("manara_session", "valid_token")
    res = c.post("/api/v1/changes/777/triage", json={"status": "reviewed", "note": "Approved place"}, headers={"X-Manara-CSRF": "1"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["triage"]["status"] == "reviewed"
    assert data["triage"]["osm_uid"] == 445566


def test_triage_rejected_when_owned_by_another_mapper(client):
    c, (conn, cur) = client
    cur.fetchone.side_effect = [
        {"osm_uid": 2, "osm_username": "other_mapper"},  # user session
        {"id": 777},  # change_events lookup
        None,  # upsert returned no row: existing decision belongs to someone else
    ]

    c.cookies.set("manara_session", "valid_token")
    res = c.post("/api/v1/changes/777/triage", json={"status": "flagged"}, headers={"X-Manara-CSRF": "1"})
    assert res.status_code == 403
    assert "another mapper" in res.json()["detail"]


def test_triage_passes_identity_and_admin_flag_to_the_ownership_check(client):
    c, (conn, cur) = client
    cur.fetchone.side_effect = [
        {"osm_uid": 5, "osm_username": "plain_mapper", "is_admin": False},
        {"id": 1},
        {"change_id": 1, "status": "reviewed", "osm_uid": 5, "note": "", "triaged_at": datetime.now(timezone.utc)},
    ]
    c.cookies.set("manara_session", "valid_token")
    res = c.post("/api/v1/changes/1/triage", json={"status": "reviewed"}, headers={"X-Manara-CSRF": "1"})
    assert res.status_code == 200

    upsert_params = [call.args[1] for call in cur.execute.call_args_list
                     if "INSERT INTO change_triage" in str(call.args[0])][0]
    # (change_id, status, uid, note, uid for the owner check, is_admin)
    assert upsert_params[2] == 5 and upsert_params[4] == 5
    assert upsert_params[5] is False


def test_freshness_endpoint(client):
    c, (conn, cur) = client
    now = datetime.now(timezone.utc)
    cur.fetchone.side_effect = [
        {"version": "v20261030", "pbf_date": "2026-10-29", "published_at": now},
        {"sequence": 654321, "osm_timestamp": now, "processed_at": now},
    ]

    res = c.get("/api/v1/freshness")
    assert res.status_code == 200
    data = res.json()
    assert data["data"]["version"] == "v20261030"
    assert data["live"]["sequence"] == 654321


def test_live_healthz(client):
    c, (conn, cur) = client
    # 1. Stale / not initialized
    cur.fetchone.return_value = None
    res = c.get("/api/healthz/live")
    assert res.status_code == 503

    # 2. Fresh
    now = datetime.now(timezone.utc)
    cur.fetchone.return_value = {"sequence": 6000000, "osm_timestamp": now}
    res = c.get("/api/healthz/live")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
