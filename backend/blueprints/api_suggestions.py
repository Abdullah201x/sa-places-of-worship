"""
Wikidata mosque suggestions endpoints.
"""

from flask import Blueprint, jsonify, request
from backend.services.data_service import get_data_service

bp = Blueprint("suggestions", __name__)


@bp.route("/api/suggestions", methods=["GET"])
def get_suggestions():
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

    q = request.args.get("q")
    limit = min(int(request.args.get("limit", 100)), 5000)

    features = data_svc.query_suggestions(bbox=bbox, q=q, limit=limit)
    return jsonify({
        "total": len(data_svc.suggestions),
        "count": len(features),
        "features": features,
    })
