# SPDX-License-Identifier: AGPL-3.0-or-later
"""NEU-B.3 (slice b): users.email_verified_at for email-verification flow.

Revision ID: 006_email_verification
Revises: 005_audit_events
Create Date: 2026-05-06

A nullable timestamp column on the users table — NULL means "not yet
verified" (the default state after registration); a set timestamp
means "verified at that moment". We do not introduce a separate
``email_verifications`` table because:

* The verification token is a JWT bound to the user's email-at-issuance
  time (``eat`` claim). Replay-after-rotation is detected by comparing
  the token's ``eat`` against ``user.email`` at verify-time, not by a
  per-token DB row. That keeps the schema small and avoids a cleanup
  cron.
* A nullable column lets a future migration add an index or a
  ``email_verification_token_hash`` column if we ever need
  invalidation-on-resend semantics — without breaking the existing
  flow.

Idempotent: re-verifying an already-verified email is a no-op (the
column gets set to the same-or-later timestamp). The route layer
returns a 200 so a user who clicks the link twice doesn't get an
error.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "006_email_verification"
down_revision: Union[str, None] = "005_audit_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "email_verified_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "email_verified_at")
