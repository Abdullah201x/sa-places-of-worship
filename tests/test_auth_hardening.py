"""Regression tests for the pre-publication security audit."""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from app.main import app
from app.database import get_db

CSRF_HEADERS = {"X-Manara-CSRF": "1", "Origin": "https://manara.saudiosm.org"}


@pytest.fixture
def client():
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__.return_value = MagicMock()

    def override_get_db():
        yield mock_conn

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


@patch("httpx.AsyncClient.get")
def test_dev_osm_login_rejected_in_production(mock_get, client, monkeypatch):
    """Tokens from the OSM dev server must never mint a production session.

    Its user ids overlap production ones and anyone can register there, so
    accepting them would let a dev account take over a production user (or admin).
    """
    monkeypatch.delenv("MANARA_DEV_MODE", raising=False)
    res = client.post(
        "/auth/session",
        headers=CSRF_HEADERS,
        json={"access_token": "dev_server_token_123456", "environment": "dev"},
    )
    assert res.status_code == 400
    mock_get.assert_not_called()  # rejected before any token leaves the server


@patch("httpx.AsyncClient.get")
def test_dev_osm_login_allowed_in_dev_mode(mock_get, client, monkeypatch):
    monkeypatch.setenv("MANARA_DEV_MODE", "1")
    mock_get.side_effect = RuntimeError("network down")  # we only care that it got past the gate
    res = client.post(
        "/auth/session",
        headers=CSRF_HEADERS,
        json={"access_token": "dev_server_token_123456", "environment": "dev"},
    )
    assert res.status_code == 502
    mock_get.assert_called_once()


@patch("httpx.AsyncClient.get")
def test_upstream_errors_do_not_leak_internals(mock_get, client, monkeypatch):
    monkeypatch.delenv("MANARA_DEV_MODE", raising=False)
    mock_get.side_effect = RuntimeError("secret-internal-host.local:5432 refused")
    res = client.post(
        "/auth/session",
        headers=CSRF_HEADERS,
        json={"access_token": "valid_token_1234567890"},
    )
    assert res.status_code == 502
    assert "secret-internal-host" not in res.text


def test_healthz_failure_does_not_leak_exception(client):
    failing_conn = MagicMock()
    cur = failing_conn.cursor.return_value.__enter__.return_value
    cur.execute.side_effect = RuntimeError("password authentication failed for user manara")

    def failing_db():
        yield failing_conn

    app.dependency_overrides[get_db] = failing_db
    res = client.get("/api/healthz")
    assert res.status_code == 503
    assert res.json() == {"status": "error", "db": "unavailable"}
