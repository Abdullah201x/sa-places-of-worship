from fastapi import APIRouter, Depends, HTTPException, Query, Response
from app.auth import require_suggestions_access
from app.database import get_db
from app.limiter import limiter

router = APIRouter(prefix="/api/v1", tags=["suggestions"])

MAX_BBOX_SPAN = 3.0  # Max degrees span in either direction


@router.get("/access/suggestions", status_code=204)
@limiter.exempt
def check_suggestions_access(response: Response, _user: dict = Depends(require_suggestions_access)):
    """
    Auth subrequest for Caddy's forward_auth (deploy/Caddyfile.container). Every request
    for the private Wikidata-suggestion files under /data/ is answered here first:
    204 lets the file through, 401/403 is returned to the visitor instead.
    Exempt from the default rate limit because one map view issues many tile requests.
    """
    response.headers["Cache-Control"] = "no-store"


@router.get("/suggestions")
def get_suggestions(
    response: Response,
    bbox: str = Query(..., description="minLon,minLat,maxLon,maxLat bounding box"),
    limit: int = Query(100, ge=1, le=500, description="Max suggestions to return (1-500)"),
    _user: dict = Depends(require_suggestions_access),
    conn=Depends(get_db)
):
    """Wikidata mosques missing from OSM. Only for OSM users on MANARA_SUGGESTIONS_ALLOWLIST."""
    response.headers["Cache-Control"] = "private, no-store"
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
            s.nearest_osm_m,
            s.is_unnamed,
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
                "qid": r["wikidata_id"],
                "wikidata_id": r["wikidata_id"],
                "name": r["name"],
                "name_ar": r["name"],
                "name_en": r["name_en"],
                "nearest_osm_m": r["nearest_osm_m"],
                "is_unnamed": bool(r["is_unnamed"]),
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
