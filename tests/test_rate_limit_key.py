"""The rate limiter must key on the proxy-set X-Real-IP.

Forged X-Forwarded-For can't be unit-tested here: TestClient skips uvicorn's proxy-header
middleware. It was verified by hand against a real uvicorn process.
"""

import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from app.main import app
from app.limiter import limiter

URL = "/api/v1/transliterate?name=test"  # 60/minute, no database needed


@pytest.fixture
def client():
    limiter.reset()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    limiter.reset()


def _statuses(client, n, headers_for):
    return [client.get(URL, headers=headers_for(i)).status_code for i in range(n)]


def test_same_visitor_is_limited(client):
    codes = _statuses(client, 65, lambda i: {"X-Real-IP": "198.51.100.7"})
    assert codes.count(200) == 60
    assert codes.count(429) == 5


def test_different_visitors_have_separate_buckets(client):
    _statuses(client, 65, lambda i: {"X-Real-IP": "198.51.100.7"})  # exhaust one visitor
    assert client.get(URL, headers={"X-Real-IP": "198.51.100.8"}).status_code == 200


def test_falls_back_to_socket_address_without_header(client):
    codes = _statuses(client, 65, lambda i: {})
    assert 429 in codes
