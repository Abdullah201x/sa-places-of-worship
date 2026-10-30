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


@router.api_route("/api/healthz/live", methods=["GET", "HEAD"])
def live_healthz(conn=Depends(get_db)):
    """503 when the minutely replication lag exceeds 2 hours."""
    try:
        with conn.cursor() as cur:
            cur.execute("""
            SELECT sequence, osm_timestamp
            FROM replication_state
            WHERE id = 1;
            """)
            row = cur.fetchone()
    except Exception:
        row = None

    if not row or not row.get("osm_timestamp"):
        return JSONResponse(
            status_code=503,
            content={"status": "stale", "detail": "Replication state not initialized."}
        )

    osm_ts = row["osm_timestamp"]
    if osm_ts.tzinfo is None:
        osm_ts = osm_ts.replace(tzinfo=timezone.utc)
    lag_seconds = (datetime.now(timezone.utc) - osm_ts).total_seconds()
    is_live = lag_seconds <= 7200  # 2 hours max lag

    return JSONResponse(
        status_code=200 if is_live else 503,
        content={
            "status": "ok" if is_live else "stale",
            "sequence": row["sequence"],
            "osm_timestamp": osm_ts.isoformat(),
            "lag_seconds": max(0, int(lag_seconds)),
        },
    )
