# SPDX-License-Identifier: AGPL-3.0-or-later
"""Account-deletion execution (DSGVO Art. 17) — the data-side core.

Two paths, per ``docs/gdpr-account-deletion-design.md`` §§ 4 + 5.B:

* **free** — full hard-delete of the ``users`` row; PostgreSQL clears the
  related rows via the ``ON DELETE`` clauses (``api_keys`` CASCADE,
  ``file_jobs`` / ``usage`` SET NULL).
* **tax_retained** — the account has touched Stripe (``stripe_customer_id``
  set); German tax law (HGB §257, AO §147) obliges a 10-year retention of
  the invoice → customer link, permitted by DSGVO Art. 17(3)(b). The
  ``users`` row is *kept* in a restricted state — only ``email``,
  ``stripe_customer_id``, ``tier``, ``created_at`` survive; everything else
  is nulled / sentinelled and ``deleted_at`` is stamped. ``api_keys`` are
  still hard-deleted, ``file_jobs`` / ``usage`` still anonymised — but
  because the ``users`` row stays, the FK cascades don't fire, so we do
  that work explicitly with bulk Core statements (which also side-step the
  ORM unit-of-work, avoiding the lazy-load-on-async-session
  ``MissingGreenlet`` the free path has to dodge with ``selectinload``).

This module imports only the ORM models, ``app.core.auth`` and
``app.core.billing`` — no FastAPI — so it's unit-testable directly and
carries no import-cycle risk back to the routes.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import func

from app.core.auth import deleted_password_sentinel
from app.core.billing import cancel_active_subscriptions
from app.db.models import ApiKey, FileJob, RoleEnum, UsageRecord, User

# Conservative trigger (see ``docs/gdpr-account-deletion-design.md`` § 5.B
# and the PR-D plan's Out-of-Scope #5): a Stripe customer id is enough to
# take the tax-retained path. The design doc's finer "ever had an active
# subscription" condition would need a Stripe round-trip to decide; over-
# retaining a minimal invoice-link record for an abandoned-checkout account
# (which Stripe itself keeps a customer record for) is strictly safer than
# the opposite mistake — wrongly hard-deleting a paying customer.
TAX_RETAINED = "tax_retained"
FREE = "free"


def deletion_mode_for(user: User) -> str:
    """Return ``"tax_retained"`` if the account must keep a tax record,
    else ``"free"``. One place, so the route's audit payload and
    :func:`perform_account_deletion` can't drift apart."""
    return TAX_RETAINED if user.stripe_customer_id is not None else FREE


async def perform_account_deletion(db: AsyncSession, user: User, mode: str) -> str:
    """Execute the deletion. The caller has already passed the three-field
    re-confirmation gate and the last-admin guard.

    Returns the deletion timestamp as an ISO-8601 UTC string (the
    confirmation email and the structured log echo it).
    """
    deleted_at_iso = datetime.now(timezone.utc).isoformat()

    if mode == TAX_RETAINED:
        # Cancel-first: stop any live Stripe billing before we touch the
        # database. A Stripe error propagates out of here; the caller maps
        # it to 500 and nothing below has run, so the account is unchanged.
        if user.stripe_customer_id is not None:
            await cancel_active_subscriptions(user.stripe_customer_id)

        # The ``users`` row is retained, so the ON DELETE cascades won't
        # fire — do the equivalent work explicitly. Bulk Core statements,
        # not ORM relationship manipulation: ``user.api_keys.clear()`` would
        # lazy-load the collection on the async session (MissingGreenlet),
        # and there's no relationship path for the SET NULL anyway. These
        # run before the row mutation; they key on ``user.id`` (the PK,
        # unchanged), so the order is deterministic and a single ``commit``
        # at the end is one transaction.
        await db.execute(delete(ApiKey).where(ApiKey.user_id == user.id))
        await db.execute(update(FileJob).where(FileJob.user_id == user.id).values(user_id=None))
        await db.execute(
            update(UsageRecord).where(UsageRecord.user_id == user.id).values(user_id=None)
        )

        # Restricted state: keep only what HGB §257 / AO §147 require to
        # reconcile an invoice to a person during a tax audit.
        user.password_hash = deleted_password_sentinel()
        user.is_active = False
        user.role = RoleEnum.user
        user.deleted_at = func.now()
        user.email_verified_at = None
        user.preferred_lang = None
        user.subscription_status = None
        await db.commit()
        return deleted_at_iso

    # Free path — full hard-delete. ``cascade="all, delete-orphan"`` on
    # ``User.api_keys`` would lazy-load the collection during flush, which
    # raises MissingGreenlet on the async session if any keys exist; re-
    # fetch with ``selectinload`` so the relationship is preloaded before
    # ``db.delete`` walks the cascade.
    result = await db.execute(
        select(User).where(User.id == user.id).options(selectinload(User.api_keys))
    )
    fetched = result.scalar_one()
    await db.delete(fetched)
    await db.commit()
    return deleted_at_iso
