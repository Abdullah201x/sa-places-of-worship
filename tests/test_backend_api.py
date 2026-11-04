import os
import sys
import pytest
from datetime import datetime, timedelta, timezone
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from unittest.mock import MagicMock
from app.main import app
from app.database import get_db
from app.arabic import normalize_arabic


@pytest.fixture
def client():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchall.return_value = []
    mock_cur.fetchone.return_value = None

    def override_get_db():
        yield mock_conn

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


def test_healthz_endpoint(client):
    res = client.get("/api/healthz")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def _freshness_client(row):
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur
    mock_cur.fetchone.return_value = row

    def override_get_db():
        yield mock_conn

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app, raise_server_exceptions=False)


def test_freshness_fresh_dataset():
    published = datetime.now(timezone.utc) - timedelta(hours=5)
    with _freshness_client({"version": "v1", "published_at": published}) as c:
        res = c.get("/api/healthz/freshness")
    app.dependency_overrides.clear()
    assert res.status_code == 200
    assert res.json()["status"] == "ok"
    assert res.json()["version"] == "v1"


def test_freshness_stale_dataset():
    published = datetime.now(timezone.utc) - timedelta(days=4)
    with _freshness_client({"version": "v1", "published_at": published}) as c:
        res = c.get("/api/healthz/freshness")
    app.dependency_overrides.clear()
    assert res.status_code == 503
    assert res.json()["status"] == "stale"


def test_freshness_no_dataset():
    with _freshness_client(None) as c:
        res = c.get("/api/healthz/freshness")
    app.dependency_overrides.clear()
    assert res.status_code == 503
    assert res.json()["status"] == "stale"


def test_health_endpoints_accept_head(client):
    # UptimeRobot's free tier checks with HEAD.
    assert client.head("/api/healthz").status_code == 200
    assert client.head("/api/healthz/freshness").status_code in (200, 503)


def test_suggestions_bbox_validation(client, monkeypatch):
    # The endpoint is allowlist-only (see tests/test_suggestions_access.py); sign in as an allowed user.
    from app.auth import get_current_user
    monkeypatch.setenv("MANARA_SUGGESTIONS_ALLOWLIST", "42")
    app.dependency_overrides[get_current_user] = lambda: {"osm_uid": 42}

    # Missing bbox parameter
    res = client.get("/api/v1/suggestions")
    assert res.status_code == 422

    # Malformed bbox
    res = client.get("/api/v1/suggestions?bbox=invalid")
    assert res.status_code == 400
    assert "Invalid bbox format" in res.json()["detail"]

    # Inverted bbox (min > max)
    res = client.get("/api/v1/suggestions?bbox=47.0,25.0,46.0,24.0")
    assert res.status_code == 400

    # Oversized bbox (> 3.0 degrees)
    res = client.get("/api/v1/suggestions?bbox=40.0,20.0,45.0,25.0")
    assert res.status_code == 400
    assert "Bbox too large" in res.json()["detail"]


def test_places_path_validation(client):
    # Invalid OSM type (only node, way, relation permitted)
    res = client.get("/api/v1/places/invalid_type/123")
    assert res.status_code == 422

    # Negative OSM id
    res = client.get("/api/v1/places/node/-5")
    assert res.status_code == 422


def test_search_query_validation(client):
    # Missing q parameter
    res = client.get("/api/v1/search")
    assert res.status_code == 422

    # Single character (min length 2)
    res = client.get("/api/v1/search?q=a")
    assert res.status_code == 422


def test_backend_arabic_normalization():
    assert normalize_arabic("جامع الإمام تركي") == "مسجد الامام تركي"
    assert normalize_arabic("مَسْجِدُ الرَّحْمَٰنِ") == "مسجد الرحمن"
    assert normalize_arabic("الجامع الكبير", strip_al=True) == "مسجد كبير"


def test_get_issues_endpoint():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    mock_cur.fetchone.return_value = None
    mock_cur.fetchall.return_value = [
        {
            "rule_id": "missing_name_en",
            "severity": "medium",
            "osm_type": "way",
            "osm_id": 12345,
            "name": "جامع الملك فهد",
            "name_en": "",
            "religion": "muslim",
            "denomination": "sunni",
            "region_code": "SA-01",
            "region_name": "منطقة الرياض",
            "lon": 46.7,
            "lat": 24.7,
            "suggested_fix": None,
            "review_status": None,
        }
    ]

    def override_get_db():
        yield mock_conn

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as c:
        res = c.get("/api/v1/issues?rule_id=missing_name_en&region_code=SA-01")
        assert res.status_code == 200
        data = res.json()
        assert data["count"] == 1
        assert data["issues"][0]["osm_id"] == 12345
        assert data["issues"][0]["coordinates"] == [46.7, 24.7]
    app.dependency_overrides.clear()


def test_issues_rejects_sql_injection_payload():
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = mock_cur

    def override_get_db():
        yield mock_conn

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            res = c.get("/api/v1/issues?rule_id=';DROP TABLE places;--")
            assert res.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_rate_limiting_active():
    from app.limiter import limiter
    try:
        with TestClient(app, raise_server_exceptions=False) as c:
            responses = [
                c.post("/api/v1/transliterate", json={"name": "مسجد الهدى"})
                for _ in range(35)
            ]
            status_codes = [r.status_code for r in responses]
            assert 429 in status_codes
    finally:
        limiter._limiter.storage.reset()





