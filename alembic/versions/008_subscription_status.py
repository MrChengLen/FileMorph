# SPDX-License-Identifier: AGPL-3.0-or-later
"""PR-J: users.subscription_status for Stripe dunning.

Revision ID: 008_subscription_status
Revises: 007_usage_quota_index
Create Date: 2026-05-09

A nullable string column mirroring Stripe's ``Subscription.status`` from
the billing webhook. NULL = never subscribed (or pre-PR-J). The webhook
writes whatever Stripe sends (``active`` / ``trialing`` / ``past_due`` /
``unpaid`` / ``canceled`` / ``incomplete`` / ``incomplete_expired``);
the dashboard reads it to surface a "payment issue" banner; the dunning-
email debounce keys off it.

No CHECK constraint — Stripe owns the value space and may add new statuses
(it has done so before, e.g. ``paused``). Validating against a frozen
enum here would mean a Stripe-side addition silently breaks the webhook.
The application treats unknown statuses conservatively (keep current tier,
record the string) so a new status degrades gracefully.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "008_subscription_status"
down_revision: Union[str, None] = "007_usage_quota_index"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("subscription_status", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "subscription_status")
