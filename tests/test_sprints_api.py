import json
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from app.main import app
from app.database import get_db
from app.auth import get_current_user, require_admin


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


def test_list_sprints_empty(client):
    c, (conn, cur) = client
    cur.fetchall.return_value = []

    res = c.get("/api/v1/sprints?status=active")
    assert res.status_code == 200
    assert res.json() == []


def test_sprint_csrf_protection_enforced(client):
    c, _ = client
    payload = {"slug": "test", "title": {"en": "Test"}, "hashtag": "#t", "area": {"region_code": "SA-01"}}
    res = c.post("/api/v1/sprints", json=payload)
    assert res.status_code == 403
    assert "CSRF" in res.json()["detail"]


def test_create_sprint_admin_only(client):
    c, (conn, cur) = client

    # Without admin -> 401
    payload = {
        "slug": "al-kharj-test",
        "title": {"ar": "مساجد الخرج", "en": "Al Kharj Mosques"},
        "hashtag": "#manara-kharj",
        "area": {"region_code": "SA-01"},
    }
    res = c.post("/api/v1/sprints", json=payload, headers={"X-Manara-CSRF": "1"})
    assert res.status_code == 401


def test_create_sprint_success(client, monkeypatch):
    c, (conn, cur) = client
    monkeypatch.setattr("app.routers.sprints.workload_tiles_for_area", lambda *a, **k: None)

    def override_require_admin():
        return {"osm_uid": 999999, "display_name": "AdminUser", "is_admin": True}

    app.dependency_overrides[require_admin] = override_require_admin

    cur.fetchone.side_effect = [
        None,  # slug check (no existing)
        {      # RETURNING sprint
            "id": 1,
            "slug": "al-kharj-sprint",
            "title": {"ar": "مساجد الخرج", "en": "Al Kharj Mosques"},
            "instructions": {},
            "theme": "worship",
            "area": {"region_code": "SA-01"},
            "rule_ids": ["missing_amenity"],
            "gap_min_urgency": 5,
            "hashtag": "#manara-kharj",
            "starts_at": datetime.now(timezone.utc),
            "ends_at": None,
            "status": "active",
            "created_by": 999999,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
        }
    ]
    cur.fetchall.return_value = [
        {"state": "ready", "cnt": 10, "work_sum": 25}
    ]

    payload = {
        "slug": "al-kharj-sprint",
        "title": {"ar": "مساجد الخرج", "en": "Al Kharj Mosques"},
        "hashtag": "#manara-kharj",
        "area": {
            "polygon": {
                "type": "Polygon",
                "coordinates": [[[46.5, 24.5], [46.6, 24.5], [46.6, 24.6], [46.5, 24.6], [46.5, 24.5]]]
            }
        },
        "rule_ids": ["missing_amenity"],
        "gap_min_urgency": 5,
        "status": "active"
    }

    res = c.post("/api/v1/sprints", json=payload, headers={"X-Manara-CSRF": "1"})
    assert res.status_code == 201
    data = res.json()
    assert data["slug"] == "al-kharj-sprint"
    assert "progress" in data
    assert data["progress"]["total"] == 10


