# SPDX-License-Identifier: AGPL-3.0-or-later
"""Baseline schema — matches ``Base.metadata`` as of Sprint 6 start.

Revision ID: 001_baseline
Revises:
Create Date: 2026-04-22

The production database was created via ``Base.metadata.create_all`` before
Alembic was introduced. Running ``alembic stamp 001_baseline`` on that
instance declares the current state as the baseline without re-running these
DDL statements. A fresh test/CI database, by contrast, runs these statements
to bootstrap the schema.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001_baseline"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


tier_enum = sa.Enum("free", "pro", "business", "enterprise", name="tier_enum")
job_status_enum = sa.Enum("processing", "done", "error", name="job_status_enum")


def _uuid_col(name: str, *args, **kwargs) -> sa.Column:
    return sa.Column(name, postgresql.UUID(as_uuid=True), *args, **kwargs)


def upgrade() -> None:
    tier_enum.create(op.get_bind(), checkfirst=True)
    job_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "users",
        _uuid_col("id", primary_key=True),
        sa.Column("email", sa.String(), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("tier", tier_enum, nullable=False, server_default="free"),
        sa.Column("stripe_customer_id", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "api_keys",
        _uuid_col("id", primary_key=True),
        _uuid_col("user_id", sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(), nullable=False, server_default=""),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"])

    op.create_table(
        "file_jobs",
        _uuid_col("id", primary_key=True),
        _uuid_col("user_id", sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("original_name", sa.String(), nullable=False),
        sa.Column("source_format", sa.String(), nullable=False),
        sa.Column("target_format", sa.String(), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("status", job_status_enum, nullable=False, server_default="processing"),
    )

    op.create_table(
        "usage",
        _uuid_col("id", primary_key=True),
        _uuid_col("user_id", sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        _uuid_col("api_key_id", sa.ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True),
        sa.Column("endpoint", sa.String(), nullable=False),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("usage")
    op.drop_table("file_jobs")
    op.drop_index("ix_api_keys_key_hash", table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
    job_status_enum.drop(op.get_bind(), checkfirst=True)
    tier_enum.drop(op.get_bind(), checkfirst=True)
