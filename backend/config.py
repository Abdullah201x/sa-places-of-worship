"""
Backend configuration settings for Saudi Places of Worship Map.
"""

import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class Config:
    BASE_DIR = BASE_DIR
    DATA_DIR = BASE_DIR
    DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE_DIR, "worship_map.db"))
    
    # Dataset files
    PLACES_GEOJSON = os.path.join(BASE_DIR, "places_of_worship_sa.geojson")
    GAPS_JSON = os.path.join(BASE_DIR, "worship_gaps_sa.json")
    MOSQUE_SIZES_JSON = os.path.join(BASE_DIR, "mosque_sizes.json")
    MOSQUE_ANOMALIES_JSON = os.path.join(BASE_DIR, "mosque_anomalies.json")
    SUGGESTED_MOSQUES_GEOJSON = os.path.join(BASE_DIR, "suggested_mosques_sa.geojson")
    SA_BOUNDARY_GEOJSON = os.path.join(BASE_DIR, "sa_boundary.geojson")
    SUMMARY_JSON = os.path.join(BASE_DIR, "summary.json")
    
    # SSL certificates for OpenStreetMap OAuth2
    CERT_PATH = os.path.join(BASE_DIR, "cert.pem")
    KEY_PATH = os.path.join(BASE_DIR, "key.pem")
    
    # Server configuration
    DEFAULT_PORT = 8000
    DEFAULT_HOST = "0.0.0.0"
    
    # App secret
    SECRET_KEY = os.environ.get("SECRET_KEY", "sa-places-of-worship-secret-key-2026")
    
    # JSON configuration
    JSON_SORT_KEYS = False
    JSON_AS_ASCII = False
