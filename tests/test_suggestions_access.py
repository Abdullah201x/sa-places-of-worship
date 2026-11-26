"""The Wikidata suggestions (mosques missing from OSM) are private to MANARA_SUGGESTIONS_ALLOWLIST."""
import os
import sys
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from app.auth import can_view_suggestions, get_current_user, get_suggestions_allowlist
from app.database import get_db
from app.main import app

ME = {
    "osm_uid": 42,
    "display_name": "Owner",
    "avatar_url": None,
    "osm_changesets": 100,
    "osm_account_created": None,
    "leaderboard_opt_in": False,
    "is_admin": False,
}
BBOX = {"bbox": "46.5,24.5,46.9,24.9"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("MANARA_SUGGESTIONS_ALLOWLIST", raising=False)
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    cur.fetchall.return_value = [
        {"wikidata_id": "Q1", "name": "جامع", "name_en": "Mosque", "nearest_osm_m": 250,
         "is_unnamed": False, "region_code": "SA-01", "lon": 46.7, "lat": 24.7}
    ]

    def override_get_db():
        yield conn

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


def login(user=ME):
    app.dependency_overrides[get_current_user] = lambda: dict(user)


def test_allowlist_parsing_ignores_usernames_and_blanks(monkeypatch):
    monkeypatch.setenv("MANARA_SUGGESTIONS_ALLOWLIST", " 42, alice ,,7 ,-3")
    assert get_suggestions_allowlist() == frozenset({42, 7})


def test_empty_allowlist_means_nobody(monkeypatch):
    monkeypatch.delenv("MANARA_SUGGESTIONS_ALLOWLIST", raising=False)
    assert can_view_suggestions(ME) is False
    assert can_view_suggestions(None) is False


def test_admin_flag_does_not_grant_access(client):
    login({**ME, "is_admin": True})
    assert client.get("/api/v1/suggestions", params=BBOX).status_code == 403
    assert client.get("/api/v1/access/suggestions").status_code == 403


def test_anonymous_gets_401(client, monkeypatch):
    monkeypatch.setenv("MANARA_SUGGESTIONS_ALLOWLIST", "42")
    assert client.get("/api/v1/suggestions", params=BBOX).status_code == 401
    assert client.get("/api/v1/access/suggestions").status_code == 401


def test_other_user_gets_403(client, monkeypatch):
    monkeypatch.setenv("MANARA_SUGGESTIONS_ALLOWLIST", "99")
    login()
    assert client.get("/api/v1/suggestions", params=BBOX).status_code == 403
    assert client.get("/api/v1/access/suggestions").status_code == 403


def test_allowlisted_user_gets_suggestions(client, monkeypatch):
    monkeypatch.setenv("MANARA_SUGGESTIONS_ALLOWLIST", "42")
    login()
    res = client.get("/api/v1/suggestions", params=BBOX)
    assert res.status_code == 200
    assert res.headers["cache-control"] == "private, no-store"
    assert res.json()["features"][0]["properties"]["qid"] == "Q1"


def test_forward_auth_endpoint_is_204_and_not_rate_limited(client, monkeypatch):
    monkeypatch.setenv("MANARA_SUGGESTIONS_ALLOWLIST", "42")
    login()
    for _ in range(150):  # more than the 120/minute default
        res = client.get("/api/v1/access/suggestions")
        assert res.status_code == 204
    assert res.headers["cache-control"] == "no-store"


def test_me_reports_access(client, monkeypatch):
    login()
    assert client.get("/api/v1/me").json()["can_view_suggestions"] is False
    monkeypatch.setenv("MANARA_SUGGESTIONS_ALLOWLIST", "42")
    assert client.get("/api/v1/me").json()["can_view_suggestions"] is True
