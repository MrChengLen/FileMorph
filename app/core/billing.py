# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stripe helpers that don't depend on FastAPI.

Lives here, not in ``app/api/routes/billing.py``, to avoid an import
cycle: the route module does ``from app.api.routes.auth import
get_current_user``, and :func:`cancel_active_subscriptions` is called
from the account-deletion flow that lives under ``app/api/routes/auth.py``
(via ``app/core/account_deletion.py``). A FastAPI-free helper module is
the clean break — see ``docs/gdpr-account-deletion-design.md`` § 5.A
("Code anchor").

The Stripe SDK is synchronous (blocking HTTP), so every call goes
through :func:`asyncio.to_thread` to keep the event loop free — same
discipline the rest of the codebase applies to ffmpeg / WeasyPrint /
pikepdf (see CLAUDE.md "Event-Loop sauber halten").
"""

from __future__ import annotations

import asyncio
import logging

import stripe

from app.core.config import settings

logger = logging.getLogger(__name__)


async def cancel_active_subscriptions(customer_id: str) -> None:
    """Cancel every active Stripe subscription for ``customer_id``.

    Used by the paid-path account delete (cancel-first pattern,
    ``docs/gdpr-account-deletion-design.md`` § 5.A): a deleted account
    must not leave an orphaned subscription that keeps billing. The
    caller runs this *before* any database write — a Stripe error
    propagates out of here so the route can map it to ``500`` and leave
    the account untouched (half-deleting an account is worse than not
    deleting it).

    No-ops when ``STRIPE_SECRET_KEY`` is unset (Community-Edition
    self-host, or a Cloud deployment with billing disabled) — the same
    inert-without-its-env-var shape every other Cloud feature has.

    Note: a single customer realistically has one (maybe two) active
    subscriptions, so the unpaginated ``limit=100`` list call covers
    every real case without driving Stripe's lazy paging iterator from
    inside the event loop.
    """
    if not settings.stripe_secret_key:
        logger.warning(
            "cancel_active_subscriptions: STRIPE_SECRET_KEY unset; no-op for customer %s",
            customer_id,
        )
        return

    stripe.api_key = settings.stripe_secret_key
    subscriptions = await asyncio.to_thread(
        stripe.Subscription.list, customer=customer_id, status="active", limit=100
    )
    for sub in subscriptions.data:
        await asyncio.to_thread(stripe.Subscription.cancel, sub.id)
        logger.info(
            "cancel_active_subscriptions: cancelled %s for customer %s", sub.id, customer_id
        )
