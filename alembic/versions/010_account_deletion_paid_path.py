# SPDX-License-Identifier: AGPL-3.0-or-later
"""PR-D: account-deletion paid-path tax-retention schema.

Revision ID: 010_account_deletion_paid_path
Revises: 009_preferred_lang
Create Date: 2026-05-12

Slice c.2 of ``docs/gdpr-account-deletion-design.md``. The paid-path
delete keeps the ``users`` row in a restricted state — German tax law
(HGB §257 Abs. 1 Nr. 4 + Abs. 4, AO §147 Abs. 1+3) obliges a 10-year
retention of the invoice → customer link, and DSGVO Art. 17(3)(b)
permits exactly that. This migration adds the marker the (future) purge
job keys on and swaps the unconditional uniqueness on ``users.email``
for a partial one so a customer can re-register after a paid-path
delete.

Schema changes

- ``users.deleted_at TIMESTAMPTZ NULL`` — set to ``NOW()`` only on the
  paid-path delete; NULL on every live account. The purge job (its own
  sprint) hard-deletes rows where
  ``deleted_at < NOW() - INTERVAL '10 years 6 months'``.
- The column-level ``UNIQUE`` on ``users.email`` (Postgres auto-named
  ``users_email_key``) is replaced by a partial unique index
  ``ix_users_email_active ON users(email) WHERE deleted_at IS NULL``.
  A tax-retained row keeps its email for the record but no longer
  occupies the uniqueness slot. The constraint drop is Postgres-only:
  SQLite cannot ``ALTER TABLE … DROP CONSTRAINT`` and the test harness
  builds its schema from ``Base.metadata.create_all()`` (which already
  has the partial index via ``sqlite_where=``), so this migration runs
  against Postgres only — same pattern as the Postgres-only trigger in
  migration 005.
- The plain non-unique ``ix_users_email`` index is left untouched (it
  serves ``WHERE email = ?`` lookups that don't carry the
  ``deleted_at IS NULL`` predicate).
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "010_account_deletion_paid_path"
down_revision: Union[str, None] = "009_preferred_lang"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Drop the unconditional UNIQUE that ``email = mapped_column(unique=True)``
        # generated; the partial index below takes over enforcement.
        op.drop_constraint("users_email_key", "users", type_="unique")

    op.create_index(
        "ix_users_email_active",
        "users",
        ["email"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
        sqlite_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_users_email_active", table_name="users")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.create_unique_constraint("users_email_key", "users", ["email"])

    op.drop_column("users", "deleted_at")
