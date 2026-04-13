"""Initial schema — all tables, indexes, immutability trigger

Revision ID: 0001_initial_schema
Revises:
Create Date: 2025-01-01 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Extensions
    # ------------------------------------------------------------------
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    # ------------------------------------------------------------------
    # companies
    # ------------------------------------------------------------------
    op.create_table(
        "companies",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("platform_source", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.Column("credential_status", sa.String(), nullable=True),
        sa.Column("credential_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("purge_credentials_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # ------------------------------------------------------------------
    # rm_credentials
    # ------------------------------------------------------------------
    op.create_table(
        "rm_credentials",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("username_encrypted", sa.String(), nullable=False),
        sa.Column("password_encrypted", sa.String(), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("company_id", name="uq_rm_credentials_company_id"),
    )

    # ------------------------------------------------------------------
    # rm_locations
    # ------------------------------------------------------------------
    op.create_table(
        "rm_locations",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rm_location_id", sa.String(), nullable=False),
        sa.Column("friendly_name", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.Column(
            "exclude_from_ops", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint(
            "company_id", "rm_location_id", name="uq_rm_locations_company_location"
        ),
    )

    # ------------------------------------------------------------------
    # rm_auth_tokens
    # ------------------------------------------------------------------
    op.create_table(
        "rm_auth_tokens",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_encrypted", sa.String(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("company_id", name="uq_rm_auth_tokens_company_id"),
    )

    # ------------------------------------------------------------------
    # idempotency_records
    # ------------------------------------------------------------------
    op.create_table(
        "idempotency_records",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("idempotency_key", sa.String(), nullable=False, unique=True),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column("rm_entity_id", sa.String(), nullable=True),
        sa.Column("response_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
    )

    # ------------------------------------------------------------------
    # service_api_keys
    # ------------------------------------------------------------------
    op.create_table(
        "service_api_keys",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("platform", sa.String(), nullable=False, unique=True),
        sa.Column("key_hash", sa.String(), nullable=False, unique=True),
        sa.Column(
            "allowed_operations",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
    )

    # ------------------------------------------------------------------
    # operation_log
    # ------------------------------------------------------------------
    op.create_table(
        "operation_log",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("platform_source", sa.String(), nullable=False),
        sa.Column("location_id", sa.String(), nullable=True),
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column("rm_endpoint", sa.String(), nullable=True),
        sa.Column("request_summary", postgresql.JSONB(), nullable=True),
        sa.Column("rm_response_code", sa.Integer(), nullable=True),
        sa.Column("rm_response_summary", postgresql.JSONB(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("idempotency_key", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
    )

    # ------------------------------------------------------------------
    # rm_webhook_events
    # ------------------------------------------------------------------
    op.create_table(
        "rm_webhook_events",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("uuid_generate_v4()"),
        ),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("rm_location_id", sa.String(), nullable=True),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("entity_id", sa.String(), nullable=True),
        sa.Column("parent_entity_id", sa.String(), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(), nullable=False),
        sa.Column("forwarded_to", sa.String(), nullable=True),
        sa.Column("forwarded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.ForeignKeyConstraint(
            ["company_id"], ["companies.id"], ondelete="SET NULL"
        ),
    )

    # ------------------------------------------------------------------
    # Indexes
    # ------------------------------------------------------------------
    op.create_index("idx_operation_log_company_id", "operation_log", ["company_id"])
    op.create_index("idx_operation_log_created_at", "operation_log", ["created_at"])
    op.create_index("idx_operation_log_platform_source", "operation_log", ["platform_source"])
    op.create_index("idx_idempotency_records_expires_at", "idempotency_records", ["expires_at"])
    op.create_index("idx_companies_deleted_at", "companies", ["deleted_at"])
    op.create_index("idx_companies_is_active", "companies", ["is_active"])

    # ------------------------------------------------------------------
    # Immutability trigger on operation_log
    # Prevents any UPDATE or DELETE — rows are write-once forever.
    # ------------------------------------------------------------------
    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_operation_log_mutation()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION
                'operation_log is immutable — rows cannot be updated or deleted. '
                'operation_id: %, operation: %, created_at: %',
                OLD.id, OLD.operation, OLD.created_at;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER trg_operation_log_immutable
        BEFORE UPDATE OR DELETE ON operation_log
        FOR EACH ROW EXECUTE FUNCTION prevent_operation_log_mutation();
    """)

    # ------------------------------------------------------------------
    # updated_at auto-update trigger (companies, rm_credentials, rm_auth_tokens)
    # ------------------------------------------------------------------
    op.execute("""
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    for table in ("companies", "rm_credentials", "rm_auth_tokens"):
        op.execute(f"""
            CREATE TRIGGER trg_{table}_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """)


def downgrade() -> None:
    # Drop triggers first
    for table in ("companies", "rm_credentials", "rm_auth_tokens"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_updated_at ON {table}")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")

    op.execute(
        "DROP TRIGGER IF EXISTS trg_operation_log_immutable ON operation_log"
    )
    op.execute("DROP FUNCTION IF EXISTS prevent_operation_log_mutation()")

    # Drop indexes
    op.drop_index("idx_companies_is_active", table_name="companies")
    op.drop_index("idx_companies_deleted_at", table_name="companies")
    op.drop_index("idx_idempotency_records_expires_at", table_name="idempotency_records")
    op.drop_index("idx_operation_log_platform_source", table_name="operation_log")
    op.drop_index("idx_operation_log_created_at", table_name="operation_log")
    op.drop_index("idx_operation_log_company_id", table_name="operation_log")

    # Drop tables in reverse FK order
    op.drop_table("rm_webhook_events")
    op.drop_table("operation_log")
    op.drop_table("service_api_keys")
    op.drop_table("idempotency_records")
    op.drop_table("rm_auth_tokens")
    op.drop_table("rm_locations")
    op.drop_table("rm_credentials")
    op.drop_table("companies")
