import json
import logging
import defusedxml.ElementTree as ET
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.auth import get_current_user, verify_csrf
from app.database import get_db, get_db_context
from app.limiter import limiter
from app.worship_tags import is_worship_tagged

OSM_USER_AGENT = "Manara/1.0 (+https://manara.saudiosm.org)"
OSM_CHANGESET_BASE = "https://api.openstreetmap.org/api/0.6/changeset"

MAX_CHANGESET_XML_BYTES = 2 * 1024 * 1024  # 2 MB safety limit
MAX_LIVE_UPSERTS_PER_CHANGESET = 50  # one fake bulk changeset must not wipe gaps nationwide
MAX_WAY_LOOKUPS_PER_CHANGESET = 3  # user-triggered way/full reads, well inside the OSM API policy
OSM_WAY_BASE = "https://api.openstreetmap.org/api/0.6/way"

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["edits"])


class EditReportRequest(BaseModel):
    changeset_id: int = Field(..., gt=0, description="OSM changeset ID to verify and record")


def parse_osmchange_objects(xml_text: str) -> list[dict]:
    """Parse OSMChange XML to extract all touched elements."""
    objects = []
    seen = set()
    try:
        root = ET.fromstring(xml_text)
        for action in root:
            if action.tag not in ("create", "modify", "delete"):
                continue
            for elem in action:
                if elem.tag in ("node", "way", "relation"):
                    elem_id = elem.attrib.get("id")
                    if elem_id and elem_id.isdigit():
                        key = (elem.tag, int(elem_id))
                        if key not in seen:
                            seen.add(key)
                            objects.append({"type": elem.tag, "id": int(elem_id)})
    except Exception:
        pass
    return objects


def parse_osmchange_live(xml_text: str) -> list[dict]:
    """Extract live_places changes (nodes only: OSMChange carries no way geometry).

    A worship-tagged create/modify is an upsert; a modify without worship tags or a
    delete is a tombstone (the SQL function ignores objects it doesn't know). Never
    keeps user/uid.
    """
    changes = []
    try:
        root = ET.fromstring(xml_text)
        for action in root:
            if action.tag not in ("create", "modify", "delete"):
                continue
            for elem in action:
                if elem.tag != "node":
                    continue
                elem_id = elem.attrib.get("id")
                if not (elem_id and elem_id.isdigit()):
                    continue
                tags = {t.attrib["k"]: t.attrib["v"] for t in elem.findall("tag") if t.attrib.get("k") and t.attrib.get("v")}
                if action.tag == "delete":
                    deleted = True
                elif is_worship_tagged(tags):
                    deleted = False
                elif action.tag == "modify":
                    deleted = True
                else:
                    continue
                lat = lon = None
                if not deleted:
                    try:
                        lat = float(elem.attrib["lat"])
                        lon = float(elem.attrib["lon"])
                    except (KeyError, ValueError):
                        continue
                version = elem.attrib.get("version", "")
                changes.append({
                    "osm_type": "node",
                    "osm_id": int(elem_id),
                    "version": int(version) if version.isdigit() else None,
                    "lat": lat,
                    "lon": lon,
                    "tags": {} if deleted else tags,
                    "deleted": deleted,
                    "timestamp": elem.attrib.get("timestamp") or None,
                })
    except Exception:
        pass
    return changes


def write_live_changes(conn, cur, changeset_id: int, changes: list[dict]) -> int:
    """Apply live changes through manara_upsert_live_place inside a savepoint, so a
    live-layer failure never loses the verified edit record."""
    if not changes:
        return 0
    if len(changes) > MAX_LIVE_UPSERTS_PER_CHANGESET:
        logger.warning(
            "Changeset %s has %d live changes; truncating to %d",
            changeset_id, len(changes), MAX_LIVE_UPSERTS_PER_CHANGESET,
        )
        changes = changes[:MAX_LIVE_UPSERTS_PER_CHANGESET]
    written = 0
    try:
        with conn.transaction():
            for ch in changes:
                cur.execute(
                    "SELECT manara_upsert_live_place(%s, %s::bigint, %s::int, %s::double precision, "
                    "%s::double precision, %s::jsonb, %s::boolean, COALESCE(%s::timestamptz, NOW()), "
                    "'manara', %s::bigint);",
                    (ch["osm_type"], ch["osm_id"], ch["version"], ch["lon"], ch["lat"],
                     json.dumps(ch["tags"]), ch["deleted"], ch["timestamp"], changeset_id),
                )
                written += 1
    except Exception:
        logger.exception("Live place write failed for changeset %s", changeset_id)
        return 0
    return written


