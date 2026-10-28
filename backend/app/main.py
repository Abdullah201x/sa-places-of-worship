from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.database import close_pool, init_pool
from app.routers import healthz, meta, places, search, stats, suggestions

limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_pool()
    yield
    close_pool()


app = FastAPI(
    title="Manara Places of Worship Data API",
    description="Public read-only geospatial API for places of worship in Saudi Arabia",
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
    allow_methods=["GET"],
    allow_headers=["*"],
)

# Register routers
app.include_router(healthz.router)
app.include_router(meta.router)
app.include_router(places.router)
app.include_router(suggestions.router)
app.include_router(search.router)
app.include_router(stats.router)
