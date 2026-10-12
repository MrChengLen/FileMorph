# SPDX-License-Identifier: AGPL-3.0-or-later
"""Audit log: record per row which recipe ``record_hash`` used.

Revision ID: 013_audit_hash_version
Revises: 012_audit_actor_erasure
Create Date: 2026-09-29

``app/core/audit.py`` now writes ``record_hash`` with recipe 2, over the
previous hash plus the row's ``event_type``, ``occurred_at`` and payload.
Rows already in the table were written with recipe 1 and keep verifying
with it: rehashing them would mean rewriting an append-only audit log.
The new column names the recipe per row, so ``verify_chain`` checks both
kinds in one pass.

Schema change

- ``audit_events.hash_version SMALLINT NOT NULL DEFAULT 1``. The default
  labels every existing row as recipe 1; the writer sets 2 on each new
  row. On Postgres 11 and later, ADD COLUMN with a constant default only
  touches the catalogue: no table rewrite, and no row trigger fires, so
  the append-only triggers (migrations 005 and 012) are not involved.
  They would refuse an UPDATE backfill. The default stays 1 for good:
  a writer that does not know the column hashes with recipe 1.
- ``CHECK (hash_version IN (1, 2))``, validated by one read of the table
  while the column is added. A recipe 3 ships its own migration that
  widens it. ``verify_chain`` still treats an unknown version as a
  broken row: the table owner can drop a constraint. The model does not
  mirror the CHECK (same as migration 004's), so tests can store other
  values and exercise the verifier.

The downgrade drops the column, but refuses while any row carries
another recipe than 1: the code before this migration cannot verify such
rows, and without the column nobody could tell which recipe they used.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "013_audit_hash_version"
down_revision: Union[str, None] = "012_audit_actor_erasure"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "audit_events",
        sa.Column(
            "hash_version",
            sa.SmallInteger(),
            sa.CheckConstraint("hash_version IN (1, 2)", name="ck_audit_events_hash_version"),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )


def downgrade() -> None:
    newer = (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM audit_events WHERE hash_version <> 1 LIMIT 1"))
        .first()
    )
    if newer is not None:
        raise RuntimeError(
            "audit_events has rows with hash_version <> 1, which the code before "
            "migration 013 cannot verify; refusing to drop the column"
        )
    op.drop_column("audit_events", "hash_version")
