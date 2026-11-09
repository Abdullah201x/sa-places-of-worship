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
            (SELECT COUNT(*) FROM places WHERE anomaly_score < 0) AS anomaly_places,
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
        WITH place_counts AS (
            SELECT region_code,
                   COUNT(*) AS places_count,
                   COUNT(*) FILTER (WHERE anomaly_score < 0) AS anomalies_count,
                   COUNT(*) FILTER (WHERE qibla_dev >= 20.0) AS qibla_deviated_count
            FROM places
            WHERE region_code IS NOT NULL
            GROUP BY region_code
        ),
        gap_counts AS (
            SELECT region_code, COUNT(*) AS gaps_count
            FROM gaps
            WHERE region_code IS NOT NULL
            GROUP BY region_code
        ),
        sug_counts AS (
            SELECT region_code, COUNT(*) AS suggestions_count
            FROM suggestions
            WHERE region_code IS NOT NULL
            GROUP BY region_code
        )
        SELECT 
            r.code,
            r.name,
            r.name_en,
            COALESCE(p.places_count, 0) AS places_count,
            COALESCE(g.gaps_count, 0) AS gaps_count,
            COALESCE(s.suggestions_count, 0) AS suggestions_count,
            COALESCE(p.anomalies_count, 0) AS anomalies_count,
            COALESCE(p.qibla_deviated_count, 0) AS qibla_deviated_count
        FROM regions r
        LEFT JOIN place_counts p ON p.region_code = r.code
        LEFT JOIN gap_counts g ON g.region_code = r.code
        LEFT JOIN sug_counts s ON s.region_code = r.code
        ORDER BY r.code ASC;
        """)
        rows = cur.fetchall()

    return {
        "count": len(rows),
        "regions": [dict(r) for r in rows],
    }


@router.get("/history")
def get_stats_history(
    region: str | None = Query(None, description="Optional ISO code to filter by, e.g. 'SA-01', or 'ALL' for Kingdom-wide"),
    limit: int = Query(50, ge=1, le=2000, description="Max history points"),
    conn=Depends(get_db)
):
    with conn.cursor() as cur:
        if region == "ALL":
            cur.execute("""
            SELECT 
                h.version,
                'ALL' AS region_code,
                'المملكة العربية السعودية' AS region_name,
                SUM(h.places_count)::int AS places_count,
                SUM(h.gaps_count)::int AS gaps_count,
                SUM(h.suggestions_count)::int AS suggestions_count,
                SUM(h.anomalies_count)::int AS anomalies_count,
                MAX(h.recorded_at) AS recorded_at
            FROM region_stats_history h
            GROUP BY h.version
            HAVING COUNT(DISTINCT h.region_code) = 13
            ORDER BY recorded_at DESC
            LIMIT %s;
            """, (limit,))
        elif region:
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
