# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pre-Stripe consent gate: §312g BGB / §356 (5) BGB withdrawal-waiver.

Cloud-Edition Pro/Business subscriptions activate paid-tier API access
immediately on Stripe checkout completion. Under §356 (5) BGB the consumer's
14-day right of withdrawal expires at that moment only if the consumer has
explicitly waived it before contract execution starts. The pricing page
gates each upgrade button behind a per-tier waiver checkbox; the checkout
endpoint enforces that the matching ``withdrawal_waiver_acknowledged: true``
flag arrives in the request body, and records the consent as a SHA-256
hash-chained audit event so it can be reproduced at dispute time.

Properties verified
-------------------
1. ``POST /billing/checkout/pro`` with ``withdrawal_waiver_acknowledged: false``
   (or missing) returns 400 ``withdrawal_waiver_required`` and writes no audit
   event.
2. ``POST /billing/checkout/pro`` with ``withdrawal_waiver_acknowledged: true``
   succeeds (mocked Stripe), writes one
   ``billing.checkout.withdrawal_waiver_recorded`` audit event with
   ``actor_user_id`` set to the user's id and ``payload`` containing
   ``{"tier": "pro"}``.
3. Same for ``business``.
4. Unauthenticated requests are rejected before the body is even examined
   (401), so no audit event is generated.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.routes import billing as billing_module
from app.core import audit as audit_module
from app.core.auth import hash_password
from app.core.config import settings
from app.db.base import Base, get_db
from app.db.models import AuditEvent, TierEnum, User
from app.main import app


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


async def _override_get_db():
    async with _TestSession() as session:
        yield session


@pytest.fixture(scope="module", autouse=True)
def _install_overrides():
    asyncio.run(_setup_schema())
    app.dependency_overrides[get_db] = _override_get_db
    # Re-point audit's self-owned session factory at the test engine —
    # without this, record_event early-returns when DATABASE_URL is unset.
    original_audit = audit_module.AsyncSessionLocal
    audit_module.AsyncSessionLocal = _TestSession
    # Configure Stripe settings so _stripe_enabled() doesn't 503.
    original_secret = settings.stripe_secret_key
    original_pro = settings.stripe_pro_price_id
    original_biz = settings.stripe_business_price_id
    settings.__dict__["stripe_secret_key"] = "sk_test_dummy"
    settings.__dict__["stripe_pro_price_id"] = "price_test_pro"
    settings.__dict__["stripe_business_price_id"] = "price_test_business"
    # Refresh the tier-to-price mapping the route reads at import time.
    billing_module._TIER_TO_PRICE = {
        "pro": "price_test_pro",
        "business": "price_test_business",
    }
    yield
    audit_module.AsyncSessionLocal = original_audit
    settings.__dict__["stripe_secret_key"] = original_secret
    settings.__dict__["stripe_pro_price_id"] = original_pro
    settings.__dict__["stripe_business_price_id"] = original_biz
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def _wipe_between_tests():
    asyncio.run(_wipe())
    yield


@pytest.fixture(autouse=True)
def _mock_stripe(monkeypatch):
    """Mock Stripe SDK calls so tests don't hit the network."""
    fake_customer = MagicMock(id="cus_test_123")
    fake_session = MagicMock(url="https://checkout.stripe.test/redirect")
    monkeypatch.setattr(
        billing_module.stripe.Customer, "create", MagicMock(return_value=fake_customer)
    )
    monkeypatch.setattr(
        billing_module.stripe.checkout.Session,
        "create",
        MagicMock(return_value=fake_session),
    )


# ── Helpers ──────────────────────────────────────────────────────────────────


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


async def _insert_user(*, email: str, password: str = "secure-pw-1") -> User:
    async with _TestSession() as s:
        user = User(email=email, password_hash=hash_password(password), tier=TierEnum.free)
        s.add(user)
        await s.commit()
        await s.refresh(user)
        return user


def _login(client, email: str, password: str = "secure-pw-1") -> str:
    res = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


# ── 1. Missing acknowledgement → 400, no audit event ─────────────────────────


def test_checkout_pro_without_acknowledgement_returns_400(client):
    asyncio.run(_insert_user(email="pro-no-ack@example.com"))
    token = _login(client, "pro-no-ack@example.com")

    res = client.post(
        "/api/v1/billing/checkout/pro",
        headers={"Authorization": f"Bearer {token}"},
        json={"withdrawal_waiver_acknowledged": False},
    )
    assert res.status_code == 400
    assert res.json()["detail"] == "withdrawal_waiver_required"
    assert _events_by_type("billing.checkout.withdrawal_waiver_recorded") == []


def test_checkout_business_with_missing_field_returns_400(client):
    """An empty body (no `withdrawal_waiver_acknowledged` key) defaults to
    False per the Pydantic schema and is therefore rejected."""
    asyncio.run(_insert_user(email="biz-empty@example.com"))
    token = _login(client, "biz-empty@example.com")

    res = client.post(
        "/api/v1/billing/checkout/business",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )
    assert res.status_code == 400
    assert res.json()["detail"] == "withdrawal_waiver_required"
    assert _events_by_type("billing.checkout.withdrawal_waiver_recorded") == []


# ── 2. With acknowledgement → 200 + audit event ──────────────────────────────


