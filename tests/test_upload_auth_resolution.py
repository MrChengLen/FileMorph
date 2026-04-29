# SPDX-License-Identifier: AGPL-3.0-or-later
"""Upload endpoints must resolve the caller to a ``User`` via either
``Authorization: Bearer`` or ``X-API-Key``, so tier-based quotas (batch
size, file size, output cap) match the account.

Prod regression guard on the bug where a business-tier user saw
``Batch size 2 exceeds tier limit of 1`` because ``get_optional_user``
only inspected Bearer, and the Web UI never attached Bearer on uploads
at all. Fix wires both ends of the boundary:

* ``app/api/routes/auth.py::get_optional_user`` now resolves X-API-Key →
  DB ``api_keys`` → ``User`` as a fallback when Bearer is absent/invalid.
* ``app/static/js/app.js`` now attaches ``Authorization: Bearer`` from
  ``localStorage.fm_access_token`` alongside the X-API-Key.

Self-contained: installs a dedicated in-memory SQLite engine with
``StaticPool`` so every connection sees the same DB, and overrides the
``get_db`` FastAPI dependency only for the duration of this module.
"""

from __future__ import annotations

import asyncio
import hashlib
import io

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.auth import create_access_token, hash_password
from app.db.base import Base, get_db
from app.db.models import ApiKey, TierEnum, User
from app.main import app

# ── Module-scoped test engine ──────────────────────────────────────────────────

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
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def _wipe_between_tests():
    asyncio.run(_reset_tables())
    yield


# ── Helpers ────────────────────────────────────────────────────────────────────


async def _insert_business_user(email: str = "biz@x.test") -> User:
    async with _TestSession() as s:
        user = User(
            email=email,
            password_hash=hash_password("test-password"),
            tier=TierEnum.business,
        )
        s.add(user)
        await s.commit()
        await s.refresh(user)
        return user


async def _insert_api_key_for(user: User, raw_key: str) -> ApiKey:
    async with _TestSession() as s:
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        api_key = ApiKey(user_id=user.id, key_hash=key_hash, label="test")
        s.add(api_key)
        await s.commit()
        await s.refresh(api_key)
        return api_key


def _two_jpegs(sample_jpg) -> list[tuple[str, tuple[str, io.BytesIO, str]]]:
    """Return a 2-file multipart payload so we actually trip the batch-size
    gate. Same file content twice is fine; the test is about tier resolution,
    not conversion correctness."""
    data = sample_jpg.read_bytes()
    return [
        ("files", ("one.jpg", io.BytesIO(data), "image/jpeg")),
        ("files", ("two.jpg", io.BytesIO(data), "image/jpeg")),
    ]


# ── Tests ──────────────────────────────────────────────────────────────────────


def test_batch_resolves_bearer_jwt_to_user_tier(client, sample_jpg):
    """A logged-in business-tier user must pass the batch gate via JWT
    — ``get_optional_user`` resolves the Bearer token to the User, so
    ``tier_for(user)`` sees ``business`` (limit 100) and a 2-file batch
    is not rejected with ``tier limit of 1``."""
    user = asyncio.run(_insert_business_user())
    token = create_access_token(str(user.id), role=user.role.value)

    res = client.post(
        "/api/v1/convert/batch",
        files=_two_jpegs(sample_jpg),
        data={"target_formats": ["png", "png"]},
        headers={"Authorization": f"Bearer {token}"},
    )

    # The tier-resolution assertion is the load-bearing one. The batch
    # itself should succeed (ZIP back) or at worst return a per-file error
    # envelope — but NOT the anonymous "tier limit of 1" wall.
    body = res.text
    assert "tier limit of 1" not in body, (
        f"Bearer JWT for business user did not lift tier — response: {body!r}"
    )
    assert res.status_code != 400 or "tier limit" not in body


def test_batch_resolves_x_api_key_to_user_tier(client, sample_jpg):
    """A DB-registered API key must resolve to its owner via
    ``get_optional_user``'s X-API-Key fallback, so a 2-file batch using
    the raw key (CLI path) is not rejected with ``tier limit of 1``."""
    from tests.conftest import TEST_KEY

    # The file-based JSON already has TEST_KEY's hash (conftest seeds it),
    # so ``require_api_key`` passes. We also register it in the DB
    # ``api_keys`` table pointing at a business-tier user, so the new
    # ``get_optional_user`` fallback finds it and returns that user.
    user = asyncio.run(_insert_business_user())
    asyncio.run(_insert_api_key_for(user, TEST_KEY))

    res = client.post(
        "/api/v1/convert/batch",
        files=_two_jpegs(sample_jpg),
        data={"target_formats": ["png", "png"]},
        headers={"X-API-Key": TEST_KEY},
    )

    body = res.text
    assert "tier limit of 1" not in body, (
        f"X-API-Key for business user did not lift tier — response: {body!r}"
    )


def test_batch_anonymous_still_capped_at_one(client, sample_jpg):
    """Regression guard on the anonymous path — no JWT, no X-API-Key →
    ``tier_for(None)`` stays ``anonymous`` and batch limit of 1 holds."""
    res = client.post(
        "/api/v1/convert/batch",
        files=_two_jpegs(sample_jpg),
        data={"target_formats": ["png", "png"]},
    )
    assert res.status_code == 400
    assert "tier limit of 1" in res.json()["detail"]
