# SPDX-License-Identifier: AGPL-3.0-or-later
"""S10-lite analytics: ``daily_metrics`` aggregation table.

Revision ID: 003_daily_metrics
Revises: 002_add_user_role
Create Date: 2026-05-04

Composite primary key on ``(date, metric_key)`` so each (day, metric) tuple
gets exactly one row, regardless of traffic volume. Atomic UPSERTs in
``app.core.metrics.increment`` enforce that invariant.

Counters live cheap: ~365 rows per metric per year. With 5-10 metrics in
active use, ~5k rows/year is well below any need for partitioning or
roll-up tables. Index on ``metric_key`` is for the cockpit summary's
GROUP-BY scans (e.g. top-N format pairs).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003_daily_metrics"
down_revision: Union[str, None] = "002_add_user_role"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "daily_metrics",
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("metric_key", sa.String(length=64), nullable=False),
        sa.Column("count", sa.BigInteger(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("date", "metric_key"),
    )
    op.create_index("ix_daily_metrics_metric_key", "daily_metrics", ["metric_key"])


def downgrade() -> None:
    op.drop_index("ix_daily_metrics_metric_key", table_name="daily_metrics")
    op.drop_table("daily_metrics")
