"""
Places of worship REST API endpoints.
"""

from flask import Blueprint, jsonify, request
from backend.services.data_service import get_data_service

bp = Blueprint("places", __name__)


@bp.route("/api/places", methods=["GET"])
def list_places():
    data_svc = get_data_service()

    # Parse bbox
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
    religion = request.args.get("religion")
    issue = request.args.get("issue")

    try:
        limit = min(int(request.args.get("limit", 100)), 5000)
        offset = max(int(request.args.get("offset", 0)), 0)
    except ValueError:
        return jsonify({"error": "limit and offset must be integers"}), 400

    min_size = float(request.args.get("min_size", 20.0))
    max_size = float(request.args.get("max_size", 15000.0))
    qibla_dev = float(request.args.get("qibla_dev", 20.0))

    result = data_svc.query_places(
        bbox=bbox,
        q=q,
        religion=religion,
        issue=issue,
        limit=limit,
        offset=offset,
        min_size_m2=min_size,
        max_size_m2=max_size,
        qibla_threshold=qibla_dev,
    )
    return jsonify(result)


@bp.route("/api/places/<string:osm_type>/<int:osm_id>", methods=["GET"])
def get_place_detail(osm_type: str, osm_id: int):
    data_svc = get_data_service()
    place = data_svc.get_place(osm_type, osm_id)
    if not place:
        return jsonify({"error": "Place not found"}), 404
    return jsonify(place)


@bp.route("/api/places/nearby", methods=["GET"])
def nearby_places():
    data_svc = get_data_service()
    lat_str = request.args.get("lat")
    lon_str = request.args.get("lon")

    if not lat_str or not lon_str:
        return jsonify({"error": "lat and lon query parameters are required"}), 400

    try:
        lat = float(lat_str)
        lon = float(lon_str)
        radius_km = float(request.args.get("radius_km", 5.0))
        limit = min(int(request.args.get("limit", 50)), 500)
    except ValueError:
        return jsonify({"error": "Invalid numerical parameters"}), 400

    results = data_svc.query_nearby(lat=lat, lon=lon, radius_km=radius_km, limit=limit)
    return jsonify({
        "lat": lat,
        "lon": lon,
        "radius_km": radius_km,
        "count": len(results),
        "places": results,
    })


@bp.route("/api/boundary", methods=["GET"])
def get_boundary():
    data_svc = get_data_service()
    if not data_svc.boundary_data:
        return jsonify({"error": "Boundary data not available"}), 404
    return jsonify(data_svc.boundary_data)