def parse_osmchange_way_candidates(xml_text: str) -> list[dict]:
    """Worship-tagged ways created/modified in a changeset. OSMChange gives them no
    coordinates, so the caller must locate them (see way_centroid_from_full)."""
    ways = []
    try:
        root = ET.fromstring(xml_text)
        for action in root:
            if action.tag not in ("create", "modify"):
                continue
            for elem in action:
                if elem.tag != "way":
                    continue
                elem_id = elem.attrib.get("id")
                tags = {t.attrib["k"]: t.attrib["v"] for t in elem.findall("tag") if t.attrib.get("k") and t.attrib.get("v")}
                if not (elem_id and elem_id.isdigit()) or not is_worship_tagged(tags):
                    continue
                version = elem.attrib.get("version", "")
                ways.append({
                    "osm_id": int(elem_id),
                    "version": int(version) if version.isdigit() else None,
                    "tags": tags,
                    "timestamp": elem.attrib.get("timestamp") or None,
                })
    except Exception:
        pass
    return ways


def way_centroid_from_full(xml_text: str) -> tuple[float, float] | None:
    """(lat, lon) mean of the nodes in a /way/{id}/full response, or None."""
    try:
        root = ET.fromstring(xml_text)
        coords = [(float(n.attrib["lat"]), float(n.attrib["lon"])) for n in root.findall("node")
                  if n.attrib.get("lat") is not None and n.attrib.get("lon") is not None]
    except Exception:
        return None
    if not coords:
        return None
    return sum(c[0] for c in coords) / len(coords), sum(c[1] for c in coords) / len(coords)


def bind_verified_marks(cur, changeset_id: int, osm_uid: int, objects: list[dict]) -> int:
    """Attach a verified changeset to the user's 'fixed' review marks.

    A merged mosque (building + inner node) has one review mark keyed by the
    building, while an edit may touch only its node (places.poi_node_id): such
    node edits are bound to the parent place's mark as well.
    """
    if not objects:
        return 0
    types = [obj["type"] for obj in objects]
    ids = [obj["id"] for obj in objects]
    cur.execute("""
        WITH touched AS (
            SELECT * FROM unnest(%s::text[], %s::bigint[]) AS t(osm_type, osm_id)
        ),
        targets AS (
            SELECT osm_type, osm_id FROM touched
            UNION
            SELECT p.osm_type, p.osm_id
            FROM touched t
            JOIN places p ON t.osm_type = 'node' AND p.poi_node_id = t.osm_id
        )
        UPDATE review_marks rm
        SET verified_changeset = %s
        FROM targets
        WHERE rm.osm_uid = %s
          AND rm.status = 'fixed'
          AND rm.osm_type = targets.osm_type
          AND rm.osm_id = targets.osm_id;
    """, (types, ids, changeset_id, osm_uid))
    return cur.rowcount


def bind_sprint_tiles(cur, objects: list[dict]) -> int:
    """Flag matching sprint tiles as pending_refresh when touched places are within their bbox."""
    if not objects:
        return 0
    types = [obj["type"] for obj in objects]
    ids = [obj["id"] for obj in objects]
    try:
        cur.execute("""
            WITH touched AS (
                SELECT * FROM unnest(%s::text[], %s::bigint[]) AS t(osm_type, osm_id)
            ),
            targets AS (
                SELECT p.geom
                FROM touched t
                JOIN places p ON (t.osm_type = p.osm_type AND t.osm_id = p.osm_id)
                              OR (t.osm_type = 'node' AND p.poi_node_id = t.osm_id)
            )
            UPDATE sprint_tiles st
            SET pending_refresh = TRUE
            FROM targets tg
            WHERE ST_Within(
                tg.geom,
                ST_MakeEnvelope(st.bbox[1]::double precision, st.bbox[2]::double precision,
                                st.bbox[3]::double precision, st.bbox[4]::double precision, 4326)
            );
        """, (types, ids))
        return cur.rowcount
    except Exception:
        return 0


