# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stripe webhook — signature validation, misconfiguration guards, and
genuinely signed events through the real route.

The first three tests cover the security-critical path: we must never trust
an unverified payload, and we must refuse to run if the secret is missing.

The signed-event tests post payloads signed the way Stripe signs them
(HMAC-SHA256 over ``"{timestamp}.{payload}"``, which
``stripe.Webhook.construct_event`` verifies) against an in-memory database.
They exist because ``tests/test_billing_dunning.py`` calls the handlers with
plain dicts, while the route hands them what the SDK parsed — and in the
pinned stripe-python (15.x) that is a ``StripeObject`` that is not a dict
(``.get()`` raises ``AttributeError``). Every real event failed with a 500
and no test noticed.
"""

import asyncio
import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core import email as email_module
from app.core.config import settings
from app.db.base import Base, get_db
from app.db.models import AuditEvent, TierEnum, User
from app.main import app


def test_webhook_rejects_when_secret_not_configured(client, monkeypatch):
    """If STRIPE_WEBHOOK_SECRET is empty, the endpoint must return 503."""
    monkeypatch.setattr(settings, "stripe_webhook_secret", "")
    res = client.post(
        "/api/v1/billing/webhook",
        content=b'{"type":"customer.subscription.created"}',
        headers={"stripe-signature": "t=0,v1=deadbeef"},
    )
    assert res.status_code == 503
    assert "not configured" in res.json()["detail"].lower()


def test_webhook_rejects_missing_signature(client, monkeypatch):
    """A request without stripe-signature header must be rejected as invalid."""
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test_dummy")
    res = client.post(
        "/api/v1/billing/webhook",
        content=b'{"type":"customer.subscription.created"}',
    )
    assert res.status_code == 400
    assert "signature" in res.json()["detail"].lower()


def test_webhook_rejects_invalid_signature(client, monkeypatch):
    """A forged signature must be rejected — no tier change can leak through."""
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test_dummy")
    res = client.post(
        "/api/v1/billing/webhook",
        content=b'{"type":"customer.subscription.created"}',
        headers={
            "stripe-signature": "t=0,v1=0000000000000000000000000000000000000000000000000000000000000000"
        },
    )
    assert res.status_code == 400
    assert "signature" in res.json()["detail"].lower()


# ── Signed events through the real route ─────────────────────────────────────

_WEBHOOK_SECRET = "whsec_test_signed_events"

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


async def _override_get_db():
    async with _TestSession() as session:
        yield session


@pytest.fixture(scope="module")
def _webhook_db():
    """In-memory database behind ``get_db`` — only the signed-event tests ask
    for it; the rejection tests above never reach the database."""
    asyncio.run(_setup_schema())
    app.dependency_overrides[get_db] = _override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def webhook_env(_webhook_db, monkeypatch):
    """Empty tables, a known webhook secret and the Pro price id; monkeypatch
    restores both settings after the test."""
    asyncio.run(_wipe())
    monkeypatch.setattr(settings, "stripe_webhook_secret", _WEBHOOK_SECRET)
    monkeypatch.setattr(settings, "stripe_pro_price_id", "price_test_pro")


@pytest.fixture
def send_mock(monkeypatch):
    fake = AsyncMock()
    monkeypatch.setattr(email_module, "send_email", fake)
    return fake


async def _insert_subscriber(
    customer_id: str, *, tier: TierEnum = TierEnum.pro, status: str | None = "active"
) -> User:
    async with _TestSession() as s:
        user = User(
            email=f"{customer_id}@example.com",
            password_hash="never-checked-here",
            tier=tier,
            stripe_customer_id=customer_id,
            subscription_status=status,
            preferred_lang="en",
        )
        s.add(user)
        await s.commit()
        await s.refresh(user)
        return user


async def _reload(user_id) -> User:
    async with _TestSession() as s:
        return (await s.execute(select(User).where(User.id == user_id))).scalar_one()


def _post_signed(client, event: dict):
    """POST ``event`` the way Stripe does: the raw JSON body plus a
    ``Stripe-Signature`` header ``t=<unix time>,v1=<HMAC-SHA256 hex>``."""
    body = json.dumps(event)
    ts = int(time.time())
    sig = hmac.new(_WEBHOOK_SECRET.encode(), f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()
    return client.post(
        "/api/v1/billing/webhook",
        content=body.encode(),
        headers={"stripe-signature": f"t={ts},v1={sig}", "content-type": "application/json"},
    )


def _subscription_event(event_type: str, customer_id: str, *, status: str = "active") -> dict:
    """A ``customer.subscription.*`` event for one Pro subscription."""
    item = {"id": "si_wh", "object": "subscription_item", "price": {"id": "price_test_pro"}}
    return {
        "id": f"evt_{event_type}",
        "object": "event",
        "type": event_type,
        "data": {
            "object": {
                "id": "sub_wh",
                "object": "subscription",
                "customer": customer_id,
                "status": status,
                "items": {"object": "list", "data": [item]},
            }
        },
    }


def test_signed_subscription_updated_event_grants_the_paid_tier(client, webhook_env, send_mock):
    """The path that turns a finished checkout into paid access."""
    user = asyncio.run(_insert_subscriber("cus_wh_updated", tier=TierEnum.free, status=None))
    res = _post_signed(
        client, _subscription_event("customer.subscription.updated", "cus_wh_updated")
    )
    assert res.status_code == 200, res.text
    reloaded = asyncio.run(_reload(user.id))
    assert reloaded.tier == TierEnum.pro
    assert reloaded.subscription_status == "active"
    send_mock.assert_not_awaited()


def test_signed_subscription_deleted_event_drops_the_tier_to_free(client, webhook_env, send_mock):
    user = asyncio.run(_insert_subscriber("cus_wh_deleted"))
    res = _post_signed(
        client, _subscription_event("customer.subscription.deleted", "cus_wh_deleted")
    )
    assert res.status_code == 200, res.text
    reloaded = asyncio.run(_reload(user.id))
    assert reloaded.tier == TierEnum.free
    assert reloaded.subscription_status == "canceled"
    send_mock.assert_not_awaited()


def test_signed_payment_failed_event_starts_dunning(client, webhook_env, send_mock):
    user = asyncio.run(_insert_subscriber("cus_wh_failed"))
    res = _post_signed(
        client,
        {
            "id": "evt_test_failed",
            "object": "event",
            "type": "invoice.payment_failed",
            "data": {
                "object": {
                    "id": "in_wh",
                    "object": "invoice",
                    "customer": "cus_wh_failed",
                    "amount_due": 300,
                    "next_payment_attempt": 1_900_000_000,
                }
            },
        },
    )
    assert res.status_code == 200, res.text
    reloaded = asyncio.run(_reload(user.id))
    assert reloaded.subscription_status == "past_due"
    assert reloaded.tier == TierEnum.pro  # grace window — not downgraded yet
    send_mock.assert_awaited_once()
    assert send_mock.await_args.kwargs["to"] == "cus_wh_failed@example.com"
