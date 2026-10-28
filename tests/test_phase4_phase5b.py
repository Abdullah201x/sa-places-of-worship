import os
import sys
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from app.main import app
from app.database import get_db
from app.auth import get_current_user, hash_token


@pytest.fixture
def db_mocks():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchall.return_value = []
    mock_cur.fetchone.return_value = None

    def override_get_db():
        yield mock_conn

    app.dependency_overrides[get_db] = override_get_db
    yield mock_conn, mock_cur
    app.dependency_overrides.clear()


@pytest.fixture
def client(db_mocks):
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# CSRF Protection Tests
# ---------------------------------------------------------------------------

def test_csrf_header_required_on_post(client):
    res = client.post("/auth/logout")
    assert res.status_code == 403
    assert "X-Manara-CSRF" in res.json()["detail"]


def test_csrf_invalid_origin_forbidden(client):
    res = client.post(
        "/auth/logout",
        headers={"X-Manara-CSRF": "1", "Origin": "https://malicious-site.com"},
    )
    assert res.status_code == 403
    assert "Forbidden cross-origin" in res.json()["detail"]


# ---------------------------------------------------------------------------
# Auth Endpoints Tests
# ---------------------------------------------------------------------------

@patch("httpx.AsyncClient.get")
def test_create_session_success(mock_get, client, db_mocks):
    mock_conn, mock_cur = db_mocks

    # Mock OSM user details response
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "user": {
            "id": 12345,
            "display_name": "TestMapper",
            "img": {"href": "https://example.com/avatar.jpg"},
            "changesets": {"count": 42},
            "account_created": "2020-01-01T00:00:00Z",
        }
    }
    mock_get.return_value = mock_resp

    mock_cur.fetchone.return_value = {
        "osm_uid": 12345,
        "display_name": "TestMapper",
        "avatar_url": "https://example.com/avatar.jpg",
        "osm_changesets": 42,
        "leaderboard_opt_in": False,
        "is_admin": False,
    }

    res = client.post(
        "/auth/session",
        headers={"X-Manara-CSRF": "1", "Origin": "https://manara.saudiosm.org"},
        json={"access_token": "valid_token_1234567890"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["user"]["osm_uid"] == 12345
    assert data["user"]["display_name"] == "TestMapper"
    # Ensure cookie is set
    assert any("manara_session" in c for c in res.cookies.keys())


def test_get_me_unauthorized(client):
    res = client.get("/api/v1/me")
    assert res.status_code == 401


def test_get_me_authorized(client, db_mocks):
    mock_conn, mock_cur = db_mocks
    raw_token = "valid_test_token_string_hex"
    token_h = hash_token(raw_token)

    mock_cur.fetchone.return_value = {
        "token_hash": token_h,
        "osm_uid": 12345,
        "display_name": "TestMapper",
        "avatar_url": "https://example.com/avatar.jpg",
        "osm_changesets": 42,
        "osm_account_created": datetime(2020, 1, 1, tzinfo=timezone.utc),
        "leaderboard_opt_in": False,
        "is_admin": False,
        "last_seen_at": datetime.now(timezone.utc),
        "expires_at": datetime.now(timezone.utc),
    }

    client.cookies.set("manara_session", raw_token)
    res = client.get("/api/v1/me")
    assert res.status_code == 200
    assert res.json()["osm_uid"] == 12345
    assert res.json()["display_name"] == "TestMapper"


def test_patch_me_leaderboard_opt_in(client, db_mocks):
    mock_conn, mock_cur = db_mocks
    raw_token = "valid_test_token_string_hex"
    token_h = hash_token(raw_token)

    mock_cur.fetchone.side_effect = [
        # Session lookup
        {
            "token_hash": token_h,
            "osm_uid": 12345,
            "display_name": "TestMapper",
            "avatar_url": None,
            "osm_changesets": 10,
            "osm_account_created": None,
            "leaderboard_opt_in": False,
            "is_admin": False,
            "last_seen_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc),
        },
        # Update returning
        {
            "osm_uid": 12345,
            "display_name": "TestMapper",
            "avatar_url": None,
            "osm_changesets": 10,
            "leaderboard_opt_in": True,
            "is_admin": False,
        },
    ]

    client.cookies.set("manara_session", raw_token)
    res = client.patch(
        "/api/v1/me",
        headers={"X-Manara-CSRF": "1", "Origin": "https://manara.saudiosm.org"},
        json={"leaderboard_opt_in": True},
    )
    assert res.status_code == 200
    assert res.json()["user"]["leaderboard_opt_in"] is True


# ---------------------------------------------------------------------------
# Reviews Endpoints Tests
# ---------------------------------------------------------------------------

def test_get_reviews_empty(client, db_mocks):
    res = client.get("/api/v1/reviews")
    assert res.status_code == 200
    assert res.json() == {"count": 0, "marks": {}}


def test_put_review_mark(client, db_mocks):
    mock_conn, mock_cur = db_mocks
    raw_token = "valid_test_token_string_hex"
    token_h = hash_token(raw_token)

    mock_cur.fetchone.side_effect = [
        # Session check
        {
            "token_hash": token_h,
            "osm_uid": 12345,
            "display_name": "TestMapper",
            "avatar_url": None,
            "osm_changesets": 50,
            "osm_account_created": None,
            "leaderboard_opt_in": True,
            "is_admin": False,
            "last_seen_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc),
        },
        # Review insert returning
        {
            "osm_type": "way",
            "osm_id": 9999,
            "osm_uid": 12345,
            "status": "fixed",
            "version": 2,
            "verified_changeset": None,
            "created_at": datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc),
        },
    ]

    client.cookies.set("manara_session", raw_token)
    res = client.put(
        "/api/v1/reviews/way/9999",
        headers={"X-Manara-CSRF": "1", "Origin": "https://manara.saudiosm.org"},
        json={"status": "fixed", "version": 2},
    )
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    assert res.json()["mark"]["key"] == "way/9999"
    assert res.json()["mark"]["status"] == "fixed"


# ---------------------------------------------------------------------------
# Community Leaderboard & Recent Edits Tests
# ---------------------------------------------------------------------------

def test_get_leaderboard(client, db_mocks):
    mock_conn, mock_cur = db_mocks
    mock_cur.fetchall.return_value = [
        {
            "osm_uid": 12345,
            "display_name": "TopMapper",
            "avatar_url": "https://example.com/avatar.jpg",
            "osm_changesets": 1500,
            "verified_edits_count": 25,
            "verified_fixes_count": 80,
            "last_active_at": datetime(2026, 10, 28, 10, 0, 0, tzinfo=timezone.utc),
        }
    ]

    res = client.get("/api/v1/leaderboard")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] == 1
    assert data["leaderboard"][0]["display_name"] == "TopMapper"
    assert data["leaderboard"][0]["verified_fixes_count"] == 80


