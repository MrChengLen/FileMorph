# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stripe billing routes: checkout, customer portal, webhook, online cancellation."""

import asyncio
import hashlib
import html as html_mod
import logging
from datetime import datetime, timezone

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import get_current_user
from app.core import email as email_mod
from app.core.audit import AuditWriteError, record_event
from app.core.billing import cancel_subscription_at_period_end
from app.core.config import settings
from app.core.i18n import get_locale
from app.core.rate_limit import account_or_ip, limiter
from app.db.base import get_db
from app.db.models import TierEnum, User
from app.models.schemas import CancellationRequest, CheckoutRequest

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
@limiter.limit("5/minute", key_func=account_or_ip)
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

    await record_event(
        event_type="billing.checkout.withdrawal_waiver_recorded",
        actor_user_id=user.id,
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
@limiter.limit("5/minute", key_func=account_or_ip)
async def customer_portal(request: Request, user: User = Depends(get_current_user)):
    """Return a Stripe Billing Portal URL for the current user."""
    _stripe_enabled()
    if not user.stripe_customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No billing account found."
        )
    stripe.api_key = settings.stripe_secret_key
    # The Stripe SDK blocks on HTTP — keep it off the event loop.
    session = await asyncio.to_thread(
        stripe.billing_portal.Session.create,
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


# Deliberately unlimited: Stripe signs every delivery and retries anything
# non-2xx for days, so a 429 would only delay tier sync and dunning, while a
# forged request fails the signature check before any DB work.
@router.post("/webhook", include_in_schema=False)
@limiter.exempt
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
    except (ValueError, stripe.SignatureVerificationError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook signature."
        )

    event_type: str = event["type"]
    # stripe >= 15: a StripeObject is not a dict (its .get() raises), but the
    # handlers below read the object with .get(); to_dict() is recursive.
    obj = event["data"]["object"].to_dict()

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
    # ``deleted_at IS NULL``: a tax-retained (paid-path-deleted) row keeps
    # its ``stripe_customer_id`` for the 10-year HGB §257 record — but a
    # late webhook (the ``customer.subscription.deleted`` from our own
    # cancel-first pass, or a stray ``invoice.payment_failed``) must not
    # mutate that frozen row (set ``tier``/``subscription_status``, email a
    # dunning notice). Skip it; the handler logs "unknown customer" and
    # no-ops. See ``docs/gdpr-account-deletion-design.md`` § 5.B.
    result = await db.execute(
        select(User).where(User.stripe_customer_id == customer_id, User.deleted_at.is_(None))
    )
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

# Plan-name labels — proper nouns, not translated. Interpolated into the
# (translated) dunning-email sentences via the {% trans %} blocks.
_TIER_LABELS = {TierEnum.pro: "Pro", TierEnum.business: "Business"}


async def _send_dunning_email(user: User, *, next_attempt_ts: int | None, db: AsyncSession) -> None:
    """Render + send the "payment failed, update your card" email.

    Fire-and-forget: a send failure logs (inside ``send_email``) but never
    raises into the webhook, so Stripe still gets its 200 and won't retry
    the webhook itself. The dunning email is a courtesy on top of Stripe's
    own dunning emails (if the operator enabled them in the Stripe
    dashboard) — losing it is not data loss.

    Rendered in the user's ``preferred_lang`` — this path has no HTTP
    request to derive a locale from (it runs from a Stripe webhook), which
    is exactly why that column exists. ``render_email`` falls back to
    ``LANG_DEFAULT`` when the column is NULL.
    """
    from datetime import datetime, timezone

    from app.core import email as email_mod

    next_attempt_date = None
    if next_attempt_ts:
        next_attempt_date = datetime.fromtimestamp(next_attempt_ts, tz=timezone.utc).strftime(
            "%Y-%m-%d"
        )

    try:
        subject, html, text = email_mod.render_email(
            "dunning",
            locale=user.preferred_lang,
            user_email=user.email,
            tier_label=_TIER_LABELS.get(user.tier, "paid"),
            next_attempt_date=next_attempt_date,
            billing_url=f"{settings.app_base_url.rstrip('/')}/dashboard",
            app_base_url=settings.app_base_url.rstrip("/"),
        )
        await email_mod.send_email(to=user.email, subject=subject, html=html, text=text)
        await record_event(
            event_type="billing.dunning_email_sent",
            actor_user_id=user.id,
            payload={"tier": user.tier.value, "next_payment_attempt": next_attempt_ts},
            db=db,
        )
    except Exception:
        logger.warning("dunning email failed for user %s", user.id, exc_info=True)


# ── Online cancellation (§ 312k BGB) ─────────────────────────────────────────

# The operator mail is German (the operator reads it) and its subject never
# carries user input.
_CANCELLATION_OPERATOR_SUBJECT = "[FileMorph Kündigung] Bitte manuell bearbeiten"

_KIND_DE = {"ordinary": "ordentliche Kündigung", "extraordinary": "außerordentliche Kündigung"}

_MANUAL_REASON_DE = {
    "no_account": "Kein Konto mit dieser E-Mail-Adresse gefunden.",
    "ambiguous_account": "Mehrere Konten mit dieser Adresse (nur Groß-/Kleinschreibung verschieden).",
    "extraordinary": "Außerordentliche Kündigung – Grund prüfen.",
    "specific_date": "Kündigung zu einem bestimmten Datum gewünscht.",
    "no_live_subscription": "Kein laufendes Stripe-Abonnement gefunden.",
    "contract_mismatch": "Das laufende Stripe-Abonnement ist nicht der angegebene Vertrag.",
    "multiple_subscriptions": "Mehrere laufende Stripe-Abonnements.",
    "stripe_error": "Stripe-Aufruf fehlgeschlagen – Stand im Stripe-Dashboard prüfen.",
    "honeypot": (
        "Spam-Verdacht: das versteckte Feld wurde ausgefüllt. Kann auch ein Passwort-Manager "
        "gewesen sein – bitte prüfen; ist die Kündigung echt, bearbeiten und die Bestätigung "
        "von Hand schicken."
    ),
}


@router.post("/cancellation")
@limiter.limit("10/hour")
async def submit_cancellation(
    body: CancellationRequest,
    request: Request,
    db: AsyncSession | None = Depends(get_db),
):
    """Cancel a Pro/Business contract online, without logging in (§ 312k BGB).

    Consumers must be able to cancel online without a login (OLG Köln
    6 U 62/24, OLG Nürnberg 3 U 2214/23, KG Berlin 5 UKl 10/25 and
    5 U 6/25), so no password can be asked for: the email address alone
    identifies the account. The confirmation of content, date and time of
    receipt and the end of the contract that § 312k (4) requires immediately
    in text form goes to the address stored on the matching account — its
    owner's mailbox is the only check there is — or, without exactly one
    matching account, to the address entered. It is sent in every case but
    a filled honeypot (below). The free-text reason is repeated in it only
    for a matching account's own mailbox; anywhere else a fixed text stands
    in, or anyone could send their words to any address from our domain.

    An ordinary cancellation "at the earliest possible date" for an address
    with exactly one live subscription of the named plan is executed at once
    (Stripe ``cancel_at_period_end``). Every other case — no account or more
    than one, extraordinary, a specific date, no, several or a different
    subscription, a Stripe error, a filled honeypot — is emailed to the
    operator to handle.

    The answer is the same whether or not the address belongs to an account
    (``received_at`` + ``email_sent``), so the form can't be used to find out
    who is a customer. A received cancellation is never answered with an
    error, and success is never reported for one that wasn't received.

    Spam: 10 requests per hour per IP, and the ``website`` honeypot. Unlike
    ``/contact``, a filled honeypot is not dropped: a password manager may
    fill it on a real cancellation. It is received, audited and mailed to
    the operator as suspected spam like any manual case — but nothing is
    changed in Stripe and no confirmation goes to the entered address, so
    bots still can't use the form to mail strangers. The answer says
    ``email_sent: false``, so the page tells the visitor to keep it as proof.

    Accepted residual risks:

    * Anyone who knows a customer's address can cancel that subscription at
      the end of the billing period — asking for a password is what the law
      rules out. The owner gets the confirmation mail and can undo the
      cancellation in the Stripe customer portal until the period ends.
    * Without a matching account, the confirmation (minus the reason) goes to
      whatever address was entered; the rate limit bounds how often.
    * Answering takes a little longer when Stripe is called, which hints
      that an address has a paid subscription.
    """
    _stripe_enabled()
    if db is None:
        # Stripe without DATABASE_URL: there are no accounts to cancel.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Billing not configured."
        )

    received = datetime.now(timezone.utc).replace(microsecond=0)
    received_at = received.strftime("%Y-%m-%dT%H:%M:%SZ")

    email = body.email.strip()
    normalised = email.lower()
    email_domain = normalised.rsplit("@", 1)[-1]
    # ``lower() ==`` rather than ``ilike``: ``_`` and ``%`` are legal in an
    # address and would act as wildcards. Two live rows (addresses differing
    # only in case) are ambiguous — a person decides.
    rows = (
        (
            await db.execute(
                select(User)
                .where(func.lower(User.email) == normalised, User.deleted_at.is_(None))
                .limit(2)
            )
        )
        .scalars()
        .all()
    )
    user = rows[0] if len(rows) == 1 else None
    # Ends the read transaction so the pooled connection goes back before the
    # slow part (Stripe, SMTP) — on a public route, held connections would let
    # slow upstreams drain the pool. ``expire_on_commit=False`` keeps ``user``.
    await db.commit()
    actor_user_id = user.id if user else None
    # The stored address, not the typed spelling: without a password,
    # reaching the account owner's own mailbox is the safeguard.
    recipient = user.email if user else email

    # With AUDIT_FAIL_CLOSED a failed write raises here → 500. Nothing has
    # been done yet, so the consumer is correctly told it didn't go through.
    await record_event(
        "billing.cancellation.received",
        actor_user_id=actor_user_id,
        payload={
            "email_hash": hashlib.sha256(normalised.encode("utf-8")).hexdigest(),
            "contract": body.contract,
            "kind": body.kind,
            "end": body.end,
            "end_date": body.end_date.isoformat() if body.end_date else None,
            "matched": user is not None,
        },
    )

    manual_reason: str | None
    ends_at: datetime | None = None
    if body.website.strip():
        manual_reason = "honeypot"  # a bot, or a password manager — a person checks
    elif user is None:
        manual_reason = "ambiguous_account" if rows else "no_account"
    elif body.kind == "extraordinary":
        manual_reason = "extraordinary"
    elif body.end == "date":
        manual_reason = "specific_date"
    elif not user.stripe_customer_id:
        manual_reason = "no_live_subscription"
    else:
        price_id = (
            settings.stripe_pro_price_id
            if body.contract == "pro"
            else settings.stripe_business_price_id
        )
        try:
            outcome = await cancel_subscription_at_period_end(user.stripe_customer_id, price_id)
            manual_reason, ends_at = outcome.manual_reason, outcome.ends_at
        except stripe.StripeError:
            logger.warning("cancellation: Stripe call failed for user %s", user.id, exc_info=True)
            manual_reason = "stripe_error"
        except Exception:
            # Anything else (an odd response shape, a bug): the cancellation
            # was received, so it goes to a person rather than into a 500.
            logger.exception("cancellation: Stripe step failed for user %s", user.id)
            manual_reason = "stripe_error"
    ends_on = ends_at.strftime("%Y-%m-%d") if ends_at else None

    try:
        if manual_reason is None:
            await record_event(
                "billing.cancellation.scheduled",
                actor_user_id=actor_user_id,
                payload={"ends_at": ends_on},
            )
        else:
            await record_event(
                "billing.cancellation.manual_review",
                actor_user_id=actor_user_id,
                payload={"reason": manual_reason},
            )
    except AuditWriteError:
        # Fail-closed refuses to hand out a result it can't log — but this
        # cancellation is already set in Stripe or about to be mailed to the
        # operator, and "received" is in the chain. Failing now would tell
        # the consumer it didn't arrive — the one answer § 312k rules out —
        # and invite a second submission. So: log loudly and carry on.
        logger.error(
            "cancellation: outcome audit event not written (user=%s, outcome=%s)",
            actor_user_id,
            manual_reason or "scheduled",
        )

    email_sent = False
    # No confirmation for a filled honeypot: that is what keeps bots from
    # using this form to mail arbitrary addresses.
    if manual_reason != "honeypot":
        email_sent = await _send_cancellation_confirmation(
            to=recipient,
            locale=(user.preferred_lang if user else None) or await get_locale(request),
            body=body,
            received=received,
            show_reason=user is not None,
            scheduled=manual_reason is None,
            ends_on=ends_on,
        )

    if manual_reason is not None or not email_sent:
        await _mail_operator_about_cancellation(
            _cancellation_operator_text(
                received=received,
                email=email,
                body=body,
                user=user,
                ambiguous=len(rows) > 1,
                manual_reason=manual_reason,
                ends_on=ends_on,
                email_sent=email_sent,
            ),
            reply_to=recipient,
        )

    logger.info(
        "cancellation: received (domain=%s, user=%s, outcome=%s, confirmation_sent=%s)",
        email_domain,
        actor_user_id,
        manual_reason or "scheduled",
        email_sent,
    )
    return {"received_at": received_at, "email_sent": email_sent}


