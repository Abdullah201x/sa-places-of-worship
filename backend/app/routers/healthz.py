from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/api/healthz")
def healthz():
    return {"status": "ok"}
