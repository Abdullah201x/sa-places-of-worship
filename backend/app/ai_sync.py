"""
Maintenance CLI for the satellite AI layer, run inside the manara-api container over SSH by
scripts/publish_ai_detections.py (no public write endpoint, no extra secret):

    python -m app.ai_sync import  < detections.json   # upsert, retire the ones not in the upload
    python -m app.ai_sync reviews                      # per-detection review tallies as JSON

The import is one transaction. Detections missing from the upload are retired (hidden), not
deleted, so their reviews are kept; a later upload that contains them again revives them.
"""

from __future__ import annotations

import json
import sys

import psycopg
from psycopg.rows import dict_row

from app.database import DATABASE_URL
from app.schema import init_app_tables


def _polygon_wkt(ring: list[list[float]] | None) -> str | None:
    if not ring or len(ring) < 3:
        return None
    pts = [(float(x), float(y)) for x, y in ring]
    if pts[0] != pts[-1]:
        pts.append(pts[0])
    return "POLYGON((" + ", ".join(f"{x} {y}" for x, y in pts) + "))"


def import_detections(conn, payload: dict) -> dict:
    dets = payload["detections"]
    ids = [d["id"] for d in dets]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate detection ids in upload")
    with conn.transaction(), conn.cursor() as cur:
        for d in dets:
            cur.execute(
                """
                INSERT INTO ai_detections (detection_id, geom, footprint, confidence, dual_provider,
                                           region_code, region_name, qibla_bearing, est_area_m2, model)
                VALUES (%(id)s, ST_SetSRID(ST_MakePoint(%(lon)s, %(lat)s), 4326),
                        ST_GeomFromText(%(fp)s, 4326), %(confidence)s, %(dual)s,
                        %(region_code)s, %(region_name)s, %(qibla)s, %(area_m2)s, %(model)s)
                ON CONFLICT (detection_id) DO UPDATE SET
                    geom = EXCLUDED.geom, footprint = EXCLUDED.footprint,
                    confidence = EXCLUDED.confidence, dual_provider = EXCLUDED.dual_provider,
                    region_code = EXCLUDED.region_code, region_name = EXCLUDED.region_name,
                    qibla_bearing = EXCLUDED.qibla_bearing, est_area_m2 = EXCLUDED.est_area_m2,
                    model = EXCLUDED.model, retired_at = NULL
                """,
                {**d, "fp": _polygon_wkt(d.get("footprint")),
                 **{k: d.get(k) for k in ("region_code", "region_name", "qibla", "area_m2", "model")}},
            )
        cur.execute(
            "UPDATE ai_detections SET retired_at = NOW() WHERE retired_at IS NULL AND NOT (detection_id = ANY(%s))",
            (ids,),
        )
        retired = cur.rowcount
        cur.execute("SELECT COUNT(*) AS n FROM ai_detections WHERE retired_at IS NULL")
        active = cur.fetchone()["n"]
    return {"upserted": len(dets), "retired": retired, "active": active}


def export_reviews(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.detection_id, ST_Y(d.geom) AS lat, ST_X(d.geom) AS lon, d.region_code,
                   d.confidence, d.model, ST_AsGeoJSON(d.footprint, 7) AS footprint,
                   COUNT(*) FILTER (WHERE r.verdict = 'positive') AS n_positive,
                   COUNT(*) FILTER (WHERE r.verdict = 'negative') AS n_negative,
                   COUNT(*) FILTER (WHERE r.verdict = 'unsure') AS n_unsure,
                   MAX(r.updated_at) AS last_review_at
            FROM ai_detections d
            JOIN ai_detection_reviews r ON r.detection_id = d.detection_id
            GROUP BY d.detection_id
            """
        )
        rows = cur.fetchall()
    return {
        r["detection_id"]: {
            "lat": r["lat"], "lon": r["lon"], "region_code": r["region_code"],
            "confidence": r["confidence"], "model": r["model"],
            "footprint": json.loads(r["footprint"])["coordinates"][0] if r["footprint"] else None,
            "n_positive": r["n_positive"], "n_negative": r["n_negative"], "n_unsure": r["n_unsure"],
            "last_review_at": r["last_review_at"].isoformat() if r["last_review_at"] else None,
        }
        for r in rows
    }


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in ("import", "reviews"):
        print(__doc__, file=sys.stderr)
        return 2
    if not DATABASE_URL:
        print("MANARA_DATABASE_URL is not set", file=sys.stderr)
        return 1
    with psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=True) as conn:
        init_app_tables(conn)
        if argv[0] == "import":
            result = import_detections(conn, json.load(sys.stdin))
        else:
            result = export_reviews(conn)
    json.dump(result, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
