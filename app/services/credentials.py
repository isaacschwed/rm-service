"""
Credential storage service.

Responsibilities:
- Store encrypted RM username + password for a company
- Retrieve and decrypt credentials when RM auth is needed
- Update credentials (rotation)
- Never log or expose plaintext credentials

The encryption layer (HKDF + Fernet) is handled entirely by encryption.py.
This module only deals with DB reads/writes.
"""

from datetime import datetime, timezone
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.credentials import RMCredentials
from app.services.encryption import (
    CredentialDecryptionError,
    decrypt_credential,
    encrypt_credential,
)

logger = structlog.get_logger(__name__)


class PlaintextCredentials:
    """
    Holds decrypted credentials in memory.
    Use immediately and discard — never store, log, or serialize this object.
    """

    __slots__ = ("username", "password")

    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password

    def __repr__(self) -> str:
        # Prevent accidental logging of credentials
        return "<PlaintextCredentials [REDACTED]>"


async def store_credentials(
    db: AsyncSession,
    company_id: UUID,
    username: str,
    password: str,
) -> RMCredentials:
    """
    Encrypt and store (or replace) RM credentials for a company.

    If credentials already exist for this company, they are replaced.
    This is the only function that accepts plaintext credentials —
    they are encrypted immediately and the plaintext is not retained.
    """
    username_enc = encrypt_credential(company_id, username)
    password_enc = encrypt_credential(company_id, password)

    # Check for existing row
    result = await db.execute(
        select(RMCredentials).where(RMCredentials.company_id == company_id)
    )
    existing = result.scalar_one_or_none()

    if existing:
        existing.username_encrypted = username_enc
        existing.password_encrypted = password_enc
        existing.updated_at = datetime.now(timezone.utc)
        creds_row = existing
        logger.info("credentials_updated", company_id=str(company_id))
    else:
        creds_row = RMCredentials(
            company_id=company_id,
            username_encrypted=username_enc,
            password_encrypted=password_enc,
        )
        db.add(creds_row)
        logger.info("credentials_stored", company_id=str(company_id))

    await db.flush()  # Write to DB within the current transaction
    return creds_row


async def retrieve_credentials(
    db: AsyncSession,
    company_id: UUID,
) -> PlaintextCredentials:
    """
    Retrieve and decrypt RM credentials for a company.

    Returns PlaintextCredentials — use immediately, discard after RM auth call.

    Raises:
        CredentialMissingError — no credentials stored for this company
        CredentialDecryptionError — decryption failed (key mismatch, tampered data)
    """
    result = await db.execute(
        select(RMCredentials).where(RMCredentials.company_id == company_id)
    )
    row = result.scalar_one_or_none()

    if row is None:
        raise CredentialMissingError(f"No credentials found for company {company_id}")

    username = decrypt_credential(company_id, row.username_encrypted)
    password = decrypt_credential(company_id, row.password_encrypted)

    return PlaintextCredentials(username=username, password=password)


async def credentials_exist(db: AsyncSession, company_id: UUID) -> bool:
    """Quick check — does this company have stored credentials?"""
    result = await db.execute(
        select(RMCredentials.id).where(RMCredentials.company_id == company_id)
    )
    return result.scalar_one_or_none() is not None


async def delete_credentials(db: AsyncSession, company_id: UUID) -> bool:
    """
    Hard-delete credentials for a company.
    Called by the credential purge background job after the 30-day grace period.
    Returns True if credentials were deleted, False if none existed.
    """
    result = await db.execute(
        select(RMCredentials).where(RMCredentials.company_id == company_id)
    )
    row = result.scalar_one_or_none()

    if row is None:
        return False

    await db.delete(row)
    logger.info("credentials_purged", company_id=str(company_id))
    return True


class CredentialMissingError(Exception):
    """Raised when no credentials are found for a company."""
    pass
