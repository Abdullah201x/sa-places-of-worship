import os
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel, Field

from app.auth import get_current_user, get_optional_user, require_admin, verify_csrf
from app.database import get_db

router = APIRouter(prefix="/api/v1", tags=["reviews"])

MIN_CHANGESETS_DEFAULT = 10


def get_min_changesets() -> int:
    try:
        return int(os.environ.get("MANARA_MIN_CHANGESETS", MIN_CHANGESETS_DEFAULT))
    except ValueError:
        return MIN_CHANGESETS_DEFAULT


class ReviewMarkRequest(BaseModel):
    status: Literal["fixed", "skipped"]
    version: int = Field(..., ge=1, description="OSM element version being reviewed")


@router.get("/reviews")
def get_reviews(
    user: dict | None = Depends(get_optional_user),
    conn=Depends(get_db),
):
    """
    Returns review marks according to the guarded sharing rules:
    - 'skipped' is personal: only returned for the authenticated mapper.
    - 'fixed' is shared if the reviewer has >= MANARA_MIN_CHANGESETS and
      either has a verified changeset or the active dataset has not yet renewed.
    - Marks for the current caller are always included.
    """
    min_changesets = get_min_changesets()
    caller_uid = user["osm_uid"] if user else None

    query = """
    WITH latest_dataset AS (
        SELECT published_at
        FROM dataset_versions
        ORDER BY published_at DESC
        LIMIT 1
    )
    SELECT
        rm.osm_type,
        rm.osm_id,
        rm.osm_uid,
        rm.status,
        rm.version,
        rm.verified_changeset,
        rm.created_at,
        u.display_name,
        u.osm_changesets
    FROM review_marks rm
    JOIN users u ON u.osm_uid = rm.osm_uid
    LEFT JOIN latest_dataset ld ON true
    WHERE
        -- 1. Caller's own marks (always visible to owner)
        (%s::bigint IS NOT NULL AND rm.osm_uid = %s::bigint)
        OR
        -- 2. Guarded shared 'fixed' marks from other reputable mappers
        (
            rm.status = 'fixed'
            AND u.osm_changesets >= %s
            AND (
                rm.verified_changeset IS NOT NULL
                OR ld.published_at IS NULL
                OR rm.created_at >= ld.published_at
            )
        );
    """

    marks_dict = {}
    with conn.cursor() as cur:
        cur.execute(query, (caller_uid, caller_uid, min_changesets))
        rows = cur.fetchall()

        for r in rows:
            key = f"{r['osm_type']}/{r['osm_id']}"
            is_personal = (caller_uid is not None and r["osm_uid"] == caller_uid)

            # If caller has their own mark, it takes precedence in the response map
            if key in marks_dict and not is_personal:
                continue

            marks_dict[key] = {
                "status": r["status"],
                "version": r["version"],
                "verified": r["verified_changeset"] is not None,
                "personal": is_personal,
                "created_at": r["created_at"].isoformat() if r.get("created_at") else None,
            }

    return {
        "count": len(marks_dict),
        "marks": marks_dict,
    }


@router.put("/reviews/{osm_type}/{osm_id}")
def set_review_mark(
    payload: ReviewMarkRequest,
    osm_type: str = Path(..., pattern="^(node|way|relation)$"),
    osm_id: int = Path(..., gt=0),
    _csrf: None = Depends(verify_csrf),
    user: dict = Depends(get_current_user),
    conn=Depends(get_db),
):
    """Set or update a review mark (fixed or skipped) for a place."""
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO review_marks (osm_type, osm_id, osm_uid, status, version, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (osm_type, osm_id, osm_uid) DO UPDATE SET
                status = EXCLUDED.status,
                version = EXCLUDED.version,
                created_at = NOW()
            RETURNING osm_type, osm_id, osm_uid, status, version, verified_changeset, created_at;
        """, (osm_type, osm_id, user["osm_uid"], payload.status, payload.version))
        mark = dict(cur.fetchone())

        cur.execute("""
            INSERT INTO review_events (osm_type, osm_id, osm_uid, status, version, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW());
        """, (osm_type, osm_id, user["osm_uid"], payload.status, payload.version))

    return {
        "status": "ok",
        "mark": {
            "key": f"{mark['osm_type']}/{mark['osm_id']}",
            "status": mark["status"],
            "version": mark["version"],
            "verified": mark["verified_changeset"] is not None,
            "created_at": mark["created_at"].isoformat() if mark.get("created_at") else None,
        },
    }


@router.delete("/reviews/{osm_type}/{osm_id}")
def delete_review_mark(
    osm_type: str = Path(..., pattern="^(node|way|relation)$"),
    osm_id: int = Path(..., gt=0),
    _csrf: None = Depends(verify_csrf),
    user: dict = Depends(get_current_user),
    conn=Depends(get_db),
):
    """Remove caller's review mark for a place."""
    with conn.cursor() as cur:
        cur.execute("""
            DELETE FROM review_marks
            WHERE osm_type = %s AND osm_id = %s AND osm_uid = %s
            RETURNING version;
        """, (osm_type, osm_id, user["osm_uid"]))
        deleted_row = cur.fetchone()

        version = deleted_row["version"] if deleted_row else 1
        cur.execute("""
            INSERT INTO review_events (osm_type, osm_id, osm_uid, status, version, created_at)
            VALUES (%s, %s, %s, 'unmarked', %s, NOW());
        """, (osm_type, osm_id, user["osm_uid"], version))

    return {"status": "ok", "deleted": True}


@router.delete("/admin/users/{osm_uid}/marks")
def admin_revoke_user_marks(
    osm_uid: int = Path(..., gt=0),
    _csrf: None = Depends(verify_csrf),
    _admin: dict = Depends(require_admin),
    conn=Depends(get_db),
):
    """Admin endpoint to revoke all review marks created by a specific user."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM review_marks WHERE osm_uid = %s;", (osm_uid,))
        deleted_count = cur.rowcount

    return {
        "status": "ok",
        "revoked_marks_count": deleted_count,
    }

