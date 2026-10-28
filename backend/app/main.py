from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app import database
from app.schema import init_app_tables
from app.routers import (
    auth,
    community_data,
    edits,
    healthz,
    meta,
    places,
    reviews,
    search,
    seo,
    stats,
    suggestions,
)

limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_pool()
    if database.pool is not None:
        try:
            with database.pool.connection() as conn:
                init_app_tables(conn)
                print("[INFO] Phase 4 tables initialized successfully.")
        except Exception as e:
            print(f"[WARN] Could not initialize Phase 4 tables: {e}")
    yield
    database.close_pool()


app = FastAPI(
    title="Manara Places of Worship Data API",
    description="Geospatial data, community review and SEO API for places of worship in Saudi Arabia",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS: allow same-origin and local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://manara.saudiosm.org",
        "https://localhost:8000",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
    allow_headers=["*"],
)

# Register routers
app.include_router(healthz.router)
app.include_router(auth.router)
app.include_router(reviews.router)
app.include_router(edits.router)
app.include_router(community_data.router)
app.include_router(meta.router)
app.include_router(places.router)
app.include_router(suggestions.router)
app.include_router(search.router)
app.include_router(stats.router)
app.include_router(seo.router)
