# SPDX-License-Identifier: AGPL-3.0-or-later
"""S10-lite — DailyMetric increment + cockpit usage-summary tests.

Self-contained, mirrors the pattern in ``test_cockpit_admin.py``: spins up an
in-memory SQLite, overrides ``get_db``, and runs assertions through the
existing ``client`` fixture.

What's covered
--------------
1. ``increment(key)`` core behaviour (insert / repeat / per-key isolation).
2. Sanitization — invalid keys are dropped without writing rows.
3. Concurrency — N parallel increments converge to N (atomic UPSERT).
4. Disabled-metrics + no-DB are no-ops.
5. ``/api/v1/cockpit/usage-summary`` admin-gating, time-window scoping,
   and ``failure_rate_today`` semantics (sample-size threshold).
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
from app.core import metrics as metrics_module
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
    # Production callers no longer pass an explicit session — increment opens
    # its own. The unit tests still pass one explicitly via ``db=`` to keep
    # writes inside the in-memory engine. The middleware integration test
    # below patches ``AsyncSessionLocal`` so the global path also targets the
    # test engine.
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
            await increment("page_views", db=s)
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
                await increment("page_views", db=s)
            row = (
                await s.execute(select(DailyMetric).where(DailyMetric.metric_key == "page_views"))
            ).scalar_one()
            assert row.count == 5

    asyncio.run(_run())


def test_increment_keeps_separate_counters_per_key():
    async def _run():
        async with _TestSession() as s:
            await increment("page_views", db=s)
            await increment("page_views", db=s)
            await increment("registrations", db=s)
            await increment("convert.jpg-to-pdf", db=s)
            await increment("convert.jpg-to-pdf", db=s)
            await increment("convert.jpg-to-pdf", db=s)

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
            await increment("page_views", db=s)
            count = (await s.execute(select(DailyMetric))).scalars().all()
            assert count == [], "no rows should be written when disabled"

    asyncio.run(_run())


def test_increment_is_noop_when_no_db_and_no_global_session(monkeypatch):
    """Community-Edition mode (no DATABASE_URL): ``AsyncSessionLocal`` is
    None, increment must early-return — never raise."""
    monkeypatch.setattr(metrics_module, "AsyncSessionLocal", None)

    async def _run():
        # No db= passed — production path. Must not raise.
        await increment("page_views")

    asyncio.run(_run())


# ── Security: metric_key sanitization (S10-fix Security F1) ─────────────────


@pytest.mark.parametrize(
    "bad_key",
    [
        "convert.jpg to pdf",  # whitespace
        "convert.JPG-to-PDF",  # uppercase
        "convert.jpg→pdf",  # multi-byte
        "a" * 65,  # length > 64
        "",  # empty
        "convert.jpg/../",  # slashes
        "convert.\x00null",  # NUL byte
        "convert.;DROP TABLE",  # SQL-shaped
    ],
)
def test_increment_rejects_invalid_metric_keys(bad_key):
    async def _run():
        async with _TestSession() as s:
            await increment(bad_key, db=s)
            rows = (await s.execute(select(DailyMetric))).scalars().all()
            assert rows == [], f"{bad_key!r} should not have been written"

    asyncio.run(_run())


def test_increment_rejects_non_string_key():
    """``key`` is typed as ``str`` but the regex check defends against
    accidental int/None values that slip past type-checks at runtime."""

    async def _run():
        async with _TestSession() as s:
            await increment(None, db=s)  # type: ignore[arg-type]
            await increment(123, db=s)  # type: ignore[arg-type]
            rows = (await s.execute(select(DailyMetric))).scalars().all()
            assert rows == []

    asyncio.run(_run())


def test_increment_accepts_documented_key_shapes():
    """All keys the codebase actually writes must pass sanitization."""

    async def _run():
        async with _TestSession() as s:
            for key in (
                "page_views",
                "registrations",
                "convert.jpg-to-pdf",
                "convert.heic-to-jpg",
                "compress.jpg",
                "failures.convert",
                "failures.compress",
            ):
                await increment(key, db=s)
            rows = (await s.execute(select(DailyMetric))).scalars().all()
            keys_seen = {r.metric_key for r in rows}
            assert "page_views" in keys_seen
            assert "failures.convert" in keys_seen
            assert "failures.compress" in keys_seen

    asyncio.run(_run())


# ── Concurrency: composite-PK + atomic UPSERT under parallel writers ────────


def test_increment_is_safe_under_concurrent_callers():
    """50 concurrent increments on the same (date, key) must converge to 50.

    Each caller opens its own session — same pattern production uses, where
    the page-view middleware and a route-handler may both fire simultaneously.
    A non-atomic implementation (read-then-write) would lose increments under
    parallel writers; the test asserts the UPSERT semantics hold.
    """
    N = 50

    async def _one_writer():
        async with _TestSession() as s:
            await increment("page_views", db=s)

    async def _run():
        await asyncio.gather(*[_one_writer() for _ in range(N)])
        async with _TestSession() as s:
            row = (
                await s.execute(select(DailyMetric).where(DailyMetric.metric_key == "page_views"))
            ).scalar_one()
            assert row.count == N

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
    assert body["failure_rate_today"] is None


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
    # No outcomes today → rate is None and sample size is 0
    assert body["failure_rate_today"] is None
    assert body["failure_sample_size"] == 0


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


# ── failure_rate_today semantics ────────────────────────────────────────────


def test_failure_rate_today_suppressed_below_sample_threshold(client):
    """A single failure on a quiet morning must NOT show 100 % failure-rate.
    The endpoint returns None until the day has ≥20 outcomes."""
    admin = asyncio.run(_insert_admin())
    _act_as(admin)

    today = datetime.now(timezone.utc).date()

    async def _seed():
        async with _TestSession() as s:
            s.add(DailyMetric(date=today, metric_key="convert.jpg-to-pdf", count=2))
            s.add(DailyMetric(date=today, metric_key="failures.convert", count=1))
            await s.commit()

    asyncio.run(_seed())

    res = client.get("/api/v1/cockpit/usage-summary?days=7")
    body = res.json()
    assert body["failure_rate_today"] is None
    assert body["failure_sample_size"] == 3


def test_failure_rate_today_computed_above_sample_threshold(client):
    """With ≥20 outcomes today, the rate is computed as
    failures / (successes + failures)."""
    admin = asyncio.run(_insert_admin())
    _act_as(admin)

    today = datetime.now(timezone.utc).date()

    async def _seed():
        async with _TestSession() as s:
            s.add(DailyMetric(date=today, metric_key="convert.jpg-to-pdf", count=80))
            s.add(DailyMetric(date=today, metric_key="compress.jpg", count=10))
            s.add(DailyMetric(date=today, metric_key="failures.convert", count=8))
            s.add(DailyMetric(date=today, metric_key="failures.compress", count=2))
            await s.commit()

    asyncio.run(_seed())

    res = client.get("/api/v1/cockpit/usage-summary?days=7")
    body = res.json()
    # 10 failures / 100 total = 0.10
    assert body["failure_rate_today"] == 0.10
    assert body["failure_sample_size"] == 100


def test_failure_rate_today_yesterday_does_not_count(client):
    """Failures from yesterday must not bleed into today's rate even when
    the requested window covers them."""
    admin = asyncio.run(_insert_admin())
    _act_as(admin)

    today = datetime.now(timezone.utc).date()
    from datetime import timedelta

    yesterday = today - timedelta(days=1)

    async def _seed():
        async with _TestSession() as s:
            s.add(DailyMetric(date=yesterday, metric_key="convert.jpg-to-pdf", count=200))
            s.add(DailyMetric(date=yesterday, metric_key="failures.convert", count=20))
            await s.commit()

    asyncio.run(_seed())

    res = client.get("/api/v1/cockpit/usage-summary?days=7")
    body = res.json()
    # No outcomes today → None despite yesterday's data
    assert body["failure_rate_today"] is None
    assert body["failure_sample_size"] == 0


# ── Privacy guard: the daily_metrics table never carries personal columns ──


def test_daily_metric_columns_are_aggregate_only():
    """Regression guard: if someone adds a ``user_id``, ``ip``, ``email`` etc.
    column to ``DailyMetric``, this test fails. The table is publicly
    documented as anonymized aggregates — adding a personal-data column
    requires re-doing the privacy-policy review.
    """
    cols = {c.key for c in DailyMetric.__table__.columns}
    assert cols == {"date", "metric_key", "count"}, (
        f"DailyMetric must stay anonymous-aggregate-only. Found columns: {cols}"
    )
