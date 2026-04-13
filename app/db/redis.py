import redis.asyncio as aioredis
from app.core.config import get_settings

_redis_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    """Return the shared Redis client. Must call init_redis() first."""
    if _redis_client is None:
        raise RuntimeError("Redis not initialized. Call init_redis() on startup.")
    return _redis_client


async def init_redis() -> aioredis.Redis:
    """Create the Redis connection pool. Called once on app startup."""
    global _redis_client
    settings = get_settings()
    _redis_client = aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
        max_connections=20,
    )
    await _redis_client.ping()  # Fail fast if Redis is unreachable
    return _redis_client


async def close_redis() -> None:
    """Close the Redis connection pool. Called on app shutdown."""
    global _redis_client
    if _redis_client:
        await _redis_client.aclose()
        _redis_client = None


async def check_redis() -> bool:
    """Health check — returns True if Redis is reachable."""
    try:
        client = get_redis()
        await client.ping()
        return True
    except Exception:
        return False
