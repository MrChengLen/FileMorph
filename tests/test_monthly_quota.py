# SPDX-License-Identifier: AGPL-3.0-or-later
"""PR-M: monthly API-call quota gate + UsageRecord writer.

The pricing page advertises 1 000/month (Free), 25 000 (Pro), 200 000
(Business). These tests pin the contract:

* ``enforce_monthly_quota`` raises 429 with a ``Retry-After`` header
  pointing at the start of the next calendar month when the user has
  hit the limit, and is a no-op below the limit.
* Anonymous (``user is None``; the anonymous ``/convert`` in
  test_docs_match_code.py runs it) and Enterprise (unlimited) tiers
  bypass the gate entirely.
* ``record_usage`` writes one ``UsageRecord`` row per successful
  conversion / compression and is a no-op for anonymous callers.
* The gate counts CALENDAR-MONTH rows — last month's usage does not
  count against this month's quota.

The end-to-end route tests wire the helper through a real TestClient on
all eight upload routes (convert.py, compress.py, pdf_pages.py), so a
regression that drops an ``await enforce_monthly_quota(user)`` line
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
from sqlalchemy import func, select

from app.api.routes.auth import get_optional_user
from app.core import usage as usage_module
from app.core.auth import hash_password
from app.core.quotas import get_quota
from app.core.usage import (
    _month_start,
    _next_month_start,
    enforce_monthly_quota,
    monthly_call_count,
    record_usage,
)
from app.db.models import TierEnum, UsageRecord, User
from app.main import app
from tests.support.db import TestSession, cloud_db


_db = cloud_db(usage_module)


async def _make_user(*, email: str, tier: TierEnum) -> User:
    async with TestSession() as s:
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
    async with TestSession() as s:
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


def test_monthly_call_count_returns_current_month_only():
    """Last-month rows must NOT count against this-month quota."""
    user = asyncio.run(_make_user(email="rollover@example.com", tier=TierEnum.free))
    now = datetime(2026, 5, 15, tzinfo=timezone.utc)
    last_month = datetime(2026, 4, 15, tzinfo=timezone.utc)
    asyncio.run(_seed_usage(user.id, 50, when=last_month))
    asyncio.run(_seed_usage(user.id, 7, when=now))

    async def _q():
        async with TestSession() as s:
            return await monthly_call_count(s, user.id, now=now)

    assert asyncio.run(_q()) == 7


# ── enforce_monthly_quota: gate behaviour ────────────────────────────────────


def _count_returning(used: int):
    """A stand-in for ``monthly_call_count``: the gate is whatever it returns,
    so this pins a boundary without materialising the rows."""

    async def _fake_count(*args, **kwargs):
        return used

    return patch.object(usage_module, "monthly_call_count", _fake_count)


def test_enforce_enterprise_is_noop():
    """Enterprise tier (api_calls_per_month=None) is unlimited — even far past
    every other tier's limit."""
    user = asyncio.run(_make_user(email="enterprise@example.com", tier=TierEnum.enterprise))
    with _count_returning(10_000_000):
        asyncio.run(enforce_monthly_quota(user))  # must not raise


@pytest.mark.parametrize("tier", [TierEnum.free, TierEnum.pro, TierEnum.business])
def test_enforce_lets_the_last_call_through_and_stops_at_the_limit(tier):
    """One call short of the tier's limit passes; at the limit it is a 429
    naming the tier."""
    user = asyncio.run(_make_user(email=f"{tier.value}@example.com", tier=tier))
    limit = get_quota(tier.value).api_calls_per_month

    with _count_returning(limit - 1):
        asyncio.run(enforce_monthly_quota(user))  # must not raise
    with _count_returning(limit), pytest.raises(HTTPException) as exc_info:
        asyncio.run(enforce_monthly_quota(user))
    assert exc_info.value.status_code == 429
    assert f"tier '{tier.value}'" in exc_info.value.detail


def test_enforce_at_limit_raises_429_with_retry_after():
    """At limit (>= api_calls_per_month) → 429 + Retry-After header."""
    user = asyncio.run(_make_user(email="at-limit@example.com", tier=TierEnum.free))
    asyncio.run(_seed_usage(user.id, 1_000))  # Free = 1 000

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


