# SPDX-License-Identifier: AGPL-3.0-or-later
"""Route-level regression coverage for the slowapi rate limiter.

``app/core/rate_limit.py`` dropped the old ``default_limits=["60/minute"]``
because no ``SlowAPIMiddleware`` is installed — without it slowapi never
applies ``default_limits`` at all, so that "60/minute" was silently enforcing
nothing on every route. Limits now live entirely on explicit
``@limiter.limit(...)`` decorators, one per route, keyed by
``key_style="endpoint"`` so a path parameter (``/keys/{key_id}``) doesn't
split the budget across URLs.

The other half of this module: ``require_api_key`` is a FastAPI dependency,
and FastAPI resolves all dependencies for an endpoint *before* calling the
(slowapi-wrapped) endpoint itself — only then does the wrapper check its
route's limit. A request with a bad ``X-API-Key`` is rejected by the
dependency and never reaches a route's own limiter at all, so it would sail
through completely unthrottled if ``reject_failed_api_key`` didn't give
failed key attempts a budget of their own, counted per IP across every
endpoint that reads the header.

These tests pin the boundary of every one of those budgets, confirm the
``@limiter.exempt`` routes and the Prometheus escape hatch are deliberately
un-throttled rather than merely forgotten, and check that
docs/api-reference.md's table matches what the app actually enforces.

Most budgets are per client IP (``get_remote_address``). Six account-scoped
routes (API keys, billing, the email-language setting) use
``key_func=account_or_ip`` instead, so colleagues behind one office IP don't
share a budget — a couple of tests below pin that two different signed-in
users on the same ``TestClient`` (same IP) do NOT share one.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import secrets
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.routing import APIRoute, iter_route_contexts
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.routes import billing as billing_module
from app.api.routes.keys import MAX_ACTIVE_KEYS
from app.core import audit as audit_module
from app.core.auth import hash_password
from app.core.config import settings
from app.core.rate_limit import account_or_ip, limiter
from app.core.tokens import create_access_token, create_refresh_token
from app.db.base import Base, get_db
from app.db.models import ApiKey, AuditEvent, TierEnum, User
from app.main import app

# Budgets under test (app/api/routes/{keys,billing,auth}.py) — one source of
# truth for the parametrized test below and the routes that need dedicated
# setup (delete_key: pre-existing SQLite bug; checkout/portal: Stripe mocks +
# extra assertions). POST /api/v1/auth/refresh is `@limiter.exempt`, not
# budgeted at all — see the exempt-routes section instead.
N_PER_ROUTE = {
    "create_key": 10,  # POST /api/v1/keys (account)
    "list_keys": 120,  # GET /api/v1/keys (account)
    "delete_key": 30,  # DELETE /api/v1/keys/{key_id} (account)
    "checkout": 5,  # POST /api/v1/billing/checkout/{tier} (account)
    "portal": 5,  # POST /api/v1/billing/portal (account)
    "set_language": 10,  # PUT /api/v1/auth/account/language (account)
}


@pytest.fixture
def rate_limiter_enabled():
    """Flip the shared slowapi limiter ON for one test, fresh storage, always
    OFF again on teardown. A local copy of the identically-named fixture in
    tests/test_rate_limit.py, kept separate rather than imported across
    modules — duplicating ~10 lines beats a cross-module dependency between
    two files that otherwise evolve independently."""
    limiter.enabled = True
    if hasattr(limiter, "reset"):
        limiter.reset()
    elif hasattr(limiter, "_storage") and hasattr(limiter._storage, "reset"):
        limiter._storage.reset()
    try:
        yield
    finally:
        limiter.enabled = False


# ── Shared test database (mirrors tests/test_billing_consent.py) ────────────

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
        await s.execute(delete(ApiKey))
        await s.execute(delete(User))
        await s.commit()


async def _override_get_db():
    async with _TestSession() as session:
        yield session


@pytest.fixture(scope="module", autouse=True)
def _install_overrides():
    asyncio.run(_setup_schema())
    app.dependency_overrides[get_db] = _override_get_db
    original_audit = audit_module.AsyncSessionLocal
    audit_module.AsyncSessionLocal = _TestSession
    original_secret = settings.stripe_secret_key
    original_pro = settings.stripe_pro_price_id
    original_biz = settings.stripe_business_price_id
    original_tier_to_price = dict(billing_module._TIER_TO_PRICE)
    settings.__dict__["stripe_secret_key"] = "sk_test_dummy"
    settings.__dict__["stripe_pro_price_id"] = "price_test_pro"
    settings.__dict__["stripe_business_price_id"] = "price_test_business"
    billing_module._TIER_TO_PRICE = {"pro": "price_test_pro", "business": "price_test_business"}
    yield
    audit_module.AsyncSessionLocal = original_audit
    settings.__dict__["stripe_secret_key"] = original_secret
    settings.__dict__["stripe_pro_price_id"] = original_pro
    settings.__dict__["stripe_business_price_id"] = original_biz
    billing_module._TIER_TO_PRICE = original_tier_to_price
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def _wipe_between_tests():
    asyncio.run(_wipe())
    yield


# ── Small helpers ─────────────────────────────────────────────────────────────


async def _insert_user(
    *, email: str, password: str = "rl-test-password-1", stripe_customer_id: str | None = None
) -> User:
    async with _TestSession() as s:
        user = User(
            email=email,
            password_hash=hash_password(password),
            tier=TierEnum.free,
            stripe_customer_id=stripe_customer_id,
        )
        s.add(user)
        await s.commit()
        await s.refresh(user)
        return user


def _bearer_headers(user: User) -> dict[str, str]:
    token = create_access_token(str(user.id), role=user.role.value)
    return {"Authorization": f"Bearer {token}"}


async def _bulk_insert_keys(user_id, count: int, *, is_active: bool) -> None:
    """Insert `count` ApiKey rows directly — bypassing POST /keys (and its
    own 10/minute limit) so the key-cap tests can set up an exact count."""
    async with _TestSession() as s:
        for _ in range(count):
            s.add(
                ApiKey(
                    user_id=user_id,
                    key_hash=hashlib.sha256(uuid4().bytes).hexdigest(),
                    label="bulk",
                    is_active=is_active,
                )
            )
        await s.commit()


async def _insert_active_key_for(user_id, raw_key: str) -> None:
    """Insert one ApiKey row a caller can then authenticate with using
    `raw_key` — only its SHA-256 hash is stored, matching find_active_api_key."""
    async with _TestSession() as s:
        s.add(
            ApiKey(
                user_id=user_id,
                key_hash=hashlib.sha256(raw_key.encode()).hexdigest(),
                label="db-valid",
                is_active=True,
            )
        )
        await s.commit()


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


def _convert_png(client, sample_jpg, headers: dict[str, str] | None = None):
    with sample_jpg.open("rb") as fp:
        return client.post(
            "/api/v1/convert",
            headers=headers,
            files={"file": ("sample.jpg", fp, "image/jpeg")},
            data={"target_format": "png"},
        )


_WRONG_KEY_HEADERS = {"X-API-Key": "definitely-not-a-real-key"}


def _assert_not_lockout_429(res) -> None:
    """A 429 here would have to come from /convert's OWN 10/minute limit,
    never the failed-API-key lockout — the two are distinguishable by body
    shape: slowapi's own handler answers {"error": ...}, the lockout in
    app/core/rate_limit.py answers {"detail": ...}."""
    if res.status_code == 429:
        body = res.json()
        assert "error" in body and "detail" not in body, (
            f"expected the route's own limiter here, not the failed-key lockout: {body}"
        )


# ══ 1. Per-route N+1 boundaries ═══════════════════════════════════════════════


def _request_factory(client, route_id: str):
    """One request-maker per "simple" route (single Bearer user, one call
    shape, reused across the whole N+1 sequence). checkout/portal/delete_key/
    refresh each need enough extra setup to warrant their own dedicated test
    below instead of living here."""
    user = asyncio.run(_insert_user(email=f"rl-{route_id}-{uuid4().hex}@example.com"))
    headers = _bearer_headers(user)
    if route_id == "create_key":
        return lambda i: client.post("/api/v1/keys", json={"label": f"rl-{i}"}, headers=headers)
    if route_id == "list_keys":
        return lambda i: client.get("/api/v1/keys", headers=headers)
    if route_id == "set_language":
        return lambda i: client.put(
            "/api/v1/auth/account/language", json={"preferred_lang": "de"}, headers=headers
        )
    raise ValueError(f"unknown route_id {route_id!r}")


@pytest.mark.parametrize(
    "route_id,expected_status",
    [
        ("create_key", 201),
        ("list_keys", 200),
        ("set_language", 200),
    ],
)
def test_route_rate_limit_trips_after_n_requests(
    client, rate_limiter_enabled, route_id, expected_status
):
    """N requests against the route's own per-IP budget succeed; the
    (N + 1)th is rejected with 429."""
    n = N_PER_ROUTE[route_id]
    make_request = _request_factory(client, route_id)
    for i in range(n):
        res = make_request(i)
        assert res.status_code == expected_status, (
            f"{route_id}: request {i + 1}/{n} expected {expected_status}, got "
            f"{res.status_code}: {res.text}"
        )
    res = make_request(n)
    assert res.status_code == 429, (
        f"{route_id}: request {n + 1} expected 429, got {res.status_code}: {res.text}"
    )


def test_delete_key_rate_limit_trips_after_n_requests(rate_limiter_enabled):
    """DELETE /api/v1/keys/{key_id} 500s inside the handler body on the
    SQLite test engine: the handler compares ``key_id: str`` directly
    against the UUID ``ApiKey.id`` column, which the SQLite test engine
    can't bind — a separate, pre-existing issue, not fixed here. The
    limiter check in the decorator wrapper runs BEFORE the handler body, so
    it is unaffected: we only assert the 429 boundary here,
    tolerating whatever the buggy handler returns for the first N requests,
    via a dedicated ``TestClient(raise_server_exceptions=False)``. 31
    DIFFERENT uuid4() ids also prove ``key_style="endpoint"`` shares one
    budget for the whole route, not one per URL.
    """
    n = N_PER_ROUTE["delete_key"]
    user = asyncio.run(_insert_user(email=f"rl-delete-{uuid4().hex}@example.com"))
    headers = _bearer_headers(user)
    with TestClient(app, raise_server_exceptions=False) as raw_client:
        for i in range(n):
            res = raw_client.delete(f"/api/v1/keys/{uuid4()}", headers=headers)
            assert res.status_code != 429, f"request {i + 1}/{n} unexpectedly rate-limited"
        res = raw_client.delete(f"/api/v1/keys/{uuid4()}", headers=headers)
        assert res.status_code == 429, f"request {n + 1} expected 429, got {res.status_code}"


def test_checkout_rate_limit_shared_across_tiers(client, rate_limiter_enabled, monkeypatch):
    """The budget is per ROUTE (create_checkout_session), not per tier —
    alternating pro/business proves it is shared, and the Stripe/audit call
    counts prove the 6th (429) request did no Stripe or audit work at all."""
    n = N_PER_ROUTE["checkout"]
    user = asyncio.run(_insert_user(email=f"rl-checkout-{uuid4().hex}@example.com"))
    headers = _bearer_headers(user)

    monkeypatch.setattr(
        billing_module.stripe.Customer,
        "create",
        MagicMock(return_value=MagicMock(id="cus_rl_test")),
    )
    create_mock = MagicMock(return_value=MagicMock(url="https://checkout.stripe.test/rl"))
    monkeypatch.setattr(billing_module.stripe.checkout.Session, "create", create_mock)

    tiers = ["pro", "business"]
    for i in range(n):
        tier = tiers[i % 2]
        res = client.post(
            f"/api/v1/billing/checkout/{tier}",
            json={"withdrawal_waiver_acknowledged": True},
            headers=headers,
        )
        assert res.status_code == 200, f"request {i + 1}/{n} ({tier}): {res.text}"

    res = client.post(
        "/api/v1/billing/checkout/pro",
        json={"withdrawal_waiver_acknowledged": True},
        headers=headers,
    )
    assert res.status_code == 429, f"request {n + 1} expected 429, got {res.status_code}"

    assert create_mock.call_count == n, "the 6th (429) request must not have called Stripe"
    rows = _events_by_type("billing.checkout.withdrawal_waiver_recorded")
    assert len(rows) == n, "the 6th (429) request must not have written an audit row"


def test_portal_rate_limit_trips_after_n_requests(client, rate_limiter_enabled, monkeypatch):
    n = N_PER_ROUTE["portal"]
    user = asyncio.run(
        _insert_user(
            email=f"rl-portal-{uuid4().hex}@example.com", stripe_customer_id="cus_rl_portal"
        )
    )
    headers = _bearer_headers(user)
    monkeypatch.setattr(
        billing_module.stripe.billing_portal.Session,
        "create",
        MagicMock(return_value=MagicMock(url="https://billing.stripe.test/rl")),
    )

    for i in range(n):
        res = client.post("/api/v1/billing/portal", headers=headers)
        assert res.status_code == 200, f"request {i + 1}/{n}: {res.text}"
    res = client.post("/api/v1/billing/portal", headers=headers)
    assert res.status_code == 429, f"request {n + 1} expected 429, got {res.status_code}"


# ── Account-scoped budgets are per account, not per IP ───────────────────────


def test_checkout_rate_limit_is_per_account_not_per_ip(client, rate_limiter_enabled, monkeypatch):
    """checkout is keyed by account_or_ip: two different signed-in users on
    the SAME TestClient (same IP) must NOT share a budget."""
    n = N_PER_ROUTE["checkout"]
    user_a = asyncio.run(_insert_user(email=f"rl-acct-a-{uuid4().hex}@example.com"))
    user_b = asyncio.run(_insert_user(email=f"rl-acct-b-{uuid4().hex}@example.com"))
    headers_a = _bearer_headers(user_a)
    headers_b = _bearer_headers(user_b)

    monkeypatch.setattr(
        billing_module.stripe.Customer,
        "create",
        MagicMock(return_value=MagicMock(id="cus_rl_acct")),
    )
    monkeypatch.setattr(
        billing_module.stripe.checkout.Session,
        "create",
        MagicMock(return_value=MagicMock(url="https://checkout.stripe.test/rl-acct")),
    )

    for i in range(n):
        res = client.post(
            "/api/v1/billing/checkout/pro",
            json={"withdrawal_waiver_acknowledged": True},
            headers=headers_a,
        )
        assert res.status_code == 200, f"user A request {i + 1}/{n}: {res.text}"
    res = client.post(
        "/api/v1/billing/checkout/pro",
        json={"withdrawal_waiver_acknowledged": True},
        headers=headers_a,
    )
    assert res.status_code == 429, f"user A request {n + 1} expected 429, got {res.status_code}"

    # Same IP (same TestClient), different account: budget untouched.
    res = client.post(
        "/api/v1/billing/checkout/pro",
        json={"withdrawal_waiver_acknowledged": True},
        headers=headers_b,
    )
    assert res.status_code == 200, f"user B: {res.text}"


def test_create_key_rate_limit_is_per_account_not_per_ip(client, rate_limiter_enabled):
    n = N_PER_ROUTE["create_key"]
    user_a = asyncio.run(_insert_user(email=f"rl-acct-a-key-{uuid4().hex}@example.com"))
    user_b = asyncio.run(_insert_user(email=f"rl-acct-b-key-{uuid4().hex}@example.com"))
    headers_a = _bearer_headers(user_a)
    headers_b = _bearer_headers(user_b)

    for i in range(n):
        res = client.post("/api/v1/keys", json={"label": f"a-{i}"}, headers=headers_a)
        assert res.status_code == 201, f"user A request {i + 1}/{n}: {res.text}"
    res = client.post("/api/v1/keys", json={"label": "a-over"}, headers=headers_a)
    assert res.status_code == 429, f"user A request {n + 1} expected 429, got {res.status_code}"

    # Same IP (same TestClient), different account: budget untouched.
    res = client.post("/api/v1/keys", json={"label": "b-first"}, headers=headers_b)
    assert res.status_code == 201, f"user B: {res.text}"


# ══ 2. Exempt routes stay unthrottled even with the limiter ON ═══════════════


def test_auth_me_is_exempt_from_rate_limiting(client, rate_limiter_enabled):
    user = asyncio.run(_insert_user(email=f"rl-me-{uuid4().hex}@example.com"))
    headers = _bearer_headers(user)
    for i in range(150):
        res = client.get("/api/v1/auth/me", headers=headers)
        assert res.status_code == 200, f"request {i + 1}/150: {res.text}"


def test_billing_webhook_is_exempt_from_rate_limiting(client, rate_limiter_enabled, monkeypatch):
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_rl_test_dummy")
    for i in range(70):
        res = client.post(
            "/api/v1/billing/webhook",
            content=b'{"type":"customer.subscription.created"}',
            headers={"stripe-signature": "t=0,v1=deadbeef"},
        )
        assert res.status_code == 400, f"request {i + 1}/70: {res.text}"


def test_auth_refresh_is_exempt_from_rate_limiting(client, rate_limiter_enabled):
    """Mass-logout fix: junk refresh tokens must never lock out a real
    session. 350 garbage tokens all fail at JWT decode (401, before any DB
    access) and must never turn into 429; a VALID token right after must
    still succeed.

    The valid-token call runs with the ``get_db`` override popped: ``refresh``
    compares the JWT subject (a plain ``str``) against the UUID ``User.id``
    column with no ``uuid.UUID(...)`` cast, unlike ``get_current_user`` (which
    casts defensively). That still raises under the SQLite test engine
    whenever a database is configured — a separate, pre-existing issue,
    unrelated to rate limiting and not fixed here.
    """
    for i in range(350):
        res = client.post("/api/v1/auth/refresh", json={"refresh_token": "x"})
        assert res.status_code == 401, f"junk request {i + 1}/350: {res.text}"

    token = create_refresh_token(str(uuid4()))
    saved_override = app.dependency_overrides.pop(get_db)
    try:
        res = client.post("/api/v1/auth/refresh", json={"refresh_token": token})
        assert res.status_code == 200, res.text
    finally:
        app.dependency_overrides[get_db] = saved_override


# ══ Privacy: slowapi's own logger must never leak an IP or account ═══════════


def test_slowapi_warning_never_logs_the_client_identifier(client, rate_limiter_enabled, caplog):
    """Privacy policy §7: rate-limiter identifiers (IP or account) must never
    be logged. slowapi's own "ratelimit ... exceeded" line (WARNING) would
    otherwise embed exactly that key; app/core/rate_limit.py silences it via
    ``logging.getLogger("slowapi").setLevel(logging.ERROR)``.

    Tripped on both an IP-keyed route (``GET /api/v1/health``, plain
    ``get_remote_address``) and an account-keyed one (``POST /keys``,
    ``account_or_ip``) — checking only the account-keyed route would make
    this vacuous, since its key is ``"user:<uuid>"`` and never contains an
    IP like "testclient" regardless of whether the level filter works.

    ``caplog`` is set to capture at WARNING globally — deliberately NOT
    scoped to the "slowapi" logger itself (``caplog.set_level(level,
    logger="slowapi")`` would override that ``setLevel(ERROR)`` call and
    defeat the point). If the app's call still holds, "slowapi" blocks the
    record before it is ever created, so caplog sees nothing from it at all;
    asserting on ``levelno`` rather than message content also means this
    still passes if slowapi ever legitimately logs something at ERROR.
    """
    caplog.set_level(logging.WARNING)

    for _ in range(31):
        client.get("/api/v1/health")

    user = asyncio.run(_insert_user(email=f"rl-logtest-{uuid4().hex}@example.com"))
    headers = _bearer_headers(user)
    n = N_PER_ROUTE["create_key"]
    for i in range(n + 1):
        client.post("/api/v1/keys", json={"label": f"log-{i}"}, headers=headers)

    slowapi_records = [r for r in caplog.records if r.name == "slowapi"]
    assert not any(r.levelno < logging.ERROR for r in slowapi_records), (
        "slowapi emitted a record below ERROR (would carry the client "
        f"identifier): {[(r.levelname, r.getMessage()) for r in slowapi_records]}"
    )


# ══ 3. Key cap (limiter disabled — the default test state) ═══════════════════


def test_create_key_returns_409_at_25_active_keys(client):
    user = asyncio.run(_insert_user(email=f"cap-409-{uuid4().hex}@example.com"))
    asyncio.run(_bulk_insert_keys(user.id, MAX_ACTIVE_KEYS, is_active=True))
    res = client.post("/api/v1/keys", json={"label": "one-too-many"}, headers=_bearer_headers(user))
    assert res.status_code == 409
    assert "25" in res.json()["detail"]
    assert "Revoke" in res.json()["detail"]


def test_create_key_allows_new_key_when_cap_only_has_inactive_keys(client):
    user = asyncio.run(_insert_user(email=f"cap-inactive-{uuid4().hex}@example.com"))
    asyncio.run(_bulk_insert_keys(user.id, MAX_ACTIVE_KEYS, is_active=False))
    asyncio.run(_bulk_insert_keys(user.id, MAX_ACTIVE_KEYS - 1, is_active=True))
    res = client.post("/api/v1/keys", json={"label": "still-room"}, headers=_bearer_headers(user))
    assert res.status_code == 201, res.text


@pytest.mark.parametrize("length,expected_status", [(101, 422), (100, 201)])
def test_create_key_label_max_length(client, length, expected_status):
    user = asyncio.run(_insert_user(email=f"cap-label-{length}-{uuid4().hex}@example.com"))
    res = client.post("/api/v1/keys", json={"label": "x" * length}, headers=_bearer_headers(user))
    assert res.status_code == expected_status, res.text


# ══ 4/5/6. Failed-API-key budget ══════════════════════════════════════════════


def test_failed_api_key_budget_locks_out_then_recovers(
    client, auth_headers, sample_jpg, rate_limiter_enabled
):
    for i in range(30):
        res = _convert_png(client, sample_jpg, _WRONG_KEY_HEADERS)
        assert res.status_code == 401, f"attempt {i + 1}/30: {res.text}"

    res = _convert_png(client, sample_jpg, _WRONG_KEY_HEADERS)
    assert res.status_code == 429
    assert res.json()["detail"] == "Too many invalid API key attempts. Try again later."
    retry_after = int(res.headers["Retry-After"])
    assert 1 <= retry_after <= 60

    # A valid file-store key is never refused by the gate, lockout or not.
    res = _convert_png(client, sample_jpg, auth_headers)
    _assert_not_lockout_429(res)

    # No X-API-Key at all never even reaches reject_failed_api_key.
    res = _convert_png(client, sample_jpg)
    _assert_not_lockout_429(res)

    # A valid DB-registered key is accepted too, even mid-lockout.
    user = asyncio.run(_insert_user(email=f"rl-dbkey-{uuid4().hex}@example.com"))
    raw_key = secrets.token_urlsafe(16)
    asyncio.run(_insert_active_key_for(user.id, raw_key))
    res = _convert_png(client, sample_jpg, {"X-API-Key": raw_key})
    assert res.status_code == 200, res.text


def test_valid_key_never_consumes_failed_key_budget(
    client, auth_headers, sample_jpg, rate_limiter_enabled
):
    """31 requests with a VALID key — whatever /convert's own 10/minute
    limiter does to them past request 10 is irrelevant here. What matters:
    a wrong key right after still gets 401 (budget untouched), not 429."""
    for _ in range(31):
        _convert_png(client, sample_jpg, auth_headers)
    res = _convert_png(client, sample_jpg, _WRONG_KEY_HEADERS)
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid API key."


def test_failed_key_budget_is_noop_while_limiter_disabled(client, sample_jpg):
    """Default test state: RATELIMIT_ENABLED=0 (conftest.py). 40 wrong keys
    must all be 401 — reject_failed_api_key no-ops entirely while
    limiter.enabled is False."""
    for i in range(40):
        res = _convert_png(client, sample_jpg, _WRONG_KEY_HEADERS)
        assert res.status_code == 401, f"attempt {i + 1}/40: {res.text}"


# ══ 7. Every /api/ route is deliberately limited or exempt ═══════════════════

# `_route_limits` / `_exempt_routes` / `_default_limits` are slowapi 0.1.10
# internals, not a public API. If a slowapi upgrade renames them, this test
# fails loudly, which is the point: quietly losing this guard would be worse
# than a red CI run over a rename.
_METRICS_PATH = "/api/v1/metrics"  # added via add_api_route; bypasses both decorators

# This FastAPI version (0.141.1) resolves `include_router(prefix=...)`
# lazily: `app.routes` holds one private `_IncludedRouter` wrapper per
# `include_router()` call rather than flattened `APIRoute`s, so a plain
# `isinstance(route, APIRoute)` walk over `app.routes` silently finds only
# routes added straight on `app` (here, just /api/v1/metrics) and nothing
# else — 35 of 36 /api/ routes would go unchecked without anyone noticing.
# `iter_route_contexts` (fastapi.routing, not underscore-prefixed, used
# internally for OpenAPI generation) walks the same resolution FastAPI itself
# uses and yields the fully-prefixed path/methods/endpoint for every route.


def _iter_api_route_contexts():
    for route_context in iter_route_contexts(app.routes):
        if not isinstance(route_context.original_route, APIRoute):
            continue
        path = route_context.path
        if path and path.startswith("/api/"):
            yield route_context


def test_every_api_route_is_classified_limited_or_exempt():
    checked = 0
    for route_context in _iter_api_route_contexts():
        path = route_context.path
        if path == _METRICS_PATH:
            continue
        endpoint = route_context.endpoint
        name = f"{endpoint.__module__}.{endpoint.__name__}"
        assert name in limiter._route_limits or name in limiter._exempt_routes, (
            f"{path} ({name}) is neither rate-limited nor exempt — add "
            "@limiter.limit(...) or @limiter.exempt."
        )
        assert getattr(endpoint, "__wrapped__", None) is not None, (
            f"{path} ({name}) has no __wrapped__ — a decorator placed above "
            "@router.<verb> would show up exactly like this."
        )
        checked += 1
    assert checked > 0, "no /api/ routes found — the discovery loop above is broken"
    assert limiter._default_limits == [], (
        "default_limits must stay empty: with no SlowAPIMiddleware installed, "
        "slowapi never applies it, so a nonempty list here would be dead config."
    )


# ══ 8. docs/api-reference.md matches what the app enforces ═══════════════════

_DOCS_PATH = Path(__file__).resolve().parent.parent / "docs" / "api-reference.md"
_ENDPOINT_RE = re.compile(r"`([A-Z]+) (/api/[^`]+)`")
_NOT_LIMITED_COUNTED_PER = "—"  # em dash, docs' "Counted per" value for not-limited rows


def _parse_rate_limit_table(markdown: str) -> dict[tuple[str, str], tuple[str, str]]:
    """Parse the "## Rate Limiting" section into
    ``{(METHOD, path): (limit_cell, counted_per_cell)}``, stopping at the
    next ``## `` or ``### `` heading so the prose below the table (failed-key
    budget, monthly quota) is never mistaken for rows."""
    heading = "\n## Rate Limiting"
    body = markdown[markdown.index(heading) + len(heading) :]
    end = len(body)
    for marker in ("\n## ", "\n### "):
        idx = body.find(marker)
        if idx != -1:
            end = min(end, idx)
    section = body[:end]

    mapping: dict[tuple[str, str], tuple[str, str]] = {}
    for line in section.splitlines():
        line = line.strip()
        if not (line.startswith("|") and line.endswith("|")):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) != 3:
            continue
        endpoints_cell, limit_cell, counted_per_cell = cells
        matches = _ENDPOINT_RE.findall(endpoints_cell)
        if not matches:
            continue  # header row or the `---|---|---` separator
        for method, path in matches:
            mapping[(method, path)] = (limit_cell, counted_per_cell)
    return mapping


def _app_rate_limit_map() -> dict[tuple[str, str], tuple[str, str]]:
    """Mirror of `_parse_rate_limit_table`, built from the live app: the
    (limit, counted-per) pair each /api/ route (HEAD ignored) is expected to
    carry in the docs. "Counted per" is derived from the actual key_func on
    the route's limit, so a route quietly switched between IP/account keying
    without a matching docs edit fails here."""
    mapping: dict[tuple[str, str], tuple[str, str]] = {}
    for route_context in _iter_api_route_contexts():
        path = route_context.path
        endpoint = route_context.endpoint
        name = f"{endpoint.__module__}.{endpoint.__name__}"
        if path == _METRICS_PATH or name in limiter._exempt_routes:
            value = ("not limited", _NOT_LIMITED_COUNTED_PER)
        elif name in limiter._route_limits:
            route_limit = limiter._route_limits[name][0]
            lim = route_limit.limit
            counted_per = "account" if route_limit.key_func is account_or_ip else "IP"
            value = (f"{lim.amount} / {lim.GRANULARITY.name}", counted_per)
        else:
            pytest.fail(f"{path} ({name}) is neither limited nor exempt (see test 7)")
        for method in route_context.methods or ():
            if method == "HEAD":
                continue
            mapping[(method, path)] = value
    return mapping


def test_docs_rate_limit_table_matches_app():
    docs_map = _parse_rate_limit_table(_DOCS_PATH.read_text(encoding="utf-8"))
    app_map = _app_rate_limit_map()

    for (method, path), (expected_limit, expected_counted_per) in app_map.items():
        assert (method, path) in docs_map, (
            f"{method} {path} is enforced by the app but not documented in docs/api-reference.md"
        )
        limit_cell, counted_per_cell = docs_map[(method, path)]
        if expected_limit == "not limited":
            assert limit_cell.startswith("not limited"), (
                f"{method} {path} should read 'not limited...' in the docs, got {limit_cell!r}"
            )
            assert counted_per_cell == _NOT_LIMITED_COUNTED_PER, (
                f"{method} {path}: not-limited routes should show "
                f"{_NOT_LIMITED_COUNTED_PER!r}, got {counted_per_cell!r}"
            )
        else:
            assert limit_cell == expected_limit, (
                f"{method} {path}: docs say {limit_cell!r}, app enforces {expected_limit!r}"
            )
            # Also covers "rows marked 'account' are exactly the routes whose
            # key_func is account_or_ip" — same comparison, both directions.
            assert counted_per_cell == expected_counted_per, (
                f"{method} {path}: docs say counted per {counted_per_cell!r}, "
                f"app's key_func implies {expected_counted_per!r}"
            )

    for (method, path), _cells in docs_map.items():
        if path == _METRICS_PATH:
            continue  # only mounted when METRICS_ENABLED
        assert (method, path) in app_map, (
            f"{method} {path} is documented in docs/api-reference.md but no such route exists"
        )
