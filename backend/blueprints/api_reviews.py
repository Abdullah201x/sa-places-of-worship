"""
Review workflow and synchronization endpoints.
"""

from flask import Blueprint, jsonify, request
from backend.services.review_service import ReviewService

bp = Blueprint("reviews", __name__)


@bp.route("/api/reviews", methods=["GET"])
def list_reviews():
    status = request.args.get("status")
    reviews = ReviewService.get_all_reviews(status=status)
    return jsonify(reviews)


@bp.route("/api/reviews", methods=["POST"])
def set_review():
    data = request.get_json(silent=True) or {}
    osm_type = data.get("osm_type")
    osm_id = data.get("osm_id")
    status = data.get("status")

    if not osm_type or not osm_id or not status:
        return jsonify({"error": "osm_type, osm_id, and status are required"}), 400

    if status not in ("fixed", "skipped", "needs_work"):
        return jsonify({"error": "Invalid status value"}), 400

    version = data.get("version")
    user_name = data.get("user_name")
    notes = data.get("notes")

    res = ReviewService.set_review(
        osm_type=osm_type,
        osm_id=osm_id,
        status=status,
        version=version,
        user_name=user_name,
        notes=notes,
    )
    return jsonify(res), 200


@bp.route("/api/reviews/<string:osm_type>/<int:osm_id>", methods=["DELETE"])
def clear_review(osm_type: str, osm_id: int):
    user_name = request.args.get("user_name")
    deleted = ReviewService.clear_review(osm_type, osm_id, user_name=user_name)
    if not deleted:
        return jsonify({"error": "Review mark not found"}), 404
    return jsonify({"success": True, "message": "Review cleared"})


@bp.route("/api/reviews/sync", methods=["POST"])
def sync_reviews():
    """Two-way sync: receives client marks and returns updated server marks + stats."""
    data = request.get_json(silent=True) or {}
    client_marks = data.get("marks", {})
    user_name = data.get("user_name")

    res = ReviewService.sync_reviews(client_marks=client_marks, user_name=user_name)
    return jsonify(res)


@bp.route("/api/reviews/stats", methods=["GET"])
def review_stats():
    return jsonify(ReviewService.get_stats())
