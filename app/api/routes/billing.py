# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stripe billing routes: checkout, customer portal, webhook."""

import logging

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
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
        success_url="https://filemorph.io/dashboard?upgraded=1",
        cancel_url="https://filemorph.io/pricing",
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
        return_url="https://filemorph.io/dashboard",
    )
    return {"url": session.url}


@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(None, alias="stripe-signature"),
    db: AsyncSession = Depends(get_db),
):
    """Stripe webhook — updates user tier on subscription events."""
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
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook signature."
        )

    event_type: str = event["type"]
    subscription = event["data"]["object"]

    if event_type in ("customer.subscription.updated", "customer.subscription.created"):
        await _sync_subscription(subscription, db, active=True)
    elif event_type == "customer.subscription.deleted":
        await _sync_subscription(subscription, db, active=False)

    return {"status": "ok"}


async def _sync_subscription(subscription: dict, db: AsyncSession, active: bool) -> None:
    from sqlalchemy import select

    customer_id: str = subscription.get("customer", "")
    if not customer_id:
        return

    result = await db.execute(select(User).where(User.stripe_customer_id == customer_id))
    user = result.scalar_one_or_none()
    if not user:
        logger.warning("Stripe webhook: no user found for customer %s", customer_id)
        return

    if not active:
        user.tier = TierEnum.free
    else:
        price_id: str = subscription["items"]["data"][0]["price"]["id"]
        if price_id == settings.stripe_pro_price_id:
            user.tier = TierEnum.pro
        elif price_id == settings.stripe_business_price_id:
            user.tier = TierEnum.business

    await db.commit()
    logger.info("User %s tier updated to %s", user.id, user.tier)
