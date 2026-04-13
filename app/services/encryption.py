"""
Credential encryption using Fernet + HKDF per-company key derivation.

Design:
- One master key stored in Railway secrets (FERNET_MASTER_KEY)
- A unique Fernet key is derived per company_id using HKDF
- Compromising one company's derived key exposes ONLY that company
- Credentials are decrypted only at the moment of RM auth, then discarded
- Raw credentials NEVER appear in logs, responses, or error messages

Key derivation:
    derived_key = HKDF(master_key, salt=company_id, info=b"rm-credentials")
    fernet = Fernet(base64url(derived_key))
"""

import base64
from uuid import UUID

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import get_settings


# HKDF context label — changing this invalidates all existing encrypted values
_HKDF_INFO = b"rm-connector-credentials-v1"
_KEY_LENGTH = 32  # Fernet requires exactly 32 bytes


def _derive_key(company_id: UUID) -> Fernet:
    """
    Derive a company-specific Fernet instance using HKDF.

    The master key is base64-decoded from the env var.
    The company_id UUID bytes are used as the HKDF salt —
    different per company, deterministic, no extra storage needed.
    """
    settings = get_settings()

    # Master key is stored as base64 in Railway secrets
    master_key_bytes = base64.urlsafe_b64decode(settings.fernet_master_key)

    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=_KEY_LENGTH,
        salt=company_id.bytes,      # UUID bytes — unique per company, deterministic
        info=_HKDF_INFO,
    )
    derived_key_bytes = hkdf.derive(master_key_bytes)

    # Fernet requires base64url-encoded 32-byte key
    fernet_key = base64.urlsafe_b64encode(derived_key_bytes)
    return Fernet(fernet_key)


def encrypt_credential(company_id: UUID, plaintext: str) -> str:
    """
    Encrypt a credential string for a specific company.
    Returns a base64url-encoded Fernet token (string).
    """
    fernet = _derive_key(company_id)
    token = fernet.encrypt(plaintext.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_credential(company_id: UUID, ciphertext: str) -> str:
    """
    Decrypt a Fernet token back to plaintext for a specific company.

    Raises:
        CredentialDecryptionError — if the token is invalid, tampered with,
                                    or was encrypted with a different company's key.
    """
    fernet = _derive_key(company_id)
    try:
        plaintext = fernet.decrypt(ciphertext.encode("utf-8"))
        return plaintext.decode("utf-8")
    except (InvalidToken, Exception) as exc:
        # Never include ciphertext or any credential material in this error
        raise CredentialDecryptionError(
            f"Failed to decrypt credential for company {company_id}"
        ) from exc


class CredentialDecryptionError(Exception):
    """Raised when Fernet decryption fails — invalid token, wrong key, or tampered data."""
    pass
