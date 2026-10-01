# SPDX-License-Identifier: AGPL-3.0-or-later
"""POST /auth/refresh — when a refresh token still stands for its user.

A refresh token (and the access token next to it) works only while the
account is live — active, not deleted — and the password is the one it was
issued under (the ``phv`` claim). Refreshing never extends a sign-in: the
answer carries the presented refresh token back.

Same self-contained harness as :mod:`tests.test_password_reset`: a StaticPool
SQLite engine, the ``get_db`` override for this module, a wipe per test.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.auth import hash_password
from app.core.config import settings
from app.core.tokens import ALGORITHM, password_hash_version
from app.db.base import Base, get_db
from app.db.models import User
from app.main import app

_test_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    echo=False,
)
_TestSession = async_sessionmaker(_test_engine, expire_on_commit=False, class_=AsyncSession)

_PASSWORD = "refresh-test-password"


async def _setup_schema() -> None:
    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def _reset_tables() -> None:
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
    asyncio.run(_reset_tables())
    yield


async def _insert_user(email: str) -> User:
    async with _TestSession() as s:
        user = User(email=email, password_hash=hash_password(_PASSWORD))
        s.add(user)
        await s.commit()
        await s.refresh(user)
        return user


async def _deactivate(user: User) -> None:
    async with _TestSession() as s:
        await s.execute(update(User).where(User.id == user.id).values(is_active=False))
        await s.commit()


async def _remove(user: User) -> None:
    async with _TestSession() as s:
        await s.execute(delete(User).where(User.id == user.id))
        await s.commit()


def _login(client, email: str) -> dict:
    res = client.post("/api/v1/auth/login", json={"email": email, "password": _PASSWORD})
    assert res.status_code == 200, res.text
    return res.json()


def _hand_mint(user: User, token_type: str, **claims) -> str:
    """Sign a token the way ``app/core/tokens.py`` does — real secret, issuer
    and audience — so only the claims given here differ from a minted one."""
    base = {
        "sub": str(user.id),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
        "type": token_type,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    return jwt.encode({**base, **claims}, settings.jwt_secret, algorithm=ALGORITHM)


def test_refresh_issues_a_working_access_token(client):
    asyncio.run(_insert_user("live@example.com"))
    tokens = _login(client, "live@example.com")

    res = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert res.status_code == 200, res.text
    me = client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {res.json()['access_token']}"}
    )
    assert me.status_code == 200
    assert me.json()["email"] == "live@example.com"


def test_refresh_hands_back_the_presented_refresh_token(client):
    """Refreshing never extends a sign-in: the answer carries the refresh
    token that was sent, so the sign-in ends when that token expires — 30
    days after login at the latest. The token expires in one day here: one
    minted at login would be byte-identical to a freshly minted one issued
    in the same second. It also works twice in a row, as it must — the web
    UI can refresh from several requests at once."""
    user = asyncio.run(_insert_user("lifetime@example.com"))
    presented = _hand_mint(
        user,
        "refresh",
        exp=datetime.now(timezone.utc) + timedelta(days=1),
        phv=password_hash_version(user.password_hash),
    )

    for _ in range(2):
        res = client.post("/api/v1/auth/refresh", json={"refresh_token": presented})
        assert res.status_code == 200, res.text
        assert res.json()["refresh_token"] == presented


@pytest.mark.parametrize("end_account", [_deactivate, _remove], ids=["deactivated", "removed"])
def test_refresh_rejects_an_account_that_is_gone(client, end_account):
    user = asyncio.run(_insert_user("gone@example.com"))
    tokens = _login(client, "gone@example.com")
    asyncio.run(end_account(user))

    res = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert res.status_code == 401


def test_tokens_without_a_password_binding_are_rejected(client):
    """A token without a ``phv`` claim is refused outright: there is nothing
    to compare with the current password hash."""
    user = asyncio.run(_insert_user("legacy@example.com"))
    access = _hand_mint(user, "access", role="user")
    refresh = _hand_mint(user, "refresh")

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access}"})
    assert me.status_code == 401
    assert me.json()["detail"] == "Invalid token."
    res = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh})
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid token."


def test_refresh_needs_a_database(client):
    """Without a database there are no accounts, so there is nothing to
    refresh — 503, like login."""
    user = asyncio.run(_insert_user("nodb@example.com"))
    token = _hand_mint(user, "refresh", phv=password_hash_version(user.password_hash))
    saved_override = app.dependency_overrides.pop(get_db)
    try:
        res = client.post("/api/v1/auth/refresh", json={"refresh_token": token})
    finally:
        app.dependency_overrides[get_db] = saved_override
    assert res.status_code == 503
