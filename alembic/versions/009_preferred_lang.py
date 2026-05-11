# SPDX-License-Identifier: AGPL-3.0-or-later
"""PR-i18n-3: users.preferred_lang for outbound-email locale.

Revision ID: 009_preferred_lang
Revises: 008_subscription_status
Create Date: 2026-05-11

A short nullable string holding the language FileMorph sends transactional
email to this user in (``de`` / ``en``). NULL = no explicit preference →
the application falls back to ``settings.lang_default`` (the ``LANG_DEFAULT``
env-var, default ``de``).

Why a column rather than reusing the request locale: email is rendered
outside any HTTP request — the verification mail is fire-and-forget at
register time, the dunning mail is fired from a Stripe webhook — so there
is no ``Accept-Language`` / URL-prefix signal at send time. The column is
seeded at registration from the locale the user signed up in and is
changeable from the dashboard.

``String(5)`` is generous for the two-letter codes we support today and
leaves room for a ``xx-YY`` regional variant later. No CHECK constraint:
the write path validates against the supported-locale tuple
(``app/core/i18n.py::SUPPORTED_LOCALES``), and an unrecognised value
read back simply falls through to the default — a frozen DB enum would
just be a second place to update when a locale is added.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009_preferred_lang"
down_revision: Union[str, None] = "008_subscription_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("preferred_lang", sa.String(length=5), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "preferred_lang")
