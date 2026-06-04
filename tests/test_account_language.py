# SPDX-License-Identifier: AGPL-3.0-or-later
"""PR-i18n-3: ``PUT /api/v1/auth/account/language`` — email-language preference.

Self-contained (own in-memory SQLite + ``get_db`` override + per-test wipe),
mirroring the pattern in ``tests.test_account_deletion``.

Pinned:

* a logged-in user can set ``preferred_lang`` to a supported locale; the
  column is persisted and ``GET /auth/me`` reflects it;
* an unsupported value is a 422 (Pydantic validator) and leaves the column
  untouched;
* the route requires auth (no bearer → 401);
* a fresh registration starts with ``preferred_lang`` already populated
  from the request locale, and the endpoint changes it from there.
"""

from __future__ import annotations

import asyncio

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.auth import hash_password
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


async def _insert_user(*, email: str, preferred_lang: str | None = None) -> User:
    async with _TestSession() as s:
        user = User(
            email=email,
            password_hash=hash_password("initial-password"),
            preferred_lang=preferred_lang,
        )
        s.add(user)
        await s.commit()
        await s.refresh(user)
        return user


async def _preferred_lang(email: str) -> str | None:
    async with _TestSession() as s:
        r = await s.execute(select(User).where(User.email == email))
        return r.scalar_one().preferred_lang


def _login(client, email: str) -> str:
    res = client.post("/api/v1/auth/login", json={"email": email, "password": "initial-password"})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Happy path ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("lang", ["de", "en"])
def test_set_preferred_language_persists(client, lang):
    asyncio.run(
        _insert_user(email="lang@example.com", preferred_lang="en" if lang == "de" else "de")
    )
    token = _login(client, "lang@example.com")

    res = client.put(
        "/api/v1/auth/account/language",
        json={"preferred_lang": lang},
        headers=_auth(token),
    )
    assert res.status_code == 200, res.text
    assert res.json()["preferred_lang"] == lang
    assert asyncio.run(_preferred_lang("lang@example.com")) == lang

    me = client.get("/api/v1/auth/me", headers=_auth(token))
    assert me.status_code == 200
    assert me.json()["preferred_lang"] == lang


def test_set_preferred_language_rejects_unsupported(client):
    asyncio.run(_insert_user(email="bad@example.com", preferred_lang="de"))
    token = _login(client, "bad@example.com")

    res = client.put(
        "/api/v1/auth/account/language",
        json={"preferred_lang": "zz"},
        headers=_auth(token),
    )
    assert res.status_code == 422, res.text
    # column unchanged
    assert asyncio.run(_preferred_lang("bad@example.com")) == "de"


def test_set_preferred_language_requires_auth(client):
    asyncio.run(_insert_user(email="noauth@example.com"))
    res = client.put("/api/v1/auth/account/language", json={"preferred_lang": "en"})
    assert res.status_code == 401


def test_register_then_change_language(client):
    # /register seeds preferred_lang from the request locale; the endpoint
    # changes it from there.
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": "flow@example.com", "password": "longenough"},
        headers={"Accept-Language": "de"},
    )
    assert reg.status_code == 201, reg.text
    token = reg.json()["access_token"]
    assert client.get("/api/v1/auth/me", headers=_auth(token)).json()["preferred_lang"] == "de"

    res = client.put(
        "/api/v1/auth/account/language",
        json={"preferred_lang": "en"},
        headers=_auth(token),
    )
    assert res.status_code == 200
    assert client.get("/api/v1/auth/me", headers=_auth(token)).json()["preferred_lang"] == "en"
    assert asyncio.run(_preferred_lang("flow@example.com")) == "en"
