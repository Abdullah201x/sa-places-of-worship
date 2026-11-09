from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def client_key(request: Request) -> str:
    """Rate-limit bucket for a request: the visitor's IP.

    The API is only reachable through the Caddy container, which overwrites
    X-Real-IP with the visitor IP it resolved from its trusted proxy. We use
    that instead of X-Forwarded-For, whose leftmost entry a client can forge to
    get a fresh bucket on every request. Falls back to the socket address when
    the header is absent (local development, direct access).
    """
    return request.headers.get("x-real-ip", "").strip() or get_remote_address(request)


limiter = Limiter(key_func=client_key, default_limits=["120/minute"])
