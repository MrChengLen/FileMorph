# SPDX-License-Identifier: AGPL-3.0-or-later
"""Audit log: entries older than three years may be deleted; TRUNCATE may not.

Revision ID: 015_audit_retention
Revises: 014_audit_drop_actor_ip
Create Date: 2026-11-24

The audit log is kept for three years: once a day the app deletes the older
entries (``delete_expired_events`` in ``app/core/audit.py``). The trigger
function of migrations 005 and 012 refuses every DELETE; it now lets through
the deletion of a row whose ``occurred_at`` lies more than three years before
``now()``, the start of the deleting transaction. The app's DELETE measures
from the same moment, so the trigger passes every row it picks. Deleting a
younger row is refused as before, also with the app's own login.

``interval '3 years'`` counts calendar years (29 February goes back to
28 February), as ``RETENTION_YEARS`` in the app does;
``tests/test_audit_postgres.py`` checks both sides of the boundary.

Two hardenings on the way:

- A statement trigger refuses TRUNCATE, which the row triggers of migration
  005 never saw: it emptied the table, younger entries included, with every
  trigger on. The table's owner can still switch the triggers off.
- The function runs with ``search_path = pg_catalog, pg_temp``, so no
  function or operator planted in another schema can stand in for ``now()``
  or ``<``; ``public.users`` stays qualified as in migration 012.

The UPDATE branch is migration 012's, unchanged. The downgrade drops the
TRUNCATE trigger and restores migration 012's function. After a retention
run, code from before this migration reports the oldest entry as broken: it
expects the chain to start at the genesis value. Postgres only, like the
triggers themselves.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "015_audit_retention"
down_revision: Union[str, None] = "014_audit_drop_actor_ip"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# CREATE OR REPLACE keeps the function's identity, so migration 005's two
# row triggers stay bound to it. For a DELETE, a BEFORE ROW trigger that
# returns OLD lets the row go; RAISE refuses the whole statement, as it does
# for TRUNCATE, which neither branch matches.
_ALLOW_EXPIRED_DELETION = """
CREATE OR REPLACE FUNCTION audit_events_block_modification()
RETURNS TRIGGER
SET search_path = pg_catalog, pg_temp
AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF OLD.actor_user_id IS NOT NULL
           AND NEW.actor_user_id IS NULL
           AND (to_jsonb(NEW) - 'actor_user_id') = (to_jsonb(OLD) - 'actor_user_id')
           AND NOT EXISTS (SELECT 1 FROM public.users WHERE id = OLD.actor_user_id) THEN
            RETURN NEW;
        END IF;
    ELSIF TG_OP = 'DELETE' THEN
        IF OLD.occurred_at < now() - interval '3 years' THEN
            RETURN OLD;
        END IF;
    END IF;
    RAISE EXCEPTION
        'audit_events is append-only; % is not permitted',
        TG_OP;
END;
$$ LANGUAGE plpgsql;
"""

_BLOCK_TRUNCATE = """
CREATE TRIGGER audit_events_no_truncate
BEFORE TRUNCATE ON audit_events
FOR EACH STATEMENT EXECUTE FUNCTION audit_events_block_modification();
"""

# Migration 012's function, verbatim.
_ALLOW_ACTOR_ERASURE = """
CREATE OR REPLACE FUNCTION audit_events_block_modification()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF OLD.actor_user_id IS NOT NULL
           AND NEW.actor_user_id IS NULL
           AND (to_jsonb(NEW) - 'actor_user_id') = (to_jsonb(OLD) - 'actor_user_id')
           AND NOT EXISTS (SELECT 1 FROM public.users WHERE id = OLD.actor_user_id) THEN
            RETURN NEW;
        END IF;
    END IF;
    RAISE EXCEPTION
        'audit_events is append-only; % is not permitted',
        TG_OP;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(_ALLOW_EXPIRED_DELETION)
        op.execute(_BLOCK_TRUNCATE)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS audit_events_no_truncate ON audit_events;")
        op.execute(_ALLOW_ACTOR_ERASURE)
