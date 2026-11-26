import json
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field

from app.auth import get_current_user, get_optional_user, require_admin, verify_csrf
from app.database import get_db
from app.limiter import limiter

router = APIRouter(prefix="/api/v1/sprints", tags=["sprints"])

TileState = Literal[
    "ready", "mapping", "mapped", "validating", "validated", "invalidated", "skipped"
]

# Fallback bounding boxes keyed by the real ISO 3166-2:SA codes (the same codes
# pipeline/extract_regions.py stores in the `regions` table):
# [min_lon, min_lat, max_lon, max_lat]. When the `regions` table is loaded its
# geometry is used instead, so tiles follow the true province outline.
REGION_BOUNDS: dict[str, list[float]] = {
    "SA-01": [44.0, 20.0, 48.5, 27.0],  # Riyadh
    "SA-02": [38.5, 19.5, 43.0, 23.5],  # Makkah
    "SA-03": [37.5, 22.5, 42.0, 26.5],  # Madinah
    "SA-04": [46.5, 19.0, 55.5, 29.5],  # Eastern Province
    "SA-05": [42.5, 25.0, 45.0, 27.0],  # Al-Qassim
    "SA-06": [39.5, 26.0, 43.5, 29.0],  # Ha'il
    "SA-07": [34.5, 26.5, 39.5, 29.5],  # Tabuk
    "SA-08": [38.0, 29.0, 44.5, 32.2],  # Northern Borders
    "SA-09": [41.5, 16.2, 43.5, 18.0],  # Jazan
    "SA-10": [43.5, 17.0, 48.0, 19.5],  # Najran
    "SA-11": [41.0, 19.5, 42.0, 20.5],  # Al-Bahah
    "SA-12": [37.0, 28.5, 41.5, 32.2],  # Al-Jawf
    "SA-14": [41.5, 17.5, 44.5, 20.5],  # Asir
}

MAX_SPRINT_AREA_KM2 = 5000.0
MAX_SPRINT_TILES = 2000
LOCK_TTL_HOURS = 2
MAX_ACTIVE_LOCKS_PER_USER = 3


class CreateSprintRequest(BaseModel):
    slug: str = Field(..., min_length=2, max_length=100, pattern=r"^[a-z0-9_-]+$")
    title: dict[str, str] = Field(..., description="Localized title: {ar: ..., en: ...}")
    instructions: dict[str, str] = Field(default_factory=dict, description="Localized instructions: {ar: ..., en: ...}")
    theme: str = Field("worship", description="Theme")
    area: dict[str, Any] = Field(..., description="Area spec: {region_code: 'SA-01'} or {polygon: GeoJSON Polygon}")
    rule_ids: list[str] = Field(default_factory=list, description="Target rule IDs")
    gap_min_urgency: int | None = Field(None, description="Include gap cells with urgency >= N")
    hashtag: str = Field(..., description="Campaign hashtag, e.g. #sa-worship-kharj")
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    status: Literal["draft", "active", "closed"] = "draft"


class UpdateSprintRequest(BaseModel):
    title: dict[str, str] | None = None
    instructions: dict[str, str] | None = None
    hashtag: str | None = None
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    status: Literal["draft", "active", "closed"] | None = None


class TileActionRequest(BaseModel):
    action: Literal["lock", "release", "done", "approve", "invalidate", "skip", "reopen"]
    rev: int | None = Field(None, description="Current tile revision for optimistic concurrency")
    kind: Literal["mapping", "validation"] | None = Field(None, description="Lock kind if action == 'lock'")
    reason: str | None = Field(None, max_length=500, description="Reason for invalidate or skip")
    note: str | None = Field(None, max_length=500, description="Optional note for done or approve")


