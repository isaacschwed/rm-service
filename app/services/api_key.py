import hashlib
import secrets
from datetime import datetime, timezone

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_key import ServiceApiKey

logger = structlog.get_logger(__name__)


def hash_api_key(raw_key: str) -> str:
    """SHA-256 hash of a raw API key. This is what gets stored in the DB."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


def generate_api_key() -> str:
    """Generate a cryptographically secure raw API key. Issued exactly once."""
    return secrets.token_urlsafe(32)


async def lookup_api_key(
    db: AsyncSession, raw_key: str
) -> ServiceApiKey | None:
    """
    Look up an API key by its SHA-256 hash.
    Returns the ServiceApiKey row if found and active, None otherwise.
    Never logs or stores the raw key.
    """
    key_hash = hash_api_key(raw_key)
    result = await db.execute(
        select(ServiceApiKey).where(
            ServiceApiKey.key_hash == key_hash,
            ServiceApiKey.is_active == True,  # noqa: E712
        )
    )
    return result.scalar_one_or_none()


async def update_last_used(db: AsyncSession, key_id) -> None:
    """
    Fire-and-forget update of last_used_at.
    Called after successful auth — non-blocking best-effort.
    """
    try:
        await db.execute(
            update(ServiceApiKey)
            .where(ServiceApiKey.id == key_id)
            .values(last_used_at=datetime.now(timezone.utc))
        )
        # No commit here — handled by the request lifecycle in get_db()
    except Exception:
        # Non-critical — don't fail the request if this update fails
        logger.warning("last_used_update_failed", key_id=str(key_id))


def is_operation_permitted(api_key: ServiceApiKey, operation: str) -> bool:
    """
    Check whether a platform API key is allowed to perform a given operation.
    Empty allowed_operations = no access to anything.
    """
    return operation in (api_key.allowed_operations or [])
