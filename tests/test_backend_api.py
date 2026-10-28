import os
import sys
import pytest
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


def test_suggestions_bbox_validation(client):
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