async def _send_cancellation_confirmation(
    *,
    to: str,
    locale: str,
    body: CancellationRequest,
    received: datetime,
    show_reason: bool,
    scheduled: bool,
    ends_on: str | None,
) -> bool:
    """Render and send the § 312k confirmation to ``to``; ``True`` once it
    was handed to SMTP.

    Never raises: the cancellation stands either way, and the caller mails
    the operator when this returns ``False``. With ``show_reason`` off, a
    non-empty reason is replaced by a fixed text rather than repeated.
    """
    base_url = settings.app_base_url.rstrip("/")
    operator = email_mod.operator_recipient()
    try:
        subject, html, text = email_mod.render_email(
            "cancellation_confirmation",
            locale=locale,
            received_at=received.strftime("%Y-%m-%d %H:%M UTC"),
            user_email=to,
            tier_label=_TIER_LABELS[TierEnum(body.contract)],
            kind=body.kind,
            reason=body.reason if show_reason else "",
            reason_withheld=bool(body.reason) and not show_reason,
            end_date=body.end_date.isoformat() if body.end_date else None,
            scheduled=scheduled,
            ends_on=ends_on,
            contact=operator or f"{base_url}/contact",
            contact_href=f"mailto:{operator}" if operator else f"{base_url}/contact",
            app_base_url=base_url,
        )
        await email_mod.send_email(
            to=to, subject=subject, html=html, text=text, reply_to=operator or None
        )
    except email_mod.EmailSendError:
        return False  # send_email has already logged the failure
    except Exception:
        # E.g. a translation with a broken placeholder: must not turn a
        # processed cancellation into a 500 — the operator mail flags it.
        logger.exception("cancellation: confirmation email could not be built or sent")
        return False
    # send_email returns quietly without SMTP — then nothing went out.
    return bool(settings.smtp_host)


