"""
RM Authentication service.

Manages the RM API token lifecycle:
  1. Check Redis cache first (key: rm_token:{company_id})
  2. Fall back to rm_auth_tokens DB table
  3. If no valid token, fetch fresh from RM API
  4. On 401 from any RM call, clear cached token and retry once

Token storage: encrypted with the company's derived Fernet key (same HKDF
derivation as credentials). Stored tokens are never in plaintext at rest.

RM auth endpoint:
  POST https://{corpid}.api.rentmanager.com/Authentication/AuthorizeUser
  body: {"UserName": "...", "Password": "..."}  — no LocationID
  response: plain string token surrounded by double-quotes, e.g. '"abc123"'

Per-request location scoping:
  Every RM API call must include header x-rm12api-locationid: {location_id}
  This is separate from authentication — one token serves all locations.

All RM API calls use header X-RM12Api-ApiToken: {token}  (not Bearer)

Rate limiting:
  Every RM response carries x-ratelimit-remaining. When it reaches 0,
  x-ratelimit-resettime (Unix timestamp) indicates when the window resets.
  rm_call_with_auth_retry waits for that time before retrying.

Deauthorization:
  POST /Authentication/Deauthorize?token={token} — called on company offboarding
"""

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable
from uuid import UUID

import httpx
import redis.asyncio as aioredis
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth_token import RMAuthToken
from app.models.credentials import RMCredentials
from app.schemas.errors import ErrorCode
from app.services.credentials import CredentialMissingError, retrieve_credentials
from app.services.encryption import (
    CredentialDecryptionError,
    decrypt_credential,
    encrypt_credential,
)

logger = structlog.get_logger(__name__)

_TOKEN_TTL_HOURS = 20
_REDIS_KEY_PREFIX = "rm_token"
_HTTP_TIMEOUT = 300.0  # RM gateway timeout is 5 minutes


class RMAuthError(Exception):
    """Raised when RM authentication fails or required credentials are missing."""

    def __init__(self, message: str, error_code: str = ErrorCode.RM_AUTH_FAILED):
        super().__init__(message)
        self.error_code = error_code


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _redis_key(company_id: UUID) -> str:
    return f"{_REDIS_KEY_PREFIX}:{company_id}"


async def _get_corpid(db: AsyncSession, company_id: UUID) -> str:
    """Fetch the corpid from rm_credentials for this company."""
    result = await db.execute(
        select(RMCredentials.corpid).where(RMCredentials.company_id == company_id)
    )
    corpid = result.scalar_one_or_none()
    if not corpid:
        raise RMAuthError(
            f"No corpid found for company {company_id}",
            error_code=ErrorCode.CREDENTIAL_MISSING,
        )
    return corpid


async def _fetch_fresh_token(
    base_url: str,
    username: str,
    password: str,
    company_id: UUID,
) -> str:
    """
    POST to /Authentication/AuthorizeUser and return the plain token string.

    RM returns the token as a JSON-encoded bare string, e.g. '"abc123"'.
    Strip the surrounding double-quotes before returning.
    """
    url = f"{base_url}/Authentication/AuthorizeUser"
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        response = await client.post(
            url,
            json={"UserName": username, "Password": password},
        )

    if response.status_code != 200:
        raise RMAuthError(
            f"RM auth returned HTTP {response.status_code} for company {company_id}",
            error_code=ErrorCode.RM_AUTH_FAILED,
        )

    token = response.text.strip().strip('"')
    if not token:
        raise RMAuthError(
            f"RM returned an empty token for company {company_id}",
            error_code=ErrorCode.RM_AUTH_FAILED,
        )
    return token


