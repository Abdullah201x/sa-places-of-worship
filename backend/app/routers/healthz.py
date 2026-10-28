import os
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.database import get_db

router = APIRouter(tags=["health"])

MAX_DATASET_AGE_HOURS = float(os.environ.get("MANARA_MAX_DATASET_AGE_HOURS", "72"))


@router.api_route("/api/healthz", methods=["GET", "HEAD"])
def healthz():
    return {"status": "ok"}


@router.api_route("/api/healthz/freshness", methods=["GET", "HEAD"])
def freshness(conn=Depends(get_db)):
    """503 when the published dataset is older than MANARA_MAX_DATASET_AGE_HOURS,
    so an external monitor also catches a silently failing pipeline."""
    with conn.cursor() as cur:
        cur.execute("""
        SELECT version, published_at
        FROM dataset_versions
        ORDER BY published_at DESC
        LIMIT 1;
        """)
        row = cur.fetchone()

    if not row or not row["published_at"]:
        return JSONResponse(status_code=503, content={"status": "stale", "detail": "No published dataset found."})

    published_at = row["published_at"]
    if published_at.tzinfo is None:
        published_at = published_at.replace(tzinfo=timezone.utc)
    age_hours = (datetime.now(timezone.utc) - published_at).total_seconds() / 3600
    fresh = age_hours <= MAX_DATASET_AGE_HOURS
    return JSONResponse(
        status_code=200 if fresh else 503,
        content={
            "status": "ok" if fresh else "stale",
            "version": row["version"],
            "published_at": published_at.isoformat(),
            "age_hours": round(age_hours, 1),
        },
    )
