# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stripe billing routes: checkout, customer portal, webhook."""

import logging
from pathlib import Path

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import get_current_user
from app.core.audit import record_event
from app.core.config import settings
from app.db.base import get_db
from app.db.models import TierEnum, User
from app.models.schemas import CheckoutRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["Billing"])

_TIER_TO_PRICE: dict[str, str] = {
    "pro": settings.stripe_pro_price_id,
    "business": settings.stripe_business_price_id,
}

_PRICE_TO_TIER: dict[str, TierEnum] = {}  # populated after Stripe prices are set


def _app_url(path: str) -> str:
    """Build an absolute URL on this deployment's public base.

    Stripe Checkout / Customer-Portal sessions need fully-qualified
    success/cancel/return URLs. They must point at *this* deployment —
    never a hardcoded ``filemorph.io`` — so a self-hoster's users land
    back on the self-hoster's own dashboard, not ours. Mirrors the same
    ``settings.app_base_url`` treatment used for outbound-email links.
    """
    return f"{settings.app_base_url.rstrip('/')}{path}"


def _stripe_enabled() -> None:
    if not settings.stripe_secret_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Billing not configured."
        )


@router.post("/checkout/{tier}")
async def create_checkout_session(
    tier: str,
    body: CheckoutRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a Stripe Checkout session for the given tier (pro | business).

    Requires `withdrawal_waiver_acknowledged: true` in the request body so the
    user has explicitly waived their 14-day §312g BGB / §356 (5) BGB right of
    withdrawal — the consent is recorded as a SHA-256 hash-chained audit event
    so it can be reproduced at dispute time.
    """
    _stripe_enabled()
    price_id = _TIER_TO_PRICE.get(tier, "")
    if not price_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid tier.")
    if not body.withdrawal_waiver_acknowledged:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="withdrawal_waiver_required",
        )

    stripe.api_key = settings.stripe_secret_key

    customer_id = user.stripe_customer_id
    if not customer_id:
        customer = stripe.Customer.create(
            email=user.email,
            metadata={"user_id": str(user.id)},
        )
        user.stripe_customer_id = customer.id
        await db.commit()
        customer_id = customer.id

    actor_ip = request.client.host if request.client else None
    await record_event(
        event_type="billing.checkout.withdrawal_waiver_recorded",
        actor_user_id=user.id,
        actor_ip=actor_ip,
        payload={"tier": tier},
        db=db,
    )

    session = stripe.checkout.Session.create(
        customer=customer_id,
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        success_url=_app_url("/dashboard?upgraded=1"),
        cancel_url=_app_url("/pricing"),
    )
    return {"url": session.url}


@router.post("/portal")
async def customer_portal(user: User = Depends(get_current_user)):
    """Return a Stripe Billing Portal URL for the current user."""
    _stripe_enabled()
    if not user.stripe_customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No billing account found."
        )
    stripe.api_key = settings.stripe_secret_key
    session = stripe.billing_portal.Session.create(
        customer=user.stripe_customer_id,
        return_url=_app_url("/dashboard"),
    )
    return {"url": session.url}


# Stripe subscription statuses that mean "the user keeps paid access for
# now" — ``active``/``trialing`` are healthy; ``past_due``/``incomplete``
# are the dunning window where Stripe is still retrying the charge and the
# user should not be cut off mid-cycle.
_PAID_OK_STATUSES = {"active", "trialing"}
_GRACE_STATUSES = {"past_due", "incomplete"}
# Terminal — Stripe gave up (or the user/we cancelled). Drop to Free.
_TERMINAL_STATUSES = {"canceled", "unpaid", "incomplete_expired", "paused"}


@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(None, alias="stripe-signature"),
    db: AsyncSession = Depends(get_db),
):
    """Stripe webhook — keeps the user's tier + subscription_status in sync,
    and drives the dunning flow on a failed charge.

    Events handled:

    * ``customer.subscription.created`` / ``customer.subscription.updated``
      — re-derive tier from the price + subscription status. A transition
      *into* ``past_due`` records a ``billing.subscription.past_due`` audit
      event and sends the dunning email (once per dunning cycle). A
      transition *out of* a grace status back to ``active`` records
      ``billing.subscription.recovered``. A terminal status drops the tier
      to Free with ``billing.subscription.canceled``.
    * ``customer.subscription.deleted`` — tier → Free,
      ``subscription_status`` → ``canceled``.
    * ``invoice.payment_failed`` — the trigger Stripe fires on each failed
      charge attempt. We send the dunning email here (debounced via
      ``subscription_status``) so the user hears about it immediately,
      rather than waiting for the slower ``subscription.updated`` event.
    """
    if not settings.stripe_webhook_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Webhook not configured."
        )

    payload = await request.body()
    try:
        stripe.api_key = settings.stripe_secret_key
        event = stripe.Webhook.construct_event(
            payload, stripe_signature or "", settings.stripe_webhook_secret
        )
    except (ValueError, stripe.error.SignatureVerificationError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook signature."
        )

    event_type: str = event["type"]
    obj = event["data"]["object"]

    if event_type in ("customer.subscription.updated", "customer.subscription.created"):
        await _sync_subscription(obj, db)
    elif event_type == "customer.subscription.deleted":
        await _sync_subscription(obj, db, force_terminal=True)
    elif event_type == "invoice.payment_failed":
        await _handle_payment_failed(obj, db)

    return {"status": "ok"}


def _tier_for_price(price_id: str) -> TierEnum | None:
    if price_id and price_id == settings.stripe_pro_price_id:
        return TierEnum.pro
    if price_id and price_id == settings.stripe_business_price_id:
        return TierEnum.business
    return None


async def _user_for_customer(customer_id: str, db: AsyncSession) -> User | None:
    from sqlalchemy import select

    if not customer_id:
        return None
    result = await db.execute(select(User).where(User.stripe_customer_id == customer_id))
    user = result.scalar_one_or_none()
    if not user:
        logger.warning("Stripe webhook: no user found for customer %s", customer_id)
    return user


async def _sync_subscription(
    subscription: dict, db: AsyncSession, *, force_terminal: bool = False
) -> None:
    """Mirror a Stripe subscription onto the user row.

    ``force_terminal`` is set for the ``customer.subscription.deleted``
    event, which carries the last-known status (often still ``active``);
    we treat that event as terminal regardless.
    """
    user = await _user_for_customer(subscription.get("customer", ""), db)
    if not user:
        return

    status_str: str = "canceled" if force_terminal else str(subscription.get("status", ""))
    prev_status = user.subscription_status

    price_id = ""
    try:
        price_id = subscription["items"]["data"][0]["price"]["id"]
    except (KeyError, IndexError, TypeError):
        pass

    if force_terminal or status_str in _TERMINAL_STATUSES:
        user.tier = TierEnum.free
        user.subscription_status = status_str or "canceled"
        await db.commit()
        await record_event(
            event_type="billing.subscription.canceled",
            actor_user_id=user.id,
            payload={"prev_status": prev_status, "status": user.subscription_status},
            db=db,
        )
        logger.info("User %s subscription terminal (%s) — tier → free", user.id, status_str)
        return

    if status_str in _GRACE_STATUSES:
        # Keep the current tier — Stripe is still retrying. Record the
        # entry into the dunning window once, and fire the dunning email
        # once (debounced on prev_status).
        user.subscription_status = status_str
        await db.commit()
        if prev_status not in _GRACE_STATUSES:
            await record_event(
                event_type="billing.subscription.past_due",
                actor_user_id=user.id,
                payload={"prev_status": prev_status, "status": status_str},
                db=db,
            )
            await _send_dunning_email(user, next_attempt_ts=None, db=db)
        logger.info(
            "User %s subscription %s — keeping tier %s (grace)", user.id, status_str, user.tier
        )
        return

    if status_str in _PAID_OK_STATUSES:
        new_tier = _tier_for_price(price_id)
        if new_tier is not None:
            user.tier = new_tier
        recovered = prev_status in _GRACE_STATUSES
        user.subscription_status = status_str
        await db.commit()
        if recovered:
            await record_event(
                event_type="billing.subscription.recovered",
                actor_user_id=user.id,
                payload={"prev_status": prev_status, "status": status_str, "tier": user.tier.value},
                db=db,
            )
        logger.info("User %s subscription %s — tier %s", user.id, status_str, user.tier)
        return

    # Unknown status (Stripe added one we don't model) — record it,
    # don't touch the tier. Conservative: never escalate or downgrade on
    # a status we don't understand.
    user.subscription_status = status_str or prev_status
    await db.commit()
    logger.info("User %s subscription unknown status %r — tier unchanged", user.id, status_str)


async def _handle_payment_failed(invoice: dict, db: AsyncSession) -> None:
    """``invoice.payment_failed`` — send the dunning email, debounced.

    Stripe fires this on *each* retry. We only mail on the first failure
    of a cycle (``subscription_status`` not already a grace status) so the
    user gets one email, not four. The subsequent
    ``customer.subscription.updated → past_due`` event will set the status
    flag if this event arrived first; we set it here too so the debounce
    works regardless of event ordering.
    """
    user = await _user_for_customer(invoice.get("customer", ""), db)
    if not user:
        return

    already_dunning = user.subscription_status in _GRACE_STATUSES
    user.subscription_status = "past_due"
    await db.commit()

    if not already_dunning:
        next_attempt_ts = invoice.get("next_payment_attempt")  # unix ts or None
        await record_event(
            event_type="billing.subscription.payment_failed",
            actor_user_id=user.id,
            payload={
                "invoice_id": invoice.get("id"),
                "amount_due": invoice.get("amount_due"),
                "next_payment_attempt": next_attempt_ts,
            },
            db=db,
        )
        await _send_dunning_email(user, next_attempt_ts=next_attempt_ts, db=db)
        logger.info("User %s payment failed — dunning email sent", user.id)


# ── Dunning email ─────────────────────────────────────────────────────────────

_DUNNING_EMAIL_ENV = Environment(
    loader=FileSystemLoader(
        str(Path(__file__).resolve().parent.parent.parent / "templates" / "emails")
    ),
    autoescape=select_autoescape(["html"]),
)

_TIER_LABELS = {TierEnum.pro: "Pro", TierEnum.business: "Business"}


async def _send_dunning_email(user: User, *, next_attempt_ts: int | None, db: AsyncSession) -> None:
    """Render + send the "payment failed, update your card" email.

    Fire-and-forget: a send failure logs (inside ``send_email``) but never
    raises into the webhook, so Stripe still gets its 200 and won't retry
    the webhook itself. The dunning email is a courtesy on top of Stripe's
    own dunning emails (if the operator enabled them in the Stripe
    dashboard) — losing it is not data loss.
    """
    from datetime import datetime, timezone

    from app.core import email as email_mod

    next_attempt_date = None
    if next_attempt_ts:
        next_attempt_date = datetime.fromtimestamp(next_attempt_ts, tz=timezone.utc).strftime(
            "%Y-%m-%d"
        )

    ctx = {
        "user_email": user.email,
        "tier_label": _TIER_LABELS.get(user.tier, "paid"),
        "next_attempt_date": next_attempt_date,
        "billing_url": f"{settings.app_base_url.rstrip('/')}/dashboard",
        "app_base_url": settings.app_base_url,
    }
    try:
        html = _DUNNING_EMAIL_ENV.get_template("dunning.html").render(**ctx)
        text = _DUNNING_EMAIL_ENV.get_template("dunning.txt").render(**ctx)
        await email_mod.send_email(
            to=user.email,
            subject="Action needed: your FileMorph payment failed",
            html=html,
            text=text,
        )
        await record_event(
            event_type="billing.dunning_email_sent",
            actor_user_id=user.id,
            payload={"tier": user.tier.value, "next_payment_attempt": next_attempt_ts},
            db=db,
        )
    except Exception:
        logger.warning("dunning email failed for user %s", user.id, exc_info=True)
