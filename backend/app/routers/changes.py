from datetime import datetime, timezone
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from app.auth import get_current_user, get_optional_user, verify_csrf
from app.database import get_db

router = APIRouter(prefix="/api/v1", tags=["changes"])


class TriageRequest(BaseModel):
    status: Literal["reviewed", "flagged", "reverted"] = Field(
        ..., description="Triage decision: reviewed, flagged, or reverted"
    )
    note: str = Field("", max_length=500, description="Optional triage note")


@router.get("/changes")
def get_changes(
    response: Response,
    since_id: int | None = Query(None, description="Fetch events with id > since_id for polling"),
    source: Literal["all", "daily", "live"] = Query("all", description="Event source filter"),
    region_code: str | None = Query(None, description="Filter by Saudi region code, e.g. SA-01"),
    flag: str | None = Query(None, description="Filter by flag, e.g. deleted-named-mosque"),
    kind: Literal["created", "modified", "deleted", "upgraded"] | None = Query(None, description="Event kind"),
    unreviewed_only: bool = Query(False, description="Filter to events not yet triaged"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    conn=Depends(get_db),
):
    """
    Paginated feed of change events affecting places of worship in Saudi Arabia.
    Supports auto-refresh via since_id and multi-criteria filtering.
    """
    conditions = ["1=1"]
    params: list = []

    if since_id is not None:
        conditions.append("c.id > %s")
        params.append(since_id)

    if source != "all":
        conditions.append("c.source = %s")
        params.append(source)

    if region_code:
        conditions.append("c.region_code = %s")
        params.append(region_code)

    if kind:
        conditions.append("c.kind = %s")
        params.append(kind)

    if flag:
        conditions.append("c.flags ? %s")
        params.append(flag)

    if unreviewed_only:
        conditions.append("ct.status IS NULL")

    where_clause = " AND ".join(conditions)

    query = f"""
    SELECT
        c.id,
        c.source,
        c.confirmed,
        c.reverted_same_day,
        c.osm_timestamp,
        c.observed_at,
        c.changeset_id,
        c.replication_seq,
        c.dataset_version,
        c.osm_type,
        c.osm_id,
        c.prev_ref,
        c.kind,
        c.flags,
        ST_X(c.geom) AS lon,
        ST_Y(c.geom) AS lat,
        c.region_code,
        c.name,
        c.tag_diff,
        c.version_before,
        c.version_after,
        ct.status AS triage_status,
        ct.osm_uid AS triage_uid,
        ct.note AS triage_note,
        ct.triaged_at
    FROM change_events c
    LEFT JOIN change_triage ct ON ct.change_id = c.id
    WHERE {where_clause}
    ORDER BY c.id DESC
    LIMIT %s OFFSET %s;
    """
    params.extend([limit, offset])

    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
    except Exception:
        # Table may not have been created yet or empty
        rows = []

    events = []
    latest_id = 0
    for r in rows:
        d = dict(r)
        if d["id"] > latest_id:
            latest_id = d["id"]
        d["coordinates"] = [d.pop("lon"), d.pop("lat")]
        # Format timestamps
        for ts_key in ("osm_timestamp", "observed_at", "triaged_at"):
            if d.get(ts_key) and isinstance(d[ts_key], datetime):
                d[ts_key] = d[ts_key].isoformat()
        events.append(d)

    response.headers["ETag"] = f'"changes-{latest_id}-{len(events)}"'

    return {
        "count": len(events),
        "limit": limit,
        "offset": offset,
        "latest_id": latest_id,
        "changes": events,
    }


@router.post("/changes/{change_id}/triage")
def triage_change(
    change_id: int,
    body: TriageRequest,
    _csrf: None = Depends(verify_csrf),
    user=Depends(get_current_user),
    conn=Depends(get_db),
):
    """
    Record a triage decision for a change event (reviewed, flagged, or reverted).
    Requires authenticated OSM user.
    """
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM change_events WHERE id = %s;", (change_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Change event not found.")

            cur.execute("""
            INSERT INTO change_triage (change_id, status, osm_uid, note, triaged_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (change_id) DO UPDATE SET
                status = EXCLUDED.status,
                osm_uid = EXCLUDED.osm_uid,
                note = EXCLUDED.note,
                triaged_at = NOW()
            RETURNING change_id, status, osm_uid, note, triaged_at;
            """, (change_id, body.status, user["osm_uid"], body.note))
            row = cur.fetchone()

    triaged_data = dict(row)
    if isinstance(triaged_data.get("triaged_at"), datetime):
        triaged_data["triaged_at"] = triaged_data["triaged_at"].isoformat()

    return {
        "status": "ok",
        "triage": triaged_data,
    }


@router.get("/freshness")
def get_freshness(conn=Depends(get_db)):
    """
    Returns data age and replication age for topbar freshness labels.
    """
    now = datetime.now(timezone.utc)
    res: dict[str, Any] = {
        "data": None,
        "live": None,
    }

    with conn.cursor() as cur:
        # 1. Dataset version age
        try:
            cur.execute("""
            SELECT version, pbf_date, pbf_timestamp, published_at
            FROM dataset_versions
            ORDER BY published_at DESC
            LIMIT 1;
            """)
            d_row = cur.fetchone()
            if d_row and d_row.get("published_at"):
                pub_at = d_row["published_at"]
                if pub_at.tzinfo is None:
                    pub_at = pub_at.replace(tzinfo=timezone.utc)
                age_sec = (now - pub_at).total_seconds()
                pbf_ts = d_row.get("pbf_timestamp")
                res["data"] = {
                    "version": d_row["version"],
                    "pbf_date": str(d_row["pbf_date"]),
                    "pbf_timestamp": pbf_ts.isoformat() if pbf_ts else None,
                    "published_at": pub_at.isoformat(),
                    "age_seconds": max(0, int(age_sec)),
                    "status": "ok" if age_sec <= 36 * 3600 else ("warn" if age_sec <= 72 * 3600 else "stale"),
                }
        except Exception:
            pass

        # 2. Live replication state
        try:
            cur.execute("""
            SELECT sequence, osm_timestamp, processed_at
            FROM replication_state
            WHERE id = 1;
            """)
            r_row = cur.fetchone()
            if r_row and r_row.get("osm_timestamp"):
                osm_ts = r_row["osm_timestamp"]
                if osm_ts.tzinfo is None:
                    osm_ts = osm_ts.replace(tzinfo=timezone.utc)
                live_age_sec = (now - osm_ts).total_seconds()
                res["live"] = {
                    "sequence": r_row["sequence"],
                    "osm_timestamp": osm_ts.isoformat(),
                    "age_seconds": max(0, int(live_age_sec)),
                    "status": "ok" if live_age_sec <= 900 else ("warn" if live_age_sec <= 7200 else "stale"),
                }
        except Exception:
            pass

    return res
