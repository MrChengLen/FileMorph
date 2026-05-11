# SPDX-License-Identifier: AGPL-3.0-or-later
"""PR-M: monthly API-call quota gate + UsageRecord writer.

The pricing page advertises 500/month (Free), 10 000 (Pro), 100 000
(Business). These tests pin the contract:

* ``enforce_monthly_quota`` raises 429 with a ``Retry-After`` header
  pointing at the start of the next calendar month when the user has
  hit the limit, and is a no-op below the limit.
* Anonymous (``user is None``) and Enterprise (unlimited) tiers
  bypass the gate entirely.
* ``record_usage`` writes one ``UsageRecord`` row per successful
  conversion / compression and is a no-op for anonymous callers.
* The gate counts CALENDAR-MONTH rows — last month's usage does not
  count against this month's quota.

The end-to-end /convert route test wires the helper through a real
TestClient so a regression that drops the ``await
enforce_monthly_quota(user)`` line in convert.py / compress.py
surfaces as a 200 where a 429 is expected.
"""

from __future__ import annotations

import asyncio
import io
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.routes.auth import get_optional_user
from app.core import usage as usage_module
from app.core.auth import hash_password
from app.core.usage import (
    _month_start,
    _next_month_start,
    enforce_monthly_quota,
    monthly_call_count,
    record_usage,
)
from app.db.base import Base, get_db
from app.db.models import TierEnum, UsageRecord, User
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
        await s.execute(delete(UsageRecord))
        await s.execute(delete(User))
        await s.commit()


async def _override_get_db():
    async with _TestSession() as session:
        yield session


@pytest.fixture(scope="module", autouse=True)
def _install_overrides():
    asyncio.run(_setup_schema())
    app.dependency_overrides[get_db] = _override_get_db
    # Re-point usage's self-owned session factory at the test engine,
    # otherwise enforce_monthly_quota / record_usage early-return when
    # DATABASE_URL is unset.
    original_session = usage_module.AsyncSessionLocal
    usage_module.AsyncSessionLocal = _TestSession
    yield
    usage_module.AsyncSessionLocal = original_session
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def _wipe_between_tests():
    asyncio.run(_wipe())
    yield


async def _make_user(*, email: str, tier: TierEnum) -> User:
    async with _TestSession() as s:
        user = User(email=email, password_hash=hash_password("pw-secure-1"), tier=tier)
        s.add(user)
        await s.commit()
        await s.refresh(user)
        return user


