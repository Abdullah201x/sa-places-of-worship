from fastapi import APIRouter, Depends, Query
from app.database import get_db

router = APIRouter(prefix="/api/v1", tags=["community_data"])


@router.get("/leaderboard")
def get_leaderboard(
    limit: int = Query(50, ge=1, le=100),
    conn=Depends(get_db),
):
    """
    Returns public rankings of mappers who opted in (leaderboard_opt_in = TRUE).
    Ranked by verified review fixes and verified changesets.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                u.osm_uid,
                u.display_name,
                u.avatar_url,
                u.osm_changesets,
                COUNT(DISTINCT e.changeset_id) AS verified_edits_count,
                COUNT(DISTINCT (rm.osm_type || '/' || rm.osm_id::text)) FILTER (
                    WHERE rm.status = 'fixed' AND rm.verified_changeset IS NOT NULL
                ) AS verified_fixes_count,
                MAX(COALESCE(e.verified_at, rm.created_at)) AS last_active_at
            FROM users u
            LEFT JOIN edits e ON e.osm_uid = u.osm_uid
            LEFT JOIN review_marks rm ON rm.osm_uid = u.osm_uid
            WHERE u.leaderboard_opt_in = TRUE
            GROUP BY u.osm_uid, u.display_name, u.avatar_url, u.osm_changesets
            ORDER BY verified_fixes_count DESC, verified_edits_count DESC, u.osm_uid ASC
            LIMIT %s;
        """, (limit,))
        rows = cur.fetchall()

    leaderboard = []
    for r in rows:
        d = dict(r)
        if d.get("last_active_at"):
            d["last_active_at"] = d["last_active_at"].isoformat()
        leaderboard.append(d)

    return {
        "count": len(leaderboard),
        "leaderboard": leaderboard,
    }


@router.get("/edits/recent")
def get_recent_edits(
    limit: int = Query(20, ge=1, le=50),
    conn=Depends(get_db),
):
    """
    Returns the feed of recent verified OpenStreetMap edits uploaded with #sa-worship-map.
    """
    with conn.cursor() as cur:
        cur.execute("""
            SELECT
                e.changeset_id,
                e.comment,
                e.verified_at,
                jsonb_array_length(e.objects) AS objects_count,
                u.osm_uid,
                u.display_name,
                u.avatar_url
            FROM edits e
            JOIN users u ON u.osm_uid = e.osm_uid
            ORDER BY e.verified_at DESC
            LIMIT %s;
        """, (limit,))
        rows = cur.fetchall()

    items = []
    for r in rows:
        d = dict(r)
        if d.get("verified_at"):
            d["verified_at"] = d["verified_at"].isoformat()
        items.append(d)

    return {
        "count": len(items),
        "edits": items,
    }