def generate_tiles_for_bounds(min_lon: float, min_lat: float, max_lon: float, max_lat: float, grid_deg: float = 0.02) -> list[dict]:
    """Generates grid tiles within given bounding box, with configurable grid_deg."""
    min_tx = math.floor(min_lon / grid_deg)
    max_tx = math.floor(max_lon / grid_deg)
    min_ty = math.floor(min_lat / grid_deg)
    max_ty = math.floor(max_lat / grid_deg)

    tiles = []
    for tx in range(min_tx, max_tx + 1):
        for ty in range(min_ty, max_ty + 1):
            t_min_lon = round(tx * grid_deg, 6)
            t_min_lat = round(ty * grid_deg, 6)
            t_max_lon = round((tx + 1) * grid_deg, 6)
            t_max_lat = round((ty + 1) * grid_deg, 6)
            tiles.append({
                "tile_id": f"{tx}:{ty}",
                "bbox": [t_min_lon, t_min_lat, t_max_lon, t_max_lat]
            })
    return tiles


TILE_DEG = 0.02


def workload_tiles_for_area(conn, area: dict, rule_ids: list[str], gap_min_urgency: int | None) -> list[dict] | None:
    """Tiles that actually contain work, clipped to the real area.

    Counts issues (matching rule_ids) and gap cells per 0.02 degree cell for the
    places/gaps that fall inside the area (province geometry from the `regions`
    table, or the drawn polygon). Only non-empty cells are returned, so a whole
    province becomes a few hundred tiles instead of tens of thousands of empty
    desert squares, and each tile already has its initial workload.

    Returns None when the dataset tables are unavailable (fresh database), so
    the caller can fall back to plain bounding-box tiles.
    """
    if "region_code" in area:
        geom_sql = "(SELECT geom FROM regions WHERE code = %s)"
        geom_param = area["region_code"]
    else:
        geom_sql = "ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)"
        geom_param = json.dumps(area["polygon"])

    query = f"""
        WITH area AS (SELECT {geom_sql} AS g),
        issue_cells AS (
            SELECT floor(ST_X(p.geom) / {TILE_DEG})::int AS gx,
                   floor(ST_Y(p.geom) / {TILE_DEG})::int AS gy,
                   COUNT(*) AS n
            FROM area a
            JOIN places p ON p.geom && a.g AND ST_Intersects(p.geom, a.g)
            JOIN issues i ON i.osm_type = p.osm_type AND i.osm_id = p.osm_id
            WHERE (cardinality(%s::text[]) = 0 OR i.rule_id = ANY(%s::text[]))
            GROUP BY 1, 2
        ),
        gap_cells AS (
            SELECT floor(ST_X(gp.geom) / {TILE_DEG})::int AS gx,
                   floor(ST_Y(gp.geom) / {TILE_DEG})::int AS gy,
                   COUNT(*) AS n
            FROM area a
            JOIN gaps gp ON gp.geom && a.g AND ST_Intersects(gp.geom, a.g)
            WHERE (%s::int IS NULL OR gp.urgency_score >= %s::int)
            GROUP BY 1, 2
        )
        SELECT gx, gy, SUM(n)::int AS workload
        FROM (SELECT * FROM issue_cells UNION ALL SELECT * FROM gap_cells) u
        GROUP BY gx, gy
        HAVING SUM(n) > 0
        ORDER BY gx, gy
        LIMIT %s;
    """
    try:
        with conn.cursor() as cur:
            cur.execute(query, (geom_param, rule_ids, rule_ids, gap_min_urgency, gap_min_urgency, MAX_SPRINT_TILES + 1))
            rows = cur.fetchall()
    except Exception:
        return None

    tiles = []
    for r in rows:
        gx, gy, workload = (r["gx"], r["gy"], r["workload"]) if isinstance(r, dict) else (r[0], r[1], r[2])
        tiles.append({
            "tile_id": f"{gx}:{gy}",
            "bbox": [round(gx * TILE_DEG, 6), round(gy * TILE_DEG, 6),
                     round((gx + 1) * TILE_DEG, 6), round((gy + 1) * TILE_DEG, 6)],
            "workload": int(workload),
        })
    return tiles