def test_checkout_pro_with_acknowledgement_records_audit_event(client):
    user = asyncio.run(_insert_user(email="pro-ok@example.com"))
    token = _login(client, "pro-ok@example.com")

    res = client.post(
        "/api/v1/billing/checkout/pro",
        headers={"Authorization": f"Bearer {token}"},
        json={"withdrawal_waiver_acknowledged": True},
    )
    assert res.status_code == 200, res.text
    assert res.json()["url"] == "https://checkout.stripe.test/redirect"

    # Deployment-agnostic redirect URLs: the success/cancel URLs handed to
    # Stripe must point at *this* deployment's APP_BASE_URL (localhost in
    # tests), never a hardcoded filemorph.io — otherwise a self-hoster's
    # paying users would land back on our dashboard, not theirs.
    create_kwargs = billing_module.stripe.checkout.Session.create.call_args.kwargs
    assert "localhost:8000" in create_kwargs["success_url"]
    assert "filemorph.io" not in create_kwargs["success_url"]
    assert "localhost:8000" in create_kwargs["cancel_url"]
    assert "filemorph.io" not in create_kwargs["cancel_url"]

    rows = _events_by_type("billing.checkout.withdrawal_waiver_recorded")
    assert len(rows) == 1
    assert str(rows[0].actor_user_id) == str(user.id)
    # M10: pin actor_ip so a regression that drops `request.client.host`
    # surfaces as a test failure rather than a silent loss of dispute
    # reproducibility. TestClient's default client host is "testclient".
    assert rows[0].actor_ip == "testclient"
    payload = json.loads(rows[0].payload_json)
    assert payload == {"tier": "pro"}


def test_checkout_business_with_acknowledgement_records_audit_event(client):
    user = asyncio.run(_insert_user(email="biz-ok@example.com"))
    token = _login(client, "biz-ok@example.com")

    res = client.post(
        "/api/v1/billing/checkout/business",
        headers={"Authorization": f"Bearer {token}"},
        json={"withdrawal_waiver_acknowledged": True},
    )
    assert res.status_code == 200, res.text

    rows = _events_by_type("billing.checkout.withdrawal_waiver_recorded")
    assert len(rows) == 1
    assert str(rows[0].actor_user_id) == str(user.id)
    assert rows[0].actor_ip == "testclient"  # M10
    payload = json.loads(rows[0].payload_json)
    assert payload == {"tier": "business"}


# ── 3. Unauthenticated → 401, no audit event ─────────────────────────────────


def test_checkout_unauthenticated_returns_401(client):
    res = client.post(
        "/api/v1/billing/checkout/pro",
        json={"withdrawal_waiver_acknowledged": True},
    )
    assert res.status_code == 401
    assert _events_by_type("billing.checkout.withdrawal_waiver_recorded") == []


# ── 4. Audit-chain integrity (H3) ────────────────────────────────────────────
#
# The hash-chain is what makes the audit log defensible at dispute time:
# verify_chain() walks the table and returns the first id where the
# recomputed SHA-256 of (prev_hash || payload) does not match the stored
# record_hash. These two tests pin both halves of the contract — the
# happy-path return of None for an intact chain, and the tamper-detection
# return of the mutated row's id when payload_json is altered after the
# fact. Without this guard, a refactor that switches the canonical-JSON
# serialiser, the hashing primitive, or the chaining order could silently
# break dispute reproducibility — the audit log would still record events
# (so existing tests pass) but verify_chain would no longer detect edits.


def test_audit_event_chain_intact_across_two_writes(client):
    """Two real audit events written through the live route → verify_chain
    returns None (chain intact). The /auth/login calls also write audit
    rows; the chain spans all of them, so we check the global table
    rather than just the checkout-typed subset.
    """
    asyncio.run(_insert_user(email="chain-1@example.com"))
    asyncio.run(_insert_user(email="chain-2@example.com"))

    for email, tier in [("chain-1@example.com", "pro"), ("chain-2@example.com", "business")]:
        token = _login(client, email)
        res = client.post(
            f"/api/v1/billing/checkout/{tier}",
            headers={"Authorization": f"Bearer {token}"},
            json={"withdrawal_waiver_acknowledged": True},
        )
        assert res.status_code == 200, res.text

    # Per-type sanity: both checkouts logged their consent event. Each
    # event's record_hash chains forward through the global table — the
    # second checkout's prev_hash will not equal the first checkout's
    # record_hash unless they happen to be adjacent in id-order, which
    # depends on what other events the auth flow writes.
    checkout_rows = _events_by_type("billing.checkout.withdrawal_waiver_recorded")
    assert len(checkout_rows) == 2

    async def _verify():
        async with _TestSession() as s:
            return await audit_module.verify_chain(s)

    assert asyncio.run(_verify()) is None


def test_audit_event_chain_detects_payload_tampering(client):
    """Mutate one row's payload_json after-the-fact → verify_chain returns
    that row's id. Pins the property that record_hash binds the payload."""
    asyncio.run(_insert_user(email="chain-tamper@example.com"))
    token = _login(client, "chain-tamper@example.com")
    res = client.post(
        "/api/v1/billing/checkout/pro",
        headers={"Authorization": f"Bearer {token}"},
        json={"withdrawal_waiver_acknowledged": True},
    )
    assert res.status_code == 200, res.text

    rows = _events_by_type("billing.checkout.withdrawal_waiver_recorded")
    assert len(rows) == 1
    tampered_id = rows[0].id

    # Tamper: rewrite the payload to claim "business" while record_hash
    # still binds the original "pro" payload. SQLite has no UPDATE
    # trigger (Postgres does, via migration 005), so we can mutate
    # directly to prove verify_chain catches it.
    async def _tamper():
        async with _TestSession() as s:
            row = (
                await s.execute(select(AuditEvent).where(AuditEvent.id == tampered_id))
            ).scalar_one()
            row.payload_json = json.dumps({"tier": "business"}, separators=(",", ":"))
            await s.commit()

    asyncio.run(_tamper())

    async def _verify():
        async with _TestSession() as s:
            return await audit_module.verify_chain(s)

    assert asyncio.run(_verify()) == tampered_id
