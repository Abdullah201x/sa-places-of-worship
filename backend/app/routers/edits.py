import json
import defusedxml.ElementTree as ET
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.auth import get_current_user, verify_csrf
from app.database import get_db, get_db_context
from app.limiter import limiter

OSM_USER_AGENT = "Manara/1.0 (+https://manara.saudiosm.org)"
OSM_CHANGESET_BASE = "https://api.openstreetmap.org/api/0.6/changeset"

MAX_CHANGESET_XML_BYTES = 2 * 1024 * 1024  # 2 MB safety limit

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

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not verify changeset with OpenStreetMap: {e}",
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

    return {
        "status": "ok",
        "changeset_id": cid,
        "verified": True,
        "objects_count": len(objects),
        "verified_marks_updated": updated_marks_count,
    }
