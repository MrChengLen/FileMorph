# SPDX-License-Identifier: AGPL-3.0-or-later
"""PR-J Part B — Stripe dunning: subscription-status sync + payment-failed flow.

When a recurring charge fails, Stripe enters its retry ("dunning") cycle
and fires ``invoice.payment_failed`` on each attempt plus
``customer.subscription.updated`` when the subscription status changes.
These tests pin the FileMorph side of that:

* A failed charge sets ``user.subscription_status = "past_due"``, sends
  the dunning email **once** per cycle (debounced), and records the
  ``billing.subscription.payment_failed`` + ``billing.dunning_email_sent``
  audit events.
* Recovery (``past_due`` → ``active``) re-derives the tier from the price
  and records ``billing.subscription.recovered``.
* A terminal status (``canceled`` / ``unpaid`` / ``incomplete_expired``)
  — or the ``customer.subscription.deleted`` event — drops the tier to
  Free and records ``billing.subscription.canceled``.
* An unknown status leaves the tier untouched (conservative — never
  escalate or downgrade on a status we don't model).
* An event for a customer we don't know is a graceful no-op.

The handlers (``_sync_subscription`` / ``_handle_payment_failed``) are
exercised directly with a real in-memory SQLite session so the test
covers the actual DB writes + audit chain, not just the HTTP shell
(which ``tests/test_billing_webhook.py`` already pins for signature
validation).
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.routes import billing as billing_module
from app.core import audit as audit_module
from app.core import email as email_module
from app.core.auth import hash_password
from app.core.config import settings
from app.db.base import Base
from app.db.models import AuditEvent, TierEnum, User

# ── Test engine ──────────────────────────────────────────────────────────────

_test_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    echo=False,
)
_TestSession = async_sessionmaker(_test_engine, expire_on_commit=False, class_=AsyncSession)


async def _setup_schema() -> None:
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _wipe() -> None:
    async with _TestSession() as s:
        await s.execute(delete(AuditEvent))
        await s.execute(delete(User))
        await s.commit()


@pytest.fixture(scope="module", autouse=True)
def _install_overrides():
    asyncio.run(_setup_schema())
    # Audit helper opens its own session — point it at the test engine.
    original_audit = audit_module.AsyncSessionLocal
    audit_module.AsyncSessionLocal = _TestSession
    # Configure Stripe price IDs so _tier_for_price() maps correctly.
    original_pro = settings.stripe_pro_price_id
    original_biz = settings.stripe_business_price_id
    settings.__dict__["stripe_pro_price_id"] = "price_test_pro"
    settings.__dict__["stripe_business_price_id"] = "price_test_business"
    yield
    audit_module.AsyncSessionLocal = original_audit
    settings.__dict__["stripe_pro_price_id"] = original_pro
    settings.__dict__["stripe_business_price_id"] = original_biz


@pytest.fixture(autouse=True)
def _wipe_between_tests():
    asyncio.run(_wipe())
    yield


@pytest.fixture(autouse=True)
def _mock_send_email(monkeypatch):
    """Capture dunning-email sends without hitting SMTP."""
    fake = AsyncMock()
    monkeypatch.setattr(email_module, "send_email", fake)
    return fake


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _make_user(
    *,
    email: str,
    tier: TierEnum,
    customer_id: str,
    status: str | None = None,
    preferred_lang: str | None = None,
) -> User:
    async with _TestSession() as s:
        user = User(
            email=email,
            password_hash=hash_password("pw-secure-1"),
            tier=tier,
            stripe_customer_id=customer_id,
            subscription_status=status,
            preferred_lang=preferred_lang,
        )
        s.add(user)
        await s.commit()
        await s.refresh(user)
        return user


async def _reload(user_id) -> User:
    async with _TestSession() as s:
        return (await s.execute(select(User).where(User.id == user_id))).scalar_one()


def _events_by_type(event_type: str) -> list[AuditEvent]:
    async def _q():
        async with _TestSession() as s:
            res = await s.execute(
                select(AuditEvent)
                .where(AuditEvent.event_type == event_type)
                .order_by(AuditEvent.id.asc())
            )
            return list(res.scalars().all())

    return asyncio.run(_q())


def _sub_obj(customer: str, status: str, price_id: str = "price_test_pro") -> dict:
    """Minimal Stripe Subscription object shape used by _sync_subscription."""
    return {
        "customer": customer,
        "status": status,
        "items": {"data": [{"price": {"id": price_id}}]},
    }


def _invoice_obj(customer: str, *, next_attempt: int | None = 1_900_000_000) -> dict:
    return {
        "customer": customer,
        "id": "in_test_123",
        "amount_due": 700,
        "next_payment_attempt": next_attempt,
    }


def _run_sync(sub: dict, **kw):
    async def _go():
        async with _TestSession() as db:
            await billing_module._sync_subscription(sub, db, **kw)

    asyncio.run(_go())


def _run_payment_failed(invoice: dict):
    async def _go():
        async with _TestSession() as db:
            await billing_module._handle_payment_failed(invoice, db)

    asyncio.run(_go())


# ── invoice.payment_failed ───────────────────────────────────────────────────


def test_payment_failed_sets_past_due_and_sends_dunning_email(_mock_send_email):
    user = asyncio.run(
        _make_user(
            email="dun1@example.com",
            tier=TierEnum.pro,
            customer_id="cus_dun1",
            status="active",
            preferred_lang="en",
        )
    )
    _run_payment_failed(_invoice_obj("cus_dun1"))

    reloaded = asyncio.run(_reload(user.id))
    assert reloaded.subscription_status == "past_due"
    assert reloaded.tier == TierEnum.pro  # grace — not downgraded yet
    _mock_send_email.assert_awaited_once()
    kwargs = _mock_send_email.await_args.kwargs
    assert "payment failed" in kwargs["subject"].lower()
    # render_email returns (subject, html, text) — the body carries the plan + email
    assert "Pro" in kwargs["html"] and "dun1@example.com" in kwargs["html"]
    assert len(_events_by_type("billing.subscription.payment_failed")) == 1
    assert len(_events_by_type("billing.dunning_email_sent")) == 1


def test_dunning_email_rendered_in_preferred_lang(_mock_send_email):
    """PR-i18n-3: a German-preference subscriber gets the dunning mail in German.

    This is the path with no HTTP request to derive a locale from — the
    webhook reads ``User.preferred_lang`` instead.
    """
    user = asyncio.run(
        _make_user(
            email="dun-de@example.com",
            tier=TierEnum.business,
            customer_id="cus_dunde",
            status="active",
            preferred_lang="de",
        )
    )
    _run_payment_failed(_invoice_obj("cus_dunde"))
    asyncio.run(_reload(user.id))
    _mock_send_email.assert_awaited_once()
    kwargs = _mock_send_email.await_args.kwargs
    assert "fehlgeschlagen" in kwargs["subject"].lower()
    assert "Die letzte Zahlung für deinen FileMorph" in kwargs["html"]
    assert 'lang="de"' in kwargs["html"]
    # The plan name stays a proper noun even in the German body.
    assert "Business" in kwargs["html"]


def test_payment_failed_debounces_second_attempt(_mock_send_email):
    """Stripe fires invoice.payment_failed per retry; we mail once per cycle."""
    user = asyncio.run(
        _make_user(
            email="dun2@example.com", tier=TierEnum.pro, customer_id="cus_dun2", status="active"
        )
    )
    _run_payment_failed(_invoice_obj("cus_dun2"))
    _run_payment_failed(_invoice_obj("cus_dun2"))  # second retry

    reloaded = asyncio.run(_reload(user.id))
    assert reloaded.subscription_status == "past_due"
    _mock_send_email.assert_awaited_once()  # still just one mail
    assert len(_events_by_type("billing.dunning_email_sent")) == 1


def test_payment_failed_for_unknown_customer_is_noop(_mock_send_email):
    _run_payment_failed(_invoice_obj("cus_does_not_exist"))
    _mock_send_email.assert_not_awaited()
    assert _events_by_type("billing.subscription.payment_failed") == []


def test_payment_failed_email_omits_date_when_stripe_gives_up(_mock_send_email):
    """next_payment_attempt=None means Stripe won't retry — email still
    sends but without a retry date."""
    asyncio.run(
        _make_user(
            email="dun3@example.com",
            tier=TierEnum.business,
            customer_id="cus_dun3",
            status="active",
        )
    )
    _run_payment_failed(_invoice_obj("cus_dun3", next_attempt=None))
    _mock_send_email.assert_awaited_once()
    body = _mock_send_email.await_args.kwargs["text"]
    assert "Stripe will retry" not in body  # the {% if next_attempt_date %} block


# ── customer.subscription.updated — status transitions ───────────────────────


def test_subscription_past_due_keeps_tier_and_records_event(_mock_send_email):
    user = asyncio.run(
        _make_user(email="pd@example.com", tier=TierEnum.pro, customer_id="cus_pd", status="active")
    )
    _run_sync(_sub_obj("cus_pd", "past_due"))

    reloaded = asyncio.run(_reload(user.id))
    assert reloaded.subscription_status == "past_due"
    assert reloaded.tier == TierEnum.pro  # grace
    assert len(_events_by_type("billing.subscription.past_due")) == 1
    _mock_send_email.assert_awaited_once()  # entering dunning → email


def test_subscription_recovery_reupgrades_and_records_recovered(_mock_send_email):
    user = asyncio.run(
        _make_user(
            email="rec@example.com", tier=TierEnum.pro, customer_id="cus_rec", status="past_due"
        )
    )
    _run_sync(_sub_obj("cus_rec", "active", price_id="price_test_pro"))

    reloaded = asyncio.run(_reload(user.id))
    assert reloaded.subscription_status == "active"
    assert reloaded.tier == TierEnum.pro
    assert len(_events_by_type("billing.subscription.recovered")) == 1
    _mock_send_email.assert_not_awaited()  # recovery, no email


def test_subscription_canceled_drops_to_free(_mock_send_email):
    user = asyncio.run(
        _make_user(
            email="cx@example.com", tier=TierEnum.business, customer_id="cus_cx", status="past_due"
        )
    )
    _run_sync(_sub_obj("cus_cx", "canceled", price_id="price_test_business"))

    reloaded = asyncio.run(_reload(user.id))
    assert reloaded.tier == TierEnum.free
    assert reloaded.subscription_status == "canceled"
    rows = _events_by_type("billing.subscription.canceled")
    assert len(rows) == 1
    payload = json.loads(rows[0].payload_json)
    assert payload["prev_status"] == "past_due"


def test_subscription_deleted_event_forces_terminal(_mock_send_email):
    """The deleted event often carries status=active; we treat it as terminal."""
    user = asyncio.run(
        _make_user(
            email="del@example.com", tier=TierEnum.pro, customer_id="cus_del", status="active"
        )
    )
    _run_sync(_sub_obj("cus_del", "active"), force_terminal=True)

    reloaded = asyncio.run(_reload(user.id))
    assert reloaded.tier == TierEnum.free
    assert reloaded.subscription_status == "canceled"
    assert len(_events_by_type("billing.subscription.canceled")) == 1


def test_subscription_unknown_status_leaves_tier_untouched(_mock_send_email):
    """Stripe could add a status we don't model — record it, don't touch tier."""
    user = asyncio.run(
        _make_user(
            email="unk@example.com", tier=TierEnum.pro, customer_id="cus_unk", status="active"
        )
    )
    _run_sync(_sub_obj("cus_unk", "some_future_status"))

    reloaded = asyncio.run(_reload(user.id))
    assert reloaded.tier == TierEnum.pro  # unchanged
    assert reloaded.subscription_status == "some_future_status"


def test_subscription_active_from_fresh_sets_tier_from_price(_mock_send_email):
    """A brand-new active subscription (created event) sets the tier."""
    user = asyncio.run(
        _make_user(email="new@example.com", tier=TierEnum.free, customer_id="cus_new", status=None)
    )
    _run_sync(_sub_obj("cus_new", "active", price_id="price_test_business"))

    reloaded = asyncio.run(_reload(user.id))
    assert reloaded.tier == TierEnum.business
    assert reloaded.subscription_status == "active"
    # First-time active is not a "recovery" — no recovered event.
    assert _events_by_type("billing.subscription.recovered") == []
