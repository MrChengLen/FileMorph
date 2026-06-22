# SPDX-License-Identifier: AGPL-3.0-or-later
"""CP5: AI credit ledger + monthly gate (app.core.ai_credits).

Pins the contract:

* ``monthly_credits_used`` sums credits for the current calendar month only.
* ``enforce_ai_credit_quota`` raises 402 when charging ``cost`` would exceed
  the tier's monthly allotment; no-op below, for anonymous, and for unlimited
  (enterprise) tiers.
* ``ai_credits_remaining`` reports allotment − used (clamped ≥ 0); None for
  anonymous / unlimited.
* ``record_ai_usage`` writes one row per charged op; no-op for anonymous.

Own in-memory SQLite engine + a patched session factory, same pattern as
tests/test_monthly_quota.py.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core import ai_credits as ai_credits_module
from app.core.ai_credits import (
    ai_credits_remaining,
    charge_ai_credits,
    enforce_ai_credit_quota,
    monthly_credits_used,
    record_ai_usage,
)
from app.core.auth import hash_password
from app.db.base import Base
from app.db.models import AiUsageRecord, TierEnum, User

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
        await s.execute(delete(AiUsageRecord))
        await s.execute(delete(User))
        await s.commit()


@pytest.fixture(scope="module", autouse=True)
def _install_overrides():
    asyncio.run(_setup_schema())
    original = ai_credits_module.AsyncSessionLocal
    ai_credits_module.AsyncSessionLocal = _TestSession
    yield
    ai_credits_module.AsyncSessionLocal = original


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


async def _seed_credits(
    user_id: uuid.UUID, credits_each: int, n: int, *, when: datetime | None = None
) -> None:
    if when is None:
        when = datetime.now(timezone.utc)
    async with _TestSession() as s:
        for _ in range(n):
            s.add(
                AiUsageRecord(
                    user_id=user_id,
                    operation="redact",
                    credits_charged=credits_each,
                    timestamp=when,
                )
            )
        await s.commit()


# ── monthly_credits_used ──────────────────────────────────────────────────


def test_credits_used_zero_for_new_user():
    user = asyncio.run(_make_user(email="z@example.com", tier=TierEnum.pro))

    async def _q():
        async with _TestSession() as s:
            return await monthly_credits_used(s, user.id)

    assert asyncio.run(_q()) == 0


def test_credits_used_sums_current_month_only():
    user = asyncio.run(_make_user(email="sum@example.com", tier=TierEnum.pro))
    now = datetime(2026, 6, 15, tzinfo=timezone.utc)
    last_month = datetime(2026, 5, 15, tzinfo=timezone.utc)
    asyncio.run(_seed_credits(user.id, 10, 5, when=last_month))  # 50, ignored
    asyncio.run(_seed_credits(user.id, 3, 4, when=now))  # 12, counted

    async def _q():
        async with _TestSession() as s:
            return await monthly_credits_used(s, user.id, now=now)

    assert asyncio.run(_q()) == 12


# ── enforce_ai_credit_quota ───────────────────────────────────────────────


def test_enforce_anonymous_is_noop():
    asyncio.run(enforce_ai_credit_quota(None, 1))  # must not raise


def test_enforce_enterprise_unlimited_is_noop():
    user = asyncio.run(_make_user(email="ent@example.com", tier=TierEnum.enterprise))
    asyncio.run(_seed_credits(user.id, 100, 50))  # 5000 credits used
    asyncio.run(enforce_ai_credit_quota(user, 1))  # unlimited → no raise


def test_enforce_below_limit_is_noop():
    user = asyncio.run(_make_user(email="below@example.com", tier=TierEnum.pro))  # 200/mo
    asyncio.run(_seed_credits(user.id, 1, 50))  # 50 used
    asyncio.run(enforce_ai_credit_quota(user, 1))  # 51 ≤ 200 → no raise


def test_enforce_cost_pushing_over_raises_402():
    user = asyncio.run(_make_user(email="over@example.com", tier=TierEnum.pro))  # 200/mo
    asyncio.run(_seed_credits(user.id, 1, 199))  # 199 used
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(enforce_ai_credit_quota(user, 2))  # 199 + 2 = 201 > 200
    assert exc_info.value.status_code == 402
    assert exc_info.value.headers.get("X-FileMorph-Error-Code") == "ai_credits_exhausted"
    assert "tier 'pro'" in exc_info.value.detail


def test_enforce_exactly_at_limit_raises_402():
    user = asyncio.run(_make_user(email="at@example.com", tier=TierEnum.pro))
    asyncio.run(_seed_credits(user.id, 1, 200))  # 200 used
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(enforce_ai_credit_quota(user, 1))  # 201 > 200
    assert exc_info.value.status_code == 402


# ── ai_credits_remaining ──────────────────────────────────────────────────


def test_remaining_anonymous_is_none():
    assert asyncio.run(ai_credits_remaining(None)) is None


def test_remaining_enterprise_is_none():
    user = asyncio.run(_make_user(email="entr@example.com", tier=TierEnum.enterprise))
    assert asyncio.run(ai_credits_remaining(user)) is None


def test_remaining_reflects_usage():
    user = asyncio.run(_make_user(email="rem@example.com", tier=TierEnum.pro))  # 200/mo
    asyncio.run(_seed_credits(user.id, 1, 50))
    assert asyncio.run(ai_credits_remaining(user)) == 150


def test_remaining_clamped_to_zero():
    user = asyncio.run(_make_user(email="clamp@example.com", tier=TierEnum.pro))
    asyncio.run(_seed_credits(user.id, 1, 250))  # over allotment
    assert asyncio.run(ai_credits_remaining(user)) == 0


# ── record_ai_usage ───────────────────────────────────────────────────────


def test_record_inserts_credits():
    user = asyncio.run(_make_user(email="rec@example.com", tier=TierEnum.pro))

    async def _do():
        await record_ai_usage(user_id=user.id, operation="redact", credits_charged=3)
        async with _TestSession() as s:
            return await monthly_credits_used(s, user.id)

    assert asyncio.run(_do()) == 3


def test_record_anonymous_is_noop():
    asyncio.run(record_ai_usage(user_id=None, operation="redact", credits_charged=5))  # no raise


# ── charge_ai_credits (atomic check+charge, H3 race fix) ───────────────────


def test_charge_inserts_and_counts():
    user = asyncio.run(_make_user(email="ch@example.com", tier=TierEnum.pro))

    async def _do():
        await charge_ai_credits(user, 3, operation="redact")
        async with _TestSession() as s:
            return await monthly_credits_used(s, user.id)

    assert asyncio.run(_do()) == 3


def test_charge_anonymous_is_noop():
    asyncio.run(charge_ai_credits(None, 1, operation="redact"))  # must not raise


def test_charge_unlimited_records_without_limit():
    user = asyncio.run(_make_user(email="chent@example.com", tier=TierEnum.enterprise))
    asyncio.run(_seed_credits(user.id, 100, 50))  # 5000 used, unlimited tier

    async def _do():
        await charge_ai_credits(user, 1, operation="redact")  # no 402
        async with _TestSession() as s:
            return await monthly_credits_used(s, user.id)

    assert asyncio.run(_do()) == 5001  # still recorded


def test_charge_over_limit_raises_402_and_does_not_insert():
    user = asyncio.run(_make_user(email="chover@example.com", tier=TierEnum.pro))  # 200/mo
    asyncio.run(_seed_credits(user.id, 1, 200))  # at the limit
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(charge_ai_credits(user, 1, operation="redact"))
    assert exc_info.value.status_code == 402
    assert exc_info.value.headers.get("X-FileMorph-Error-Code") == "ai_credits_exhausted"

    async def _q():
        async with _TestSession() as s:
            return await monthly_credits_used(s, user.id)

    assert asyncio.run(_q()) == 200  # the rejected charge left no row


def test_charge_rechecks_fresh_state_at_the_boundary():
    """The race the pre-check can't close: the authoritative charge re-reads usage
    (incl. the row a concurrent op just wrote) before inserting, so it refuses
    once the ledger actually reaches the limit — never overspends.

    NOTE: this is *logic* coverage, run sequentially. It pins the re-read-before-
    insert behaviour but does not exercise the SELECT ... FOR UPDATE row lock —
    SQLite has no row locks and serializes writers regardless. The lock's
    correctness rests on Postgres in production (verified by code review)."""
    user = asyncio.run(_make_user(email="chrace@example.com", tier=TierEnum.pro))  # 200/mo
    asyncio.run(_seed_credits(user.id, 1, 199))  # 199 used

    async def _q():
        async with _TestSession() as s:
            return await monthly_credits_used(s, user.id)

    asyncio.run(charge_ai_credits(user, 1, operation="redact"))  # 199 -> 200, ok
    assert asyncio.run(_q()) == 200
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(charge_ai_credits(user, 1, operation="redact"))  # would be 201
    assert exc_info.value.status_code == 402
    assert asyncio.run(_q()) == 200  # never exceeded the allotment
