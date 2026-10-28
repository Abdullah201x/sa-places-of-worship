from fastapi import APIRouter, Depends, HTTPException, Query
from app.database import get_db

router = APIRouter(prefix="/api/v1", tags=["suggestions"])

MAX_BBOX_SPAN = 3.0  # Max degrees span in either direction


@router.get("/suggestions")
def get_suggestions(
    bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat bounding box"),
    limit: int = Query(100, ge=1, le=500, description="Max suggestions to return (1-500)"),
    conn=Depends(get_db)
):
    try:
        parts = [float(x.strip()) for x in bbox.split(",")]
        if len(parts) != 4:
            raise ValueError
        min_lon, min_lat, max_lon, max_lat = parts
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid bbox format. Expected 'minLon,minLat,maxLon,maxLat' (e.g. 46.5,24.5,46.9,24.9)"
        )

    if min_lon > max_lon or min_lat > max_lat:
        raise HTTPException(status_code=400, detail="Invalid bbox: min values must be less than max values.")

    # Guard against whole-country queries: limit bbox span
    if (max_lon - min_lon) > MAX_BBOX_SPAN or (max_lat - min_lat) > MAX_BBOX_SPAN:
        raise HTTPException(
            status_code=400,
            detail=f"Bbox too large. Maximum allowed span is {MAX_BBOX_SPAN} degrees. Please zoom in."
        )

    with conn.cursor() as cur:
        cur.execute("""
        SELECT 
            s.wikidata_id,
            s.name,
            s.name_en,
            s.region_code,
            ST_X(s.geom) AS lon,
            ST_Y(s.geom) AS lat
        FROM suggestions s
        WHERE s.geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326)
        LIMIT %s;
        """, (min_lon, min_lat, max_lon, max_lat, limit))
        rows = cur.fetchall()

    features = []
    for r in rows:
        features.append({
            "type": "Feature",
            "id": r["wikidata_id"],
            "properties": {
                "wikidata_id": r["wikidata_id"],
                "name": r["name"],
                "name_en": r["name_en"],
                "region_code": r["region_code"],
            },
            "geometry": {
                "type": "Point",
                "coordinates": [r["lon"], r["lat"]],
            }
        })

    return {
        "type": "FeatureCollection",
        "features": features,
    }
