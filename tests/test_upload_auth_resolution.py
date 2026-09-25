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

The upload gate in front of both (``require_api_key``) must accept the same
dashboard keys: it once checked only the file store, so every key minted via
``POST /api/v1/keys`` got 401 before the fallback above could resolve it.

Self-contained: installs a dedicated in-memory SQLite engine with
``StaticPool`` so every connection sees the same DB, and overrides the
``get_db`` FastAPI dependency only for the duration of this module.
"""

from __future__ import annotations

import asyncio
import io
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.auth import hash_password
from app.core.security import validate_api_key
from app.core.tokens import create_access_token
from app.db.base import Base, get_db
from app.db.models import ApiKey, TierEnum, User
from app.main import app
from tests.conftest import TEST_KEY

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


async def _revoke_keys(user: User) -> None:
    """What ``DELETE /api/v1/keys/{id}`` does: flip ``is_active`` off. Done
    directly because that route compares its ``str`` path param to a UUID
    column, which the SQLite test engine rejects."""
    async with _TestSession() as s:
        await s.execute(update(ApiKey).where(ApiKey.user_id == user.id).values(is_active=False))
        await s.commit()


async def _update_owner(user: User, **values) -> None:
    async with _TestSession() as s:
        await s.execute(update(User).where(User.id == user.id).values(**values))
        await s.commit()


async def _last_used_at(user: User) -> datetime | None:
    async with _TestSession() as s:
        return await s.scalar(select(ApiKey.last_used_at).where(ApiKey.user_id == user.id))


def _mint_dashboard_key(client, user: User) -> str:
    """Mint a key the way the dashboard does (``POST /api/v1/keys``). It
    lands only in the DB ``api_keys`` table — never in the file store that
    self-host/CLI keys live in."""
    token = create_access_token(str(user.id), role=user.role.value)
    res = client.post(
        "/api/v1/keys", json={"label": "cli"}, headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 201, res.text
    raw_key = res.json()["key"]
    assert not validate_api_key(raw_key), "precondition: key must be DB-only"
    return raw_key


def _convert_jpg(client, sample_jpg, api_key: str):
    return client.post(
        "/api/v1/convert",
        files={"file": ("photo.jpg", sample_jpg.read_bytes(), "image/jpeg")},
        data={"target_format": "png"},
        headers={"X-API-Key": api_key},
    )


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
    """A dashboard-minted API key must pass the upload gate *and* resolve to
    its owner via ``get_optional_user``'s X-API-Key fallback, so a 2-file
    batch using the raw key (CLI path) is not rejected with ``tier limit of
    1``. The key is DB-only on purpose: this test used to reuse the
    file-store TEST_KEY, which hid that the gate rejected every dashboard
    key — hence the explicit 200 (a 401 body has no "tier limit" either)."""
    user = asyncio.run(_insert_business_user())
    raw_key = _mint_dashboard_key(client, user)

    res = client.post(
        "/api/v1/convert/batch",
        files=_two_jpegs(sample_jpg),
        data={"target_formats": ["png", "png"]},
        headers={"X-API-Key": raw_key},
    )

    body = res.text
    assert res.status_code == 200, body
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


# ── Upload gate (require_api_key) ─────────────────────────────────────────────


def test_dashboard_key_passes_upload_gate(client, sample_jpg):
    """The documented CLI path: mint a key on the dashboard, send it alone
    (no Bearer). Regression: the gate checked only the file store, so this
    got 401 "Invalid API key." for every dashboard key."""
    user = asyncio.run(_insert_business_user())
    raw_key = _mint_dashboard_key(client, user)

    res = _convert_jpg(client, sample_jpg, raw_key)

    assert res.status_code == 200, res.text
    # Only ``get_optional_user`` stamps this, so the key resolved to its owner.
    assert asyncio.run(_last_used_at(user)) is not None


def test_revoked_dashboard_key_is_rejected(client, sample_jpg):
    """A key revoked on the dashboard gets 401 — not a silent fall-through
    to the anonymous tier."""
    user = asyncio.run(_insert_business_user())
    raw_key = _mint_dashboard_key(client, user)
    asyncio.run(_revoke_keys(user))

    res = _convert_jpg(client, sample_jpg, raw_key)

    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid API key."


@pytest.mark.parametrize(
    "owner_state",
    [{"is_active": False}, {"deleted_at": datetime.now(timezone.utc)}],
    ids=["deactivated", "deleted"],
)
def test_dashboard_key_of_inactive_owner_is_rejected(client, sample_jpg, owner_state):
    """An active key whose owner is deactivated or deleted is no credential.
    ``deleted`` keeps ``is_active`` on: account deletion removes the keys,
    so this pins the ``deleted_at`` backstop that ``get_current_user`` has."""
    user = asyncio.run(_insert_business_user())
    raw_key = _mint_dashboard_key(client, user)
    asyncio.run(_update_owner(user, **owner_state))

    res = _convert_jpg(client, sample_jpg, raw_key)

    assert res.status_code == 401


def test_unknown_key_rejected_with_database_configured(client, sample_jpg):
    """The DB fallback must not widen the gate: a key in neither store is
    still 401 when a database is configured."""
    res = _convert_jpg(client, sample_jpg, "not-a-real-key")

    assert res.status_code == 401


def test_file_store_key_accepted_with_database_configured(client, sample_jpg):
    """Self-host/CLI keys from the file store have no ``api_keys`` row and
    must keep working when a database is configured."""
    res = _convert_jpg(client, sample_jpg, TEST_KEY)

    assert res.status_code == 200, res.text
