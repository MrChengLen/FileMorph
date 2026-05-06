# SPDX-License-Identifier: AGPL-3.0-or-later
"""NEU-B.3 (slice a): auth events land in the audit chain.

ISO 27001 A.9.4.2 ("Secure log-on procedures") and A.9.2.1
("User registration and de-registration") expect successful and
failed authentication events to leave a tamper-evident trail.
NEU-B.1 shipped the chain itself; this slice wires four routes —
``/auth/register``, ``/auth/login``, ``/auth/forgot-password``,
``/auth/reset-password`` — into that chain.

These tests drive the routes through ``TestClient`` and inspect
the resulting ``audit_events`` rows. The harness is the same
StaticPool / SQLite shape used in ``test_password_reset.py``,
extended with one extra step: ``app.core.audit.AsyncSessionLocal``
gets re-pointed at the test session factory so ``record_event``'s
self-owned session uses the test database. Without that override
the helper would early-return (no DATABASE_URL → no audit-log).

Properties verified
-------------------
1. Successful registration writes a single ``auth.register.success``
   row, with ``actor_user_id`` set to the new user's id.
2. A duplicate-email registration writes ``auth.register.duplicate``
   with the SHA-256 of the email — *not* the email itself — and no
   ``actor_user_id``.
3. Successful login writes ``auth.login.success``.
4. Wrong-password login writes ``auth.login.failure`` with the
   email-hash, no ``actor_user_id`` (no enumeration leak).
5. ``/auth/forgot-password`` writes ``auth.password_reset.requested``
   on the match path *and* the no-match path. The match path
   sets ``actor_user_id``; the no-match path leaves it null.
6. ``/auth/reset-password`` (happy path) writes
   ``auth.password_reset.completed`` with the user's id.
7. The chain remains intact after the auth events — verifiable via
   ``audit.verify_chain``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core import audit as audit_module
from app.core.audit import verify_chain
from app.core.auth import hash_password
from app.db.base import Base, get_db
from app.db.models import AuditEvent, TierEnum, User
from app.main import app


# ── Test engine — single in-memory SQLite shared across tests ───────────────

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


async def _wipe() -> None:
    async with _TestSession() as s:
        await s.execute(delete(AuditEvent))
        await s.execute(delete(User))
        await s.commit()


async def _override_get_db():
    async with _TestSession() as session:
        yield session


@pytest.fixture(scope="module", autouse=True)
def _install_overrides():
    asyncio.run(_setup_schema())
    app.dependency_overrides[get_db] = _override_get_db
    # Re-point audit's self-owned session factory at the test engine.
    # Without this, record_event returns early because
    # AsyncSessionLocal is None in the default test environment.
    original = audit_module.AsyncSessionLocal
    audit_module.AsyncSessionLocal = _TestSession
    yield
    audit_module.AsyncSessionLocal = original
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture(autouse=True)
def _wipe_between_tests():
    asyncio.run(_wipe())
    yield


# ── Helpers ─────────────────────────────────────────────────────────────────


def _events_by_type(event_type: str) -> list[AuditEvent]:
    async def _q():
        async with _TestSession() as s:
            res = await s.execute(
                select(AuditEvent)
                .where(AuditEvent.event_type == event_type)
                .order_by(AuditEvent.id.asc())
            )
            return list(res.scalars().all())

    return asyncio.run(_q())


def _all_events() -> list[AuditEvent]:
    async def _q():
        async with _TestSession() as s:
            res = await s.execute(select(AuditEvent).order_by(AuditEvent.id.asc()))
            return list(res.scalars().all())

    return asyncio.run(_q())


def _email_hash(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()


async def _insert_user(*, email: str, password: str = "initial-password") -> User:
    async with _TestSession() as s:
        user = User(email=email, password_hash=hash_password(password), tier=TierEnum.free)
        s.add(user)
        await s.commit()
        await s.refresh(user)
        return user


# ── 1. /register success ────────────────────────────────────────────────────


def test_register_success_writes_audit_event(client):
    res = client.post(
        "/api/v1/auth/register",
        json={"email": "fresh@example.com", "password": "abcdefghi"},
    )
    assert res.status_code == 201, res.text

    rows = _events_by_type("auth.register.success")
    assert len(rows) == 1
    assert rows[0].actor_user_id is not None
    # Email plaintext must not appear in the payload.
    assert "fresh@example.com" not in rows[0].payload_json


# ── 2. /register duplicate ──────────────────────────────────────────────────


def test_register_duplicate_writes_email_hash_not_email(client):
    asyncio.run(_insert_user(email="taken@example.com"))

    res = client.post(
        "/api/v1/auth/register",
        json={"email": "taken@example.com", "password": "abcdefghi"},
    )
    assert res.status_code == 409

    rows = _events_by_type("auth.register.duplicate")
    assert len(rows) == 1
    assert rows[0].actor_user_id is None
    payload = json.loads(rows[0].payload_json)
    assert payload["email_hash"] == _email_hash("taken@example.com")
    assert "taken@example.com" not in rows[0].payload_json


# ── 3. /login success ──────────────────────────────────────────────────────


def test_login_success_writes_audit_event(client):
    user = asyncio.run(_insert_user(email="login@example.com", password="pw-correct-1"))

    res = client.post(
        "/api/v1/auth/login",
        json={"email": "login@example.com", "password": "pw-correct-1"},
    )
    assert res.status_code == 200, res.text

    rows = _events_by_type("auth.login.success")
    assert len(rows) == 1
    assert str(rows[0].actor_user_id) == str(user.id)


# ── 4. /login failure ──────────────────────────────────────────────────────


def test_login_failure_records_email_hash_only(client):
    asyncio.run(_insert_user(email="login@example.com", password="pw-correct-1"))

    res = client.post(
        "/api/v1/auth/login",
        json={"email": "login@example.com", "password": "wrong-password"},
    )
    assert res.status_code == 401

    rows = _events_by_type("auth.login.failure")
    assert len(rows) == 1
    # No actor_user_id — we don't reveal whether the email is real.
    assert rows[0].actor_user_id is None
    payload = json.loads(rows[0].payload_json)
    assert payload["email_hash"] == _email_hash("login@example.com")
    assert "login@example.com" not in rows[0].payload_json


def test_login_failure_for_unknown_email_records_email_hash(client):
    """No user in the DB at all — failure path still records the
    attempt-shape so brute-force scans are visible."""
    res = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "anything"},
    )
    assert res.status_code == 401

    rows = _events_by_type("auth.login.failure")
    assert len(rows) == 1
    assert rows[0].actor_user_id is None
    payload = json.loads(rows[0].payload_json)
    assert payload["email_hash"] == _email_hash("nobody@example.com")


# ── 5. /forgot-password — match + no-match both record ─────────────────────


def test_forgot_password_match_writes_event_with_user_id(client, monkeypatch):
    from app.core import email as email_mod
    from unittest.mock import AsyncMock

    monkeypatch.setattr(email_mod, "send_email", AsyncMock())

    user = asyncio.run(_insert_user(email="real@example.com"))

    res = client.post("/api/v1/auth/forgot-password", json={"email": "real@example.com"})
    assert res.status_code == 200

    rows = _events_by_type("auth.password_reset.requested")
    assert len(rows) == 1
    assert str(rows[0].actor_user_id) == str(user.id)
    payload = json.loads(rows[0].payload_json)
    assert payload["email_hash"] == _email_hash("real@example.com")


def test_forgot_password_no_match_writes_event_without_user_id(client, monkeypatch):
    from app.core import email as email_mod
    from unittest.mock import AsyncMock

    mock = AsyncMock()
    monkeypatch.setattr(email_mod, "send_email", mock)

    res = client.post("/api/v1/auth/forgot-password", json={"email": "nobody@example.com"})
    assert res.status_code == 200
    mock.assert_not_awaited()

    rows = _events_by_type("auth.password_reset.requested")
    assert len(rows) == 1
    assert rows[0].actor_user_id is None
    payload = json.loads(rows[0].payload_json)
    assert payload["email_hash"] == _email_hash("nobody@example.com")


# ── 6. /reset-password — completed event ───────────────────────────────────


def test_reset_password_completion_writes_event(client, monkeypatch):
    """End-to-end: forgot → reset → login. Audit chain has the
    completed event with the user's id."""
    from app.core import email as email_mod
    from unittest.mock import AsyncMock

    mock = AsyncMock()
    monkeypatch.setattr(email_mod, "send_email", mock)

    user = asyncio.run(_insert_user(email="u@example.com", password="old-pw-123"))

    client.post("/api/v1/auth/forgot-password", json={"email": "u@example.com"})
    text_body = mock.await_args.kwargs["text"]
    token = text_body[text_body.find("token=") + len("token=") :].split()[0].strip()

    res = client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "brand-new-pw-456"},
    )
    assert res.status_code == 200

    rows = _events_by_type("auth.password_reset.completed")
    assert len(rows) == 1
    assert str(rows[0].actor_user_id) == str(user.id)


# ── 7. Chain integrity after auth events ────────────────────────────────────


def test_chain_remains_intact_after_auth_events(client):
    """Multi-event smoke test: a register, a login, a failed login.
    verify_chain must walk all three rows without flagging."""
    client.post(
        "/api/v1/auth/register",
        json={"email": "chain@example.com", "password": "abcdefghi"},
    )
    client.post(
        "/api/v1/auth/login",
        json={"email": "chain@example.com", "password": "abcdefghi"},
    )
    client.post(
        "/api/v1/auth/login",
        json={"email": "chain@example.com", "password": "wrong"},
    )

    rows = _all_events()
    assert len(rows) >= 3

    async def _verify():
        async with _TestSession() as s:
            return await verify_chain(s)

    assert asyncio.run(_verify()) is None
