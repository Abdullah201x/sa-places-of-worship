"""
Satellite AI mosque candidates and their human reviews.

The detections come from a YOLO model scanning coverage-gap cells (scripts/ai_background_sweeper.py)
and are unreviewed machine guesses over commercial imagery, so they get the same audience as the
Wikidata suggestions: OSM users on MANARA_SUGGESTIONS_ALLOWLIST. Reviews ("positive" = a mosque,
"negative" = not a mosque, "unsure") are pulled back by scripts/publish_ai_detections.py and become
training labels for the next model.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Response
from pydantic import BaseModel

from app.auth import require_suggestions_access, verify_csrf
from app.database import get_db

router = APIRouter(prefix="/api/v1/ai", tags=["ai-detections"])

DETECTION_ID = Path(..., pattern=r"^ai_det_\d{1,8}$", max_length=20)


class ReviewRequest(BaseModel):
    verdict: Literal["positive", "negative", "unsure"]


@router.get("/detections")
def list_detections(
    response: Response,
    user: dict = Depends(require_suggestions_access),
    conn=Depends(get_db),
):
    """All active AI detections with review tallies and the caller's own verdict."""
    response.headers["Cache-Control"] = "private, no-store"
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT d.detection_id, d.confidence, d.dual_provider, d.region_code, d.region_name,
                   d.qibla_bearing, d.est_area_m2, d.model,
                   ST_X(d.geom) AS lon, ST_Y(d.geom) AS lat,
                   ST_AsGeoJSON(d.footprint, 7) AS footprint,
                   COUNT(r.*) FILTER (WHERE r.verdict = 'positive') AS n_positive,
                   COUNT(r.*) FILTER (WHERE r.verdict = 'negative') AS n_negative,
                   COUNT(r.*) FILTER (WHERE r.verdict = 'unsure') AS n_unsure,
                   MAX(r.verdict) FILTER (WHERE r.osm_uid = %s) AS my_verdict
            FROM ai_detections d
            LEFT JOIN ai_detection_reviews r ON r.detection_id = d.detection_id
            WHERE d.retired_at IS NULL
            GROUP BY d.detection_id
            ORDER BY d.confidence DESC
            """,
            (user["osm_uid"],),
        )
        rows = cur.fetchall()

    features = []
    for r in rows:
        features.append({
            "type": "Feature",
            "id": r["detection_id"],
            "properties": {
                "id": r["detection_id"],
                "confidence": round(float(r["confidence"]), 3),
                "dual": bool(r["dual_provider"]),
                "region_code": r["region_code"],
                "region_name": r["region_name"],
                "qibla": r["qibla_bearing"],
                "area_m2": r["est_area_m2"],
                "model": r["model"],
                "footprint": r["footprint"],
                "n_positive": r["n_positive"],
                "n_negative": r["n_negative"],
                "n_unsure": r["n_unsure"],
                "my_verdict": r["my_verdict"],
            },
            "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
        })
    return {"type": "FeatureCollection", "features": features}


@router.put("/detections/{detection_id}/review", dependencies=[Depends(verify_csrf)])
def review_detection(
    body: ReviewRequest,
    detection_id: str = DETECTION_ID,
    user: dict = Depends(require_suggestions_access),
    conn=Depends(get_db),
):
    """Record (or change) the caller's verdict on one detection."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM ai_detections WHERE detection_id = %s AND retired_at IS NULL",
            (detection_id,),
        )
        if cur.fetchone() is None:
            raise HTTPException(status_code=404, detail="Unknown or retired detection.")
        cur.execute(
            """
            INSERT INTO ai_detection_reviews (detection_id, osm_uid, verdict)
            VALUES (%s, %s, %s)
            ON CONFLICT (detection_id, osm_uid)
            DO UPDATE SET verdict = EXCLUDED.verdict, updated_at = NOW()
            """,
            (detection_id, user["osm_uid"], body.verdict),
        )
        cur.execute(
            """
            SELECT COUNT(*) FILTER (WHERE verdict = 'positive') AS n_positive,
                   COUNT(*) FILTER (WHERE verdict = 'negative') AS n_negative,
                   COUNT(*) FILTER (WHERE verdict = 'unsure') AS n_unsure
            FROM ai_detection_reviews WHERE detection_id = %s
            """,
            (detection_id,),
        )
        tally = cur.fetchone()
    return {"id": detection_id, "my_verdict": body.verdict, **{k: tally[k] for k in tally}}
