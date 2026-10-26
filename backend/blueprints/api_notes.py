"""
Community notes and place comments endpoints.
"""

from flask import Blueprint, jsonify, request
from backend.services.note_service import NoteService

bp = Blueprint("notes", __name__)


@bp.route("/api/notes/<string:osm_type>/<int:osm_id>", methods=["GET"])
def get_place_notes(osm_type: str, osm_id: int):
    notes = NoteService.get_notes(osm_type, osm_id)
    return jsonify(notes)


@bp.route("/api/notes", methods=["POST"])
def add_note():
    data = request.get_json(silent=True) or {}
    osm_type = data.get("osm_type")
    osm_id = data.get("osm_id")
    content = data.get("content")

    if not osm_type or not osm_id or not content or not content.strip():
        return jsonify({"error": "osm_type, osm_id, and non-empty content are required"}), 400

    user_name = data.get("user_name", "مساهم")
    tags = data.get("tags")

    res = NoteService.add_note(
        osm_type=osm_type,
        osm_id=osm_id,
        user_name=user_name,
        content=content,
        tags=tags,
    )
    return jsonify(res), 201


@bp.route("/api/notes/recent", methods=["GET"])
def get_recent():
    limit = min(int(request.args.get("limit", 20)), 100)
    notes = NoteService.get_recent_notes(limit=limit)
    return jsonify(notes)
