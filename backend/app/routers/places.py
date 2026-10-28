import json
from fastapi import APIRouter, Depends, HTTPException, Path
from app.database import get_db

router = APIRouter(prefix="/api/v1", tags=["places"])


@router.get("/places/{type}/{id}")
def get_place(
    type: str = Path(..., pattern="^(node|way|relation)$", description="OSM object type"),
    id: int = Path(..., gt=0, description="OSM ID"),
    conn=Depends(get_db)
):
    with conn.cursor() as cur:
        cur.execute("""
        SELECT 
            p.osm_type,
            p.osm_id,
            p.version,
            p.edited_at,
            p.name,
            p.name_en,
            p.religion,
            p.denomination,
            p.building,
            p.amenity,
            p.poi_node_id,
            p.tags,
            p.geom_type,
            ST_X(p.geom) AS lon,
            ST_Y(p.geom) AS lat,
            p.area_m2,
            p.anomaly_score,
            p.qibla_dev,
            p.region_code,
            r.name AS region_name,
            r.name_en AS region_name_en
        FROM places p
        LEFT JOIN regions r ON r.code = p.region_code
        WHERE p.osm_type = %s AND p.osm_id = %s;
        """, (type, id))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Place {type}/{id} not found")

        props = dict(row)
        lon = props.pop("lon")
        lat = props.pop("lat")
        if props.get("edited_at"):
            props["edited_at"] = props["edited_at"].isoformat()

        return {
            "type": "Feature",
            "properties": props,
            "geometry": {
                "type": "Point",
                "coordinates": [lon, lat],
            }
        }
