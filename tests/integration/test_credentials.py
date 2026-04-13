"""
Integration tests for credential storage service.
DB session is mocked — tests the store/retrieve logic without a live DB.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet

from app.models.credentials import RMCredentials
from app.services.credentials import (
    CredentialMissingError,
    PlaintextCredentials,
    credentials_exist,
    delete_credentials,
    retrieve_credentials,
    store_credentials,
)

TEST_MASTER_KEY = Fernet.generate_key().decode()

MASTER_KEY_PATCH = patch(
    "app.services.encryption.get_settings",
    return_value=type("S", (), {"fernet_master_key": TEST_MASTER_KEY})(),
)


def _mock_db():
    db = AsyncMock()
    db.add = MagicMock()   # db.add() is synchronous in SQLAlchemy
    db.flush = AsyncMock()
    db.delete = AsyncMock()
    return db


# ---------------------------------------------------------------------------
# store_credentials — new company
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_store_creates_new_row_when_none_exists():
    db = _mock_db()
    company_id = uuid.uuid4()

    # Simulate no existing credentials
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    with MASTER_KEY_PATCH:
        row = await store_credentials(db, company_id, "rmuser", "rmpass")

    db.add.assert_called_once()
    db.flush.assert_called_once()
    added_row = db.add.call_args[0][0]
    assert isinstance(added_row, RMCredentials)
    assert added_row.company_id == company_id
    # Encrypted values must not equal plaintext
    assert added_row.username_encrypted != "rmuser"
    assert added_row.password_encrypted != "rmpass"


@pytest.mark.asyncio
async def test_store_updates_existing_row():
    db = _mock_db()
    company_id = uuid.uuid4()

    existing_row = RMCredentials()
    existing_row.company_id = company_id
    existing_row.username_encrypted = "old_enc"
    existing_row.password_encrypted = "old_enc"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = existing_row
    db.execute = AsyncMock(return_value=mock_result)

    with MASTER_KEY_PATCH:
        await store_credentials(db, company_id, "newuser", "newpass")

    # Should NOT call db.add — row already existed
    db.add.assert_not_called()
    # Encrypted values should be updated
    assert existing_row.username_encrypted != "old_enc"
    assert existing_row.password_encrypted != "old_enc"


# ---------------------------------------------------------------------------
# retrieve_credentials
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_retrieve_returns_decrypted_credentials():
    db = _mock_db()
    company_id = uuid.uuid4()

    with MASTER_KEY_PATCH:
        from app.services.encryption import encrypt_credential
        enc_user = encrypt_credential(company_id, "myuser")
        enc_pass = encrypt_credential(company_id, "mypassword")

    row = RMCredentials()
    row.company_id = company_id
    row.username_encrypted = enc_user
    row.password_encrypted = enc_pass

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = row
    db.execute = AsyncMock(return_value=mock_result)

    with MASTER_KEY_PATCH:
        creds = await retrieve_credentials(db, company_id)

    assert isinstance(creds, PlaintextCredentials)
    assert creds.username == "myuser"
    assert creds.password == "mypassword"


@pytest.mark.asyncio
async def test_retrieve_raises_when_no_credentials():
    db = _mock_db()
    company_id = uuid.uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    with MASTER_KEY_PATCH:
        with pytest.raises(CredentialMissingError):
            await retrieve_credentials(db, company_id)


# ---------------------------------------------------------------------------
# credentials_exist
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_credentials_exist_returns_true_when_found():
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = uuid.uuid4()  # Any non-None
    db.execute = AsyncMock(return_value=mock_result)

    result = await credentials_exist(db, uuid.uuid4())
    assert result is True


@pytest.mark.asyncio
async def test_credentials_exist_returns_false_when_not_found():
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    result = await credentials_exist(db, uuid.uuid4())
    assert result is False


# ---------------------------------------------------------------------------
# delete_credentials
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_removes_existing_credentials():
    db = _mock_db()
    company_id = uuid.uuid4()

    row = RMCredentials()
    row.company_id = company_id

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = row
    db.execute = AsyncMock(return_value=mock_result)

    with MASTER_KEY_PATCH:
        result = await delete_credentials(db, company_id)

    assert result is True
    db.delete.assert_called_once_with(row)


@pytest.mark.asyncio
async def test_delete_returns_false_when_nothing_to_delete():
    db = _mock_db()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    result = await delete_credentials(db, uuid.uuid4())
    assert result is False
    db.delete.assert_not_called()


# ---------------------------------------------------------------------------
# Security: store does not retain plaintext
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_stored_values_are_not_plaintext():
    db = _mock_db()
    company_id = uuid.uuid4()

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=mock_result)

    with MASTER_KEY_PATCH:
        await store_credentials(db, company_id, "plainuser", "plainpass")

    added_row = db.add.call_args[0][0]
    assert "plainuser" not in added_row.username_encrypted
    assert "plainpass" not in added_row.password_encrypted
