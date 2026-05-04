# SPDX-License-Identifier: AGPL-3.0-or-later
"""S10-lite — DailyMetric increment + cockpit usage-summary tests.

Self-contained, mirrors the pattern in ``test_cockpit_admin.py``: spins up an
in-memory SQLite, overrides ``get_db``, and runs assertions through the
existing ``client`` fixture.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.routes.auth import get_current_user
from app.core.auth import hash_password
from app.core.config import settings
from app.core.metrics import increment
from app.db.base import Base, get_db
from app.db.models import DailyMetric, RoleEnum, User
from app.main import app

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


async def _reset_tables() -> None:
    async with _TestSession() as s:
        await s.execute(delete(DailyMetric))
        await s.execute(delete(User))
        await s.commit()


async def _override_get_db():
    async with _TestSession() as session:
        yield session


@pytest.fixture(scope="module", autouse=True)
def _install_overrides():
    asyncio.run(_setup_schema())
    app.dependency_overrides[get_db] = _override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def _wipe_between_tests():
    asyncio.run(_reset_tables())
    yield
    app.dependency_overrides.pop(get_current_user, None)


async def _insert_admin() -> User:
    async with _TestSession() as s:
        u = User(
            email="admin@test.local",
            password_hash=hash_password("test-password"),
            role=RoleEnum.admin,
        )
        s.add(u)
        await s.commit()
        await s.refresh(u)
        return u


def _act_as(user: User) -> None:
    async def _current():
        return user

    app.dependency_overrides[get_current_user] = _current


# ── increment() core behaviour ───────────────────────────────────────────────


def test_increment_creates_row_when_absent():
    async def _run():
        async with _TestSession() as s:
            await increment(s, "page_views")
            row = (
                await s.execute(select(DailyMetric).where(DailyMetric.metric_key == "page_views"))
            ).scalar_one()
            assert row.count == 1
            assert row.date == datetime.now(timezone.utc).date()

    asyncio.run(_run())


def test_increment_is_atomic_upsert_on_repeat():
    async def _run():
        async with _TestSession() as s:
            for _ in range(5):
                await increment(s, "page_views")
            row = (
                await s.execute(select(DailyMetric).where(DailyMetric.metric_key == "page_views"))
            ).scalar_one()
            assert row.count == 5

    asyncio.run(_run())


def test_increment_keeps_separate_counters_per_key():
    async def _run():
        async with _TestSession() as s:
            await increment(s, "page_views")
            await increment(s, "page_views")
            await increment(s, "registrations")
            await increment(s, "convert.jpg-to-pdf")
            await increment(s, "convert.jpg-to-pdf")
            await increment(s, "convert.jpg-to-pdf")

            rows = (await s.execute(select(DailyMetric))).scalars().all()
            counts = {r.metric_key: r.count for r in rows}
            assert counts["page_views"] == 2
            assert counts["registrations"] == 1
            assert counts["convert.jpg-to-pdf"] == 3

    asyncio.run(_run())


def test_increment_is_noop_when_metrics_disabled(monkeypatch):
    monkeypatch.setattr(settings, "metrics_enabled", False)

    async def _run():
        async with _TestSession() as s:
            await increment(s, "page_views")
            count = (await s.execute(select(DailyMetric))).scalars().all()
            assert count == [], "no rows should be written when disabled"

    asyncio.run(_run())


def test_increment_is_noop_when_db_is_none():
    """In Community-Edition mode (no DATABASE_URL), the dependency yields None.
    increment() must early-return — never raise."""

    async def _run():
        await increment(None, "page_views")  # must not raise

    asyncio.run(_run())


# ── cockpit /usage-summary endpoint ──────────────────────────────────────────


def test_usage_summary_requires_admin(client):
    res = client.get("/api/v1/cockpit/usage-summary")
    assert res.status_code == 401


def test_usage_summary_zeroed_when_metrics_disabled(client, monkeypatch):
    admin = asyncio.run(_insert_admin())
    _act_as(admin)
    monkeypatch.setattr(settings, "metrics_enabled", False)

    res = client.get("/api/v1/cockpit/usage-summary?days=7")
    assert res.status_code == 200
    body = res.json()
    assert body["metrics_enabled"] is False
    assert body["totals"]["page_views"] == 0
    assert body["page_views_series"] == []
    assert body["top_format_pairs"] == []


def test_usage_summary_aggregates_recent_counters(client):
    admin = asyncio.run(_insert_admin())
    _act_as(admin)

    today = datetime.now(timezone.utc).date()

    async def _seed():
        async with _TestSession() as s:
            s.add(DailyMetric(date=today, metric_key="page_views", count=42))
            s.add(DailyMetric(date=today, metric_key="registrations", count=3))
            s.add(DailyMetric(date=today, metric_key="convert.jpg-to-pdf", count=10))
            s.add(DailyMetric(date=today, metric_key="convert.heic-to-jpg", count=4))
            s.add(DailyMetric(date=today, metric_key="compress.jpg", count=7))
            await s.commit()

    asyncio.run(_seed())

    res = client.get("/api/v1/cockpit/usage-summary?days=7")
    assert res.status_code == 200
    body = res.json()
    assert body["metrics_enabled"] is True
    # Conversions sum convert.* and compress.* per the endpoint contract.
    assert body["totals"]["page_views"] == 42
    assert body["totals"]["registrations"] == 3
    assert body["totals"]["conversions"] == 10 + 4 + 7
    # 7 days of zero-filled series, with today's row populated.
    assert len(body["page_views_series"]) == 7
    today_iso = today.isoformat()
    today_entry = next(p for p in body["page_views_series"] if p["date"] == today_iso)
    assert today_entry["count"] == 42
    # Top pair-list excludes compress.* (transforms only).
    pair_keys = [p["pair"] for p in body["top_format_pairs"]]
    assert "jpg-to-pdf" in pair_keys
    assert "heic-to-jpg" in pair_keys
    assert all(not p.startswith("compress.") for p in pair_keys)


def test_usage_summary_zero_filled_for_empty_window(client):
    admin = asyncio.run(_insert_admin())
    _act_as(admin)
    res = client.get("/api/v1/cockpit/usage-summary?days=7")
    assert res.status_code == 200
    body = res.json()
    assert body["metrics_enabled"] is True
    assert len(body["page_views_series"]) == 7
    assert all(p["count"] == 0 for p in body["page_views_series"])
    assert body["totals"]["page_views"] == 0
    assert body["top_format_pairs"] == []


def test_usage_summary_old_records_outside_window_are_ignored(client):
    admin = asyncio.run(_insert_admin())
    _act_as(admin)

    async def _seed():
        async with _TestSession() as s:
            s.add(DailyMetric(date=date(2020, 1, 1), metric_key="page_views", count=999))
            await s.commit()

    asyncio.run(_seed())

    res = client.get("/api/v1/cockpit/usage-summary?days=7")
    assert res.status_code == 200
    assert res.json()["totals"]["page_views"] == 0


def test_usage_summary_clamps_days_param(client):
    """`days` is bounded [1, 90] by the Pydantic Query — anything outside
    that range must 422 so the endpoint can't be flooded with huge ranges."""
    admin = asyncio.run(_insert_admin())
    _act_as(admin)

    res = client.get("/api/v1/cockpit/usage-summary?days=999")
    assert res.status_code == 422
    res = client.get("/api/v1/cockpit/usage-summary?days=0")
    assert res.status_code == 422
