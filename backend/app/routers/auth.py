from datetime import datetime, timezone
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.auth import (
    clear_session_cookie,
    generate_session_token,
    get_admin_uids,
    get_current_user,
    get_token_from_request,
    hash_token,
    set_session_cookie,
    verify_csrf,
)
from app.database import get_db

OSM_USER_AGENT = "Manara/1.0 (+https://manara.saudiosm.org)"
OSM_USER_DETAILS_URL = "https://api.openstreetmap.org/api/0.6/user/details.json"

router = APIRouter(tags=["auth"])
limiter = Limiter(key_func=get_remote_address)


class SessionRequest(BaseModel):
    access_token: str = Field(..., min_length=10, max_length=500)


class UpdateMeRequest(BaseModel):
    leaderboard_opt_in: bool


def _upsert_user_and_create_session(conn, osm_uid, display_name, avatar_url, osm_changesets, account_created_dt, is_admin):
    """Upserts the user and creates a session row; returns (user_row, raw_session_token)."""
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (
                    osm_uid, display_name, avatar_url, osm_changesets,
                    osm_account_created, is_admin, last_login_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (osm_uid) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    avatar_url = EXCLUDED.avatar_url,
                    osm_changesets = EXCLUDED.osm_changesets,
                    is_admin = EXCLUDED.is_admin,
                    last_login_at = NOW()
                RETURNING osm_uid, display_name, avatar_url, osm_changesets, leaderboard_opt_in, is_admin;
            """, (osm_uid, display_name, avatar_url, osm_changesets, account_created_dt, is_admin))
            user_row = dict(cur.fetchone())

            # 3. Create cryptographically secure random session
            raw_token = generate_session_token()
            token_h = hash_token(raw_token)

            cur.execute("""
                INSERT INTO sessions (token_hash, osm_uid, created_at, expires_at, last_seen_at)
                VALUES (%s, %s, NOW(), NOW() + INTERVAL '30 days', NOW());
            """, (token_h, osm_uid))
    return user_row, raw_token


@router.post("/auth/session")
@limiter.limit("10/minute")
async def create_session(
    payload: SessionRequest,
    request: Request,
    response: Response,
    _csrf: None = Depends(verify_csrf),
    conn=Depends(get_db),
):
    """
    Exchange a client-side OSM OAuth token for an HTTP-only Manara session cookie.
    Validates with OSM once, reads public profile details, and immediately discards the token.
    """
    token = payload.access_token

    # 1. Fetch user details from OSM API with strict User-Agent
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            osm_res = await client.get(
                OSM_USER_DETAILS_URL,
                headers={
                    "Authorization": f"Bearer {token}",
                    "User-Agent": OSM_USER_AGENT,
                    "Accept": "application/json",
                },
            )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not contact OpenStreetMap API: {e}",
        )

    # Clean up token reference immediately
    del token

    if osm_res.status_code == 401:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="OpenStreetMap access token is invalid or expired.",
        )
    if osm_res.status_code == 429:
        retry_after = osm_res.headers.get("Retry-After", "60")
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"OpenStreetMap rate limit exceeded. Retry after {retry_after}s.",
        )
    if osm_res.status_code != 200:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"OpenStreetMap API error: {osm_res.status_code}",
        )

    try:
        data = osm_res.json()
    except ValueError:
        data = None
    osm_user = data.get("user") if isinstance(data, dict) else None
    if not isinstance(osm_user, dict) or "id" not in osm_user:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Unexpected response structure from OpenStreetMap API.",
        )

    osm_uid = int(osm_user["id"])
    display_name = osm_user.get("display_name") or f"user_{osm_uid}"
    img = osm_user.get("img") or {}
    avatar_url = img.get("href") if isinstance(img, dict) else None
    changesets = osm_user.get("changesets") or {}
    osm_changesets = int(changesets.get("count") or 0)

    account_created_str = osm_user.get("account_created")
    account_created_dt = None
    if account_created_str:
        try:
            account_created_dt = datetime.fromisoformat(account_created_str.replace("Z", "+00:00"))
        except ValueError:
            pass

    is_admin = osm_uid in get_admin_uids()

    # 2. Upsert user and create session atomically in database. The driver is
    # synchronous, so run it in the threadpool rather than blocking the event loop.
    user_row, raw_token = await run_in_threadpool(
        _upsert_user_and_create_session,
        conn, osm_uid, display_name, avatar_url, osm_changesets, account_created_dt, is_admin,
    )

    # 4. Set HTTP-only secure cookie
    set_session_cookie(response, request, raw_token)

    return {
        "status": "ok",
        "user": user_row,
    }


@router.post("/auth/logout")
def logout(
    request: Request,
    response: Response,
    _csrf: None = Depends(verify_csrf),
    conn=Depends(get_db),
):
    """Invalidate current session and clear session cookie."""
    raw_token = get_token_from_request(request)
    if raw_token:
        token_h = hash_token(raw_token)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM sessions WHERE token_hash = %s;", (token_h,))

    clear_session_cookie(response, request)
    return {"status": "ok"}


@router.get("/api/v1/me")
def get_me(user: dict = Depends(get_current_user)):
    """Return the profile of the currently authenticated mapper."""
    return {
        "osm_uid": user["osm_uid"],
        "display_name": user["display_name"],
        "avatar_url": user["avatar_url"],
        "osm_changesets": user["osm_changesets"],
        "osm_account_created": user["osm_account_created"].isoformat() if user.get("osm_account_created") else None,
        "leaderboard_opt_in": user["leaderboard_opt_in"],
        "is_admin": user["is_admin"],
    }


@router.patch("/api/v1/me")
def update_me(
    payload: UpdateMeRequest,
    _csrf: None = Depends(verify_csrf),
    user: dict = Depends(get_current_user),
    conn=Depends(get_db),
):
    """Update settings for the current user (e.g. leaderboard opt-in)."""
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE users
            SET leaderboard_opt_in = %s
            WHERE osm_uid = %s
            RETURNING osm_uid, display_name, avatar_url, osm_changesets, leaderboard_opt_in, is_admin;
        """, (payload.leaderboard_opt_in, user["osm_uid"]))
        updated = dict(cur.fetchone())

    return {
        "status": "ok",
        "user": updated,
    }


@router.delete("/api/v1/me")
def delete_me(
    request: Request,
    response: Response,
    _csrf: None = Depends(verify_csrf),
    user: dict = Depends(get_current_user),
    conn=Depends(get_db),
):
    """
    Permanently delete the user's account and associated review marks.
    Clears session cookie.
    """
    with conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE osm_uid = %s;", (user["osm_uid"],))

    clear_session_cookie(response, request)
    return {"status": "ok", "deleted": True}

