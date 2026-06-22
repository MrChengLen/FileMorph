# SPDX-License-Identifier: AGPL-3.0-or-later
"""CP5: AI credit ledger (ai_usage) for the Enterprise-Edition AI add-on.

Revision ID: 011_ai_usage
Revises: 010_account_deletion_paid_path
Create Date: 2026-06-20

One row per charged AI operation (:class:`app.db.models.AiUsageRecord`).
Powers the per-tier monthly AI-credit gate and the dashboard balance. Counts
*credits* (the business unit) — never the euro cost or provider token count,
which live in deployment env so the margin is not derivable from the schema.

SQLite (test harness) builds the schema from ``Base.metadata.create_all``, so
this migration runs against Postgres; the model carries the same two indexes.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "011_ai_usage"
down_revision: Union[str, None] = "010_account_deletion_paid_path"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_usage",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column("credits_charged", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("used_llm", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_ai_usage_user_id_timestamp", "ai_usage", ["user_id", "timestamp"])
    op.create_index("ix_ai_usage_operation", "ai_usage", ["operation"])


def downgrade() -> None:
    op.drop_index("ix_ai_usage_operation", table_name="ai_usage")
    op.drop_index("ix_ai_usage_user_id_timestamp", table_name="ai_usage")
    op.drop_table("ai_usage")
