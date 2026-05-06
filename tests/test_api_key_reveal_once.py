# SPDX-License-Identifier: AGPL-3.0-or-later
"""H6 — API-key plaintext-reveal-once regression guard.

Privacy policy § 2e:
    > Only the SHA-256 hash of your key is stored. The plaintext key is
    > shown to you exactly once at creation time and is never persisted
    > on our servers.

Two ways this promise can silently break:

1. A future endpoint accidentally returns the plaintext (e.g., a debug
   route, an admin export, an unfortunate ``response_model`` change).
2. A future migration adds a ``key`` column to the response model of
   ``GET /keys`` to "make it easier" — and now every list call leaks
   every key.

The test creates a key, asserts the plaintext is in the *creation*
response (the reveal), then asserts no subsequent list/auth path
returns it. This pins the contract; if a regression introduces a leak,
this fails before merge.

Test scaffolding mirrors ``tests/test_account_deletion.py`` — a
module-scoped sqlite-in-memory engine that replaces ``get_db``.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.auth import hash_password
from app.db.base import Base, get_db
from app.db.models import RoleEnum, TierEnum, User
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


async def _reset() -> None:
    async with _TestSession() as s:
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
    asyncio.run(_reset())
    yield


async def _insert_user(email: str, password: str = "initial-password") -> User:
    async with _TestSession() as s:
        user = User(
            email=email,
            password_hash=hash_password(password),
            tier=TierEnum.free,
            role=RoleEnum.user,
            is_active=True,
            email_verified_at=None,
        )
        s.add(user)
        await s.commit()
        await s.refresh(user)
        return user


def _login_token(client, email: str, password: str = "initial-password") -> str:
    res = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def test_create_key_reveals_plaintext_in_response(client) -> None:
    """The reveal-once happens here. POST /api/v1/keys returns the
    plaintext under ``key``. This is the *only* legitimate exposure."""
    asyncio.run(_insert_user("alice@example.com"))
    token = _login_token(client, "alice@example.com")
    res = client.post(
        "/api/v1/keys",
        json={"label": "ci-test-key"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 201, res.text
    data = res.json()
    # Plaintext must be in the create response
    assert "key" in data, "Create-key response must include the plaintext under `key`"
    assert isinstance(data["key"], str) and len(data["key"]) > 16, (
        "Plaintext key looks too short to be a real token"
    )
    # And metadata must be there too
    assert data["label"] == "ci-test-key"
    assert "id" in data
    assert "created_at" in data


def test_list_keys_never_returns_plaintext(client) -> None:
    """After creation, GET /api/v1/keys must return only metadata. The
    plaintext is gone for good — only the SHA-256 hash lives in the DB.
    A future change that adds the plaintext to the list response would
    silently leak every key on every list call."""
    asyncio.run(_insert_user("bob@example.com"))
    token = _login_token(client, "bob@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    # Create three keys
    plaintexts = []
    for label in ["k1", "k2", "k3"]:
        res = client.post("/api/v1/keys", json={"label": label}, headers=headers)
        assert res.status_code == 201
        plaintexts.append(res.json()["key"])

    # List them — none of the plaintexts may appear in the response body
    res = client.get("/api/v1/keys", headers=headers)
    assert res.status_code == 200, res.text
    body = res.text  # full HTTP body, not just JSON
    for plaintext in plaintexts:
        assert plaintext not in body, (
            f"Plaintext API key leaked in /keys list response: prefix {plaintext[:8]}…"
        )

    # And explicitly: no item has a "key" field
    items = res.json()
    assert len(items) == 3
    for item in items:
        assert "key" not in item, f"List item should never carry plaintext `key` field: {item}"


def test_key_response_schema_is_metadata_only(client) -> None:
    """Defensive schema pin: the list-response item shape is fixed.
    Adding ``key`` (or anything containing it) to the response model
    fails this test before a single user is affected."""
    asyncio.run(_insert_user("carol@example.com"))
    token = _login_token(client, "carol@example.com")
    headers = {"Authorization": f"Bearer {token}"}
    client.post("/api/v1/keys", json={"label": "the-key"}, headers=headers)

    res = client.get("/api/v1/keys", headers=headers)
    assert res.status_code == 200
    items = res.json()
    assert len(items) == 1
    item = items[0]
    expected_fields = {"id", "label", "created_at", "last_used_at", "is_active"}
    assert set(item.keys()) == expected_fields, (
        f"Unexpected fields in /keys response: extra={set(item.keys()) - expected_fields}, "
        f"missing={expected_fields - set(item.keys())}"
    )