async def _persist_token(
    db: AsyncSession,
    redis: aioredis.Redis,
    company_id: UUID,
    plain_token: str,
) -> None:
    """Encrypt and store the token in Redis (TTL 20 h) and the rm_auth_tokens table."""
    encrypted = encrypt_credential(company_id, plain_token)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=_TOKEN_TTL_HOURS)
    ttl_seconds = _TOKEN_TTL_HOURS * 3600

    await redis.set(_redis_key(company_id), encrypted, ex=ttl_seconds)

    result = await db.execute(
        select(RMAuthToken).where(RMAuthToken.company_id == company_id)
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.token_encrypted = encrypted
        existing.expires_at = expires_at
    else:
        db.add(RMAuthToken(
            company_id=company_id,
            token_encrypted=encrypted,
            expires_at=expires_at,
        ))
    await db.flush()


async def _check_rate_limit(response: httpx.Response, company_id: UUID) -> bool:
    """
    Log x-ratelimit-remaining from the response headers.

    If the limit is exhausted (== 0), read x-ratelimit-resettime (Unix timestamp),
    sleep until the window reopens, and return True so the caller can retry.
    Returns False when rate limit is not exhausted or the header is absent.
    """
    remaining_raw = response.headers.get("x-ratelimit-remaining")
    if remaining_raw is None:
        return False

    remaining = int(remaining_raw)
    logger.info("rm_rate_limit_remaining", company_id=str(company_id), remaining=remaining)

    if remaining == 0:
        reset_raw = response.headers.get("x-ratelimit-resettime")
        if reset_raw:
            sleep_secs = max(0.0, float(reset_raw) - time.time())
            logger.warning(
                "rm_rate_limit_exhausted",
                company_id=str(company_id),
                sleep_seconds=round(sleep_secs, 1),
            )
            await asyncio.sleep(sleep_secs)
            return True

    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def get_rm_token(
    db: AsyncSession,
    company_id: UUID,
    redis: aioredis.Redis,
) -> str:
    """
    Return a valid, decrypted RM API token for the given company.

    Resolution order:
      1. Redis cache (rm_token:{company_id})
      2. rm_auth_tokens DB row (if not expired)
      3. Fresh fetch from RM API

    Raises:
        RMAuthError(error_code=RM_AUTH_FAILED)     — RM API call failed
        RMAuthError(error_code=CREDENTIAL_MISSING) — no corpid or credentials found
    """
    # --- 1. Redis cache ---
    cached = await redis.get(_redis_key(company_id))
    if cached:
        try:
            return decrypt_credential(company_id, cached)
        except CredentialDecryptionError:
            logger.warning("rm_token_cache_corrupted", company_id=str(company_id))
            # Fall through to DB / re-fetch

    # --- 2. DB fallback ---
    result = await db.execute(
        select(RMAuthToken).where(RMAuthToken.company_id == company_id)
    )
    db_row = result.scalar_one_or_none()
    if db_row and db_row.expires_at > datetime.now(timezone.utc):
        try:
            plain_token = decrypt_credential(company_id, db_row.token_encrypted)
            # Repopulate Redis with the remaining TTL
            remaining = int(
                (db_row.expires_at - datetime.now(timezone.utc)).total_seconds()
            )
            if remaining > 0:
                await redis.set(
                    _redis_key(company_id), db_row.token_encrypted, ex=remaining
                )
            return plain_token
        except CredentialDecryptionError:
            logger.warning("rm_token_db_corrupted", company_id=str(company_id))
            # Fall through to re-fetch

    # --- 3. Fresh fetch ---
    corpid = await _get_corpid(db, company_id)
    base_url = f"https://{corpid}.api.rentmanager.com"

    try:
        creds = await retrieve_credentials(db, company_id)
    except CredentialMissingError:
        raise RMAuthError(
            f"No credentials found for company {company_id}",
            error_code=ErrorCode.CREDENTIAL_MISSING,
        )

    plain_token = await _fetch_fresh_token(
        base_url, creds.username, creds.password, company_id
    )
    await _persist_token(db, redis, company_id, plain_token)

    logger.info("rm_token_refreshed", company_id=str(company_id), corpid=corpid)
    return plain_token


async def clear_rm_token(
    company_id: UUID,
    redis: aioredis.Redis,
    db: AsyncSession,
) -> None:
    """
    Invalidate the cached token — delete from Redis and the rm_auth_tokens table.
    Call this on any 401 response before re-authenticating.
    """
    await redis.delete(_redis_key(company_id))

    result = await db.execute(
        select(RMAuthToken).where(RMAuthToken.company_id == company_id)
    )
    token_row = result.scalar_one_or_none()
    if token_row:
        await db.delete(token_row)
        await db.flush()


async def deauth_rm_token(
    db: AsyncSession,
    company_id: UUID,
    redis: aioredis.Redis,
    token: str,
) -> None:
    """
    Invalidate a token at the RM API level and clear the local cache.

    Calls POST /Authentication/Deauthorize?token={token} so RM can revoke it
    server-side. Used during company offboarding.

    Logs but never raises on RM API failure — local cache is always cleared
    regardless of whether the remote call succeeds.
    """
    try:
        corpid = await _get_corpid(db, company_id)
    except RMAuthError:
        logger.warning("rm_deauth_no_corpid", company_id=str(company_id))
        await clear_rm_token(company_id, redis, db)
        return

    url = f"https://{corpid}.api.rentmanager.com/Authentication/Deauthorize"
    async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT) as client:
        try:
            response = await client.post(url, params={"token": token})
            if response.status_code not in (200, 204):
                logger.warning(
                    "rm_deauth_unexpected_status",
                    company_id=str(company_id),
                    status=response.status_code,
                )
        except httpx.RequestError as exc:
            logger.warning(
                "rm_deauth_request_failed",
                company_id=str(company_id),
                error=str(exc),
            )

    await clear_rm_token(company_id, redis, db)
    logger.info("rm_token_deauthorized", company_id=str(company_id))


async def rm_call_with_auth_retry(
    db: AsyncSession,
    company_id: UUID,
    redis: aioredis.Redis,
    location_id: str,
    make_call: Callable[[str, str], Awaitable[httpx.Response]],
) -> httpx.Response:
    """
    Execute an RM API request with rate-limit handling and 401 re-authentication.

    ``make_call(token, location_id)`` is responsible for setting the required headers:
      - X-RM12Api-ApiToken: {token}
      - x-rm12api-locationid: {location_id}

    After each response:
      - x-ratelimit-remaining is logged.
      - If exhausted (== 0), sleeps until x-ratelimit-resettime and retries once.

    On 401: clears the cached token, re-authenticates, and retries once.
    If the retry also returns 401, that response is returned as-is.

    Usage::

        response = await rm_call_with_auth_retry(
            db, company_id, redis, location_id,
            lambda token, loc_id: client.get(
                url,
                headers={
                    "X-RM12Api-ApiToken": token,
                    "x-rm12api-locationid": loc_id,
                },
            ),
        )
    """
    token = await get_rm_token(db, company_id, redis)
    response = await make_call(token, location_id)
    rate_limited = await _check_rate_limit(response, company_id)

    if rate_limited:
        response = await make_call(token, location_id)
        await _check_rate_limit(response, company_id)

    if response.status_code == 401:
        logger.warning("rm_401_clearing_token_and_retrying", company_id=str(company_id))
        await clear_rm_token(company_id, redis, db)
        token = await get_rm_token(db, company_id, redis)
        response = await make_call(token, location_id)
        await _check_rate_limit(response, company_id)

    return response
