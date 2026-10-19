# SPDX-License-Identifier: AGPL-3.0-or-later
"""Account lookup and password checks in the auth routes.

* "Forgot password" matches the address exactly, ignoring case; case
  variants of one address resolve to the spelling entered, or to no account.
* The reset email is sent after the response.
* Sign-in checks the password against a dummy hash when no account matches.
* bcrypt runs in a worker thread, not on the event loop, and reads the first
  72 bytes of a password.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import bcrypt
import pytest
from fastapi import BackgroundTasks
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from starlette.requests import Request

from app.api.routes import auth as auth_route
from app.core import email as email_mod
from app.core.auth import DUMMY_PASSWORD_HASH, hash_password, verify_password
from app.core.tokens import create_password_reset_token, password_hash_version
from app.db.base import Base, get_db
from app.db.models import User
from app.main import app

_engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_Session = async_sessionmaker(_engine, expire_on_commit=False, class_=AsyncSession)
_PASSWORD_HASH = hash_password("correct-password")


async def _override_get_db():
    async with _Session() as session:
        yield session


@pytest.fixture(scope="module", autouse=True)
def _database():
    async def _create():
        async with _engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create())
    app.dependency_overrides[get_db] = _override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def _no_users():
    async def _wipe():
        async with _Session() as session:
            await session.execute(delete(User))
            await session.commit()

    asyncio.run(_wipe())


@pytest.fixture
def sent_mail(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr(email_mod, "send_email", mock)
    return mock


def _add_users(*emails: str) -> list[User]:
    async def _insert():
        users = [User(email=e, password_hash=_PASSWORD_HASH, preferred_lang="en") for e in emails]
        async with _Session() as session:
            session.add_all(users)
            await session.commit()
        return users

    return asyncio.run(_insert())


def _forgot(client, email: str):
    return client.post("/api/v1/auth/forgot-password", json={"email": email})


def _where_called(real, calls: list[str]):
    """Wrap ``real`` to record whether it ran on the event loop's thread."""

    def wrapper(*args):
        try:
            asyncio.get_running_loop()
            calls.append("event loop")
        except RuntimeError:
            calls.append("worker thread")
        return real(*args)

    return wrapper


# ── Forgot password ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("entered", ["%@example.com", "_eal@example.com"])
def test_forgot_password_needs_the_whole_address(client, sent_mail, entered):
    _add_users("real@example.com")
    res = _forgot(client, entered)
    assert res.status_code == 200
    assert res.json() == auth_route._ENUMERATION_SAFE_RESPONSE
    sent_mail.assert_not_awaited()


def test_forgot_password_ignores_case(client, sent_mail):
    _add_users("Mixed.Case@example.com")
    assert _forgot(client, "mixed.case@example.com").status_code == 200
    assert sent_mail.await_args.kwargs["to"] == "Mixed.Case@example.com"


def test_forgot_password_matches_a_non_ascii_address_as_stored(client, sent_mail):
    _add_users("\u00c4rger@example.com")
    assert _forgot(client, "\u00c4rger@example.com").status_code == 200
    sent_mail.assert_awaited_once()


def test_case_variants_resolve_to_the_spelling_entered(client, sent_mail):
    _add_users("Twin@example.com", "twin@example.com")
    assert _forgot(client, "twin@example.com").status_code == 200
    assert [call.kwargs["to"] for call in sent_mail.await_args_list] == ["twin@example.com"]


def test_case_variants_without_the_spelling_entered_get_no_mail(client, sent_mail):
    _add_users("Twin@example.com", "twin@example.com")
    res = _forgot(client, "TWIN@example.com")
    assert res.status_code == 200
    assert res.json() == auth_route._ENUMERATION_SAFE_RESPONSE
    sent_mail.assert_not_awaited()


def test_the_reset_mail_is_sent_after_the_response(sent_mail):
    _add_users("real@example.com")

    async def _call():
        tasks = BackgroundTasks()
        request = Request(
            {"type": "http", "method": "POST", "path": "/", "headers": [], "query_string": b""}
        )
        body = auth_route.ForgotPasswordRequest(email="real@example.com")
        async with _Session() as db:
            answer = await auth_route.forgot_password.__wrapped__(
                request=request, body=body, background_tasks=tasks, db=db
            )
        assert answer == auth_route._ENUMERATION_SAFE_RESPONSE
        sent_mail.assert_not_awaited()  # nothing was sent while answering
        await tasks()
        sent_mail.assert_awaited_once()
        assert sent_mail.await_args.kwargs["to"] == "real@example.com"

    asyncio.run(_call())


# ── Sign-in ──────────────────────────────────────────────────────────────────


def test_sign_in_without_an_account_checks_the_dummy_hash(client, monkeypatch):
    checked: list[str] = []

    def _verify(password, password_hash):
        checked.append(password_hash)
        return False

    monkeypatch.setattr(auth_route, "verify_password", _verify)
    _add_users("real@example.com")
    for email in ("nobody@example.com", "real@example.com"):
        res = client.post("/api/v1/auth/login", json={"email": email, "password": "wrong-password"})
        assert res.status_code == 401
        assert res.json()["detail"] == "Invalid email or password."
    assert checked == [DUMMY_PASSWORD_HASH, _PASSWORD_HASH]


def test_the_dummy_hash_is_a_valid_cost_12_bcrypt_hash():
    assert DUMMY_PASSWORD_HASH[:7] == _PASSWORD_HASH[:7] == "$2b$12$"
    # bcrypt itself, not verify_password: that one turns a malformed hash into False.
    assert bcrypt.checkpw(b"correct-password", DUMMY_PASSWORD_HASH.encode()) is False


# ── bcrypt off the event loop ────────────────────────────────────────────────


def test_sign_in_checks_the_password_in_a_worker_thread(client, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(auth_route, "verify_password", _where_called(verify_password, calls))
    _add_users("real@example.com")
    res = client.post(
        "/api/v1/auth/login", json={"email": "real@example.com", "password": "correct-password"}
    )
    assert res.status_code == 200
    assert calls == ["worker thread"]


def test_register_hashes_the_password_in_a_worker_thread(client, sent_mail, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(auth_route, "hash_password", _where_called(hash_password, calls))
    res = client.post(
        "/api/v1/auth/register", json={"email": "new@example.com", "password": "a-new-password"}
    )
    assert res.status_code == 201
    assert calls == ["worker thread"]


def test_reset_hashes_the_password_in_a_worker_thread(client, monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(auth_route, "hash_password", _where_called(hash_password, calls))
    (user,) = _add_users("real@example.com")
    token = create_password_reset_token(str(user.id), password_hash_version(user.password_hash))
    res = client.post(
        "/api/v1/auth/reset-password", json={"token": token, "new_password": "a-new-password"}
    )
    assert res.status_code == 200
    assert calls == ["worker thread"]


def test_long_passwords_register_and_sign_in(client, sent_mail):
    password = "\u00e4" * 60  # 120 bytes in UTF-8
    res = client.post(
        "/api/v1/auth/register", json={"email": "long@example.com", "password": password}
    )
    assert res.status_code == 201, res.text
    res = client.post(
        "/api/v1/auth/login", json={"email": "long@example.com", "password": password}
    )
    assert res.status_code == 200, res.text


def test_a_hash_of_the_first_72_bytes_verifies_the_whole_password():
    # The hash bcrypt 4 stored for a long password: it only ever read 72 bytes.
    password = "x" * 100
    old_hash = bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt(rounds=4)).decode()
    assert verify_password(password, old_hash) is True
    assert verify_password("x" * 71, old_hash) is False
