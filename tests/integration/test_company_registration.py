"""
Integration tests for POST /v1/companies/register.
DB and auth are mocked — no live DB or API keys required.
"""
import uuid
from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.db.session import get_db
from app.main import app
from app.models.api_key import ServiceApiKey

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

RAW_KEY = "test-registration-key-xyz"
VALID_HEADER = f"Bearer {RAW_KEY}"

VALID_PAYLOAD = {
    "name": "Acme Properties",
    "platform_source": "resira",
    "rm_username": "acme_user",
    "rm_password": "acme_pass",
    "locations": [
        {
            "rm_location_id": "LOC001",
            "friendly_name": "Downtown Office",
            "exclude_from_ops": False,
        },
        {
            "rm_location_id": "LOC002",
            "friendly_name": "Uptown Branch",
            "exclude_from_ops": True,
        },
    ],
}


def _make_api_key_row(operations: list[str] | None = None) -> ServiceApiKey:
    row = MagicMock(spec=ServiceApiKey)
    row.platform = "resira"
    row.allowed_operations = operations if operations is not None else ["register_company"]
    row.is_active = True
    row.id = "test-key-id"
    return row


def _make_mock_db():
    """
    Mock DB session that simulates uuid_generate_v4() by assigning
    fresh UUIDs to ORM objects on each flush() call.
    """
    db = AsyncMock()
    _added: list = []

    def _add(obj):
        _added.append(obj)

    async def _flush():
        for obj in _added:
            if not getattr(obj, "id", None):
                obj.id = uuid.uuid4()

    db.add = MagicMock(side_effect=_add)
    db.flush = AsyncMock(side_effect=_flush)
    return db


@contextmanager
def _db_override(mock_db):
    """Temporarily replace the get_db FastAPI dependency with mock_db."""

    async def _gen():
        yield mock_db

    app.dependency_overrides[get_db] = _gen
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_db, None)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    with (
        patch("app.main.init_redis", new_callable=AsyncMock),
        patch("app.main.close_redis", new_callable=AsyncMock),
    ):
        with TestClient(app) as c:
            yield c


# ---------------------------------------------------------------------------
# Success — response shape
# ---------------------------------------------------------------------------


def test_register_returns_201(client):
    key_row = _make_api_key_row()
    mock_db = _make_mock_db()
    with (
        _db_override(mock_db),
        patch("app.core.auth.lookup_api_key", new_callable=AsyncMock, return_value=key_row),
        patch("app.core.auth.update_last_used", new_callable=AsyncMock),
        patch("app.api.v1.companies.store_credentials", new_callable=AsyncMock),
    ):
        response = client.post(
            "/v1/companies/register",
            json=VALID_PAYLOAD,
            headers={"Authorization": VALID_HEADER},
        )

    assert response.status_code == 201


def test_register_response_has_correct_shape(client):
    key_row = _make_api_key_row()
    mock_db = _make_mock_db()
    with (
        _db_override(mock_db),
        patch("app.core.auth.lookup_api_key", new_callable=AsyncMock, return_value=key_row),
        patch("app.core.auth.update_last_used", new_callable=AsyncMock),
        patch("app.api.v1.companies.store_credentials", new_callable=AsyncMock),
    ):
        response = client.post(
            "/v1/companies/register",
            json=VALID_PAYLOAD,
            headers={"Authorization": VALID_HEADER},
        )

    data = response.json()
    assert data["success"] is True
    assert "company_id" in data
    # UUID serialised to string
    uuid.UUID(data["company_id"])  # raises if not a valid UUID
    assert len(data["locations"]) == 2


def test_register_locations_carry_correct_data(client):
    key_row = _make_api_key_row()
    mock_db = _make_mock_db()
    with (
        _db_override(mock_db),
        patch("app.core.auth.lookup_api_key", new_callable=AsyncMock, return_value=key_row),
        patch("app.core.auth.update_last_used", new_callable=AsyncMock),
        patch("app.api.v1.companies.store_credentials", new_callable=AsyncMock),
    ):
        response = client.post(
            "/v1/companies/register",
            json=VALID_PAYLOAD,
            headers={"Authorization": VALID_HEADER},
        )

    locations = response.json()["locations"]
    by_rm_id = {loc["rm_location_id"]: loc for loc in locations}

    assert set(by_rm_id) == {"LOC001", "LOC002"}
    assert by_rm_id["LOC001"]["friendly_name"] == "Downtown Office"
    assert by_rm_id["LOC001"]["exclude_from_ops"] is False
    assert by_rm_id["LOC002"]["friendly_name"] == "Uptown Branch"
    assert by_rm_id["LOC002"]["exclude_from_ops"] is True
    # Each location gets its own UUID
    assert by_rm_id["LOC001"]["location_id"] != by_rm_id["LOC002"]["location_id"]
    # location_id differs from company_id
    company_id = response.json()["company_id"]
    assert by_rm_id["LOC001"]["location_id"] != company_id