def _cancellation_operator_text(
    *,
    received: datetime,
    email: str,
    body: CancellationRequest,
    user: User | None,
    ambiguous: bool,
    manual_reason: str | None,
    ends_on: str | None,
    email_sent: bool,
) -> str:
    """Plain German summary for the operator. The consumer's free-text
    reason goes last, below ``---``, so it can't pose as one of the
    fields above it."""
    if user is not None:
        account = f"gefunden (ID {user.id}, Tarif {user.tier.value})"
    elif ambiguous:
        account = "mehrdeutig – mehrere Konten mit dieser Adresse"
    else:
        account = "nicht gefunden"
    requested_end = (
        f"zum {body.end_date.isoformat()}" if body.end_date else "zum nächstmöglichen Zeitpunkt"
    )
    lines = [
        f"Eingang: {received:%Y-%m-%d %H:%M:%S} UTC",
        f"E-Mail: {email}",
        f"Konto: {account}",
        f"Vertrag: FileMorph {_TIER_LABELS[TierEnum(body.contract)]}",
        f"Art: {_KIND_DE[body.kind]}",
        f"Gewünschtes Ende: {requested_end}",
    ]
    if manual_reason is None:
        lines.append(
            "Automatisch erledigt: in Stripe zum Ende der Abrechnungsperiode gekündigt, "
            f"Vertragsende {ends_on or 'unbekannt (Ende der laufenden Abrechnungsperiode)'}"
        )
    else:
        lines.append(f"Warum manuell: {_MANUAL_REASON_DE[manual_reason]}")
        if manual_reason != "honeypot":  # the Spam-Verdacht line says what to do
            lines.append(
                "Zu tun: bearbeiten und dem Kunden das Vertragsende per E-Mail bestätigen."
            )
    if manual_reason == "honeypot":
        confirmation = "NICHT versendet (Spam-Verdacht)"
    elif email_sent:
        confirmation = "versendet"
    else:
        confirmation = "NICHT versendet – bitte manuell nachholen"
    lines.append(f"Bestätigung an Kunden: {confirmation}")
    text = "\n".join(lines) + "\n"
    if body.reason:
        text += f"---\nGrund:\n{body.reason}\n"
    return text


async def _mail_operator_about_cancellation(text: str, *, reply_to: str) -> None:
    """Send the summary to the operator inbox; ``Reply-To`` is the consumer.

    A missing operator address or an SMTP failure is logged, not answered
    with an error — the cancellation has been received either way. Plain
    text in an escaped ``<pre>``, like ``/contact``.
    """
    recipient = email_mod.operator_recipient()
    if not recipient:
        logger.error(
            "cancellation: needs a person, but no operator address is set "
            "(CONTACT_FORM_RECIPIENT_EMAIL / SMTP_REPLY_TO / SMTP_FROM_EMAIL)"
        )
        return
    html_body = (
        '<pre style="white-space:pre-wrap;font-family:inherit;margin:0">'
        + html_mod.escape(text)
        + "</pre>"
    )
    try:
        await email_mod.send_email(
            to=recipient,
            subject=_CANCELLATION_OPERATOR_SUBJECT,
            html=html_body,
            text=text,
            reply_to=reply_to,
        )
    except email_mod.EmailSendError:
        logger.error(
            "cancellation: operator mail failed (recipient_domain=%s)",
            recipient.rsplit("@", 1)[-1],
        )
