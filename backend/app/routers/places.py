import hashlib
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from app.database import get_db
from app.limiter import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["places"])

LIVE_LIMIT = 2000


def _parse_since(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


@router.get("/places/live")
@limiter.limit("120/minute")
def get_live_places(
    request: Request,
    since: str | None = Query(None, description="ISO pbf_timestamp of the client's static snapshot"),
    conn=Depends(get_db),
):
    """Delta of mosques changed after the client's static snapshot: new/changed ones as
    features, deleted ones (and snapshot POIs that lost their worship tags) as `removed`."""
    since_ts = _parse_since(since)
    with conn.cursor() as cur:
        if since_ts is None:
            cur.execute("SELECT pbf_timestamp FROM dataset_versions WHERE pbf_timestamp IS NOT NULL "
                        "ORDER BY pbf_timestamp DESC LIMIT 1;")
            row = cur.fetchone()
            since_ts = row["pbf_timestamp"] if row else datetime(1970, 1, 1, tzinfo=timezone.utc)
        cur.execute("""
        SELECT lp.osm_type, lp.osm_id, lp.version, lp.deleted,
               ST_X(lp.geom) AS lon, ST_Y(lp.geom) AS lat,
               lp.region_code, lp.tags, lp.osm_timestamp, lp.seen_at
        FROM live_places lp
        WHERE lp.geom IS NOT NULL
          AND lp.osm_timestamp > %(since)s
          AND (lp.deleted OR (
                NOT EXISTS (
                  SELECT 1 FROM places p
                  WHERE p.osm_type = lp.osm_type AND p.osm_id = lp.osm_id)
                AND NOT (lp.osm_type = 'node' AND EXISTS (
                  SELECT 1 FROM places p
                  WHERE p.poi_node_id = lp.osm_id))))
        ORDER BY lp.osm_timestamp DESC
        LIMIT %(limit)s;
        """, {"since": since_ts, "limit": LIVE_LIMIT})
        rows = cur.fetchall()

    if len(rows) >= LIVE_LIMIT:
        logger.warning("/places/live hit its %d-row limit: pruning or abuse went wrong", LIVE_LIMIT)

    newest_seen = max((r["seen_at"] for r in rows), default=None)
    etag = '"' + hashlib.sha1(
        f"{len(rows)}|{newest_seen.isoformat() if newest_seen else ''}|{since_ts.isoformat()}".encode()
    ).hexdigest() + '"'
    headers = {"ETag": etag, "Cache-Control": "public, max-age=30"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)

    features = []
    removed = []
    for r in rows:
        if r["deleted"]:
            removed.append({"osm_type": r["osm_type"], "osm_id": r["osm_id"]})
            continue
        tags = r["tags"]
        if isinstance(tags, str):
            tags = json.loads(tags)
        features.append({
            "type": "Feature",
            "properties": {
                "osm_type": r["osm_type"],
                "osm_id": r["osm_id"],
                "version": r["version"],
                "edited_at": r["osm_timestamp"].isoformat() if r["osm_timestamp"] else None,
                "region_code": r["region_code"],
                "tags": tags or {},
            },
            "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
        })
    body = {
        "type": "FeatureCollection",
        "features": features,
        "removed": removed,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    return Response(content=json.dumps(body), media_type="application/json", headers=headers)


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
