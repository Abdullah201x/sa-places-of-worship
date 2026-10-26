"""
Coverage gaps endpoints.
"""

from flask import Blueprint, jsonify, request
from backend.services.data_service import get_data_service

bp = Blueprint("gaps", __name__)


@bp.route("/api/gaps", methods=["GET"])
def get_gaps():
    data_svc = get_data_service()

    bbox_str = request.args.get("bbox")
    bbox = None
    if bbox_str:
        try:
            parts = [float(p.strip()) for p in bbox_str.split(",")]
            if len(parts) == 4:
                bbox = (parts[0], parts[1], parts[2], parts[3])
        except ValueError:
            return jsonify({"error": "Invalid bbox format. Use minLon,minLat,maxLon,maxLat"}), 400

    min_score = float(request.args.get("min_score", 0.0))
    limit = min(int(request.args.get("limit", 2000)), 50000)

    cells = data_svc.query_gaps(bbox=bbox, min_score=min_score, limit=limit)
    return jsonify({
        "grid_size": data_svc.gaps_data.get("grid_size", 0.004),
        "count": len(cells),
        "limit": limit,
        "cells": cells,
    })


@bp.route("/api/gaps/stats", methods=["GET"])
def get_gaps_stats():
    data_svc = get_data_service()
    cells = data_svc.gaps_list
    total = len(cells)
    scores = [c["gap_score"] for c in cells]
    max_score = max(scores, default=0.0)
    min_score = min(scores, default=0.0)
    avg_score = round(sum(scores) / total, 2) if total else 0.0

    return jsonify({
        "grid_size": data_svc.gaps_data.get("grid_size", 0.004),
        "total_cells": total,
        "max_score": round(max_score, 2),
        "min_score": round(min_score, 2),
        "avg_score": avg_score,
    })
