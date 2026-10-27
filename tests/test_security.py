"""
Security regression tests for Saudi Places of Worship Map.
"""

from serve_ssl import HardenedHandler


def test_hardened_handler_blocks_sensitive_files():
    h = HardenedHandler.__new__(HardenedHandler)

    blocked_paths = [
        "/key.pem",
        "/key.pem.",
        "/cert.pem",
        "/cert.pem.",
        "/.git/config",
        "/.git/HEAD",
        "/.env",
        "/serve_ssl.py",
        "/serve_ssl.py.",
        "/server.py",
        "/server.py.",
        "/common.py",
        "/worship_map.db",
        "/worship_map.db.",
        "/worship_map.sqlite",
        "/test.ini",
        "/test.sh",
    ]

    for path in blocked_paths:
        h.path = path
        assert not h._is_safe_request(), f"Path should be blocked: {path}"


def test_hardened_handler_allows_public_assets():
    h = HardenedHandler.__new__(HardenedHandler)

    allowed_paths = [
        "/",
        "/index.html",
        "/index.css",
        "/app.js",
        "/places_of_worship_sa.geojson",
        "/worship_gaps_sa.json",
        "/sa_boundary.geojson",
        "/mosque_sizes.json",
        "/mosque_anomalies.json",
        "/suggested_mosques_sa.geojson",
        "/summary.json",
        "/js/i18n.js",
        "/js/translations.js",
        "/js/arabic.js",
        "/js/exporters.js",
        "/js/review.js",
        "/js/osm_api.js",
        "/js/editing.js",
    ]

    for path in allowed_paths:
        h.path = path
        assert h._is_safe_request(), f"Public path should be allowed: {path}"
