# SPDX-License-Identifier: AGPL-3.0-or-later
"""Compliance Edition: tamper-evident audit_events table with hash chain.

Revision ID: 005_audit_events
Revises: 004_daily_metrics_check
Create Date: 2026-05-05

Each row records one operation; the ``record_hash`` is computed as
``SHA-256(prev_hash || canonical_record)`` so any retroactive edit
breaks the chain from that row onward and is detected by the
verification CLI. The first row in any deployment carries
``prev_hash = '0' * 64`` (genesis sentinel).

Schema decisions

- ``id`` is a monotonic BigInt rather than a UUID. Hash-chain
  verification walks rows in order; a numeric PK gives both insertion
  order (via DB sequence / autoincrement) and an O(1) "next row" lookup
  without a secondary index.
- ``occurred_at`` uses ``timezone=True`` so the chain is interpretable
  across deployments in different time zones. We stamp on the server
  side (server_default=now()) so an attacker who controls the client
  cannot rewrite history with future timestamps.
- ``actor_user_id`` is nullable + ON DELETE SET NULL so an Art. 17
  account-deletion can NULL the FK without destroying the audit row;
  the chain stays verifiable even if the user record disappears.
- ``payload_json`` is the canonical-JSON serialisation of the event
  details (sorted keys, no whitespace) — that's what the hash covers.
- ``record_hash`` is UNIQUE so a duplicate-write race or replay attack
  cannot insert a second row with the same hash; insertion fails loudly
  rather than silently corrupting the chain.

The Postgres-side append-only trigger (UPDATE / DELETE → raise) is in a
separate migration step below so it runs only on Postgres — the SQLite
test harness skips it.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005_audit_events"
down_revision: Union[str, None] = "004_daily_metrics_check"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column(
            "actor_user_id",
            sa.dialects.postgresql.UUID(as_uuid=True).with_variant(sa.String(length=36), "sqlite"),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("actor_ip", sa.String(length=45), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("prev_hash", sa.String(length=64), nullable=False),
        sa.Column("record_hash", sa.String(length=64), nullable=False),
        sa.UniqueConstraint("record_hash", name="uq_audit_events_record_hash"),
    )
    op.create_index("ix_audit_events_occurred_at", "audit_events", ["occurred_at"])
    op.create_index("ix_audit_events_event_type", "audit_events", ["event_type"])
    op.create_index("ix_audit_events_actor_user_id", "audit_events", ["actor_user_id"])

    # Postgres-only: append-only enforcement at the database layer. UPDATE
    # and DELETE on audit_events raise EXCEPTION, so even a compromised
    # application credential cannot rewrite the chain. Cleanup of expired
    # rows (retention policy) is done by a privileged maintenance role
    # that explicitly disables this trigger; production deployments should
    # restrict that role.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION audit_events_block_modification()
            RETURNS TRIGGER AS $$
            BEGIN
                RAISE EXCEPTION
                    'audit_events is append-only; % is not permitted',
                    TG_OP;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            CREATE TRIGGER audit_events_no_update
            BEFORE UPDATE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION audit_events_block_modification();
            """
        )
        op.execute(
            """
            CREATE TRIGGER audit_events_no_delete
            BEFORE DELETE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION audit_events_block_modification();
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS audit_events_no_delete ON audit_events;")
        op.execute("DROP TRIGGER IF EXISTS audit_events_no_update ON audit_events;")
        op.execute("DROP FUNCTION IF EXISTS audit_events_block_modification();")
    op.drop_index("ix_audit_events_actor_user_id", table_name="audit_events")
    op.drop_index("ix_audit_events_event_type", table_name="audit_events")
    op.drop_index("ix_audit_events_occurred_at", table_name="audit_events")
    op.drop_table("audit_events")
