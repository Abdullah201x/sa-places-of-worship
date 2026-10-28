import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone
from fastapi import Cookie, Depends, Header, HTTPException, Request, Response, status
from app.database import get_db

SESSION_COOKIE_SECURE = "__Host-manara_session"
SESSION_COOKIE_DEV = "manara_session"
SESSION_DURATION_DAYS = 30

ALLOWED_ORIGINS = {
    "https://manara.saudiosm.org",
    "http://localhost:8000",
    "https://localhost:8000",
    "http://127.0.0.1:8000",
    "https://127.0.0.1:8000",
}


def get_admin_uids() -> set[int]:
    raw = os.environ.get("MANARA_ADMIN_UIDS", "")
    uids = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            uids.add(int(part))
    return uids


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_session_token() -> str:
    return secrets.token_hex(32)


def set_session_cookie(response: Response, request: Request, raw_token: str):
    is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    cookie_name = SESSION_COOKIE_SECURE if is_https else SESSION_COOKIE_DEV
    max_age = SESSION_DURATION_DAYS * 86400

    response.set_cookie(
        key=cookie_name,
        value=raw_token,
        max_age=max_age,
        expires=datetime.now(timezone.utc) + timedelta(days=SESSION_DURATION_DAYS),
        path="/",
        secure=is_https,
        httponly=True,
        samesite="lax",
    )


def clear_session_cookie(response: Response, request: Request):
    is_https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    for name in [SESSION_COOKIE_SECURE, SESSION_COOKIE_DEV]:
        response.delete_cookie(
            key=name,
            path="/",
            secure=is_https if name == SESSION_COOKIE_SECURE else False,
            httponly=True,
            samesite="lax",
        )


def verify_csrf(request: Request):
    """
    Enforce CSRF protection on state-changing requests.
    Requires Origin matching allowed host and header X-Manara-CSRF: 1.
    """
    csrf_header = request.headers.get("x-manara-csrf")
    if csrf_header not in ("1", "true", "True"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing or invalid X-Manara-CSRF header.",
        )

    origin = request.headers.get("origin")
    # If Origin header is present, validate against allowlist
    if origin and origin.rstrip("/") not in ALLOWED_ORIGINS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Forbidden cross-origin request from {origin}.",
        )


def get_token_from_request(request: Request) -> str | None:
    return request.cookies.get(SESSION_COOKIE_SECURE) or request.cookies.get(SESSION_COOKIE_DEV)


def get_current_user(request: Request, conn=Depends(get_db)) -> dict:
    raw_token = get_token_from_request(request)
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    token_h = hash_token(raw_token)
    now = datetime.now(timezone.utc)

    with conn.cursor() as cur:
        cur.execute("""
            SELECT s.token_hash, s.osm_uid, s.expires_at, s.last_seen_at,
                   u.display_name, u.avatar_url, u.osm_changesets,
                   u.osm_account_created, u.leaderboard_opt_in, u.is_admin
            FROM sessions s
            JOIN users u ON u.osm_uid = s.osm_uid
            WHERE s.token_hash = %s AND s.expires_at > %s;
        """, (token_h, now))
        row = cur.fetchone()

        if not row:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Session invalid or expired.",
            )

        user = dict(row)

        # Update last_seen_at and slide expiration if last seen > 1 hour ago
        last_seen = user.get("last_seen_at")
        if not last_seen or (now - last_seen) > timedelta(hours=1):
            new_expires = now + timedelta(days=SESSION_DURATION_DAYS)
            cur.execute("""
                UPDATE sessions
                SET last_seen_at = %s, expires_at = %s
                WHERE token_hash = %s;
            """, (now, new_expires, token_h))

    return user


def get_optional_user(request: Request, conn=Depends(get_db)) -> dict | None:
    try:
        return get_current_user(request, conn)
    except HTTPException:
        return None


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if not user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required.",
        )
    return user

