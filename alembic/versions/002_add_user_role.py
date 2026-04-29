# SPDX-License-Identifier: AGPL-3.0-or-later
"""Add ``role`` column to ``users`` + supporting indexes.

Revision ID: 002_add_user_role
Revises: 001_baseline
Create Date: 2026-04-22

Sprint 6 / Phase 1: introduce role-based access control for the admin
cockpit. ``server_default='user'`` means existing rows default safely to
the non-admin role on a production upgrade; promotion is then explicit via
``scripts/promote_admin.py``.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002_add_user_role"
down_revision: Union[str, None] = "001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


role_enum = sa.Enum("user", "admin", name="role_enum")


def upgrade() -> None:
    role_enum.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "users",
        sa.Column("role", role_enum, nullable=False, server_default="user"),
    )
    op.create_index("ix_users_role", "users", ["role"])
    op.create_index("ix_users_created_at", "users", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_users_created_at", table_name="users")
    op.drop_index("ix_users_role", table_name="users")
    op.drop_column("users", "role")
    role_enum.drop(op.get_bind(), checkfirst=True)