def test_get_sprint_tiles_and_etag(client):
    c, (conn, cur) = client

    cur.fetchone.return_value = {"id": 1, "slug": "al-kharj-sprint"}
    cur.fetchall.side_effect = [
        [    # sprint tiles
            {
                "tile_id": "2330:1225",
                "bbox": [46.60, 24.50, 46.62, 24.52],
                "state": "ready",
                "rev": 3,
                "workload": 5,
                "pending_refresh": False,
                "lock_uid": None,
                "lock_display_name": None,
                "lock_kind": None,
                "lock_expires_at": None,
                "mapped_by": None,
                "validated_by": None,
                "auto": False
            }
        ]
    ]

    res = c.get("/api/v1/sprints/al-kharj-sprint/tiles")
    assert res.status_code == 200
    assert "ETag" in res.headers
    assert res.headers["ETag"] == 'W/"1:1:3:0"'
    data = res.json()
    assert data["rev_max"] == 3
    assert len(data["tiles"]) == 1

    # 304 Not Modified when matching If-None-Match
    cur.fetchone.return_value = {"id": 1, "slug": "al-kharj-sprint"}
    cur.fetchall.side_effect = [
        [
            {
                "tile_id": "2330:1225",
                "bbox": [46.60, 24.50, 46.62, 24.52],
                "state": "ready",
                "rev": 3,
                "workload": 5,
                "pending_refresh": False,
                "lock_uid": None,
                "lock_display_name": None,
                "lock_kind": None,
                "lock_expires_at": None,
                "mapped_by": None,
                "validated_by": None,
                "auto": False
            }
        ]
    ]
    res304 = c.get("/api/v1/sprints/al-kharj-sprint/tiles", headers={"If-None-Match": 'W/"1:1:3:0"'})
    assert res304.status_code == 304


def test_optimistic_concurrency_conflict_409(client):
    c, (conn, cur) = client

    def override_current_user():
        return {"osm_uid": 1001, "display_name": "Mapper1", "is_admin": False}

    app.dependency_overrides[get_current_user] = override_current_user

    cur.fetchone.side_effect = [
        {"id": 1},  # sprint lookup
        {           # tile lookup with rev = 5
            "sprint_id": 1,
            "tile_id": "2330:1225",
            "bbox": [46.60, 24.50, 46.62, 24.52],
            "state": "ready",
            "rev": 5,
            "workload": 2,
            "mapped_by": None
        }
    ]
    cur.fetchall.return_value = []

    # Client thinks rev is 4 -> must return 409 Conflict
    res = c.put(
        "/api/v1/sprints/al-kharj-sprint/tiles/2330:1225",
        json={"action": "lock", "rev": 4, "kind": "mapping"},
        headers={"X-Manara-CSRF": "1"}
    )
    assert res.status_code == 409
    assert "Conflict" in res.json()["detail"]


def test_self_validation_rejected_403(client):
    c, (conn, cur) = client

    def override_current_user():
        return {"osm_uid": 1001, "display_name": "Mapper1", "is_admin": False}

    app.dependency_overrides[get_current_user] = override_current_user

    cur.fetchone.side_effect = [
        {"id": 1},  # sprint lookup
        {           # tile lookup: mapped_by == 1001!
            "sprint_id": 1,
            "tile_id": "2330:1225",
            "bbox": [46.60, 24.50, 46.62, 24.52],
            "state": "mapped",
            "rev": 2,
            "workload": 0,
            "mapped_by": 1001,  # same user!
            "lock_uid": None
        },
        {"active_locks": 0}
    ]
    cur.fetchall.return_value = []

    # Mapper tries to lock their own mapped tile for validation -> 403 Forbidden!
    res = c.put(
        "/api/v1/sprints/al-kharj-sprint/tiles/2330:1225",
        json={"action": "lock", "rev": 2, "kind": "validation"},
        headers={"X-Manara-CSRF": "1"}
    )
    assert res.status_code == 403
    assert "Self-validation is not allowed" in res.json()["detail"]


def test_max_locks_limit_enforced_403(client):
    c, (conn, cur) = client

    def override_current_user():
        return {"osm_uid": 1002, "display_name": "Mapper2", "is_admin": False}

    app.dependency_overrides[get_current_user] = override_current_user

    cur.fetchone.side_effect = [
        {"id": 1},  # sprint lookup
        {           # tile lookup
            "sprint_id": 1,
            "tile_id": "2330:1225",
            "bbox": [46.60, 24.50, 46.62, 24.52],
            "state": "ready",
            "rev": 1,
            "workload": 4,
            "mapped_by": None
        },
        {"active_locks": 3}  # user already has 3 active locks!
    ]
    cur.fetchall.return_value = []

    res = c.put(
        "/api/v1/sprints/al-kharj-sprint/tiles/2330:1225",
        json={"action": "lock", "rev": 1, "kind": "mapping"},
        headers={"X-Manara-CSRF": "1"}
    )
    assert res.status_code == 403
    assert "simultaneous locks" in res.json()["detail"]


