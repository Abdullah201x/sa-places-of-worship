from fastapi import APIRouter, Depends, HTTPException, Query
from app.database import get_db
from app.arabic import normalize_arabic

router = APIRouter(prefix="/api/v1", tags=["search"])


@router.get("/search")
def search_places(
    q: str = Query(..., min_length=2, max_length=100, description="Search query in Arabic or English"),
    limit: int = Query(20, ge=1, le=50, description="Max results to return (1-50)"),
    conn=Depends(get_db)
):
    clean_q = q.strip()
    norm_q = normalize_arabic(clean_q)

    # Escape LIKE metacharacters to prevent wildcard injection
    escaped_norm = norm_q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    escaped_clean = clean_q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    with conn.cursor() as cur:
        # Search places using trigram index for both normalized Arabic and English
        cur.execute("""
        SELECT 
            p.osm_type,
            p.osm_id,
            p.name,
            p.name_en,
            p.religion,
            p.denomination,
            p.building,
            p.amenity,
            p.region_code,
            r.name AS region_name,
            ST_X(p.geom) AS lon,
            ST_Y(p.geom) AS lat,
            GREATEST(similarity(p.name_norm, %s), similarity(LOWER(COALESCE(p.name_en, '')), LOWER(%s))) AS sim
        FROM places p
        LEFT JOIN regions r ON r.code = p.region_code
        WHERE 
            (p.name_norm %% %s OR LOWER(COALESCE(p.name_en, '')) %% LOWER(%s) OR p.name_norm ILIKE %s ESCAPE '\\' OR p.name_en ILIKE %s ESCAPE '\\')
        ORDER BY sim DESC, p.osm_id ASC
        LIMIT %s;
        """, (norm_q, clean_q, norm_q, clean_q, f"%{escaped_norm}%", f"%{escaped_clean}%", limit))
        rows = cur.fetchall()

    results = []
    for r in rows:
        results.append({
            "osm_type": r["osm_type"],
            "osm_id": r["osm_id"],
            "name": r["name"],
            "name_en": r["name_en"],
            "religion": r["religion"],
            "denomination": r["denomination"],
            "region_code": r["region_code"],
            "region_name": r["region_name"],
            "coordinates": [r["lon"], r["lat"]],
            "score": round(float(r["sim"]), 3) if r["sim"] is not None else 0.0,
        })

    return {
        "query": clean_q,
        "count": len(results),
        "results": results,
    }
