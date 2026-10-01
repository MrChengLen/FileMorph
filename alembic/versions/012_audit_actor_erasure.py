# SPDX-License-Identifier: AGPL-3.0-or-later
"""Let an account deletion null ``audit_events.actor_user_id``.

Revision ID: 012_audit_actor_erasure
Revises: 011_ai_usage
Create Date: 2026-09-29

Migration 005 gave ``audit_events.actor_user_id`` an ``ON DELETE SET NULL``
foreign key, so that deleting an account (GDPR Art. 17) keeps its audit rows
but drops their link to the person. The same migration made the table
append-only with a trigger that raises on every UPDATE. Postgres carries out
SET NULL as an UPDATE of the referencing rows, so the trigger refused it and
the whole ``DELETE FROM users`` failed. Every registered account has audit
rows naming it (registration, login), so self-service deletion of a free
account failed with a 500 and deleted nothing.

The trigger function now lets exactly that change through: ``actor_user_id``
goes from a value to NULL, nothing else in the row changes, and the ``users``
row it named no longer exists. Only deleting that account produces this
combination. A direct UPDATE of a live account's rows, and every other
UPDATE or DELETE, is still refused. The rest of the row is
compared as a whole (``to_jsonb(row) - 'actor_user_id'``) rather than column
by column, so a column added later is covered too and dropping one cannot
break the function. ``actor_user_id`` is not an input to ``record_hash``, so
``verify_chain`` still passes.

Postgres only, like the trigger itself; SQLite (the test harness) never had
it. ``tests/test_audit_postgres.py`` runs this against a real Postgres in CI.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "012_audit_actor_erasure"
down_revision: Union[str, None] = "011_ai_usage"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# CREATE OR REPLACE keeps the function's identity, so migration 005's two
# triggers (audit_events_no_update, audit_events_no_delete) stay bound to it;
# a later exception has to re-issue the whole function. NEW is read only for
# an UPDATE; a DELETE trigger has none. The lookup names public.users because
# a session's temporary tables come first in the search path, so a temporary
# "users" could answer it otherwise. The migrations create the tables in the
# connecting role's current schema, public unless configured otherwise; where
# they live elsewhere, the lookup fails and the deletion is refused.
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

# Migration 005's function, verbatim.
_BLOCK_EVERYTHING = """
CREATE OR REPLACE FUNCTION audit_events_block_modification()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        'audit_events is append-only; % is not permitted',
        TG_OP;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(_ALLOW_ACTOR_ERASURE)


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(_BLOCK_EVERYTHING)