def test_tile_done_and_validation_lifecycle(client):
    c, (conn, cur) = client

    # 1. Mapper marks tile done
    def override_mapper():
        return {"osm_uid": 2001, "display_name": "MapperAlice", "is_admin": False}

    app.dependency_overrides[get_current_user] = override_mapper

    cur.fetchone.side_effect = [
        {"id": 1},  # sprint lookup
        {           # tile lookup
            "sprint_id": 1,
            "tile_id": "2330:1225",
            "bbox": [46.60, 24.50, 46.62, 24.52],
            "state": "mapping",
            "rev": 2,
            "workload": 3,
            "lock_uid": 2001,
            "mapped_by": None
        },
        {           # updated tile
            "tile_id": "2330:1225",
            "bbox": [46.60, 24.50, 46.62, 24.52],
            "state": "mapped",
            "rev": 3,
            "workload": 3,
            "mapped_by": 2001,
            "validated_by": None,
            "auto": False
        }
    ]
    cur.fetchall.return_value = []

    res_done = c.put(
        "/api/v1/sprints/al-kharj-sprint/tiles/2330:1225",
        json={"action": "done", "rev": 2, "note": "Mapped all 3 mosques"},
        headers={"X-Manara-CSRF": "1"}
    )
    assert res_done.status_code == 200
    assert res_done.json()["state"] == "mapped"
    assert res_done.json()["mapped_by"] == 2001

    # 2. Validator (different user 2002) approves tile
    def override_validator():
        return {"osm_uid": 2002, "display_name": "ValidatorBob", "is_admin": False}

    app.dependency_overrides[get_current_user] = override_validator

    cur.fetchone.side_effect = [
        {"id": 1},  # sprint lookup
        {           # tile lookup
            "sprint_id": 1,
            "tile_id": "2330:1225",
            "bbox": [46.60, 24.50, 46.62, 24.52],
            "state": "mapped",
            "rev": 3,
            "workload": 3,
            "lock_uid": None,
            "mapped_by": 2001  # mapped by Alice!
        },
        {           # updated tile
            "tile_id": "2330:1225",
            "bbox": [46.60, 24.50, 46.62, 24.52],
            "state": "validated",
            "rev": 4,
            "workload": 3,
            "mapped_by": 2001,
            "validated_by": 2002,
            "auto": False
        }
    ]

    res_approve = c.put(
        "/api/v1/sprints/al-kharj-sprint/tiles/2330:1225",
        json={"action": "approve", "rev": 3, "note": "Verified tags and outlines"},
        headers={"X-Manara-CSRF": "1"}
    )
    assert res_approve.status_code == 200
    assert res_approve.json()["state"] == "validated"
    assert res_approve.json()["validated_by"] == 2002


def test_tile_invalidate_requires_reason(client):
    c, (conn, cur) = client

    def override_validator():
        return {"osm_uid": 2002, "display_name": "ValidatorBob", "is_admin": False}

    app.dependency_overrides[get_current_user] = override_validator

    cur.fetchone.side_effect = [
        {"id": 1},
        {
            "sprint_id": 1,
            "tile_id": "2330:1225",
            "bbox": [46.60, 24.50, 46.62, 24.52],
            "state": "mapped",
            "rev": 3,
            "workload": 3,
            "mapped_by": 2001
        }
    ]
    cur.fetchall.return_value = []

    # Invalidate without reason -> 400
    res_no_reason = c.put(
        "/api/v1/sprints/al-kharj-sprint/tiles/2330:1225",
        json={"action": "invalidate", "rev": 3},
        headers={"X-Manara-CSRF": "1"}
    )
    assert res_no_reason.status_code == 400

    # Invalidate with reason -> 200
    cur.fetchone.side_effect = [
        {"id": 1},
        {
            "sprint_id": 1,
            "tile_id": "2330:1225",
            "bbox": [46.60, 24.50, 46.62, 24.52],
            "state": "mapped",
            "rev": 3,
            "workload": 3,
            "mapped_by": 2001
        },
        {
            "tile_id": "2330:1225",
            "bbox": [46.60, 24.50, 46.62, 24.52],
            "state": "invalidated",
            "rev": 4,
            "workload": 3,
            "mapped_by": 2001,
            "validated_by": None,
            "auto": False
        }
    ]

    res_valid = c.put(
        "/api/v1/sprints/al-kharj-sprint/tiles/2330:1225",
        json={"action": "invalidate", "rev": 3, "reason": "Missing mosque outline on north side"},
        headers={"X-Manara-CSRF": "1"}
    )
    assert res_valid.status_code == 200
    assert res_valid.json()["state"] == "invalidated"