def expire_stale_locks(conn, sprint_id: int | None = None):
    """Reverts expired locks back to ready or mapped states and writes tile_events.

    One atomic statement: rows are claimed with FOR UPDATE SKIP LOCKED, so two
    concurrent requests never expire (and double-bump) the same tile.
    """
    now = datetime.now(timezone.utc)
    sprint_filter = "AND sprint_id = %s" if sprint_id is not None else ""
    params: list = [now, now]
    if sprint_id is not None:
        params.append(sprint_id)
    params.append(now)
    with conn.cursor() as cur:
        cur.execute(f"""
            WITH claimed AS (
                SELECT sprint_id, tile_id, state AS old_state, lock_uid
                FROM sprint_tiles
                WHERE state IN ('mapping', 'validating')
                  AND lock_expires_at IS NOT NULL
                  AND lock_expires_at <= %s
                  {sprint_filter}
                FOR UPDATE SKIP LOCKED
            ),
            expired AS (
                UPDATE sprint_tiles st
                SET state = CASE WHEN c.old_state = 'mapping' THEN 'ready' ELSE 'mapped' END,
                    lock_uid = NULL,
                    lock_display_name = NULL,
                    lock_kind = NULL,
                    lock_expires_at = NULL,
                    rev = st.rev + 1,
                    updated_at = %s
                FROM claimed c
                WHERE st.sprint_id = c.sprint_id AND st.tile_id = c.tile_id
                RETURNING st.sprint_id, st.tile_id, c.old_state, c.lock_uid, st.state AS new_state
            )
            INSERT INTO tile_events (sprint_id, tile_id, osm_uid, from_state, to_state, reason, created_at)
            SELECT sprint_id, tile_id, COALESCE(lock_uid, 0), old_state, new_state, 'lock_expired', %s
            FROM expired;
        """, params)


def compute_sprint_progress(cur, sprint_id: int) -> dict:
    """Computes total, by_state counts, and workload_remaining for a sprint."""
    cur.execute("""
        SELECT state, COUNT(*) as cnt, COALESCE(SUM(workload), 0) as work_sum
        FROM sprint_tiles
        WHERE sprint_id = %s
        GROUP BY state;
    """, (sprint_id,))
    rows = cur.fetchall()

    by_state = {st: 0 for st in ["ready", "mapping", "mapped", "validating", "validated", "invalidated", "skipped"]}
    total = 0
    workload_remaining = 0

    for r in rows:
        st = r["state"] if isinstance(r, dict) else r[0]
        cnt = int(r["cnt"] if isinstance(r, dict) else r[1])
        w_sum = int(r["work_sum"] if isinstance(r, dict) else r[2])
        if st in by_state:
            by_state[st] = cnt
        total += cnt
        if st not in ("validated", "skipped"):
            workload_remaining += w_sum

    pct = round((by_state["validated"] / total) * 100, 1) if total > 0 else 0.0
    return {
        "total": total,
        "by_state": by_state,
        "workload_remaining": workload_remaining,
        "percent_complete": pct,
    }


def row_to_tile_dict(r) -> dict:
    d = dict(r) if hasattr(r, "keys") else {
        "tile_id": r[0], "bbox": r[1], "state": r[2], "rev": r[3],
        "workload": r[4], "pending_refresh": r[5], "lock_uid": r[6],
        "lock_display_name": r[7], "lock_kind": r[8], "lock_expires_at": r[9],
        "mapped_by": r[10], "validated_by": r[11], "auto": r[12]
    }
    lock_info = None
    if d.get("lock_uid") and d.get("lock_expires_at"):
        lock_info = {
            "osm_uid": d["lock_uid"],
            "display_name": d.get("lock_display_name") or "mapper",
            "kind": d.get("lock_kind") or "mapping",
            "expires_at": d["lock_expires_at"].isoformat() if hasattr(d["lock_expires_at"], "isoformat") else str(d["lock_expires_at"])
        }

    return {
        "tile_id": d["tile_id"],
        "bbox": d["bbox"],
        "state": d["state"],
        "rev": d["rev"],
        "workload": d["workload"],
        "pending_refresh": bool(d.get("pending_refresh", False)),
        "lock": lock_info,
        "mapped_by": d.get("mapped_by"),
        "validated_by": d.get("validated_by"),
        "auto": bool(d.get("auto", False)),
    }


