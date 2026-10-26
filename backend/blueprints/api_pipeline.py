"""
Pipeline status and data validation endpoints.
"""

from flask import Blueprint, jsonify
from backend.services.pipeline_service import PipelineService

bp = Blueprint("pipeline", __name__)


@bp.route("/api/pipeline/status", methods=["GET"])
def pipeline_status():
    status = PipelineService.get_status()
    return jsonify(status)


@bp.route("/api/pipeline/validate", methods=["POST"])
def validate_datasets():
    res = PipelineService.run_validation()
    status_code = 200 if res["is_valid"] else 400
    return jsonify(res), status_code