# ── record_usage: writer correctness ─────────────────────────────────────────


def test_record_usage_anonymous_is_noop():
    """No user_id and no api_key_id → nothing to attribute the row to, so no
    row is written. (record_usage swallows a failed write, so "it didn't
    raise" alone would prove nothing.)"""

    async def _do():
        await record_usage(
            user_id=None,
            api_key_id=None,
            endpoint="convert",
            file_size_bytes=1,
            duration_ms=1,
        )
        async with TestSession() as s:
            return (await s.execute(select(func.count()).select_from(UsageRecord))).scalar_one()

    assert asyncio.run(_do()) == 0


# ── End-to-end via the upload routes ─────────────────────────────────────────


def _override_user(user: User):
    """Force get_optional_user to return this user (skips API-key resolution)."""

    async def _override():
        return user

    return _override


def _tiny_pdf_bytes() -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


_UPLOADS = {
    "png": lambda: ("a.png", io.BytesIO(_tiny_png_bytes()), "image/png"),
    "pdf": lambda: ("a.pdf", io.BytesIO(_tiny_pdf_bytes()), "application/pdf"),
}

# Every route that calls enforce_monthly_quota (single and batch convert and
# compress, and the four PDF tools).
_GATED_ROUTES = [
    pytest.param("/api/v1/convert", {"file": "png"}, {"target_format": "jpg"}, id="convert"),
    pytest.param(
        "/api/v1/convert/batch", {"files": "png"}, {"target_formats": "jpg"}, id="convert-batch"
    ),
    pytest.param("/api/v1/compress", {"file": "png"}, {"quality": "85"}, id="compress"),
    pytest.param(
        "/api/v1/compress/batch", {"files": "png"}, {"quality": "85"}, id="compress-batch"
    ),
    pytest.param("/api/v1/pdf/extract", {"file": "pdf"}, {"pages": "1"}, id="pdf-extract"),
    pytest.param("/api/v1/pdf/split", {"file": "pdf"}, {}, id="pdf-split"),
    pytest.param("/api/v1/pdf/compress", {"file": "pdf"}, {"target_kb": "100"}, id="pdf-compress"),
    pytest.param("/api/v1/pdf/insert", {"file": "pdf", "insert_file": "pdf"}, {}, id="pdf-insert"),
]


@pytest.mark.parametrize(("endpoint", "uploads", "data"), _GATED_ROUTES)
def test_every_upload_route_returns_429_at_the_monthly_limit(client, endpoint, uploads, data):
    """End-to-end: a free-tier user at the limit gets 429 + Retry-After on
    every upload route, not only on /convert."""
    user = asyncio.run(
        _make_user(email=f"blocked-{uuid.uuid4().hex}@example.com", tier=TierEnum.free)
    )
    app.dependency_overrides[get_optional_user] = _override_user(user)
    try:
        with _count_returning(get_quota("free").api_calls_per_month):
            res = client.post(
                endpoint,
                headers={"X-API-Key": "test-api-key-filemorph-ci"},
                files=[(field, _UPLOADS[kind]()) for field, kind in uploads.items()],
                data=data,
            )
        assert res.status_code == 429, res.text
        assert "Retry-After" in res.headers
        assert "Monthly API call" in res.json()["detail"]
    finally:
        app.dependency_overrides.pop(get_optional_user, None)


def test_convert_route_succeeds_when_user_is_below_monthly_limit(client):
    """Negative twin: a fresh free user (no usage rows) gets through."""
    user = asyncio.run(_make_user(email="convert-ok@example.com", tier=TierEnum.free))

    async def _q(now=None):
        async with TestSession() as s:
            return await monthly_call_count(s, user.id, now=now)

    assert asyncio.run(_q()) == 0  # a new user starts at zero (default "now")
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
        assert asyncio.run(_q(datetime.now(timezone.utc) + timedelta(seconds=1))) == 1
    finally:
        app.dependency_overrides.pop(get_optional_user, None)