def test_register_single_location(client):
    key_row = _make_api_key_row()
    mock_db = _make_mock_db()
    payload = {**VALID_PAYLOAD, "locations": [VALID_PAYLOAD["locations"][0]]}
    with (
        _db_override(mock_db),
        patch("app.core.auth.lookup_api_key", new_callable=AsyncMock, return_value=key_row),
        patch("app.core.auth.update_last_used", new_callable=AsyncMock),
        patch("app.api.v1.companies.store_credentials", new_callable=AsyncMock),
    ):
        response = client.post(
            "/v1/companies/register",
            json=payload,
            headers={"Authorization": VALID_HEADER},
        )

    assert response.status_code == 201
    assert len(response.json()["locations"]) == 1


# ---------------------------------------------------------------------------
# Success — service interaction
# ---------------------------------------------------------------------------


def test_store_credentials_called_with_correct_args(client):
    key_row = _make_api_key_row()
    mock_db = _make_mock_db()
    with (
        _db_override(mock_db),
        patch("app.core.auth.lookup_api_key", new_callable=AsyncMock, return_value=key_row),
        patch("app.core.auth.update_last_used", new_callable=AsyncMock),
        patch("app.api.v1.companies.store_credentials", new_callable=AsyncMock) as mock_store,
    ):
        response = client.post(
            "/v1/companies/register",
            json=VALID_PAYLOAD,
            headers={"Authorization": VALID_HEADER},
        )

    assert response.status_code == 201
    mock_store.assert_called_once()
    _, company_id_arg, username_arg, password_arg = mock_store.call_args.args
    uuid.UUID(str(company_id_arg))  # must be a valid UUID
    assert username_arg == "acme_user"
    assert password_arg == "acme_pass"


def test_company_id_in_response_matches_credential_call(client):
    """The company_id passed to store_credentials matches what's in the response."""
    key_row = _make_api_key_row()
    mock_db = _make_mock_db()
    with (
        _db_override(mock_db),
        patch("app.core.auth.lookup_api_key", new_callable=AsyncMock, return_value=key_row),
        patch("app.core.auth.update_last_used", new_callable=AsyncMock),
        patch("app.api.v1.companies.store_credentials", new_callable=AsyncMock) as mock_store,
    ):
        response = client.post(
            "/v1/companies/register",
            json=VALID_PAYLOAD,
            headers={"Authorization": VALID_HEADER},
        )

    response_company_id = response.json()["company_id"]
    _, credential_company_id, *_ = mock_store.call_args.args
    assert str(credential_company_id) == response_company_id


# ---------------------------------------------------------------------------
# Auth failures
# ---------------------------------------------------------------------------


def test_missing_auth_header_returns_401(client):
    response = client.post("/v1/companies/register", json=VALID_PAYLOAD)
    assert response.status_code == 401
    assert response.json()["detail"]["error_code"] == "INVALID_API_KEY"


def test_invalid_key_returns_401(client):
    with patch("app.core.auth.lookup_api_key", new_callable=AsyncMock, return_value=None):
        response = client.post(
            "/v1/companies/register",
            json=VALID_PAYLOAD,
            headers={"Authorization": VALID_HEADER},
        )
    assert response.status_code == 401


def test_key_missing_register_permission_returns_403(client):
    key_row = _make_api_key_row(operations=["post_payment"])
    with (
        patch("app.core.auth.lookup_api_key", new_callable=AsyncMock, return_value=key_row),
        patch("app.core.auth.update_last_used", new_callable=AsyncMock),
    ):
        response = client.post(
            "/v1/companies/register",
            json=VALID_PAYLOAD,
            headers={"Authorization": VALID_HEADER},
        )
    assert response.status_code == 403
    assert response.json()["detail"]["error_code"] == "OPERATION_NOT_PERMITTED"


# ---------------------------------------------------------------------------
# Request validation (422)
# ---------------------------------------------------------------------------


def _post_with_valid_auth(client, payload):
    """POST with a properly mocked auth so validation errors aren't shadowed by 401."""
    key_row = _make_api_key_row()
    mock_db = _make_mock_db()
    with (
        _db_override(mock_db),
        patch("app.core.auth.lookup_api_key", new_callable=AsyncMock, return_value=key_row),
        patch("app.core.auth.update_last_used", new_callable=AsyncMock),
    ):
        return client.post(
            "/v1/companies/register",
            json=payload,
            headers={"Authorization": VALID_HEADER},
        )


def test_missing_name_returns_422(client):
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "name"}
    assert _post_with_valid_auth(client, payload).status_code == 422


def test_missing_rm_username_returns_422(client):
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "rm_username"}
    assert _post_with_valid_auth(client, payload).status_code == 422


def test_missing_rm_password_returns_422(client):
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "rm_password"}
    assert _post_with_valid_auth(client, payload).status_code == 422


def test_invalid_platform_source_returns_422(client):
    payload = {**VALID_PAYLOAD, "platform_source": "unknown_platform"}
    assert _post_with_valid_auth(client, payload).status_code == 422


def test_empty_locations_list_returns_422(client):
    payload = {**VALID_PAYLOAD, "locations": []}
    assert _post_with_valid_auth(client, payload).status_code == 422