def test_maproulette_export(client):
    c, (conn, cur) = client

    cur.fetchone.return_value = {
        "id": 1,
        "slug": "al-kharj-sprint",
        "hashtag": "#manara-kharj"
    }
    cur.fetchall.return_value = [
        {
            "tile_id": "2330:1225",
            "bbox": [46.60, 24.50, 46.62, 24.52],
            "state": "ready",
            "workload": 3,
            "mapped_by": None
        }
    ]

    res = c.get("/api/v1/sprints/al-kharj-sprint/maproulette")
    assert res.status_code == 200
    fc = res.json()
    assert fc["type"] == "FeatureCollection"
    assert len(fc["features"]) == 1
    feat = fc["features"][0]
    assert feat["properties"]["taskIdentifier"] == "al-kharj-sprint_2330_1225"
    assert feat["geometry"]["type"] == "Polygon"


def test_every_region_code_is_a_real_iso_code():
    from app.routers.sprints import REGION_BOUNDS
    assert set(REGION_BOUNDS) == {f"SA-{n:02d}" for n in (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14)}


def test_region_sprint_uses_non_empty_clipped_tiles(client, monkeypatch):
    """A province must not be tiled as its full bbox (up to 236k tiles): only cells with work are stored."""
    c, (conn, cur) = client
    app.dependency_overrides[require_admin] = lambda: {"osm_uid": 1, "display_name": "A", "is_admin": True}
    tiles = [{"tile_id": f"{i}:1", "bbox": [0, 0, 1, 1], "workload": 3} for i in range(300)]
    monkeypatch.setattr("app.routers.sprints.workload_tiles_for_area", lambda *a, **k: tiles)
    cur.fetchone.side_effect = [None, {
        "id": 1, "slug": "r", "title": {}, "instructions": {}, "theme": "worship", "area": {"region_code": "SA-04"},
        "rule_ids": [], "gap_min_urgency": None, "hashtag": "#r", "starts_at": None, "ends_at": None,
        "status": "active", "created_by": 1, "created_at": None, "updated_at": None,
    }]
    cur.fetchall.return_value = [{"state": "ready", "cnt": 300, "work_sum": 900}]
    res = c.post("/api/v1/sprints", headers={"X-Manara-CSRF": "1"}, json={
        "slug": "eastern", "title": {"en": "E"}, "hashtag": "#e", "area": {"region_code": "SA-04"}, "status": "active"})
    assert res.status_code == 201
    inserted = cur.executemany.call_args[0][1]
    assert len(inserted) == 300
    assert all(row[5] == 3 for row in inserted)  # initial workload set immediately


def test_tile_actions_blocked_when_sprint_not_active(client):
    c, (conn, cur) = client
    app.dependency_overrides[get_current_user] = lambda: {"osm_uid": 5, "display_name": "m", "is_admin": False}
    cur.fetchone.side_effect = [{"id": 1, "status": "closed"}]
    res = c.put("/api/v1/sprints/x/tiles/1:1", headers={"X-Manara-CSRF": "1"}, json={"action": "lock"})
    assert res.status_code == 409
