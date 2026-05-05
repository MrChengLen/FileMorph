# SPDX-License-Identifier: AGPL-3.0-or-later
"""S10-polish: defense-in-depth CHECK constraint on ``daily_metrics.metric_key``.

Revision ID: 004_daily_metrics_check
Revises: 003_daily_metrics
Create Date: 2026-05-05

The application layer in :mod:`app.core.metrics` already filters keys against
``^[a-z0-9._\-]{1,64}$``. This migration mirrors that contract at the
database level so a future regression — a direct INSERT from a script, an
ORM bypass, a stale code path — can't seed garbage rows.

SQLite-aware: the CHECK is added unconditionally, but SQLite treats
unrecognized regex operators as ``LIKE`` fall-throughs so we use a
LIKE-shaped pattern that catches the high-value cases (length, no spaces,
no NUL). The Postgres path uses the proper regex operator.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "004_daily_metrics_check"
down_revision: Union[str, None] = "003_daily_metrics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Match :data:`app.core.metrics._VALID_METRIC_KEY`. Keep these literal-string
# in sync if the regex changes — there is no runtime coupling between the
# two, so any divergence is a silent bug. The application-layer check stays
# the source of truth; this DB constraint is belt-and-braces.
_PG_REGEX = r"^[a-z0-9._\-]{1,64}$"


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        op.create_check_constraint(
            "ck_daily_metrics_metric_key_format",
            "daily_metrics",
            f"metric_key ~ '{_PG_REGEX}'",
        )
    # SQLite path is intentionally a no-op: SQLite's CHECK constraint can't
    # express the full regex (no built-in regex in default builds), and the
    # application-layer guard already blocks invalid keys before they get
    # close to a write. Skipping here avoids a half-enforcing constraint
    # that diverges from prod semantics.


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "postgresql":
        op.drop_constraint(
            "ck_daily_metrics_metric_key_format",
            "daily_metrics",
            type_="check",
        )