def _tiny_png_bytes() -> bytes:
    """Generate a minimal valid 1×1 PNG that Pillow can decode."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (1, 1), color="red").save(buf, format="PNG")
    return buf.getvalue()


async def _seed_usage(user_id: uuid.UUID, n: int, *, when: datetime | None = None) -> None:
    """Insert N UsageRecord rows for a user at the given timestamp."""
    if when is None:
        when = datetime.now(timezone.utc)
    async with _TestSession() as s:
        for _ in range(n):
            s.add(
                UsageRecord(
                    user_id=user_id,
                    endpoint="convert",
                    timestamp=when,
                    file_size_bytes=1000,
                    duration_ms=10,
                )
            )
        await s.commit()


# ── Pure helpers ─────────────────────────────────────────────────────────────


def test_month_start_returns_first_of_month_utc_midnight():
    now = datetime(2026, 5, 15, 14, 30, 45, tzinfo=timezone.utc)
    start = _month_start(now)
    assert start == datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


def test_next_month_start_rolls_year_boundary():
    """December → January-of-next-year."""
    now = datetime(2026, 12, 28, 23, 59, tzinfo=timezone.utc)
    nxt = _next_month_start(now)
    assert nxt == datetime(2027, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


def test_next_month_start_within_year():
    now = datetime(2026, 5, 15, tzinfo=timezone.utc)
    nxt = _next_month_start(now)
    assert nxt == datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc)


# ── monthly_call_count: time-window correctness ──────────────────────────────


def test_monthly_call_count_zero_for_new_user():
    user = asyncio.run(_make_user(email="zero@example.com", tier=TierEnum.free))

    async def _q():
        async with _TestSession() as s:
            return await monthly_call_count(s, user.id)

    assert asyncio.run(_q()) == 0


def test_monthly_call_count_returns_current_month_only():
    """Last-month rows must NOT count against this-month quota."""
    user = asyncio.run(_make_user(email="rollover@example.com", tier=TierEnum.free))
    now = datetime(2026, 5, 15, tzinfo=timezone.utc)
    last_month = datetime(2026, 4, 15, tzinfo=timezone.utc)
    asyncio.run(_seed_usage(user.id, 50, when=last_month))
    asyncio.run(_seed_usage(user.id, 7, when=now))

    async def _q():
        async with _TestSession() as s:
            return await monthly_call_count(s, user.id, now=now)

    assert asyncio.run(_q()) == 7


# ── enforce_monthly_quota: gate behaviour ────────────────────────────────────


def test_enforce_anonymous_is_noop():
    """No user → no gate. The per-IP rate-limiter is the only constraint."""
    asyncio.run(enforce_monthly_quota(None))  # must not raise


def test_enforce_enterprise_is_noop():
    """Enterprise tier (api_calls_per_month=None) is unlimited."""
    user = asyncio.run(_make_user(email="enterprise@example.com", tier=TierEnum.enterprise))
    # Even with a million seeded rows, no 429.
    asyncio.run(_seed_usage(user.id, 100))
    asyncio.run(enforce_monthly_quota(user))


def test_enforce_below_limit_is_noop():
    user = asyncio.run(_make_user(email="below@example.com", tier=TierEnum.free))
    # Free = 500/month. 100 rows is well under.
    asyncio.run(_seed_usage(user.id, 100))
    asyncio.run(enforce_monthly_quota(user))  # must not raise


def test_enforce_at_limit_raises_429_with_retry_after():
    """At limit (>= api_calls_per_month) → 429 + Retry-After header."""
    user = asyncio.run(_make_user(email="at-limit@example.com", tier=TierEnum.free))
    asyncio.run(_seed_usage(user.id, 500))  # Free = 500

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(enforce_monthly_quota(user))

    err = exc_info.value
    assert err.status_code == 429
    assert "Retry-After" in err.headers
    retry = int(err.headers["Retry-After"])
    # Retry-After must be positive and at most ~32 days (calendar month upper bound).
    assert 1 <= retry <= 32 * 24 * 3600
    assert "Monthly API call limit" in err.detail
    assert "tier 'free'" in err.detail


def test_enforce_pro_tier_at_10k():
    """Pro tier = 10 000/month."""
    user = asyncio.run(_make_user(email="pro@example.com", tier=TierEnum.pro))
    asyncio.run(_seed_usage(user.id, 10_000))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(enforce_monthly_quota(user))
    assert exc_info.value.status_code == 429
    assert "tier 'pro'" in exc_info.value.detail


def test_enforce_business_tier_at_100k():
    """Business tier = 100 000/month. Use a Python-side patched count
    so the test doesn't have to materialise 100 000 rows in SQLite —
    the gate is whatever ``monthly_call_count`` returns, mocking that
    pins the boundary precisely.
    """
    user = asyncio.run(_make_user(email="biz@example.com", tier=TierEnum.business))

    async def _fake_count(*args, **kwargs):
        return 100_000

    with patch.object(usage_module, "monthly_call_count", _fake_count):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(enforce_monthly_quota(user))
    assert exc_info.value.status_code == 429
    assert "tier 'business'" in exc_info.value.detail


# ── record_usage: writer correctness ─────────────────────────────────────────


def test_record_usage_inserts_one_row():
    user = asyncio.run(_make_user(email="writer@example.com", tier=TierEnum.free))

    async def _do():
        await record_usage(
            user_id=user.id,
            api_key_id=None,
            endpoint="convert",
            file_size_bytes=12345,
            duration_ms=42,
        )
        async with _TestSession() as s:
            return await monthly_call_count(s, user.id)

    assert asyncio.run(_do()) == 1


def test_record_usage_anonymous_is_noop():
    """No user_id and no api_key_id → nothing to attribute the row to."""

    async def _do():
        await record_usage(
            user_id=None,
            api_key_id=None,
            endpoint="convert",
            file_size_bytes=1,
            duration_ms=1,
        )
        # No user means no count to verify; just assert it didn't raise.

    asyncio.run(_do())  # must not raise


# ── End-to-end via /convert route ────────────────────────────────────────────


def _login(client, email: str, password: str = "pw-secure-1") -> str:
    res = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _override_user(user: User):
    """Force get_optional_user to return this user (skips API-key resolution)."""

    async def _override():
        return user

    return _override


def test_convert_route_returns_429_when_user_is_at_monthly_limit(client):
    """End-to-end: a free-tier user with 500 rows already gets 429 on /convert."""
    user = asyncio.run(_make_user(email="convert-blocked@example.com", tier=TierEnum.free))
    asyncio.run(_seed_usage(user.id, 500))
    app.dependency_overrides[get_optional_user] = _override_user(user)
    try:
        png_bytes = _tiny_png_bytes()  # Reused across both end-to-end tests.
        res = client.post(
            "/api/v1/convert",
            headers={"X-API-Key": "test-api-key-filemorph-ci"},
            files={"file": ("a.png", io.BytesIO(png_bytes), "image/png")},
            data={"target_format": "jpg"},
        )
        assert res.status_code == 429, res.text
        assert "Retry-After" in res.headers
        assert "Monthly API call" in res.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_optional_user, None)


def test_convert_route_succeeds_when_user_is_below_monthly_limit(client):
    """Negative twin: a fresh free user (no usage rows) gets through."""
    user = asyncio.run(_make_user(email="convert-ok@example.com", tier=TierEnum.free))
    app.dependency_overrides[get_optional_user] = _override_user(user)
    try:
        png_bytes = _tiny_png_bytes()
        res = client.post(
            "/api/v1/convert",
            headers={"X-API-Key": "test-api-key-filemorph-ci"},
            files={"file": ("a.png", io.BytesIO(png_bytes), "image/png")},
            data={"target_format": "jpg"},
        )
        assert res.status_code == 200, res.text
        # Side effect: the successful call wrote one UsageRecord row.

        async def _q():
            async with _TestSession() as s:
                return await monthly_call_count(
                    s, user.id, now=datetime.now(timezone.utc) + timedelta(seconds=1)
                )

        assert asyncio.run(_q()) == 1
    finally:
        app.dependency_overrides.pop(get_optional_user, None)
