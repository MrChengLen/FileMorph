# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-user monthly AI-credit gate + ledger writer (EE add-on plumbing).

Mirrors :mod:`app.core.usage` but counts *credits* for the commercial AI
add-on. The gating/ledger plumbing is AGPL (like billing and quotas) — only
the feature logic under ``app/ee/`` is commercial. Cost-revealing values (the
euro price of a credit, the model, token counts) deliberately never live here:
this module deals purely in the credit unit, so a reader cannot derive the
margin from it.

No-op when:

* ``user is None`` — anonymous; AI is paid-only and gated upstream anyway.
* ``ai_credits_per_month is None`` — unlimited tier (enterprise).
* ``AsyncSessionLocal is None`` and no ``db=`` — Community Edition without
  ``DATABASE_URL``; there is no ledger to count against.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.quotas import get_quota
from app.core.usage import _month_start
from app.db.base import AsyncSessionLocal
from app.db.models import AiUsageRecord, User

logger = logging.getLogger(__name__)


def _tier(user: User) -> str:
    return user.tier.value if hasattr(user.tier, "value") else str(user.tier)


async def monthly_credits_used(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> int:
    """Sum of credits this user spent in the current calendar month."""
    if now is None:
        now = datetime.now(timezone.utc)
    start = _month_start(now)
    stmt = select(func.coalesce(func.sum(AiUsageRecord.credits_charged), 0)).where(
        AiUsageRecord.user_id == user_id,
        AiUsageRecord.timestamp >= start,
    )
    result = await db.execute(stmt)
    return int(result.scalar() or 0)


async def _used(user: User, *, db: AsyncSession | None, now: datetime | None) -> int | None:
    """Used credits this month, or None when there is no ledger to count."""
    if db is not None:
        return await monthly_credits_used(db, user.id, now=now)
    if AsyncSessionLocal is None:
        return None
    async with AsyncSessionLocal() as session:
        return await monthly_credits_used(session, user.id, now=now)


async def ai_credits_remaining(
    user: User | None,
    *,
    db: AsyncSession | None = None,
    now: datetime | None = None,
) -> int | None:
    """Credits left this month for display, or None if unlimited / unknown."""
    if user is None:
        return None
    allotment = get_quota(_tier(user)).ai_credits_per_month
    if allotment is None:
        return None
    used = await _used(user, db=db, now=now)
    if used is None:
        return None
    return max(allotment - used, 0)


def _credit_limit_error(allotment: int, tier: str) -> HTTPException:
    """The 402 raised by both the pre-check and the atomic charge — one source of
    truth for the detail string + the ``ai_credits_exhausted`` error code (tests
    pin both)."""
    return HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail=(
            f"AI credit limit reached ({allotment} per month for tier "
            f"'{tier}'). Upgrade your plan or wait for the monthly reset."
        ),
        headers={"X-FileMorph-Error-Code": "ai_credits_exhausted"},
    )


async def enforce_ai_credit_quota(
    user: User | None,
    cost: int,
    *,
    db: AsyncSession | None = None,
    now: datetime | None = None,
) -> None:
    """Raise 402 if charging ``cost`` credits would exceed the monthly allotment."""
    if user is None:
        return
    allotment = get_quota(_tier(user)).ai_credits_per_month
    if allotment is None:
        return
    used = await _used(user, db=db, now=now)
    if used is None:
        return
    if used + cost > allotment:
        raise _credit_limit_error(allotment, _tier(user))


async def record_ai_usage(
    *,
    user_id: uuid.UUID | None,
    operation: str,
    credits_charged: int,
    model: str | None = None,
    used_llm: bool = False,
    db: AsyncSession | None = None,
) -> None:
    """Append one ``AiUsageRecord``. Fire-and-forget; no-op for anonymous."""
    if user_id is None:
        return
    if db is not None:
        await _insert(db, user_id, operation, credits_charged, model, used_llm)
        return
    if AsyncSessionLocal is None:
        return
    try:
        async with AsyncSessionLocal() as session:
            await _insert(session, user_id, operation, credits_charged, model, used_llm)
    except Exception:
        logger.warning(
            "record_ai_usage failed for operation=%s user_id=%s",
            operation,
            user_id,
            exc_info=True,
        )


async def _insert(
    db: AsyncSession,
    user_id: uuid.UUID,
    operation: str,
    credits_charged: int,
    model: str | None,
    used_llm: bool,
) -> None:
    db.add(
        AiUsageRecord(
            user_id=user_id,
            operation=operation,
            credits_charged=credits_charged,
            model=model,
            used_llm=used_llm,
        )
    )
    await db.commit()


async def _charge(
    db: AsyncSession,
    user: User,
    cost: int,
    operation: str,
    model: str | None,
    used_llm: bool,
    now: datetime | None,
) -> None:
    # Lock the user row for the duration of the transaction so two concurrent
    # charges for the same user serialize: the second sees the first's insert and
    # cannot also pass the limit check. (Postgres honours FOR UPDATE; SQLite has
    # no row locks but serializes writers, so the check+insert stays atomic.)
    await db.execute(select(User.id).where(User.id == user.id).with_for_update())
    allotment = get_quota(_tier(user)).ai_credits_per_month
    if allotment is not None:
        used = await monthly_credits_used(db, user.id, now=now)
        if used + cost > allotment:
            await db.rollback()
            raise _credit_limit_error(allotment, _tier(user))
    # The GATE (lock + check) above has passed; recording the row is best-effort —
    # a failed insert under-reports one op rather than denying an already-authorized
    # request. A failure *before* this point (DB down during lock/check) must NOT be
    # swallowed: it propagates so the route fails closed (no metered op slips free).
    try:
        await _insert(db, user.id, operation, cost, model, used_llm)
    except Exception:
        logger.warning(
            "ai usage insert failed (op authorized but unrecorded) op=%s user_id=%s",
            operation,
            user.id,
            exc_info=True,
        )


async def charge_ai_credits(
    user: User | None,
    cost: int,
    *,
    operation: str,
    model: str | None = None,
    used_llm: bool = False,
    db: AsyncSession | None = None,
    now: datetime | None = None,
) -> None:
    """Atomically charge ``cost`` credits and append the ledger record.

    This is the authoritative charge: it re-checks the monthly allotment *while
    holding a per-user lock*, so it closes the check-then-charge race that the
    upstream :func:`enforce_ai_credit_quota` pre-check (run before the work) can't
    — concurrent requests can no longer both pass and overspend. Raises 402 if the
    charge would exceed the allotment; a ledger/DB failure during the gate
    propagates (the route fails closed). No-op for anonymous / no ledger; unlimited
    tiers are recorded but never limit-checked.
    """
    if user is None:
        return
    if db is not None:
        await _charge(db, user, cost, operation, model, used_llm, now)
        return
    if AsyncSessionLocal is None:
        return
    async with AsyncSessionLocal() as session:
        await _charge(session, user, cost, operation, model, used_llm, now)
