# SPDX-License-Identifier: AGPL-3.0-or-later
"""Admin cockpit — role-gated via unified JWT (``role=admin`` claim + DB re-check).

Replaces the former HTTP Basic-Auth gate (Sprint 6 / Phase 1). Every endpoint
here depends on :func:`app.api.routes.auth.require_admin`, which verifies both
the decoded access token *and* the current ``role`` column on the loaded
``User`` instance so an admin demotion takes effect on the next request.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.auth import require_admin
from app.core.config import settings
from app.core.rate_limit import limiter
from app.db.base import get_db
from app.db.models import DailyMetric, FileJob, JobStatusEnum, RoleEnum, TierEnum, UsageRecord, User

# Metric keys grouped by the cockpit analytics roll-up — kept here so the
# /usage-summary endpoint and any future filters share one definition. New
# converters/compressors flow in via the prefix match; failure counters are
# explicit so renames stay caught at static analysis.
_FAILURE_KEYS = ("failures.convert", "failures.compress")

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cockpit", tags=["Cockpit"], include_in_schema=False)


# ── helpers ───────────────────────────────────────────────────────────────────


def _db_required(db: AsyncSession | None) -> AsyncSession:
    if db is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database not configured."
        )
    return db


def _serialize_user(u: User) -> dict:
    return {
        "id": str(u.id),
        "email": u.email,
        "tier": u.tier.value,
        "role": u.role.value,
        "is_active": u.is_active,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "stripe_customer_id": u.stripe_customer_id,
    }


def _bucket_expr(db: AsyncSession, col, bucket: str):
    """Return a dialect-appropriate bucket expression (day / week / month).

    Postgres uses ``date_trunc('day' | 'week' | 'month', col)``.
    SQLite uses ``strftime(fmt, col)`` with a format that collapses the
    timestamp to the bucket's start.
    """
    dialect = db.bind.dialect.name if db.bind is not None else "postgresql"
    if dialect == "postgresql":
        return func.date_trunc(bucket, col)
    # SQLite fallback — return the ISO-like bucket label
    if bucket == "day":
        return func.strftime("%Y-%m-%d", col)
    if bucket == "week":
        # ISO week via strftime: year-Www. Good enough for chart bucketing.
        return func.strftime("%Y-W%W", col)
    return func.strftime("%Y-%m", col)


# ── Pydantic schemas ──────────────────────────────────────────────────────────


class PatchUserRequest(BaseModel):
    tier: TierEnum | None = None
    is_active: bool | None = None
    role: RoleEnum | None = None


# ── Stats ─────────────────────────────────────────────────────────────────────


@router.get("/stats")
@limiter.limit("30/minute")
async def cockpit_stats(
    request: Request,
    _admin: User = Depends(require_admin),
    db: AsyncSession | None = Depends(get_db),
):
    db = _db_required(db)
    now = datetime.now(timezone.utc)
    since_24h = now - timedelta(hours=24)
    since_7d = now - timedelta(days=7)

    async def scalar_count(stmt: Select) -> int:
        return (await db.execute(stmt)).scalar() or 0

    users_total = await scalar_count(select(func.count()).select_from(User))

    # Per-tier breakdown (one row per tier, zero-filled for missing tiers).
    tier_rows = (
        await db.execute(select(User.tier, func.count()).select_from(User).group_by(User.tier))
    ).all()
    by_tier = {t.value: 0 for t in TierEnum}
    for tier_val, cnt in tier_rows:
        key = tier_val.value if hasattr(tier_val, "value") else str(tier_val)
        by_tier[key] = cnt

    role_rows = (
        await db.execute(select(User.role, func.count()).select_from(User).group_by(User.role))
    ).all()
    by_role = {r.value: 0 for r in RoleEnum}
    for role_val, cnt in role_rows:
        key = role_val.value if hasattr(role_val, "value") else str(role_val)
        by_role[key] = cnt

    signups_7d = await scalar_count(
        select(func.count()).select_from(User).where(User.created_at >= since_7d)
    )

    active_24h = await scalar_count(
        select(func.count(func.distinct(UsageRecord.user_id))).where(
            UsageRecord.timestamp >= since_24h,
            UsageRecord.user_id.is_not(None),
        )
    )

    ops_total = await scalar_count(select(func.count()).select_from(UsageRecord))

    failed_24h = await scalar_count(
        select(func.count())
        .select_from(FileJob)
        .where(
            FileJob.status == JobStatusEnum.error,
            FileJob.created_at >= since_24h,
        )
    )

    return {
        "users": {"total": users_total, "by_tier": by_tier, "by_role": by_role},
        "signups_7d": signups_7d,
        "active_24h": active_24h,
        "operations_total": ops_total,
        "failed_24h": failed_24h,
    }


# ── Users (list / patch / soft-delete) ────────────────────────────────────────


@router.get("/users")
@limiter.limit("30/minute")
async def cockpit_users(
    request: Request,
    q: str | None = Query(None, description="Case-insensitive email substring."),
    tier: TierEnum | None = Query(None),
    role: RoleEnum | None = Query(None),
    is_active: bool | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
    sort: Literal["created_at", "email", "tier"] = Query("created_at"),
    _admin: User = Depends(require_admin),
    db: AsyncSession | None = Depends(get_db),
):
    db = _db_required(db)

    conds = []
    if q:
        conds.append(User.email.ilike(f"%{q}%"))
    if tier is not None:
        conds.append(User.tier == tier)
    if role is not None:
        conds.append(User.role == role)
    if is_active is not None:
        conds.append(User.is_active.is_(is_active))

    base = select(User)
    if conds:
        base = base.where(and_(*conds))

    total = (
        await db.execute(
            select(func.count()).select_from(User).where(and_(*conds) if conds else True)
        )
    ).scalar() or 0

    sort_col = {
        "created_at": User.created_at,
        "email": User.email,
        "tier": User.tier,
    }[sort]
    order = sort_col.desc() if sort == "created_at" else sort_col.asc()

    stmt = base.order_by(order).offset((page - 1) * limit).limit(limit)
    users = (await db.execute(stmt)).scalars().all()

    return {
        "items": [_serialize_user(u) for u in users],
        "total": total,
        "page": page,
        "limit": limit,
    }


@router.patch("/users/{user_id}")
@limiter.limit("10/minute")
async def cockpit_patch_user(
    request: Request,
    user_id: str,
    body: PatchUserRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession | None = Depends(get_db),
):
    db = _db_required(db)
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user id.")

    user = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    # Guard: an admin cannot demote themselves or deactivate themselves in this flow
    # (would lock the account out of the cockpit). Promotion CLI remains the recovery path.
    if user.id == admin.id:
        if body.role is not None and body.role != RoleEnum.admin:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot demote yourself via the cockpit — use the promote_admin CLI.",
            )
        if body.is_active is False:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot deactivate your own account from the cockpit.",
            )

    if body.tier is not None:
        user.tier = body.tier
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.role is not None:
        user.role = body.role

    await db.commit()
    await db.refresh(user)
    logger.info(
        "cockpit.patch_user admin=%s target=%s changes=%s",
        admin.id,
        user.id,
        body.model_dump(exclude_none=True),
    )
    return _serialize_user(user)


@router.delete("/users/{user_id}")
@limiter.limit("10/minute")
async def cockpit_soft_delete_user(
    request: Request,
    user_id: str,
    admin: User = Depends(require_admin),
    db: AsyncSession | None = Depends(get_db),
):
    db = _db_required(db)
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user id.")

    if uid == admin.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot soft-delete your own account.",
        )

    user = (await db.execute(select(User).where(User.id == uid))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    user.is_active = False
    await db.commit()
    logger.info("cockpit.soft_delete admin=%s target=%s", admin.id, user.id)
    return {"id": str(user.id), "is_active": False}


# ── Timeseries ────────────────────────────────────────────────────────────────


@router.get("/timeseries")
@limiter.limit("30/minute")
async def cockpit_timeseries(
    request: Request,
    metric: Literal["signups"] = Query("signups"),
    bucket: Literal["day", "week", "month"] = Query("day"),
    date_from: datetime | None = Query(None, alias="from"),
    date_to: datetime | None = Query(None, alias="to"),
    _admin: User = Depends(require_admin),
    db: AsyncSession | None = Depends(get_db),
):
    db = _db_required(db)
    now = datetime.now(timezone.utc)
    if date_to is None:
        date_to = now
    if date_from is None:
        date_from = date_to - timedelta(days=30)

    if metric == "signups":
        col = User.created_at
        bucket_col = _bucket_expr(db, col, bucket).label("t")
        stmt = (
            select(bucket_col, func.count().label("v"))
            .where(and_(col >= date_from, col <= date_to))
            .group_by(bucket_col)
            .order_by(bucket_col.asc())
        )
        rows = (await db.execute(stmt)).all()
        points = []
        for t_val, v_val in rows:
            if isinstance(t_val, datetime):
                t_out = t_val.isoformat()
            else:
                t_out = str(t_val)
            points.append({"t": t_out, "v": int(v_val)})
        return {
            "metric": metric,
            "bucket": bucket,
            "from": date_from.isoformat(),
            "to": date_to.isoformat(),
            "points": points,
        }

    # Unreachable under Literal narrowing, but kept for defensive clarity.
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported metric.")


# ── S10-lite: usage-summary aggregations from daily_metrics ──────────────────


@router.get("/usage-summary")
@limiter.limit("30/minute")
async def cockpit_usage_summary(
    request: Request,
    days: int = Query(7, ge=1, le=90, description="How many days of history to include."),
    _admin: User = Depends(require_admin),
    db: AsyncSession | None = Depends(get_db),
):
    """Aggregate the daily_metrics table into the cockpit Analytics view.

    Returns one tile-set covering the last ``days`` days:

    - ``page_views_series``: list of ``{date, count}`` for sparkline rendering.
    - ``conversions_series``: same shape, summed across all ``convert.*`` keys per day.
    - ``registrations_series``: ``registrations`` counter per day.
    - ``top_format_pairs``: top-10 ``(src, tgt)`` pairs over the window.
    - ``failure_rate_today``: today's failures / (today's successes + failures).
      Aggregated from ``daily_metrics`` (``failures.convert``, ``failures.compress``
      vs ``convert.*`` and ``compress.*``). Returns ``null`` when the day is too
      young to be meaningful (< 20 outcomes total) so the UI doesn't show a
      noisy 100 %-on-one-failure tile.
    - ``totals``: convenience numbers for the header row.

    When ``METRICS_ENABLED`` is off, returns an explicit
    ``{"metrics_enabled": false, ...zeroed-payload...}`` so the UI can render
    a "Tracking disabled" state instead of empty charts.
    """
    db = _db_required(db)

    if not settings.metrics_enabled:
        return {
            "metrics_enabled": False,
            "days": days,
            "page_views_series": [],
            "conversions_series": [],
            "registrations_series": [],
            "top_format_pairs": [],
            "failure_rate_today": None,
            "totals": {"page_views": 0, "conversions": 0, "registrations": 0},
        }

    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days - 1)

    # Pull every relevant row in one query — the table is tiny (one row per
    # day per metric), so a date-range scan is cheaper than N round-trips.
    rows = (
        await db.execute(
            select(DailyMetric.date, DailyMetric.metric_key, DailyMetric.count).where(
                DailyMetric.date >= start, DailyMetric.date <= today
            )
        )
    ).all()

    # Group rows by metric category. Iso-date strings keep JSON serialization
    # simple and order-stable for the frontend.
    page_views: dict[str, int] = {}
    registrations: dict[str, int] = {}
    conversions: dict[str, int] = {}
    pair_totals: dict[str, int] = {}
    today_str = today.isoformat()
    today_successes = 0
    today_failures = 0

    for r_date, key, count in rows:
        d_str = r_date.isoformat() if hasattr(r_date, "isoformat") else str(r_date)
        if key == "page_views":
            page_views[d_str] = page_views.get(d_str, 0) + int(count)
        elif key == "registrations":
            registrations[d_str] = registrations.get(d_str, 0) + int(count)
        elif key.startswith("convert."):
            conversions[d_str] = conversions.get(d_str, 0) + int(count)
            pair = key.removeprefix("convert.")
            pair_totals[pair] = pair_totals.get(pair, 0) + int(count)
            if d_str == today_str:
                today_successes += int(count)
        elif key.startswith("compress."):
            # Compressions count toward "conversions" total; format-pair table
            # tracks transforms only, so compressions don't appear there.
            conversions[d_str] = conversions.get(d_str, 0) + int(count)
            if d_str == today_str:
                today_successes += int(count)
        elif key in _FAILURE_KEYS:
            if d_str == today_str:
                today_failures += int(count)

    def _series(values: dict[str, int]) -> list[dict]:
        # Zero-fill missing days so the sparkline has continuous x-axis ticks.
        out: list[dict] = []
        for i in range(days):
            day = (start + timedelta(days=i)).isoformat()
            out.append({"date": day, "count": values.get(day, 0)})
        return out

    # Today's failure rate from daily_metrics. Suppress the value when the
    # sample is too small — a single failure on a quiet morning shouldn't
    # show "100 % failure rate" on the dashboard.
    today_total = today_successes + today_failures
    _MIN_OUTCOMES_FOR_RATE = 20
    if today_total >= _MIN_OUTCOMES_FOR_RATE:
        failure_rate_today: float | None = today_failures / today_total
    else:
        failure_rate_today = None

    top_pairs = sorted(pair_totals.items(), key=lambda kv: kv[1], reverse=True)[:10]

    return {
        "metrics_enabled": True,
        "days": days,
        "page_views_series": _series(page_views),
        "conversions_series": _series(conversions),
        "registrations_series": _series(registrations),
        "top_format_pairs": [{"pair": p, "count": c} for p, c in top_pairs],
        "failure_rate_today": (
            round(failure_rate_today, 4) if failure_rate_today is not None else None
        ),
        "failure_sample_size": today_total,
        "totals": {
            "page_views": sum(page_views.values()),
            "conversions": sum(conversions.values()),
            "registrations": sum(registrations.values()),
        },
    }