@router.get("")
def list_sprints(
    status: Literal["all", "draft", "active", "closed"] = Query("active", description="Filter by sprint status"),
    conn=Depends(get_db),
):
    """Lists sprints with calculated progress and workload statistics."""
    expire_stale_locks(conn)
    with conn.cursor() as cur:
        query = "SELECT * FROM sprints"
        params = []
        if status != "all":
            query += " WHERE status = %s"
            params.append(status)
        query += " ORDER BY created_at DESC;"

        cur.execute(query, params)
        rows = cur.fetchall()

        sprints = []
        for r in rows:
            s_dict = dict(r)
            s_dict["progress"] = compute_sprint_progress(cur, s_dict["id"])
            sprints.append(s_dict)

        return sprints


@router.post("", status_code=status.HTTP_201_CREATED)
def create_sprint(
    payload: CreateSprintRequest,
    _csrf: None = Depends(verify_csrf),
    admin: dict = Depends(require_admin),
    conn=Depends(get_db),
):
    """
    Creates a new mapping sprint over a region or drawn polygon.
    Generates 0.02° tiles (~2.2 km blocks) clipped to the area, keeping only cells with work.
    Admin only (MANARA_ADMIN_UIDS).
    """
    area_dict = payload.area
    min_lon, min_lat, max_lon, max_lat = 0.0, 0.0, 0.0, 0.0

    if "region_code" in area_dict:
        rc = area_dict["region_code"]
        if rc not in REGION_BOUNDS:
            raise HTTPException(status_code=400, detail=f"Unknown region_code '{rc}'. Available: {list(REGION_BOUNDS.keys())}")
        min_lon, min_lat, max_lon, max_lat = REGION_BOUNDS[rc]
    elif "polygon" in area_dict:
        try:
            poly_coords = area_dict["polygon"]["coordinates"][0]
            lons = [c[0] for c in poly_coords]
            lats = [c[1] for c in poly_coords]
            min_lon, min_lat, max_lon, max_lat = min(lons), min(lats), max(lons), max(lats)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid polygon GeoJSON: {e}")
    else:
        raise HTTPException(status_code=400, detail="area must specify 'region_code' or 'polygon'")

    # Validate bounds are within Saudi Arabia
    if not (33.0 <= min_lon <= 56.5 and 15.5 <= min_lat <= 33.0 and 33.0 <= max_lon <= 56.5 and 15.5 <= max_lat <= 33.0):
        raise HTTPException(status_code=400, detail="Sprint area must be within Saudi Arabia boundary.")

    # Prefer tiles clipped to the real area that already carry workload.
    tiles = workload_tiles_for_area(conn, area_dict, payload.rule_ids, payload.gap_min_urgency)
    if not tiles:
        # Dataset not loaded (or nothing to do yet): plain bounding-box tiles.
        # Auto-scale grid_deg for large area bounds to stay within MAX_SPRINT_TILES
        grid_deg = 0.02
        span_x = max_lon - min_lon
        span_y = max_lat - min_lat
        for candidate_deg in (0.02, 0.05, 0.1, 0.2, 0.5):
            est_count = (math.ceil(span_x / candidate_deg) + 1) * (math.ceil(span_y / candidate_deg) + 1)
            if est_count <= MAX_SPRINT_TILES:
                grid_deg = candidate_deg
                break
        tiles = generate_tiles_for_bounds(min_lon, min_lat, max_lon, max_lat, grid_deg=grid_deg)
    if len(tiles) > MAX_SPRINT_TILES:
        raise HTTPException(
            status_code=400,
            detail=f"Sprint covers {len(tiles)}+ tiles, exceeding maximum {MAX_SPRINT_TILES} tiles. Please select a smaller area."
        )

    starts_at = payload.starts_at or datetime.now(timezone.utc)
    now = datetime.now(timezone.utc)

    # Autocommit is on, so FOR UPDATE only holds its row lock inside a transaction block
    with conn.transaction():
        with conn.cursor() as cur:
            # Check slug uniqueness
            cur.execute("SELECT id FROM sprints WHERE slug = %s;", (payload.slug,))
            if cur.fetchone():
                raise HTTPException(status_code=409, detail=f"Sprint slug '{payload.slug}' already exists.")

            cur.execute("""
                INSERT INTO sprints (
                    slug, title, instructions, theme, area, rule_ids, gap_min_urgency,
                    hashtag, starts_at, ends_at, status, created_by, created_at, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *;
            """, (
                payload.slug,
                json.dumps(payload.title),
                json.dumps(payload.instructions),
                payload.theme,
                json.dumps(payload.area),
                payload.rule_ids,
                payload.gap_min_urgency,
                payload.hashtag,
                starts_at,
                payload.ends_at,
                payload.status,
                admin["osm_uid"],
                now,
                now
            ))
            sprint_row = dict(cur.fetchone())
            sprint_id = sprint_row["id"]

            # Insert tiles in bulk
            tile_rows = []
            for t in tiles:
                tile_rows.append((
                    sprint_id,
                    t["tile_id"],
                    t["bbox"],
                    "ready",
                    1,
                    t.get("workload", 0),
                    False,
                    now
                ))

            cur.executemany(
                """
                INSERT INTO sprint_tiles (
                    sprint_id, tile_id, bbox, state, rev, workload, pending_refresh, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                """,
                tile_rows
            )

            sprint_row["progress"] = compute_sprint_progress(cur, sprint_id)
            return sprint_row


