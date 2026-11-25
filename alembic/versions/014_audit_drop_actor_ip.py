# SPDX-License-Identifier: AGPL-3.0-or-later
"""Audit log: drop ``actor_ip`` and with it the addresses older entries hold.

Revision ID: 014_audit_drop_actor_ip
Revises: 013_audit_hash_version
Create Date: 2026-11-24

Migration 005 gave every audit entry the caller's IP address in
``actor_ip``. Since 2026-10-10 the app writes none: ``record_event`` has no
parameter for one and the model no longer maps the column. The column stayed
for the entries written before; dropping it deletes their addresses.

DROP COLUMN only changes the catalogue: no row trigger fires, so the
append-only triggers (migrations 005 and 012) are not involved, and
migration 012's whole-row comparison no longer sees the column.
``tests/test_audit_postgres.py`` checks that the chain still verifies
afterwards. Postgres would keep the old values in the table's data files
until a row is rewritten, which in this table only the account-deletion
cascade does, so the upgrade rewrites the table at once: ``VACUUM FULL`` as
the table's owner,
outside a transaction (VACUUM can't run in one). It locks ``audit_events``
while it runs and needs free disk space for one copy of the table.

The VACUUM commits the DROP before Alembic records this revision; if the
start stops in between, the next start runs the upgrade again, hence
``IF EXISTS``. The downgrade adds the column back, empty: the addresses are
gone.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "014_audit_drop_actor_ip"
down_revision: Union[str, None] = "013_audit_hash_version"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        op.drop_column("audit_events", "actor_ip")
        return
    op.execute("ALTER TABLE audit_events DROP COLUMN IF EXISTS actor_ip")
    with op.get_context().autocommit_block():
        op.execute("VACUUM FULL audit_events")


def downgrade() -> None:
    op.add_column("audit_events", sa.Column("actor_ip", sa.String(length=45), nullable=True))
