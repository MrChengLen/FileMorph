# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-user monthly API-call quota — write-side and gate-side.

The pricing page advertises 500/month (Free), 10 000/month (Pro),
100 000/month (Business). Until now the limits in
``app/core/quotas.py`` were informational; this module wires them up
so the system actually enforces what the pricing page promises.

Two responsibilities:

1. **Writer** — :func:`record_usage` inserts one ``UsageRecord`` row
   per successful conversion / compression. Called from the success
   branch of ``_do_convert`` / ``_do_compress`` (single + batch).
2. **Gate** — :func:`enforce_monthly_quota` counts the rows for the
   current calendar month and raises ``HTTPException(429)`` when the
   user is at or above their tier limit. Called *after* the
   concurrency slot is acquired and *before* file I/O begins, so a
   refused request never touches the temp dir.

Session ownership mirrors :mod:`app.core.audit` and
:mod:`app.core.metrics`: each helper opens its own
``AsyncSession`` from ``AsyncSessionLocal``. The route does not need
to thread a ``db=`` parameter through. Tests pass an explicit
``db=`` for the in-memory SQLite engine.

Time window
-----------
Calendar month, UTC. Picked because:

* It matches how the pricing page is read ("you get 10 k per month").
* Users see their reset boundary in their own calendar (1st of the
  next month at 00:00 UTC) — cheap to display, easy to remember.
* A rolling 30-day window is smoother under load but harder to
  communicate ("when does my quota reset?" → "depends which calls
  you made"). Not worth the cognitive cost for an MVP.

Anonymous tier (no ``user_id``) skips both the writer and the gate —
the per-IP rate-limiter (10/min) is the only constraint.
``Enterprise`` (``api_calls_per_month=None``) is unlimited and is
also exempt from the gate; ``record_usage`` still writes its row so
the cockpit gets accurate counts.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.quotas import get_quota
from app.db.base import AsyncSessionLocal
from app.db.models import UsageRecord, User

logger = logging.getLogger(__name__)


def _month_start(now: datetime) -> datetime:
    """Return the UTC timestamp at the start of the given moment's calendar month."""
    return now.astimezone(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_month_start(now: datetime) -> datetime:
    """Return the UTC timestamp at the start of the *following* calendar month.

    Used for the ``Retry-After`` header so a refused caller knows when their
    quota resets. Computed as "1st of (this month + 1)" — December rolls
    forward to January of next year.
    """
    month_start = _month_start(now)
    if month_start.month == 12:
        return month_start.replace(year=month_start.year + 1, month=1)
    return month_start.replace(month=month_start.month + 1)


async def monthly_call_count(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    now: datetime | None = None,
) -> int:
    """Count this user's ``UsageRecord`` rows for the current calendar month.

    The index on ``(user_id, timestamp)`` (migration 007) makes this a fast
    range scan even at 100 k rows/user/month for the Business tier.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    start = _month_start(now)
    stmt = (
        select(func.count())
        .select_from(UsageRecord)
        .where(
            UsageRecord.user_id == user_id,
            UsageRecord.timestamp >= start,
        )
    )
    result = await db.execute(stmt)
    return int(result.scalar() or 0)


async def enforce_monthly_quota(
    user: User | None,
    *,
    db: AsyncSession | None = None,
    now: datetime | None = None,
) -> None:
    """Raise ``HTTPException(429)`` if the user is at or above their monthly limit.

    No-op when:

    * ``user is None`` — anonymous tier; per-IP rate-limiter is the
      only gate.
    * ``user.tier`` is ``enterprise`` or otherwise has
      ``api_calls_per_month=None`` — unlimited tier.
    * ``AsyncSessionLocal is None`` and no ``db=`` passed — Community
      Edition without ``DATABASE_URL``; nothing to count against.
    """
    if user is None:
        return

    tier = user.tier.value if hasattr(user.tier, "value") else str(user.tier)
    quota = get_quota(tier)
    if quota.api_calls_per_month is None:
        return

    if now is None:
        now = datetime.now(timezone.utc)

    if db is not None:
        used = await monthly_call_count(db, user.id, now=now)
    else:
        if AsyncSessionLocal is None:
            return
        async with AsyncSessionLocal() as session:
            used = await monthly_call_count(session, user.id, now=now)

    if used >= quota.api_calls_per_month:
        retry_at = _next_month_start(now)
        retry_after_seconds = max(int((retry_at - now).total_seconds()), 1)
        detail = (
            f"Monthly API call limit reached ({quota.api_calls_per_month} per month "
            f"for tier '{tier}'). Quota resets {retry_at.isoformat()}. Upgrade your plan "
            "or wait until the reset to continue."
        )
        # 429 is the conventional rate-limit code; Retry-After is in
        # seconds per RFC 9110 § 10.2.3.
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=detail,
            headers={"Retry-After": str(retry_after_seconds)},
        )


async def record_usage(
    *,
    user_id: uuid.UUID | None,
    api_key_id: uuid.UUID | None,
    endpoint: str,
    file_size_bytes: int,
    duration_ms: int,
    db: AsyncSession | None = None,
) -> None:
    """Append one ``UsageRecord`` for a successful conversion / compression.

    Fire-and-forget by design — failures are logged at ``WARNING`` and
    never bubble into the request path. The audit log
    (:mod:`app.core.audit`) is the source-of-truth for compliance
    purposes; ``UsageRecord`` is the lightweight per-user counter that
    powers the monthly-quota gate and the dashboard usage display.

    Anonymous tier (``user_id is None`` and ``api_key_id is None``)
    is a no-op — there is no caller identity to attribute the row to.
    """
    if user_id is None and api_key_id is None:
        return

    if db is not None:
        await _insert(db, user_id, api_key_id, endpoint, file_size_bytes, duration_ms)
        return

    if AsyncSessionLocal is None:
        return

    try:
        async with AsyncSessionLocal() as session:
            await _insert(session, user_id, api_key_id, endpoint, file_size_bytes, duration_ms)
    except Exception:
        logger.warning(
            "record_usage failed for endpoint=%s user_id=%s",
            endpoint,
            user_id,
            exc_info=True,
        )


async def _insert(
    db: AsyncSession,
    user_id: uuid.UUID | None,
    api_key_id: uuid.UUID | None,
    endpoint: str,
    file_size_bytes: int,
    duration_ms: int,
) -> None:
    """Single INSERT, owned-session caller commits."""
    row = UsageRecord(
        user_id=user_id,
        api_key_id=api_key_id,
        endpoint=endpoint,
        file_size_bytes=file_size_bytes,
        duration_ms=duration_ms,
    )
    db.add(row)
    await db.commit()
