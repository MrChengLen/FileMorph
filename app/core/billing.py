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
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import stripe

from app.core.config import settings

logger = logging.getLogger(__name__)

# Subscriptions a customer is still being billed for — the ones a
# cancellation has to end. ``past_due`` counts: Stripe keeps retrying the
# charge and the paid plan stays on during that window.
_LIVE_STATUSES = frozenset({"active", "trialing", "past_due"})


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


@dataclass(frozen=True)
class PeriodEndCancellation:
    """What :func:`cancel_subscription_at_period_end` did.

    ``manual_reason`` is ``None`` when the subscription was set to end with
    its current billing period; ``ends_at`` is then that moment, or ``None``
    if Stripe didn't report it. Otherwise nothing was changed in Stripe and
    ``manual_reason`` says why a person has to handle the cancellation:
    ``no_live_subscription``, ``multiple_subscriptions``,
    ``contract_mismatch`` or ``stripe_error``.
    """

    manual_reason: str | None = None
    ends_at: datetime | None = None


def _dig(obj: Any, *path: str | int) -> Any:
    """``obj[path[0]][path[1]]…``, or ``None`` as soon as a step is missing.

    Item access only: in the pinned SDK a ``StripeObject`` is not a ``dict``
    (``.get()`` raises ``AttributeError``); in older releases it was, and
    ``sub.items`` was the dict method rather than the field. ``obj[key]``
    means the field in both.
    """
    for key in path:
        try:
            obj = obj[key]
        except (KeyError, IndexError, TypeError):
            return None
    return obj


async def cancel_subscription_at_period_end(
    customer_id: str, price_id: str
) -> PeriodEndCancellation:
    """Let the customer's one live subscription of ``price_id`` end with its
    current billing period (``cancel_at_period_end``) — the ordinary
    cancellation "at the earliest possible date".

    Only acts when the case is unambiguous: exactly one live subscription
    (``active`` / ``trialing`` / ``past_due``) and it bills ``price_id``.
    Anything else changes nothing and comes back as a ``manual_reason``.
    Setting the flag again on an already-cancelling subscription is a
    harmless repeat, so a resubmitted form confirms the same end date.

    ``stripe.StripeError`` propagates; the caller decides what that means
    for the user. No-ops (``stripe_error``, nothing called) when
    ``STRIPE_SECRET_KEY`` is unset, like :func:`cancel_active_subscriptions`.
    ``limit=10`` covers every real customer without paging.
    """
    if not settings.stripe_secret_key:
        logger.warning(
            "cancel_subscription_at_period_end: STRIPE_SECRET_KEY unset; no-op for customer %s",
            customer_id,
        )
        return PeriodEndCancellation(manual_reason="stripe_error")

    stripe.api_key = settings.stripe_secret_key
    subscriptions = await asyncio.to_thread(
        stripe.Subscription.list, customer=customer_id, status="all", limit=10
    )
    live = [sub for sub in subscriptions.data if _dig(sub, "status") in _LIVE_STATUSES]
    if not live:
        return PeriodEndCancellation(manual_reason="no_live_subscription")
    if len(live) > 1:
        return PeriodEndCancellation(manual_reason="multiple_subscriptions")
    sub = live[0]
    if not price_id or not any(
        _dig(item, "price", "id") == price_id for item in _dig(sub, "items", "data") or []
    ):
        return PeriodEndCancellation(manual_reason="contract_mismatch")

    updated = await asyncio.to_thread(
        stripe.Subscription.modify, sub["id"], cancel_at_period_end=True
    )
    # Newer Stripe API versions moved ``current_period_end`` from the
    # subscription onto its items; ``cancel_at`` is set by the call above.
    end_ts = (
        _dig(updated, "cancel_at")
        or _dig(updated, "items", "data", 0, "current_period_end")
        or _dig(updated, "current_period_end")
    )
    ends_at = datetime.fromtimestamp(end_ts, tz=timezone.utc) if isinstance(end_ts, int) else None
    logger.info(
        "cancel_subscription_at_period_end: %s for customer %s ends at period end",
        sub["id"],
        customer_id,
    )
    return PeriodEndCancellation(ends_at=ends_at)
