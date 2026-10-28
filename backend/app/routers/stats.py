from fastapi import APIRouter, Depends, Query
from app.database import get_db

router = APIRouter(prefix="/api/v1/stats", tags=["stats"])


@router.get("")
def get_overall_stats(conn=Depends(get_db)):
    with conn.cursor() as cur:
        cur.execute("""
        SELECT
            (SELECT COUNT(*) FROM places) AS total_places,
            (SELECT COUNT(*) FROM places WHERE religion = 'muslim') AS muslim_places,
            (SELECT COUNT(*) FROM places WHERE anomaly_score IS NOT NULL) AS anomaly_places,
            (SELECT COUNT(*) FROM places WHERE qibla_dev >= 20.0) AS qibla_deviated_places,
            (SELECT COUNT(*) FROM gaps) AS total_gaps,
            (SELECT COUNT(*) FROM suggestions) AS total_suggestions,
            (SELECT COUNT(*) FROM regions) AS total_regions;
        """)
        row = cur.fetchone()
        return dict(row)


@router.get("/regions")
def get_region_stats(conn=Depends(get_db)):
    with conn.cursor() as cur:
        cur.execute("""
        SELECT 
            r.code,
            r.name,
            r.name_en,
            COUNT(DISTINCT p.id) AS places_count,
            COUNT(DISTINCT g.id) AS gaps_count,
            COUNT(DISTINCT s.id) AS suggestions_count,
            COUNT(DISTINCT p.id) FILTER (WHERE p.anomaly_score IS NOT NULL) AS anomalies_count,
            COUNT(DISTINCT p.id) FILTER (WHERE p.qibla_dev >= 20.0) AS qibla_deviated_count
        FROM regions r
        LEFT JOIN places p ON p.region_code = r.code
        LEFT JOIN gaps g ON g.region_code = r.code
        LEFT JOIN suggestions s ON s.region_code = r.code
        GROUP BY r.code, r.name, r.name_en
        ORDER BY r.code ASC;
        """)
        rows = cur.fetchall()

    return {
        "count": len(rows),
        "regions": [dict(r) for r in rows],
    }


@router.get("/history")
def get_stats_history(
    region: str | None = Query(None, description="Optional ISO code to filter by, e.g. 'SA-01'"),
    limit: int = Query(50, ge=1, le=200, description="Max history points"),
    conn=Depends(get_db)
):
    with conn.cursor() as cur:
        if region:
            cur.execute("""
            SELECT 
                h.version,
                h.region_code,
                r.name AS region_name,
                h.places_count,
                h.gaps_count,
                h.suggestions_count,
                h.anomalies_count,
                h.recorded_at
            FROM region_stats_history h
            LEFT JOIN regions r ON r.code = h.region_code
            WHERE h.region_code = %s
            ORDER BY h.recorded_at DESC
            LIMIT %s;
            """, (region, limit))
        else:
            cur.execute("""
            SELECT 
                h.version,
                h.region_code,
                r.name AS region_name,
                h.places_count,
                h.gaps_count,
                h.suggestions_count,
                h.anomalies_count,
                h.recorded_at
            FROM region_stats_history h
            LEFT JOIN regions r ON r.code = h.region_code
            ORDER BY h.recorded_at DESC
            LIMIT %s;
            """, (limit,))
        rows = cur.fetchall()

    items = []
    for r in rows:
        d = dict(r)
        if d.get("recorded_at"):
            d["recorded_at"] = d["recorded_at"].isoformat()
        items.append(d)

    return {
        "count": len(items),
        "history": items,
    }