@router.get("/{slug}")
def get_sprint_by_slug(
    slug: str,
    conn=Depends(get_db),
):
    """Returns details and progress summary for a single sprint."""
    expire_stale_locks(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM sprints WHERE slug = %s;", (slug,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Sprint not found.")

        sprint = dict(row)
        sprint["progress"] = compute_sprint_progress(cur, sprint["id"])
        return sprint


@router.patch("/{slug}")
def update_sprint(
    slug: str,
    payload: UpdateSprintRequest,
    _csrf: None = Depends(verify_csrf),
    admin: dict = Depends(require_admin),
    conn=Depends(get_db),
):
    """Admin-only partial update of a sprint (title, instructions, status, dates)."""
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM sprints WHERE slug = %s;", (slug,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Sprint not found.")
        sprint_id = row["id"] if isinstance(row, dict) else row[0]

        updates = []
        params = []
        if payload.title is not None:
            updates.append("title = %s")
            params.append(json.dumps(payload.title))
        if payload.instructions is not None:
            updates.append("instructions = %s")
            params.append(json.dumps(payload.instructions))
        if payload.hashtag is not None:
            updates.append("hashtag = %s")
            params.append(payload.hashtag)
        if payload.starts_at is not None:
            updates.append("starts_at = %s")
            params.append(payload.starts_at)
        if payload.ends_at is not None:
            updates.append("ends_at = %s")
            params.append(payload.ends_at)
        if payload.status is not None:
            updates.append("status = %s")
            params.append(payload.status)

        if updates:
            updates.append("updated_at = %s")
            params.append(datetime.now(timezone.utc))
            params.append(sprint_id)

            cur.execute(f"UPDATE sprints SET {', '.join(updates)} WHERE id = %s RETURNING *;", params)
            updated = dict(cur.fetchone())
            conn.commit()
            updated["progress"] = compute_sprint_progress(cur, sprint_id)
            return updated

        cur.execute("SELECT * FROM sprints WHERE id = %s;", (sprint_id,))
        res = dict(cur.fetchone())
        res["progress"] = compute_sprint_progress(cur, sprint_id)
        return res