@router.post("/edits")
@limiter.limit("30/minute")
async def report_and_verify_edit(
    request: Request,
    payload: EditReportRequest,
    _csrf: None = Depends(verify_csrf),
    user: dict = Depends(get_current_user),
):
    """
    Verify and record an OSM changeset uploaded with #sa-worship-map.
    Fetches changeset metadata once, verifies ownership and hashtag, downloads touched objects,
    and binds verified_changeset to matching 'fixed' review marks.
    """
    cid = payload.changeset_id

    # 1. Check if already recorded
    with get_db_context() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT changeset_id, osm_uid, comment, verified_at, objects FROM edits WHERE changeset_id = %s;", (cid,))
            existing = cur.fetchone()
            if existing:
                # A repeated report still (re)binds marks: the first report may have
                # arrived before the mapper's 'fixed' mark existed.
                rebound = 0
                if existing["osm_uid"] == user["osm_uid"]:
                    with conn.transaction():
                        with conn.cursor() as bind_cur:
                            rebound = bind_verified_marks(bind_cur, cid, user["osm_uid"], existing["objects"] or [])
                            bind_sprint_tiles(bind_cur, existing["objects"] or [])
                return {
                    "status": "ok",
                    "changeset_id": existing["changeset_id"],
                    "already_verified": True,
                    "objects_count": len(existing["objects"] or []),
                    "verified_marks_updated": rebound,
                }

    # 2. Fetch changeset metadata from OSM API once
    changeset_url = f"{OSM_CHANGESET_BASE}/{cid}.json"
    download_url = f"{OSM_CHANGESET_BASE}/{cid}/download"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            meta_res = await client.get(
                changeset_url,
                headers={"User-Agent": OSM_USER_AGENT, "Accept": "application/json"},
            )
            if meta_res.status_code == 404:
                raise HTTPException(status_code=404, detail=f"Changeset {cid} not found on OpenStreetMap.")
            if meta_res.status_code == 429:
                retry = meta_res.headers.get("Retry-After", "60")
                raise HTTPException(status_code=429, detail=f"OSM rate limit reached. Retry after {retry}s.")
            if meta_res.status_code != 200:
                raise HTTPException(status_code=502, detail=f"OSM API returned HTTP {meta_res.status_code}.")

            cs_data = meta_res.json().get("changeset", {})

            # Validate author
            cs_uid = cs_data.get("uid")
            if cs_uid != user["osm_uid"]:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Changeset was created by OSM UID {cs_uid}, but you are logged in as {user['osm_uid']}.",
                )

            # Validate closed
            if cs_data.get("open") is True:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Changeset is still open. Please wait until upload is finalized and closed.",
                )

            # Validate comment or hashtags contain #sa-worship-map
            tags = cs_data.get("tags", {})
            comment = tags.get("comment", "")
            hashtags = tags.get("hashtags", "")
            text_to_check = f"{comment} {hashtags}".lower()
            if "#sa-worship-map" not in text_to_check:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Changeset must contain the hashtag #sa-worship-map in comment or tags.",
                )

            # Fetch touched objects (streaming with 2 MiB safety cap)
            async with client.stream(
                "GET",
                download_url,
                headers={"User-Agent": OSM_USER_AGENT},
            ) as dl_res:
                if dl_res.status_code != 200:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"Could not download changeset contents (HTTP {dl_res.status_code}). Please try again.",
                    )
                content_chunks = []
                total_bytes = 0
                async for chunk in dl_res.aiter_bytes():
                    total_bytes += len(chunk)
                    if total_bytes > MAX_CHANGESET_XML_BYTES:
                        raise HTTPException(
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            detail="Changeset XML exceeds maximum allowed size (2 MiB).",
                        )
                    content_chunks.append(chunk)
                xml_text = b"".join(content_chunks).decode("utf-8", errors="replace")
                objects = parse_osmchange_objects(xml_text)
                live_changes = parse_osmchange_live(xml_text)

            # Existing buildings tagged as mosques: no coordinates in OSMChange, so read
            # each unknown way once (capped) and use its centroid.
            way_candidates = parse_osmchange_way_candidates(xml_text)[:MAX_WAY_LOOKUPS_PER_CHANGESET]
            known_ways: set[int] = set()
            if way_candidates:
                try:
                    with get_db_context() as lookup_conn:
                        with lookup_conn.cursor() as lookup_cur:
                            lookup_cur.execute(
                                "SELECT osm_id FROM places WHERE osm_type = 'way' AND osm_id = ANY(%s::bigint[]);",
                                ([w["osm_id"] for w in way_candidates],),
                            )
                            known_ways = {r["osm_id"] for r in lookup_cur.fetchall()}
                except Exception:
                    logger.exception("Way lookup against places failed; skipping live placement of ways")
                    way_candidates = []
                for way in way_candidates:
                    if way["osm_id"] in known_ways:
                        continue
                    try:
                        way_res = await client.get(
                            f"{OSM_WAY_BASE}/{way['osm_id']}/full",
                            headers={"User-Agent": OSM_USER_AGENT},
                        )
                        centroid = way_centroid_from_full(way_res.text) if way_res.status_code == 200 else None
                    except Exception:
                        logger.warning("Could not read way %s for live placement", way["osm_id"])
                        continue
                    if centroid:
                        live_changes.append({
                            "osm_type": "way", "osm_id": way["osm_id"], "version": way["version"],
                            "lat": centroid[0], "lon": centroid[1], "tags": way["tags"],
                            "deleted": False, "timestamp": way["timestamp"],
                        })

    except HTTPException:
        raise
    except Exception:
        logger.exception("Changeset verification against OSM failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not verify the changeset with OpenStreetMap.",
        )

    # 3. Store verified edit and bind marks inside an atomic transaction
    with get_db_context() as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO edits (changeset_id, osm_uid, objects, comment, verified_at, created_at)
                    VALUES (%s, %s, %s::jsonb, %s, NOW(), NOW())
                    ON CONFLICT (changeset_id) DO NOTHING;
                """, (cid, user["osm_uid"], json.dumps(objects), comment))

                # 4. Batch bind verified_changeset to user's 'fixed' marks for touched objects
                updated_marks_count = bind_verified_marks(cur, cid, user["osm_uid"], objects)
                # 5. Flag matching sprint tiles as pending_refresh
                bind_sprint_tiles(cur, objects)

                # 6. Make new/changed/deleted mosques visible to everyone at once
                write_live_changes(conn, cur, cid, live_changes)

    return {
        "status": "ok",
        "changeset_id": cid,
        "verified": True,
        "objects_count": len(objects),
        "verified_marks_updated": updated_marks_count,
    }
