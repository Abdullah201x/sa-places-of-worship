from urllib.parse import urlparse
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


def dev_mode_enabled() -> bool:
    return os.environ.get("MANARA_DEV_MODE", "0").lower() in ("1", "true")


def is_request_https(request: Request) -> bool:
    """Check if the request originated over HTTPS, handling multi-hop reverse proxies."""
    if request.url.scheme == "https":
        return True
    proto = request.headers.get("x-forwarded-proto", "")
    return proto.split(",")[0].strip().lower() == "https"


def get_admin_uids() -> set[int]:
    raw = os.environ.get("MANARA_ADMIN_UIDS", "")
    uids = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            uids.add(int(part))
    return uids


def get_suggestions_allowlist() -> frozenset[int]:
    """
    OSM numeric user ids allowed to see Wikidata mosques that are missing from OSM
    (the "suggestions" layer). Comma-separated MANARA_SUGGESTIONS_ALLOWLIST; unset or
    empty means nobody. Read on every call so a redeploy is the only step to change it.
    Non-numeric entries are ignored: usernames are mutable, only the uid is trusted.
    Deliberately separate from MANARA_ADMIN_UIDS, so being an admin does not grant it.
    """
    uids = set()
    for part in os.environ.get("MANARA_SUGGESTIONS_ALLOWLIST", "").split(","):
        part = part.strip()
        if part.isdigit():
            uids.add(int(part))
    return frozenset(uids)


def can_view_suggestions(user: dict | None) -> bool:
    return bool(user) and user.get("osm_uid") in get_suggestions_allowlist()


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_session_token() -> str:
    return secrets.token_hex(32)


def set_session_cookie(response: Response, request: Request, raw_token: str):
    is_https = is_request_https(request)
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
    is_https = is_request_https(request)
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
    Requires header X-Manara-CSRF: 1 AND Origin matching allowed host (or Referer check when Origin omitted).
    """
    csrf_header = request.headers.get("x-manara-csrf")
    if csrf_header not in ("1", "true", "True"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing or invalid X-Manara-CSRF header.",
        )

    origin = request.headers.get("origin")
    if origin:
        if origin.rstrip("/") not in ALLOWED_ORIGINS:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden cross-origin request from {origin}.",
            )
    else:
        referer = request.headers.get("referer")
        if referer:
            parsed = urlparse(referer)
            ref_origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
            if ref_origin and ref_origin not in ALLOWED_ORIGINS:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Forbidden cross-origin request from {referer}.",
                )


def get_token_from_request(request: Request) -> str | None:
    is_https = is_request_https(request)
    if is_https:
        return request.cookies.get(SESSION_COOKIE_SECURE)
    if dev_mode_enabled() or request.url.scheme == "http":
        return request.cookies.get(SESSION_COOKIE_SECURE) or request.cookies.get(SESSION_COOKIE_DEV)
    return request.cookies.get(SESSION_COOKIE_SECURE)


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
        user["is_admin"] = bool(user.get("is_admin")) or (user["osm_uid"] in get_admin_uids())

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
    admin_uids = get_admin_uids()
    is_admin = bool(user.get("is_admin")) or (user.get("osm_uid") in admin_uids)
    if not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required.",
        )
    return user


def require_suggestions_access(user: dict = Depends(get_current_user)) -> dict:
    if not can_view_suggestions(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not on the Wikidata suggestions allowlist.",
        )
    return user
