"""
Health check endpoint.
"""

import time
from flask import Blueprint, jsonify
from backend.services.data_service import get_data_service
from backend.database import get_db_connection

bp = Blueprint("health", __name__)
START_TIME = time.time()


@bp.route("/api/health", methods=["GET"])
def health_check():
    data_svc = get_data_service()
    db_ok = False
    try:
        conn = get_db_connection()
        conn.execute("SELECT 1")
        conn.close()
        db_ok = True
    except Exception:
        db_ok = False

    return jsonify({
        "status": "healthy" if data_svc.is_loaded and db_ok else "degraded",
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "database_connected": db_ok,
        "datasets": {
            "places_count": len(data_svc.places),
            "gaps_count": len(data_svc.gaps_list),
            "suggestions_count": len(data_svc.suggestions),
        },
        "server_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
