"""
Unit tests for API key service logic.
No DB, no network — pure function tests.
"""
import hashlib

from app.models.api_key import ServiceApiKey
from app.services.api_key import (
    generate_api_key,
    hash_api_key,
    is_operation_permitted,
)


def _make_key(platform: str, operations: list[str], active: bool = True) -> ServiceApiKey:
    key = ServiceApiKey()
    key.platform = platform
    key.allowed_operations = operations
    key.is_active = active
    return key


# ---------------------------------------------------------------------------
# hash_api_key
# ---------------------------------------------------------------------------

def test_hash_is_sha256():
    raw = "mysecretkey"
    expected = hashlib.sha256(raw.encode()).hexdigest()
    assert hash_api_key(raw) == expected


def test_same_key_always_same_hash():
    raw = "consistent-key-abc123"
    assert hash_api_key(raw) == hash_api_key(raw)


def test_different_keys_different_hashes():
    assert hash_api_key("key-one") != hash_api_key("key-two")


def test_raw_key_not_in_hash():
    raw = "supersecretkey"
    hashed = hash_api_key(raw)
    assert raw not in hashed


# ---------------------------------------------------------------------------
# generate_api_key
# ---------------------------------------------------------------------------

def test_generated_keys_are_unique():
    keys = {generate_api_key() for _ in range(100)}
    assert len(keys) == 100


def test_generated_key_is_string():
    key = generate_api_key()
    assert isinstance(key, str)
    assert len(key) > 20


# ---------------------------------------------------------------------------
# is_operation_permitted
# ---------------------------------------------------------------------------

def test_permitted_operation_returns_true():
    key = _make_key("resira", ["create_prospect", "get_units", "post_history_note"])
    assert is_operation_permitted(key, "create_prospect") is True


def test_unpermitted_operation_returns_false():
    key = _make_key("resira", ["create_prospect"])
    assert is_operation_permitted(key, "post_payment") is False


def test_empty_operations_denies_everything():
    key = _make_key("subsidy", [])
    assert is_operation_permitted(key, "post_payment") is False


def test_exact_match_required():
    key = _make_key("ap", ["post_bill"])
    # Partial match must not be allowed
    assert is_operation_permitted(key, "post") is False
    assert is_operation_permitted(key, "bill") is False
    assert is_operation_permitted(key, "post_bills") is False


def test_none_operations_denies_everything():
    key = _make_key("resira", [])
    key.allowed_operations = None  # type: ignore
    assert is_operation_permitted(key, "anything") is False


def test_all_platforms_default_permissions():
    """Document the intended default permission sets from the spec."""
    resira_ops = [
        "create_prospect", "update_prospect", "get_prospect",
        "create_contact", "update_contact",
        "get_units", "get_properties",
        "post_history_note", "post_attachment",
    ]
    subsidy_ops = [
        "post_payment", "get_payments",
        "get_tenant", "get_units",
        "post_history_note", "post_attachment",
    ]
    ap_ops = [
        "post_bill", "void_bill", "get_bill",
        "get_vendors", "create_vendor", "update_vendor", "hold_vendor",
        "get_properties", "get_gl_codes", "get_bank_accounts",
        "post_history_note", "post_attachment",
    ]

    resira_key = _make_key("resira", resira_ops)
    subsidy_key = _make_key("subsidy", subsidy_ops)
    ap_key = _make_key("ap", ap_ops)

    # Resira cannot post payments
    assert is_operation_permitted(resira_key, "post_payment") is False
    # Subsidy cannot post bills
    assert is_operation_permitted(subsidy_key, "post_bill") is False
    # AP cannot create prospects
    assert is_operation_permitted(ap_key, "create_prospect") is False

    # Each can do its own thing
    assert is_operation_permitted(resira_key, "create_prospect") is True
    assert is_operation_permitted(subsidy_key, "post_payment") is True
    assert is_operation_permitted(ap_key, "post_bill") is True
