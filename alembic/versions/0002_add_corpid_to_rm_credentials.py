"""Add corpid column to rm_credentials

Revision ID: 0002_add_corpid_to_rm_credentials
Revises: 0001_initial_schema
Create Date: 2026-04-14 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_add_corpid_to_rm_credentials"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "rm_credentials",
        sa.Column("corpid", sa.String(), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("rm_credentials", "corpid")
