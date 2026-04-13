"""
Integration tests for the auth dependency (require_auth).
Uses a real FastAPI test client with a mock endpoint.
DB lookup is mocked — no live DB required.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from app.core.auth import AuthContext, require_auth, require_admin
from app.main import app
from app.models.api_key import ServiceApiKey
from app.services.api_key import hash_api_key

# ---------------------------------------------------------------------------
# Test endpoint wired into the app for testing only
# ---------------------------------------------------------------------------

TEST_OPERATION = "post_payment"
TEST_ROUTE = "/test/auth-check"
TEST_ADMIN_ROUTE = "/test/admin-check"


@app.get(TEST_ROUTE)
async def _test_auth_endpoint(auth: AuthContext = Depends(require_auth(TEST_OPERATION))):
    return {"platform": auth.platform, "ok": True}


@app.get(TEST_ADMIN_ROUTE)
async def _test_admin_endpoint(_=Depends(require_admin())):
    return {"admin": True}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_api_key_row(platform: str, operations: list[str]) -> ServiceApiKey:
    row = MagicMock(spec=ServiceApiKey)
    row.platform = platform
    row.allowed_operations = operations
    row.is_active = True
    row.id = "test-id-123"
    return row


RAW_KEY = "test-raw-key-abc123"
VALID_HEADER = f"Bearer {RAW_KEY}"


@pytest.fixture()
def client():
    with (
        patch("app.main.init_redis", new_callable=AsyncMock),
        patch("app.main.close_redis", new_callable=AsyncMock),
    ):
        with TestClient(app) as c:
            yield c


# ---------------------------------------------------------------------------
# Valid auth
# ---------------------------------------------------------------------------

def test_valid_key_with_permission_returns_200(client):
    key_row = _make_api_key_row("subsidy", [TEST_OPERATION])
    with (
        patch("app.core.auth.lookup_api_key", new_callable=AsyncMock, return_value=key_row),
        patch("app.core.auth.update_last_used", new_callable=AsyncMock),
    ):
        response = client.get(TEST_ROUTE, headers={"Authorization": VALID_HEADER})

    assert response.status_code == 200
    assert response.json()["platform"] == "subsidy"


def test_auth_context_carries_correct_platform(client):
    key_row = _make_api_key_row("resira", [TEST_OPERATION])
    with (
        patch("app.core.auth.lookup_api_key", new_callable=AsyncMock, return_value=key_row),
        patch("app.core.auth.update_last_used", new_callable=AsyncMock),
    ):
        response = client.get(TEST_ROUTE, headers={"Authorization": VALID_HEADER})

    assert response.json()["platform"] == "resira"


# ---------------------------------------------------------------------------
# Missing / malformed auth header
# ---------------------------------------------------------------------------

def test_missing_auth_header_returns_401(client):
    response = client.get(TEST_ROUTE)
    assert response.status_code == 401
    assert response.json()["detail"]["error_code"] == "INVALID_API_KEY"


def test_malformed_bearer_returns_401(client):
    response = client.get(TEST_ROUTE, headers={"Authorization": "NotBearer abc"})
    assert response.status_code == 401


def test_bearer_without_token_returns_401(client):
    response = client.get(TEST_ROUTE, headers={"Authorization": "Bearer"})
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Invalid / inactive key
# ---------------------------------------------------------------------------

def test_unknown_key_returns_401(client):
    with patch("app.core.auth.lookup_api_key", new_callable=AsyncMock, return_value=None):
        response = client.get(TEST_ROUTE, headers={"Authorization": VALID_HEADER})
    assert response.status_code == 401
    assert response.json()["detail"]["error_code"] == "INVALID_API_KEY"


# ---------------------------------------------------------------------------
# Permission denied
# ---------------------------------------------------------------------------

def test_key_without_operation_returns_403(client):
    # Key exists but doesn't have this operation
    key_row = _make_api_key_row("resira", ["create_prospect", "get_units"])
    with (
        patch("app.core.auth.lookup_api_key", new_callable=AsyncMock, return_value=key_row),
        patch("app.core.auth.update_last_used", new_callable=AsyncMock),
    ):
        response = client.get(TEST_ROUTE, headers={"Authorization": VALID_HEADER})
    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "OPERATION_NOT_PERMITTED"


def test_permission_error_includes_platform_and_operation(client):
    key_row = _make_api_key_row("resira", [])
    with (
        patch("app.core.auth.lookup_api_key", new_callable=AsyncMock, return_value=key_row),
        patch("app.core.auth.update_last_used", new_callable=AsyncMock),
    ):
        response = client.get(TEST_ROUTE, headers={"Authorization": VALID_HEADER})
    detail = response.json()["detail"]
    assert "resira" in detail["error_message"]
    assert TEST_OPERATION in detail["error_message"]


# ---------------------------------------------------------------------------
# Admin auth
# ---------------------------------------------------------------------------

def test_valid_admin_key_returns_200(client):
    with patch("app.core.auth.settings") as mock_settings:
        mock_settings.admin_api_key = "correct-admin-key"
        response = client.get(
            TEST_ADMIN_ROUTE,
            headers={"Authorization": "Bearer correct-admin-key"},
        )
    assert response.status_code == 200


def test_wrong_admin_key_returns_401(client):
    with patch("app.core.auth.settings") as mock_settings:
        mock_settings.admin_api_key = "correct-admin-key"
        response = client.get(
            TEST_ADMIN_ROUTE,
            headers={"Authorization": "Bearer wrong-key"},
        )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Error response shape
# ---------------------------------------------------------------------------

def test_error_response_always_has_required_fields(client):
    response = client.get(TEST_ROUTE)
    detail = response.json()["detail"]
    assert "success" in detail
    assert "error_code" in detail
    assert "error_message" in detail
    assert "retryable" in detail
    assert detail["success"] is False
    assert detail["retryable"] is False