@router.get("/{slug}/tiles")
def get_sprint_tiles(
    slug: str,
    response: Response,
    request: Request,
    state: TileState | None = Query(None, description="Filter tiles by state"),
    conn=Depends(get_db),
):
    """
    Returns compact array of tiles for the sprint board.
    Supports ETag caching via tile count + summed revs for cheap 60s background polling.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM sprints WHERE slug = %s;", (slug,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Sprint not found.")
        sprint_id = row["id"] if isinstance(row, dict) else row[0]

        expire_stale_locks(conn, sprint_id)

        query = """
            SELECT tile_id, bbox, state, rev, workload, pending_refresh,
                   lock_uid, lock_display_name, lock_kind, lock_expires_at,
                   mapped_by, validated_by, auto
            FROM sprint_tiles
            WHERE sprint_id = %s
        """
        params = [sprint_id]
        if state:
            query += " AND state = %s"
            params.append(state)
        query += " ORDER BY tile_id ASC;"

        cur.execute(query, params)
        rows = cur.fetchall()

        tiles = [row_to_tile_dict(r) for r in rows]
        rev_max = max((t["rev"] for t in tiles), default=1)

        # max(rev) alone collides: tile A going 1 -> 2 leaves it at 2 while B is
        # already 2. Count, sum of revs and pending flags change on every edit.
        sum_rev = sum(t["rev"] for t in tiles)
        pending = sum(1 for t in tiles if t["pending_refresh"])
        etag = f'W/"{sprint_id}:{len(tiles)}:{sum_rev}:{pending}"'
        response.headers["ETag"] = etag
        response.headers["Cache-Control"] = "public, max-age=10, must-revalidate"

        # Check client ETag
        if_none_match = request.headers.get("if-none-match")
        if if_none_match and if_none_match == etag:
            return Response(status_code=status.HTTP_304_NOT_MODIFIED)

        return {
            "rev_max": rev_max,
            "tiles": tiles
        }


@router.put("/{slug}/tiles/{tile_id}")
@limiter.limit("60/minute")
def update_tile_state(
    request: Request,
    slug: str,
    tile_id: str,
    payload: TileActionRequest,
    if_match: str | None = Header(None, alias="If-Match"),
    _csrf: None = Depends(verify_csrf),
    user: dict = Depends(get_current_user),
    conn=Depends(get_db),
):
    """
    Executes an atomic tile state transition with optimistic concurrency and validation checks:
    - lock: locks ready tile for mapping, or mapped tile for validation.
    - release: returns locked tile to ready or mapped.
    - done: mapper finishes mapping -> state becomes mapped.
    - approve: validator approves tile -> state becomes validated (self-validation rejected).
    - invalidate: validator rejects tile with required reason.
    - skip: flags tile as skipped (no imagery / out of scope).
    - reopen: admin reopens validated/invalidated/skipped tile back to ready.
    """
    now = datetime.now(timezone.utc)
    user_uid = user["osm_uid"]
    is_admin = bool(user.get("is_admin", False))

    # Autocommit is on, so FOR UPDATE only holds its row lock inside a transaction block
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("SELECT id, status FROM sprints WHERE slug = %s;", (slug,))
            sprint_row = cur.fetchone()
            if not sprint_row:
                raise HTTPException(status_code=404, detail="Sprint not found.")
            sprint_id = sprint_row["id"] if isinstance(sprint_row, dict) else sprint_row[0]
            sprint_status = sprint_row.get("status", "active") if isinstance(sprint_row, dict) else "active"
            if sprint_status != "active":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Sprint is {sprint_status}; tiles can only be changed while it is active.",
                )

            expire_stale_locks(conn, sprint_id)

            cur.execute("""
                SELECT * FROM sprint_tiles
                WHERE sprint_id = %s AND tile_id = %s
                FOR UPDATE;
            """, (sprint_id, tile_id))
            t_row = cur.fetchone()
            if not t_row:
                raise HTTPException(status_code=404, detail="Tile not found.")

            tile = dict(t_row)
            current_rev = tile["rev"]
            current_state = tile["state"]
            from_state = current_state

            # Optimistic concurrency check
            expected_rev = payload.rev
            if if_match:
                try:
                    expected_rev = int(if_match.strip('"').strip('W/').strip('"'))
                except ValueError:
                    pass

            if expected_rev is not None and expected_rev != current_rev:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Conflict: Tile revision has changed (expected {expected_rev}, current {current_rev}). Please reload.",
                )

            action = payload.action

            # A tile locked by someone else can only be approved, invalidated or
            # skipped by its lock holder (or an admin).
            locked_by_other = tile.get("lock_uid") is not None and tile["lock_uid"] != user_uid and not is_admin
            if action in ("approve", "invalidate", "skip") and locked_by_other:
                raise HTTPException(status_code=403, detail="This tile is locked by another user.")

            if action == "lock":
                # Check maximum active locks per user
                cur.execute("""
                    SELECT COUNT(*) as active_locks FROM sprint_tiles
                    WHERE lock_uid = %s AND lock_expires_at > %s;
                """, (user_uid, now))
                c_row = cur.fetchone()
                active_cnt = (c_row["active_locks"] if isinstance(c_row, dict) else c_row[0]) or 0
                if active_cnt >= MAX_ACTIVE_LOCKS_PER_USER:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Maximum {MAX_ACTIVE_LOCKS_PER_USER} simultaneous locks permitted per user.",
                    )

                lock_kind = payload.kind or ("validation" if current_state == "mapped" else "mapping")

                # An invalidated tile goes back to being mapped again.
                if current_state in ("ready", "invalidated"):
                    new_state = "mapping"
                elif current_state == "mapped":
                    # Self-validation rejection check
                    if tile.get("mapped_by") and tile["mapped_by"] == user_uid and not is_admin:
                        raise HTTPException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            detail="Self-validation is not allowed. A different mapper must validate this tile.",
                        )
                    new_state = "validating"
                else:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Cannot lock tile in state '{current_state}'. Only 'ready', 'invalidated' or 'mapped' tiles can be locked."
                    )

                expires_at = now + timedelta(hours=LOCK_TTL_HOURS)
                cur.execute("""
                    UPDATE sprint_tiles
                    SET state = %s,
                        lock_uid = %s,
                        lock_display_name = %s,
                        lock_kind = %s,
                        lock_expires_at = %s,
                        rev = rev + 1,
                        updated_at = %s
                    WHERE sprint_id = %s AND tile_id = %s
                    RETURNING *;
                """, (new_state, user_uid, user.get("display_name", "mapper"), lock_kind, expires_at, now, sprint_id, tile_id))

            elif action == "release":
                if tile.get("lock_uid") != user_uid and not is_admin:
                    raise HTTPException(status_code=403, detail="Only the lock holder or an admin can release this lock.")
                if current_state not in ("mapping", "validating"):
                    raise HTTPException(status_code=400, detail=f"Cannot release tile in state '{current_state}'; it is not locked.")

                new_state = "ready" if current_state == "mapping" else "mapped"
                cur.execute("""
                    UPDATE sprint_tiles
                    SET state = %s,
                        lock_uid = NULL,
                        lock_display_name = NULL,
                        lock_kind = NULL,
                        lock_expires_at = NULL,
                        rev = rev + 1,
                        updated_at = %s
                    WHERE sprint_id = %s AND tile_id = %s
                    RETURNING *;
                """, (new_state, now, sprint_id, tile_id))

            elif action == "done":
                if current_state != "mapping":
                    raise HTTPException(status_code=400, detail=f"Cannot mark tile done from state '{current_state}'.")
                if tile.get("lock_uid") != user_uid and not is_admin:
                    raise HTTPException(status_code=403, detail="Only the mapper who locked the tile can submit it.")

                new_state = "mapped"
                cur.execute("""
                    UPDATE sprint_tiles
                    SET state = %s,
                        mapped_by = %s,
                        note = %s,
                        lock_uid = NULL,
                        lock_display_name = NULL,
                        lock_kind = NULL,
                        lock_expires_at = NULL,
                        rev = rev + 1,
                        updated_at = %s
                    WHERE sprint_id = %s AND tile_id = %s
                    RETURNING *;
                """, (new_state, user_uid, payload.note, now, sprint_id, tile_id))

            elif action == "approve":
                if current_state not in ("validating", "mapped"):
                    raise HTTPException(status_code=400, detail=f"Cannot approve tile in state '{current_state}'.")
                if tile.get("mapped_by") and tile["mapped_by"] == user_uid and not is_admin:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Self-validation is not allowed. A different mapper must validate this tile.",
                    )

                new_state = "validated"
                cur.execute("""
                    UPDATE sprint_tiles
                    SET state = %s,
                        validated_by = %s,
                        note = %s,
                        lock_uid = NULL,
                        lock_display_name = NULL,
                        lock_kind = NULL,
                        lock_expires_at = NULL,
                        rev = rev + 1,
                        updated_at = %s
                    WHERE sprint_id = %s AND tile_id = %s
                    RETURNING *;
                """, (new_state, user_uid, payload.note, now, sprint_id, tile_id))

            elif action == "invalidate":
                if current_state not in ("validating", "mapped"):
                    raise HTTPException(status_code=400, detail=f"Cannot invalidate tile in state '{current_state}'.")
                if not payload.reason:
                    raise HTTPException(status_code=400, detail="A reason is required when invalidating a tile.")

                new_state = "invalidated"
                cur.execute("""
                    UPDATE sprint_tiles
                    SET state = %s,
                        skip_reason = %s,
                        lock_uid = NULL,
                        lock_display_name = NULL,
                        lock_kind = NULL,
                        lock_expires_at = NULL,
                        rev = rev + 1,
                        updated_at = %s
                    WHERE sprint_id = %s AND tile_id = %s
                    RETURNING *;
                """, (new_state, payload.reason, now, sprint_id, tile_id))

            elif action == "skip":
                if current_state not in ("ready", "mapping"):
                    raise HTTPException(status_code=400, detail=f"Cannot skip tile in state '{current_state}'.")

                new_state = "skipped"
                skip_reason = payload.reason or "out of scope"
                cur.execute("""
                    UPDATE sprint_tiles
                    SET state = %s,
                        skip_reason = %s,
                        lock_uid = NULL,
                        lock_display_name = NULL,
                        lock_kind = NULL,
                        lock_expires_at = NULL,
                        rev = rev + 1,
                        updated_at = %s
                    WHERE sprint_id = %s AND tile_id = %s
                    RETURNING *;
                """, (new_state, skip_reason, now, sprint_id, tile_id))

            elif action == "reopen":
                if not is_admin:
                    raise HTTPException(status_code=403, detail="Only admins can reopen finished or skipped tiles.")

                new_state = "ready"
                cur.execute("""
                    UPDATE sprint_tiles
                    SET state = %s,
                        mapped_by = NULL,
                        validated_by = NULL,
                        skip_reason = NULL,
                        note = NULL,
                        auto = FALSE,
                        lock_uid = NULL,
                        lock_display_name = NULL,
                        lock_kind = NULL,
                        lock_expires_at = NULL,
                        rev = rev + 1,
                        updated_at = %s
                    WHERE sprint_id = %s AND tile_id = %s
                    RETURNING *;
                """, (new_state, now, sprint_id, tile_id))

            else:
                raise HTTPException(status_code=400, detail=f"Unknown action '{action}'")

            updated_row = dict(cur.fetchone())

            # Log transition event in tile_events
            cur.execute("""
                INSERT INTO tile_events (
                    sprint_id, tile_id, osm_uid, from_state, to_state, reason, note, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
            """, (
                sprint_id,
                tile_id,
                user_uid,
                from_state,
                updated_row["state"],
                payload.reason,
                payload.note,
                now
            ))

            return row_to_tile_dict(updated_row)


@router.get("/{slug}/maproulette")
def export_maproulette_challenge(
    slug: str,
    conn=Depends(get_db),
):
    """
    Exports sprint tiles as a MapRoulette challenge GeoJSON FeatureCollection.
    Each task corresponds to an unvalidated tile with instruction and boundary.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM sprints WHERE slug = %s;", (slug,))
        s_row = cur.fetchone()
        if not s_row:
            raise HTTPException(status_code=404, detail="Sprint not found.")
        sprint = dict(s_row)
        sprint_id = sprint["id"]

        cur.execute("""
            SELECT tile_id, bbox, state, workload, mapped_by
            FROM sprint_tiles
            WHERE sprint_id = %s AND state NOT IN ('validated', 'skipped')
            ORDER BY workload DESC, tile_id ASC;
        """, (sprint_id,))
        tiles = cur.fetchall()

        features = []
        for r in tiles:
            t = dict(r)
            min_lon, min_lat, max_lon, max_lat = t["bbox"]
            poly_coords = [[
                [min_lon, min_lat],
                [max_lon, min_lat],
                [max_lon, max_lat],
                [min_lon, max_lat],
                [min_lon, min_lat],
            ]]
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": poly_coords,
                },
                "properties": {
                    "taskIdentifier": f"{slug}_{t['tile_id'].replace(':', '_')}",
                    "instruction": f"Review, map or validate places of worship in tile {t['tile_id']}. Hashtag: {sprint['hashtag']}",
                    "sprint": slug,
                    "tile_id": t["tile_id"],
                    "state": t["state"],
                    "workload": t["workload"],
                }
            })

        return {
            "type": "FeatureCollection",
            "name": f"manara_{slug}",
            "features": features
        }
