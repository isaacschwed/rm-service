from fastapi import APIRouter
from app.core.config import get_settings
from app.db.session import check_db
from app.db.redis import check_redis

router = APIRouter()


@router.get("/health", tags=["system"])
async def health_check():
    """
    Railway health check endpoint — no auth required.
    Returns 200 if all systems are operational, 503 if any are degraded.
    """
    settings = get_settings()
    db_ok = await check_db()
    redis_ok = await check_redis()

    status = "ok" if (db_ok and redis_ok) else "degraded"

    payload = {
        "status": status,
        "db": "ok" if db_ok else "error",
        "redis": "ok" if redis_ok else "error",
        "version": settings.app_version,
    }

    from fastapi.responses import JSONResponse
    status_code = 200 if status == "ok" else 503
    return JSONResponse(content=payload, status_code=status_code)
