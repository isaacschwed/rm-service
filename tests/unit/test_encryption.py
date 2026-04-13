"""
Unit tests for HKDF key derivation and Fernet encrypt/decrypt.
No DB, no network — pure cryptography tests.
All tests use a generated master key so they're fully self-contained.
"""
import base64
import uuid
from unittest.mock import patch

import pytest
from cryptography.fernet import Fernet

from app.services.encryption import (
    CredentialDecryptionError,
    decrypt_credential,
    encrypt_credential,
)

# A real Fernet key for use as the master key in tests
TEST_MASTER_KEY = Fernet.generate_key().decode()


def _patch_master_key():
    """Context manager that injects the test master key into settings."""
    return patch(
        "app.services.encryption.get_settings",
        return_value=type("S", (), {"fernet_master_key": TEST_MASTER_KEY})(),
    )


# ---------------------------------------------------------------------------
# Basic encrypt / decrypt roundtrip
# ---------------------------------------------------------------------------

def test_encrypt_returns_string():
    company_id = uuid.uuid4()
    with _patch_master_key():
        result = encrypt_credential(company_id, "my-password")
    assert isinstance(result, str)
    assert len(result) > 0


def test_decrypt_roundtrip():
    company_id = uuid.uuid4()
    plaintext = "supersecretpassword123"
    with _patch_master_key():
        ciphertext = encrypt_credential(company_id, plaintext)
        recovered = decrypt_credential(company_id, ciphertext)
    assert recovered == plaintext


def test_roundtrip_with_special_characters():
    company_id = uuid.uuid4()
    plaintext = "p@$$w0rd!#%^&*()"
    with _patch_master_key():
        ciphertext = encrypt_credential(company_id, plaintext)
        recovered = decrypt_credential(company_id, ciphertext)
    assert recovered == plaintext


def test_roundtrip_with_long_value():
    company_id = uuid.uuid4()
    plaintext = "a" * 500
    with _patch_master_key():
        ciphertext = encrypt_credential(company_id, plaintext)
        recovered = decrypt_credential(company_id, ciphertext)
    assert recovered == plaintext


# ---------------------------------------------------------------------------
# Ciphertext does not contain plaintext
# ---------------------------------------------------------------------------

def test_plaintext_not_in_ciphertext():
    company_id = uuid.uuid4()
    plaintext = "my-rm-password"
    with _patch_master_key():
        ciphertext = encrypt_credential(company_id, plaintext)
    assert plaintext not in ciphertext
    assert plaintext not in base64.b64decode(ciphertext + "==").decode("latin-1", errors="replace")


def test_same_plaintext_encrypts_differently_each_time():
    """Fernet uses a random IV — same input must produce different ciphertexts."""
    company_id = uuid.uuid4()
    plaintext = "same-password"
    with _patch_master_key():
        c1 = encrypt_credential(company_id, plaintext)
        c2 = encrypt_credential(company_id, plaintext)
    assert c1 != c2  # Random IV guarantees this


# ---------------------------------------------------------------------------
# Per-company key isolation — the critical security property
# ---------------------------------------------------------------------------

def test_different_companies_get_different_ciphertexts():
    company_a = uuid.uuid4()
    company_b = uuid.uuid4()
    plaintext = "shared-password"
    with _patch_master_key():
        ca = encrypt_credential(company_a, plaintext)
        cb = encrypt_credential(company_b, plaintext)
    assert ca != cb


def test_cannot_decrypt_with_wrong_company_key():
    """
    A token encrypted for company A must NOT be decryptable with company B's key.
    This is the core security guarantee of per-company HKDF derivation.
    """
    company_a = uuid.uuid4()
    company_b = uuid.uuid4()
    plaintext = "secret"

    with _patch_master_key():
        ciphertext_for_a = encrypt_credential(company_a, plaintext)

        with pytest.raises(CredentialDecryptionError):
            decrypt_credential(company_b, ciphertext_for_a)


def test_same_company_id_always_derives_same_key():
    """HKDF derivation must be deterministic — same inputs = same key."""
    company_id = uuid.uuid4()
    plaintext = "password"

    with _patch_master_key():
        ciphertext = encrypt_credential(company_id, plaintext)
        # Decrypt in a separate call — must still work (same derived key)
        recovered = decrypt_credential(company_id, ciphertext)

    assert recovered == plaintext


# ---------------------------------------------------------------------------
# Tamper detection
# ---------------------------------------------------------------------------

def test_tampered_ciphertext_raises_error():
    company_id = uuid.uuid4()
    with _patch_master_key():
        ciphertext = encrypt_credential(company_id, "password")

    # Flip some bytes in the middle of the token
    token_bytes = base64.urlsafe_b64decode(ciphertext + "==")
    mid = len(token_bytes) // 2
    tampered = token_bytes[:mid] + bytes([b ^ 0xFF for b in token_bytes[mid:mid+4]]) + token_bytes[mid+4:]
    tampered_ciphertext = base64.urlsafe_b64encode(tampered).decode().rstrip("=")

    with _patch_master_key():
        with pytest.raises(CredentialDecryptionError):
            decrypt_credential(company_id, tampered_ciphertext)


def test_empty_ciphertext_raises_error():
    company_id = uuid.uuid4()
    with _patch_master_key():
        with pytest.raises(CredentialDecryptionError):
            decrypt_credential(company_id, "")


def test_garbage_ciphertext_raises_error():
    company_id = uuid.uuid4()
    with _patch_master_key():
        with pytest.raises(CredentialDecryptionError):
            decrypt_credential(company_id, "not-a-valid-fernet-token")


# ---------------------------------------------------------------------------
# PlaintextCredentials repr safety
# ---------------------------------------------------------------------------

def test_plaintext_credentials_repr_does_not_leak():
    from app.services.credentials import PlaintextCredentials
    creds = PlaintextCredentials("admin_user", "supersecret")
    repr_str = repr(creds)
    assert "admin_user" not in repr_str
    assert "supersecret" not in repr_str
    assert "REDACTED" in repr_str
