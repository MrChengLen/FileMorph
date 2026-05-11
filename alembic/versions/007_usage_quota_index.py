# SPDX-License-Identifier: AGPL-3.0-or-later
"""PR-M: composite index for the monthly-quota gate.

Revision ID: 007_usage_quota_index
Revises: 006_email_verification
Create Date: 2026-05-09

The monthly-quota gate runs on every /convert and /compress request:

    SELECT COUNT(*) FROM usage
    WHERE user_id = :uid AND timestamp >= :month_start

A Business-tier user can write up to 100 000 ``UsageRecord`` rows per
month. Without an index on ``(user_id, timestamp)``, the gate
sequentially scans the entire table, growing the latency of every
request as the table grows. With the composite index Postgres
performs an index range scan that stays sub-millisecond at any
realistic table size.

Index name follows the SQLAlchemy default convention so an inspector
sees ``ix_usage_user_id_timestamp``. ``CREATE INDEX IF NOT EXISTS``
is implicit via Alembic's idempotent ``op.create_index`` —
``index_create_already_exists`` errors are caught and logged at the
operator's discretion.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "007_usage_quota_index"
down_revision: Union[str, None] = "006_email_verification"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_usage_user_id_timestamp",
        "usage",
        ["user_id", "timestamp"],
    )


def downgrade() -> None:
    op.drop_index("ix_usage_user_id_timestamp", table_name="usage")