def test_get_recent_edits(client, db_mocks):
    mock_conn, mock_cur = db_mocks
    mock_cur.fetchall.return_value = [
        {
            "changeset_id": 160000000,
            "comment": "Fix mosque tags #sa-worship-map",
            "verified_at": datetime(2026, 10, 28, 9, 30, 0, tzinfo=timezone.utc),
            "objects_count": 3,
            "osm_uid": 12345,
            "display_name": "TopMapper",
            "avatar_url": None,
        }
    ]

    res = client.get("/api/v1/edits/recent")
    assert res.status_code == 200
    data = res.json()
    assert data["count"] == 1
    assert data["edits"][0]["changeset_id"] == 160000000
    assert data["edits"][0]["objects_count"] == 3


# ---------------------------------------------------------------------------
# SEO Endpoints Tests
# ---------------------------------------------------------------------------

def test_get_region_page(client, db_mocks):
    mock_conn, mock_cur = db_mocks
    mock_cur.fetchone.side_effect = [
        # Region info
        {
            "code": "SA-01",
            "name": "منطقة الرياض",
            "name_en": "Riyadh Region",
            "center_lat": 24.7,
            "center_lon": 46.7,
        },
        # Region stats
        {
            "places_count": 4132,
            "gaps_count": 10642,
            "suggestions_count": 10320,
            "anomalies_count": 11,
            "qibla_deviated_count": 69,
        },
    ]
    mock_cur.fetchall.return_value = [
        {
            "osm_type": "way",
            "osm_id": 1234,
            "name": "جامع الإمام تركي بن عبد الله",
            "name_en": "Imam Turki bin Abdullah Mosque",
            "religion": "muslim",
            "denomination": "sunni",
        }
    ]

    res = client.get("/region/SA-01")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "منطقة الرياض" in res.text
    assert "Riyadh Region" in res.text
    assert "جامع الإمام تركي" in res.text
    assert res.headers.get("cache-control") == "public, max-age=3600"


def test_get_place_page_named_indexable(client, db_mocks):
    mock_conn, mock_cur = db_mocks
    mock_cur.fetchone.return_value = {
        "osm_type": "way",
        "osm_id": 9999,
        "version": 3,
        "name": "مسجد الرحمة",
        "name_en": "Al-Rahma Mosque",
        "religion": "muslim",
        "denomination": "sunni",
        "area_m2": 850.5,
        "qibla_dev": 2.1,
        "region_code": "SA-02",
        "region_name": "منطقة مكة المكرمة",
        "lat": 21.5,
        "lon": 39.1,
    }

    res = client.get("/place/way/9999")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "مسجد الرحمة" in res.text
    assert "Al-Rahma Mosque" in res.text
    # Named places are indexable, so noindex should NOT be present
    assert '<meta name="robots" content="noindex' not in res.text


def test_get_place_page_unnamed_noindex(client, db_mocks):
    mock_conn, mock_cur = db_mocks
    mock_cur.fetchone.return_value = {
        "osm_type": "node",
        "osm_id": 8888,
        "version": 1,
        "name": "",
        "name_en": None,
        "religion": "muslim",
        "denomination": None,
        "area_m2": None,
        "qibla_dev": None,
        "region_code": "SA-01",
        "region_name": "منطقة الرياض",
        "lat": 24.5,
        "lon": 46.5,
    }

    res = client.get("/place/node/8888")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    # Generic/unnamed places get noindex
    assert '<meta name="robots" content="noindex, follow">' in res.text


def test_get_sitemap(client, db_mocks):
    mock_conn, mock_cur = db_mocks
    mock_cur.fetchall.side_effect = [
        # Regions
        [{"code": "SA-01"}, {"code": "SA-02"}],
        # Named places
        [
            {"osm_type": "way", "osm_id": 111, "edited_at": datetime(2026, 10, 20)},
            {"osm_type": "node", "osm_id": 222, "edited_at": None},
        ],
    ]

    res = client.get("/sitemap.xml")
    assert res.status_code == 200
    assert "application/xml" in res.headers["content-type"]
    assert "<urlset" in res.text
    assert "<loc>https://manara.saudiosm.org/</loc>" in res.text
    assert "<loc>https://manara.saudiosm.org/region/SA-01</loc>" in res.text
    assert "<loc>https://manara.saudiosm.org/place/way/111</loc>" in res.text
