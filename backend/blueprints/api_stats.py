"""
Statistics and metrics endpoints.
"""

from flask import Blueprint, jsonify, request
from backend.services.stats_service import StatsService
from backend.services.data_service import get_data_service

bp = Blueprint("stats", __name__)


@bp.route("/api/stats", methods=["GET"])
def get_stats():
    refresh = request.args.get("refresh", "").lower() in ("1", "true")
    stats = StatsService.get_dashboard_stats(force_refresh=refresh)
    return jsonify(stats)


@bp.route("/api/summary", methods=["GET"])
def get_summary():
    data_svc = get_data_service()
    return jsonify(data_svc.summary_data)
