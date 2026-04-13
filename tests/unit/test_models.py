"""
Verify all models are importable and have the expected columns.
No DB connection required — tests SQLAlchemy metadata only.
"""
import pytest
from sqlalchemy import inspect

from app.db.session import Base
import app.models  # noqa — registers all models


def get_table(name: str):
    return Base.metadata.tables[name]


def test_all_tables_registered():
    expected = {
        "companies",
        "rm_credentials",
        "rm_locations",
        "rm_auth_tokens",
        "idempotency_records",
        "service_api_keys",
        "operation_log",
        "rm_webhook_events",
    }
    assert expected.issubset(set(Base.metadata.tables.keys()))


def test_companies_columns():
    t = get_table("companies")
    cols = {c.name for c in t.columns}
    assert {"id", "name", "platform_source", "is_active", "credential_status",
            "credential_checked_at", "deleted_at", "purge_credentials_at",
            "created_at", "updated_at"}.issubset(cols)


def test_rm_credentials_has_encrypted_fields():
    t = get_table("rm_credentials")
    cols = {c.name for c in t.columns}
    assert "username_encrypted" in cols
    assert "password_encrypted" in cols
    # Raw username/password must NOT exist
    assert "username" not in cols
    assert "password" not in cols


def test_rm_locations_has_exclude_flag():
    t = get_table("rm_locations")
    cols = {c.name for c in t.columns}
    assert "exclude_from_ops" in cols
    assert "friendly_name" in cols


def test_operation_log_has_required_audit_fields():
    t = get_table("operation_log")
    cols = {c.name for c in t.columns}
    assert {"company_id", "platform_source", "operation", "success",
            "created_at", "duration_ms", "idempotency_key"}.issubset(cols)


def test_service_api_keys_no_raw_key_column():
    """Raw API keys must never be stored — only SHA-256 hashes."""
    t = get_table("service_api_keys")
    cols = {c.name for c in t.columns}
    assert "key_hash" in cols
    assert "key" not in cols
    assert "api_key" not in cols
    assert "raw_key" not in cols


def test_companies_soft_delete_fields():
    t = get_table("companies")
    cols = {c.name for c in t.columns}
    assert "deleted_at" in cols
    assert "purge_credentials_at" in cols


def test_idempotency_has_expiry():
    t = get_table("idempotency_records")
    cols = {c.name for c in t.columns}
    assert "expires_at" in cols
    assert "response_snapshot" in cols
