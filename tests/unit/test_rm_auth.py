"""
Unit tests for app.services.rm_auth

External dependencies are mocked:
  - httpx.AsyncClient   — via pytest-httpx fixture
  - Redis               — AsyncMock
  - AsyncSession        — MagicMock with AsyncMock for async methods
  - retrieve_credentials — patched directly to decouple from the credentials service
"""

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from cryptography.fernet import Fernet

from app.schemas.errors import ErrorCode
from app.services.credentials import CredentialMissingError, PlaintextCredentials
from app.services.rm_auth import (
    RMAuthError,
    _redis_key,
    clear_rm_token,
    deauth_rm_token,
    get_rm_token,
    rm_call_with_auth_retry,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEST_MASTER_KEY = Fernet.generate_key().decode()
COMPANY_ID = uuid.uuid4()
CORPID = "testcorp"
PLAIN_TOKEN = "valid-rm-token-abc123"
LOCATION_ID = "rm-loc-42"
AUTH_URL = f"https://{CORPID}.api.rentmanager.com/Authentication/AuthorizeUser"
DEAUTH_URL = f"https://{CORPID}.api.rentmanager.com/Authentication/Deauthorize"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _master_key_patch():
    """Inject the test Fernet master key into the encryption service."""
    return patch(
        "app.services.encryption.get_settings",
        return_value=type("S", (), {"fernet_master_key": TEST_MASTER_KEY})(),
    )


def _db_result(value):
    """Wrap a scalar value in a mock db.execute() result."""
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _encrypt(value: str) -> str:
    """Encrypt value using the test master key (mirrors what the service stores)."""
    with _master_key_patch():
        from app.services.encryption import encrypt_credential
        return encrypt_credential(COMPANY_ID, value)


def _mock_response(
    status_code: int = 200,
    remaining: int | None = None,
    reset_time: float | None = None,
) -> MagicMock:
    """
    Build a mock httpx.Response with a real dict for headers so that
    response.headers.get(...) behaves correctly.
    """
    headers: dict[str, str] = {}
    if remaining is not None:
        headers["x-ratelimit-remaining"] = str(remaining)
    if reset_time is not None:
        headers["x-ratelimit-resettime"] = str(reset_time)
    return MagicMock(status_code=status_code, headers=headers)


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.set = AsyncMock(return_value=True)
    redis.delete = AsyncMock(return_value=1)
    return redis


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.execute = AsyncMock()
    db.flush = AsyncMock()
    db.delete = AsyncMock()
    # db.add is sync in SQLAlchemy — left as plain MagicMock
    return db


# ---------------------------------------------------------------------------
# _redis_key
# ---------------------------------------------------------------------------

def test_redis_key_format():
    cid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    assert _redis_key(cid) == f"rm_token:{cid}"


# ---------------------------------------------------------------------------
# get_rm_token — Redis cache hit
# ---------------------------------------------------------------------------

async def test_get_rm_token_redis_hit_returns_token(mock_db, mock_redis):
    """Token returned directly from Redis — no DB or RM API calls."""
    mock_redis.get.return_value = _encrypt(PLAIN_TOKEN)

    with _master_key_patch():
        token = await get_rm_token(mock_db, COMPANY_ID, mock_redis)

    assert token == PLAIN_TOKEN
    mock_db.execute.assert_not_called()


async def test_get_rm_token_redis_hit_uses_namespaced_key(mock_db, mock_redis):
    """Redis lookup uses the correct rm_token:{company_id} key."""
    mock_redis.get.return_value = _encrypt(PLAIN_TOKEN)

    with _master_key_patch():
        await get_rm_token(mock_db, COMPANY_ID, mock_redis)

    mock_redis.get.assert_called_once_with(_redis_key(COMPANY_ID))


# ---------------------------------------------------------------------------
# get_rm_token — DB fallback
# ---------------------------------------------------------------------------

async def test_get_rm_token_db_hit_returns_token(mock_db, mock_redis):
    """Redis miss, valid (non-expired) DB row → token returned."""
    encrypted = _encrypt(PLAIN_TOKEN)
    mock_redis.get.return_value = None

    token_row = MagicMock(
        token_encrypted=encrypted,
        expires_at=datetime.now(timezone.utc) + timedelta(hours=10),
    )
    mock_db.execute.return_value = _db_result(token_row)

    with _master_key_patch():
        token = await get_rm_token(mock_db, COMPANY_ID, mock_redis)

    assert token == PLAIN_TOKEN


async def test_get_rm_token_db_hit_repopulates_redis(mock_db, mock_redis):
    """DB hit repopulates Redis with the remaining TTL so the next call is a cache hit."""
    encrypted = _encrypt(PLAIN_TOKEN)
    mock_redis.get.return_value = None

    expires_at = datetime.now(timezone.utc) + timedelta(hours=5)
    token_row = MagicMock(token_encrypted=encrypted, expires_at=expires_at)
    mock_db.execute.return_value = _db_result(token_row)

    with _master_key_patch():
        await get_rm_token(mock_db, COMPANY_ID, mock_redis)

    mock_redis.set.assert_called_once()
    key = mock_redis.set.call_args.args[0]
    value = mock_redis.set.call_args.args[1]
    ttl = mock_redis.set.call_args.kwargs["ex"]
    assert key == _redis_key(COMPANY_ID)
    assert value == encrypted
    # Remaining TTL should be ~5 hours (10-second tolerance for test execution)
    assert abs(ttl - 5 * 3600) < 10


async def test_get_rm_token_db_expired_falls_through(mock_db, mock_redis, httpx_mock):
    """Expired DB token falls through to a fresh RM API fetch."""
    mock_redis.get.return_value = None
    httpx_mock.add_response(status_code=200, text=f'"{PLAIN_TOKEN}"')

    expired_row = MagicMock(
        token_encrypted=_encrypt("old-token"),
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    mock_db.execute.side_effect = [
        _db_result(expired_row),  # rm_auth_tokens check → expired, skip
        _db_result(CORPID),       # corpid query
        _db_result(None),         # _persist_token upsert check
    ]

    with _master_key_patch(), \
         patch("app.services.rm_auth.retrieve_credentials",
               AsyncMock(return_value=PlaintextCredentials("u", "p"))):
        token = await get_rm_token(mock_db, COMPANY_ID, mock_redis)

    assert token == PLAIN_TOKEN
    assert len(httpx_mock.get_requests()) == 1


# ---------------------------------------------------------------------------
# get_rm_token — Fresh fetch from RM API
# ---------------------------------------------------------------------------

async def test_get_rm_token_fresh_fetch_returns_token(mock_db, mock_redis, httpx_mock):
    """No Redis, no DB token — fetches fresh token from RM API."""
    mock_redis.get.return_value = None
    httpx_mock.add_response(status_code=200, text=f'"{PLAIN_TOKEN}"')

    mock_db.execute.side_effect = [
        _db_result(None),    # rm_auth_tokens: miss
        _db_result(CORPID),  # corpid
        _db_result(None),    # _persist_token upsert check
    ]

    with _master_key_patch(), \
         patch("app.services.rm_auth.retrieve_credentials",
               AsyncMock(return_value=PlaintextCredentials("rmuser", "rmpass"))):
        token = await get_rm_token(mock_db, COMPANY_ID, mock_redis)

    assert token == PLAIN_TOKEN


async def test_get_rm_token_posts_to_correct_url(mock_db, mock_redis, httpx_mock):
    """Auth POST targets {corpid}.api.rentmanager.com/Authentication/AuthorizeUser."""
    mock_redis.get.return_value = None
    httpx_mock.add_response(status_code=200, text=f'"{PLAIN_TOKEN}"')

    mock_db.execute.side_effect = [
        _db_result(None),
        _db_result(CORPID),
        _db_result(None),
    ]

    with _master_key_patch(), \
         patch("app.services.rm_auth.retrieve_credentials",
               AsyncMock(return_value=PlaintextCredentials("u", "p"))):
        await get_rm_token(mock_db, COMPANY_ID, mock_redis)

    request = httpx_mock.get_requests()[0]
    assert str(request.url) == AUTH_URL


async def test_get_rm_token_posts_username_and_password_only(mock_db, mock_redis, httpx_mock):
    """Auth body contains UserName and Password — no LocationID (one token per company)."""
    mock_redis.get.return_value = None
    httpx_mock.add_response(status_code=200, text=f'"{PLAIN_TOKEN}"')

    mock_db.execute.side_effect = [
        _db_result(None),
        _db_result(CORPID),
        _db_result(None),
    ]

    with _master_key_patch(), \
         patch("app.services.rm_auth.retrieve_credentials",
               AsyncMock(return_value=PlaintextCredentials("myuser", "mypass"))):
        await get_rm_token(mock_db, COMPANY_ID, mock_redis)

    body = json.loads(httpx_mock.get_requests()[0].content)
    assert body["UserName"] == "myuser"
    assert body["Password"] == "mypass"
    assert "LocationID" not in body


async def test_get_rm_token_strips_surrounding_quotes(mock_db, mock_redis, httpx_mock):
    """RM wraps the token in double-quotes — they are stripped before returning."""
    mock_redis.get.return_value = None
    httpx_mock.add_response(status_code=200, text='"the-real-token"')

    mock_db.execute.side_effect = [
        _db_result(None),
        _db_result(CORPID),
        _db_result(None),
    ]

    with _master_key_patch(), \
         patch("app.services.rm_auth.retrieve_credentials",
               AsyncMock(return_value=PlaintextCredentials("u", "p"))):
        token = await get_rm_token(mock_db, COMPANY_ID, mock_redis)

    assert token == "the-real-token"


async def test_get_rm_token_stores_encrypted_token_in_redis(mock_db, mock_redis, httpx_mock):
    """After fresh fetch the encrypted token is written to Redis with a 20 h TTL."""
    mock_redis.get.return_value = None
    httpx_mock.add_response(status_code=200, text=f'"{PLAIN_TOKEN}"')

    mock_db.execute.side_effect = [
        _db_result(None),
        _db_result(CORPID),
        _db_result(None),
    ]

    with _master_key_patch(), \
         patch("app.services.rm_auth.retrieve_credentials",
               AsyncMock(return_value=PlaintextCredentials("u", "p"))):
        await get_rm_token(mock_db, COMPANY_ID, mock_redis)

    mock_redis.set.assert_called_once()
    key = mock_redis.set.call_args.args[0]
    stored_value = mock_redis.set.call_args.args[1]
    ttl = mock_redis.set.call_args.kwargs["ex"]
    assert key == _redis_key(COMPANY_ID)
    assert stored_value != PLAIN_TOKEN   # never stored in plaintext
    assert ttl == 20 * 3600


async def test_get_rm_token_inserts_new_db_row_on_fresh_fetch(mock_db, mock_redis, httpx_mock):
    """When no rm_auth_tokens row exists, a new one is added and flushed."""
    mock_redis.get.return_value = None
    httpx_mock.add_response(status_code=200, text=f'"{PLAIN_TOKEN}"')

    mock_db.execute.side_effect = [
        _db_result(None),
        _db_result(CORPID),
        _db_result(None),   # No existing row → insert
    ]

    with _master_key_patch(), \
         patch("app.services.rm_auth.retrieve_credentials",
               AsyncMock(return_value=PlaintextCredentials("u", "p"))):
        await get_rm_token(mock_db, COMPANY_ID, mock_redis)

    mock_db.add.assert_called_once()
    mock_db.flush.assert_called()


async def test_get_rm_token_updates_existing_db_row_in_place(mock_db, mock_redis, httpx_mock):
    """When an rm_auth_tokens row already exists, it is updated — no new insert."""
    mock_redis.get.return_value = None
    httpx_mock.add_response(status_code=200, text=f'"{PLAIN_TOKEN}"')

    existing_row = MagicMock()
    mock_db.execute.side_effect = [
        _db_result(None),           # initial rm_auth_tokens check → no valid token
        _db_result(CORPID),
        _db_result(existing_row),   # _persist_token finds existing row → update
    ]

    with _master_key_patch(), \
         patch("app.services.rm_auth.retrieve_credentials",
               AsyncMock(return_value=PlaintextCredentials("u", "p"))):
        await get_rm_token(mock_db, COMPANY_ID, mock_redis)

    mock_db.add.assert_not_called()
    assert existing_row.token_encrypted is not None
    assert existing_row.expires_at is not None


# ---------------------------------------------------------------------------
# get_rm_token — Error cases
# ---------------------------------------------------------------------------

async def test_get_rm_token_no_corpid_raises_credential_missing(mock_db, mock_redis):
    """CREDENTIAL_MISSING raised when rm_credentials has no corpid for this company."""
    mock_redis.get.return_value = None
    mock_db.execute.side_effect = [
        _db_result(None),  # rm_auth_tokens miss
        _db_result(None),  # corpid → not found
    ]

    with pytest.raises(RMAuthError) as exc_info:
        await get_rm_token(mock_db, COMPANY_ID, mock_redis)

    assert exc_info.value.error_code == ErrorCode.CREDENTIAL_MISSING


async def test_get_rm_token_no_credentials_raises_credential_missing(mock_db, mock_redis):
    """CREDENTIAL_MISSING raised when retrieve_credentials finds no row."""
    mock_redis.get.return_value = None
    mock_db.execute.side_effect = [
        _db_result(None),
        _db_result(CORPID),
    ]

    with patch("app.services.rm_auth.retrieve_credentials",
               AsyncMock(side_effect=CredentialMissingError("no creds"))), \
         pytest.raises(RMAuthError) as exc_info:
        await get_rm_token(mock_db, COMPANY_ID, mock_redis)

    assert exc_info.value.error_code == ErrorCode.CREDENTIAL_MISSING


async def test_get_rm_token_rm_non_200_raises_auth_failed(mock_db, mock_redis, httpx_mock):
    """RM_AUTH_FAILED raised when RM returns a non-200 status."""
    mock_redis.get.return_value = None
    httpx_mock.add_response(status_code=401, text="Unauthorized")

    mock_db.execute.side_effect = [
        _db_result(None),
        _db_result(CORPID),
    ]

    with patch("app.services.rm_auth.retrieve_credentials",
               AsyncMock(return_value=PlaintextCredentials("u", "p"))), \
         pytest.raises(RMAuthError) as exc_info:
        await get_rm_token(mock_db, COMPANY_ID, mock_redis)

    assert exc_info.value.error_code == ErrorCode.RM_AUTH_FAILED


async def test_get_rm_token_empty_token_raises_auth_failed(mock_db, mock_redis, httpx_mock):
    """RM_AUTH_FAILED raised when RM returns an empty quoted string."""
    mock_redis.get.return_value = None
    httpx_mock.add_response(status_code=200, text='""')

    mock_db.execute.side_effect = [
        _db_result(None),
        _db_result(CORPID),
    ]

    with patch("app.services.rm_auth.retrieve_credentials",
               AsyncMock(return_value=PlaintextCredentials("u", "p"))), \
         pytest.raises(RMAuthError) as exc_info:
        await get_rm_token(mock_db, COMPANY_ID, mock_redis)

    assert exc_info.value.error_code == ErrorCode.RM_AUTH_FAILED


async def test_get_rm_token_corrupted_redis_falls_through_to_fetch(mock_db, mock_redis, httpx_mock):
    """Corrupted Redis value (invalid ciphertext) falls through to a fresh fetch."""
    mock_redis.get.return_value = "not-a-valid-fernet-token"
    httpx_mock.add_response(status_code=200, text=f'"{PLAIN_TOKEN}"')

    mock_db.execute.side_effect = [
        _db_result(None),
        _db_result(CORPID),
        _db_result(None),
    ]

    with _master_key_patch(), \
         patch("app.services.rm_auth.retrieve_credentials",
               AsyncMock(return_value=PlaintextCredentials("u", "p"))):
        token = await get_rm_token(mock_db, COMPANY_ID, mock_redis)

    assert token == PLAIN_TOKEN
    assert len(httpx_mock.get_requests()) == 1


async def test_get_rm_token_corrupted_db_token_falls_through_to_fetch(
    mock_db, mock_redis, httpx_mock
):
    """Corrupted DB token (invalid ciphertext) falls through to a fresh fetch."""
    mock_redis.get.return_value = None
    httpx_mock.add_response(status_code=200, text=f'"{PLAIN_TOKEN}"')

    corrupted_row = MagicMock(
        token_encrypted="not-a-valid-fernet-token",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=10),
    )
    mock_db.execute.side_effect = [
        _db_result(corrupted_row),
        _db_result(CORPID),
        _db_result(None),
    ]

    with _master_key_patch(), \
         patch("app.services.rm_auth.retrieve_credentials",
               AsyncMock(return_value=PlaintextCredentials("u", "p"))):
        token = await get_rm_token(mock_db, COMPANY_ID, mock_redis)

    assert token == PLAIN_TOKEN
    assert len(httpx_mock.get_requests()) == 1


# ---------------------------------------------------------------------------
# clear_rm_token
# ---------------------------------------------------------------------------

async def test_clear_rm_token_deletes_redis_key(mock_db, mock_redis):
    mock_db.execute.return_value = _db_result(None)

    await clear_rm_token(COMPANY_ID, mock_redis, mock_db)

    mock_redis.delete.assert_called_once_with(_redis_key(COMPANY_ID))


async def test_clear_rm_token_deletes_existing_db_row(mock_db, mock_redis):
    token_row = MagicMock()
    mock_db.execute.return_value = _db_result(token_row)

    await clear_rm_token(COMPANY_ID, mock_redis, mock_db)

    mock_db.delete.assert_called_once_with(token_row)
    mock_db.flush.assert_called_once()


async def test_clear_rm_token_no_db_row_is_silent(mock_db, mock_redis):
    """clear_rm_token does not raise and does not call db.delete when no row exists."""
    mock_db.execute.return_value = _db_result(None)

    await clear_rm_token(COMPANY_ID, mock_redis, mock_db)  # Must not raise

    mock_db.delete.assert_not_called()
    mock_db.flush.assert_not_called()


# ---------------------------------------------------------------------------
# deauth_rm_token
# ---------------------------------------------------------------------------

async def test_deauth_rm_token_calls_deauthorize_endpoint(mock_db, mock_redis, httpx_mock):
    """POST /Authentication/Deauthorize?token={token} is called with the correct URL."""
    httpx_mock.add_response(method="POST", status_code=200)

    mock_db.execute.side_effect = [
        _db_result(CORPID),   # _get_corpid
        _db_result(None),     # clear_rm_token DB query
    ]

    await deauth_rm_token(mock_db, COMPANY_ID, mock_redis, PLAIN_TOKEN)

    request = httpx_mock.get_requests()[0]
    assert "Deauthorize" in str(request.url)
    assert f"token={PLAIN_TOKEN}" in str(request.url)


async def test_deauth_rm_token_clears_local_cache(mock_db, mock_redis, httpx_mock):
    """Redis and DB token are cleared after a successful deauth call."""
    httpx_mock.add_response(method="POST", status_code=200)

    token_row = MagicMock()
    mock_db.execute.side_effect = [
        _db_result(CORPID),      # _get_corpid
        _db_result(token_row),   # clear_rm_token DB query
    ]

    await deauth_rm_token(mock_db, COMPANY_ID, mock_redis, PLAIN_TOKEN)

    mock_redis.delete.assert_called_once_with(_redis_key(COMPANY_ID))
    mock_db.delete.assert_called_once_with(token_row)


async def test_deauth_rm_token_no_corpid_still_clears_cache(mock_db, mock_redis):
    """If no corpid exists (offboarded company), local cache is still cleared."""
    mock_db.execute.side_effect = [
        _db_result(None),  # _get_corpid → not found
        _db_result(None),  # clear_rm_token DB query → no row
    ]

    await deauth_rm_token(mock_db, COMPANY_ID, mock_redis, PLAIN_TOKEN)  # Must not raise

    mock_redis.delete.assert_called_once_with(_redis_key(COMPANY_ID))


async def test_deauth_rm_token_rm_failure_still_clears_cache(mock_db, mock_redis, httpx_mock):
    """If the RM API call fails, local cache is still cleared."""
    httpx_mock.add_exception(httpx.ConnectError("connection refused"))

    token_row = MagicMock()
    mock_db.execute.side_effect = [
        _db_result(CORPID),      # _get_corpid
        _db_result(token_row),   # clear_rm_token DB query
    ]

    await deauth_rm_token(mock_db, COMPANY_ID, mock_redis, PLAIN_TOKEN)  # Must not raise

    mock_redis.delete.assert_called_once_with(_redis_key(COMPANY_ID))
    mock_db.delete.assert_called_once_with(token_row)


async def test_deauth_rm_token_unexpected_status_still_clears_cache(mock_db, mock_redis, httpx_mock):
    """A non-200/204 deauth response is logged but cache is still cleared."""
    httpx_mock.add_response(method="POST", status_code=500)

    mock_db.execute.side_effect = [
        _db_result(CORPID),
        _db_result(None),
    ]

    await deauth_rm_token(mock_db, COMPANY_ID, mock_redis, PLAIN_TOKEN)  # Must not raise

    mock_redis.delete.assert_called_once_with(_redis_key(COMPANY_ID))


# ---------------------------------------------------------------------------
# rm_call_with_auth_retry — location_id
# ---------------------------------------------------------------------------

async def test_rm_call_passes_location_id_to_make_call(mock_db, mock_redis):
    """make_call receives both the token and location_id as positional arguments."""
    mock_redis.get.return_value = _encrypt(PLAIN_TOKEN)

    received: list[tuple[str, str]] = []

    async def make_call(token: str, loc_id: str) -> MagicMock:
        received.append((token, loc_id))
        return _mock_response(200)

    with _master_key_patch():
        await rm_call_with_auth_retry(mock_db, COMPANY_ID, mock_redis, LOCATION_ID, make_call)

    assert received == [(PLAIN_TOKEN, LOCATION_ID)]


# ---------------------------------------------------------------------------
# rm_call_with_auth_retry — happy path and 401
# ---------------------------------------------------------------------------

async def test_rm_call_no_401_returns_response_and_calls_once(mock_db, mock_redis):
    """Happy path: RM returns 200 — response returned, make_call invoked once."""
    mock_redis.get.return_value = _encrypt(PLAIN_TOKEN)

    ok_response = _mock_response(200)
    make_call = AsyncMock(return_value=ok_response)

    with _master_key_patch():
        response = await rm_call_with_auth_retry(
            mock_db, COMPANY_ID, mock_redis, LOCATION_ID, make_call
        )

    assert response.status_code == 200
    make_call.assert_called_once_with(PLAIN_TOKEN, LOCATION_ID)


async def test_rm_call_passes_decrypted_plain_token(mock_db, mock_redis):
    """make_call receives the decrypted plaintext token, not the encrypted form."""
    mock_redis.get.return_value = _encrypt(PLAIN_TOKEN)

    captured: list[str] = []

    async def make_call(token: str, loc_id: str) -> MagicMock:
        captured.append(token)
        return _mock_response(200)

    with _master_key_patch():
        await rm_call_with_auth_retry(mock_db, COMPANY_ID, mock_redis, LOCATION_ID, make_call)

    assert captured == [PLAIN_TOKEN]


async def test_rm_call_retries_on_401_and_uses_new_token(mock_db, mock_redis, httpx_mock):
    """On 401: cached token cleared, re-authenticated, make_call retried with new token."""
    new_token = "brand-new-token-xyz"
    encrypted_initial = _encrypt(PLAIN_TOKEN)

    # First get_rm_token → Redis hit with old token
    # After clear, second get_rm_token → Redis miss → DB miss → fresh RM fetch
    mock_redis.get.side_effect = [encrypted_initial, None]
    httpx_mock.add_response(status_code=200, text=f'"{new_token}"')

    mock_db.execute.side_effect = [
        _db_result(MagicMock()),  # clear_rm_token: existing DB row → delete it
        _db_result(None),         # 2nd get_rm_token: rm_auth_tokens miss
        _db_result(CORPID),       # 2nd get_rm_token: corpid
        _db_result(None),         # 2nd get_rm_token: _persist_token upsert
    ]

    response_401 = _mock_response(401)
    response_ok = _mock_response(200)
    make_call = AsyncMock(side_effect=[response_401, response_ok])

    with _master_key_patch(), \
         patch("app.services.rm_auth.retrieve_credentials",
               AsyncMock(return_value=PlaintextCredentials("u", "p"))):
        response = await rm_call_with_auth_retry(
            mock_db, COMPANY_ID, mock_redis, LOCATION_ID, make_call
        )

    assert response.status_code == 200
    assert make_call.call_count == 2
    make_call.assert_called_with(new_token, LOCATION_ID)   # second call used the new token


async def test_rm_call_does_not_retry_more_than_once(mock_db, mock_redis, httpx_mock):
    """If the retry also 401s, return it as-is — make_call called exactly twice."""
    encrypted = _encrypt(PLAIN_TOKEN)
    mock_redis.get.side_effect = [encrypted, None]
    httpx_mock.add_response(status_code=200, text=f'"{PLAIN_TOKEN}"')

    mock_db.execute.side_effect = [
        _db_result(None),    # clear_rm_token: no DB row
        _db_result(None),    # 2nd get_rm_token: rm_auth_tokens miss
        _db_result(CORPID),  # 2nd get_rm_token: corpid
        _db_result(None),    # 2nd get_rm_token: _persist_token upsert
    ]

    always_401 = _mock_response(401)
    make_call = AsyncMock(return_value=always_401)

    with _master_key_patch(), \
         patch("app.services.rm_auth.retrieve_credentials",
               AsyncMock(return_value=PlaintextCredentials("u", "p"))):
        response = await rm_call_with_auth_retry(
            mock_db, COMPANY_ID, mock_redis, LOCATION_ID, make_call
        )

    assert response.status_code == 401
    assert make_call.call_count == 2   # tried exactly twice, never three times


# ---------------------------------------------------------------------------
# rm_call_with_auth_retry — rate limiting
# ---------------------------------------------------------------------------

async def test_rm_call_logs_rate_limit_remaining(mock_db, mock_redis):
    """x-ratelimit-remaining is consumed without sleeping when > 0."""
    mock_redis.get.return_value = _encrypt(PLAIN_TOKEN)

    make_call = AsyncMock(return_value=_mock_response(200, remaining=42))

    with _master_key_patch(), \
         patch("app.services.rm_auth.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        response = await rm_call_with_auth_retry(
            mock_db, COMPANY_ID, mock_redis, LOCATION_ID, make_call
        )

    assert response.status_code == 200
    mock_sleep.assert_not_called()
    make_call.assert_called_once_with(PLAIN_TOKEN, LOCATION_ID)


async def test_rm_call_no_rate_limit_header_skips_wait(mock_db, mock_redis):
    """Responses without x-ratelimit-remaining do not trigger any sleep."""
    mock_redis.get.return_value = _encrypt(PLAIN_TOKEN)

    make_call = AsyncMock(return_value=_mock_response(200))  # no rate-limit headers

    with _master_key_patch(), \
         patch("app.services.rm_auth.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await rm_call_with_auth_retry(
            mock_db, COMPANY_ID, mock_redis, LOCATION_ID, make_call
        )

    mock_sleep.assert_not_called()


async def test_rm_call_waits_when_rate_limited_and_retries(mock_db, mock_redis):
    """
    When x-ratelimit-remaining == 0, sleeps until x-ratelimit-resettime
    and retries the call once with the same token and location_id.
    """
    mock_redis.get.return_value = _encrypt(PLAIN_TOKEN)

    # current time = 1000, reset at 1060 → sleep 60 s
    rate_limited = _mock_response(200, remaining=0, reset_time=1060.0)
    after_reset = _mock_response(200, remaining=99)
    make_call = AsyncMock(side_effect=[rate_limited, after_reset])

    with _master_key_patch(), \
         patch("app.services.rm_auth.time.time", return_value=1000.0), \
         patch("app.services.rm_auth.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        response = await rm_call_with_auth_retry(
            mock_db, COMPANY_ID, mock_redis, LOCATION_ID, make_call
        )

    assert response.status_code == 200
    mock_sleep.assert_called_once_with(60.0)
    assert make_call.call_count == 2
    make_call.assert_called_with(PLAIN_TOKEN, LOCATION_ID)


async def test_rm_call_rate_limit_sleep_duration_uses_reset_time(mock_db, mock_redis):
    """Sleep duration is max(0, resettime - now) — never negative."""
    mock_redis.get.return_value = _encrypt(PLAIN_TOKEN)

    # Reset time is already in the past → sleep 0 seconds
    rate_limited = _mock_response(200, remaining=0, reset_time=500.0)
    after_reset = _mock_response(200, remaining=99)
    make_call = AsyncMock(side_effect=[rate_limited, after_reset])

    with _master_key_patch(), \
         patch("app.services.rm_auth.time.time", return_value=1000.0), \
         patch("app.services.rm_auth.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await rm_call_with_auth_retry(
            mock_db, COMPANY_ID, mock_redis, LOCATION_ID, make_call
        )

    mock_sleep.assert_called_once_with(0.0)
