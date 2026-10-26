"""
Comprehensive unit and integration tests for the Flask backend.
"""

import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import create_app
from backend.config import Config


@pytest.fixture
def app():
    # Use a temporary SQLite database for testing to avoid touching production DB
    temp_db_fd, temp_db_path = tempfile.mkstemp(suffix=".db")
    os.close(temp_db_fd)

    class TestConfig(Config):
        TESTING = True
        DB_PATH = temp_db_path

    app = create_app(TestConfig)
    yield app

    if os.path.exists(temp_db_path):
        os.remove(temp_db_path)


@pytest.fixture
def client(app):
    return app.test_client()


def test_health_endpoint(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.get_json()
    assert data["status"] in ("healthy", "degraded")
    assert data["database_connected"] is True
    assert data["datasets"]["places_count"] > 10000


def test_stats_and_summary_endpoints(client):
    res = client.get("/api/stats")
    assert res.status_code == 200
    data = res.get_json()
    assert "places" in data
    assert data["places"]["total"] > 10000
    assert "quality_issues" in data
    assert "gaps" in data

    res_sum = client.get("/api/summary")
    assert res_sum.status_code == 200


def test_places_list_and_search(client):
    # Basic pagination
    res = client.get("/api/places?limit=5")
    assert res.status_code == 200
    data = res.get_json()
    assert data["count"] == 5
    assert data["total"] > 10000
    assert len(data["features"]) == 5

    # Arabic search query
    res_search = client.get("/api/places?q=الراجحي&limit=5")
    assert res_search.status_code == 200
    search_data = res_search.get_json()
    assert search_data["count"] > 0

    # Filter by issue
    res_issue = client.get("/api/places?issue=missing_name&limit=5")
    assert res_issue.status_code == 200


def test_places_detail(client):
    # Lookup first place from list
    res_list = client.get("/api/places?limit=1")
    feat = res_list.get_json()["features"][0]
    osm_type = feat["properties"]["osm_type"]
    osm_id = feat["properties"]["osm_id"]

    res_detail = client.get(f"/api/places/{osm_type}/{osm_id}")
    assert res_detail.status_code == 200
    detail_data = res_detail.get_json()
    assert detail_data["properties"]["osm_id"] == osm_id
    assert "issues" in detail_data["properties"]


def test_nearby_places(client):
    # Query around Riyadh coordinates
    res = client.get("/api/places/nearby?lat=24.7136&lon=46.6753&radius_km=10&limit=5")
    assert res.status_code == 200
    data = res.get_json()
    assert data["count"] > 0
    assert "distance_m" in data["places"][0]


def test_gaps_api(client):
    res = client.get("/api/gaps?limit=10")
    assert res.status_code == 200
    data = res.get_json()
    assert data["count"] == 10
    assert "cells" in data

    res_stats = client.get("/api/gaps/stats")
    assert res_stats.status_code == 200
    stats = res_stats.get_json()
    assert stats["total_cells"] > 50000


def test_reviews_workflow(client):
    # 1. Post a review mark
    mark_payload = {
        "osm_type": "way",
        "osm_id": 99999999,
        "status": "fixed",
        "version": 2,
        "user_name": "TestUser",
        "notes": "Verified outline",
    }
    res_post = client.post("/api/reviews", json=mark_payload)
    assert res_post.status_code == 200

    # 2. Retrieve review marks
    res_get = client.get("/api/reviews")
    assert res_get.status_code == 200
    marks = res_get.get_json()
    assert "way/99999999" in marks
    assert marks["way/99999999"]["status"] == "fixed"

    # 3. Check review stats
    res_stats = client.get("/api/reviews/stats")
    assert res_stats.status_code == 200
    stats = res_stats.get_json()
    assert stats["total_reviews"] >= 1
    assert stats["fixed_count"] >= 1

    # 4. Sync reviews
    sync_payload = {
        "marks": {
            "node/88888888": {"status": "skipped", "version": 1}
        },
        "user_name": "SyncTester",
    }
    res_sync = client.post("/api/reviews/sync", json=sync_payload)
    assert res_sync.status_code == 200
    sync_data = res_sync.get_json()
    assert "node/88888888" in sync_data["marks"]

    # 5. Clear review
    res_del = client.delete("/api/reviews/way/99999999")
    assert res_del.status_code == 200

    # Verify cleared
    res_get2 = client.get("/api/reviews")
    assert "way/99999999" not in res_get2.get_json()


def test_notes_api(client):
    note_payload = {
        "osm_type": "way",
        "osm_id": 123456,
        "user_name": "AliMapper",
        "content": "This mosque has an ongoing expansion.",
    }
    res_add = client.post("/api/notes", json=note_payload)
    assert res_add.status_code == 201

    res_get = client.get("/api/notes/way/123456")
    assert res_get.status_code == 200
    notes = res_get.get_json()
    assert len(notes) >= 1
    assert notes[0]["content"] == "This mosque has an ongoing expansion."


def test_export_api(client):
    # CSV export
    res_csv = client.get("/api/export/csv?limit=5")
    assert res_csv.status_code == 200
    assert res_csv.headers["Content-Type"].startswith("text/csv")
    assert b"osm_id" in res_csv.data

    # GeoJSON export
    res_geojson = client.get("/api/export/geojson?limit=5")
    assert res_geojson.status_code == 200
    data = res_geojson.get_json()
    assert data["type"] == "FeatureCollection"
    assert len(data["features"]) == 5

    # MapRoulette export
    res_mr = client.get("/api/export/maproulette?limit=5")
    assert res_mr.status_code == 200
    assert b"instruction_ar" in res_mr.data


def test_pipeline_api(client):
    res_status = client.get("/api/pipeline/status")
    assert res_status.status_code == 200
    assert "datasets" in res_status.get_json()

    res_val = client.post("/api/pipeline/validate")
    assert res_val.status_code == 200
    assert res_val.get_json()["is_valid"] is True


def test_docs_and_static(client):
    res_docs = client.get("/api/docs")
    assert res_docs.status_code == 200
    assert b"REST API" in res_docs.data

    res_index = client.get("/")
    assert res_index.status_code == 200
    assert b"<!DOCTYPE html>" in res_index.data
