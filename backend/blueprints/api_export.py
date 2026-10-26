"""
Dynamic export endpoints for CSV, GeoJSON, and MapRoulette.
"""

from flask import Blueprint, Response, jsonify, request
from backend.services.data_service import get_data_service
from backend.services.export_service import ExportService

bp = Blueprint("export", __name__)


@bp.route("/api/export/<string:fmt>", methods=["GET"])
def export_places(fmt: str):
    data_svc = get_data_service()

    bbox_str = request.args.get("bbox")
    bbox = None
    if bbox_str:
        try:
            parts = [float(p.strip()) for p in bbox_str.split(",")]
            if len(parts) == 4:
                bbox = (parts[0], parts[1], parts[2], parts[3])
        except ValueError:
            return jsonify({"error": "Invalid bbox format"}), 400

    q = request.args.get("q")
    religion = request.args.get("religion")
    issue = request.args.get("issue")
    limit = int(request.args.get("limit", 0))  # 0 = all

    query_res = data_svc.query_places(
        bbox=bbox,
        q=q,
        religion=religion,
        issue=issue,
        limit=limit,
        offset=0,
    )
    features = query_res["features"]

    fmt = fmt.lower()
    if fmt == "csv":
        csv_data = ExportService.to_csv(features)
        return Response(
            csv_data,
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=places_of_worship_export.csv"},
        )
    elif fmt == "geojson":
        geojson_data = ExportService.to_geojson(features)
        return jsonify(geojson_data)
    elif fmt in ("maproulette", "ndjson"):
        mr_data = ExportService.to_maproulette(features)
        return Response(
            mr_data,
            mimetype="application/x-ndjson; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=maproulette_tasks.geojson"},
        )
    else:
        return jsonify({"error": f"Unsupported format '{fmt}'. Choose 'csv', 'geojson', or 'maproulette'"}), 400
