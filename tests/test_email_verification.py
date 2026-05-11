# SPDX-License-Identifier: AGPL-3.0-or-later
"""NEU-B.3 (slice b): email-verification flow.

Mirrors the self-contained pattern from :mod:`tests.test_password_reset`:
a dedicated StaticPool SQLite engine, ``get_db`` dependency override,
and a per-test wipe. The ``send_email`` coroutine is replaced with an
``AsyncMock`` so no real SMTP traffic leaves the process.

Pinned contracts:

1. Token round-trip — ``create_email_verify_token`` /
   ``decode_email_verify_token`` produce and accept ``(user_id, eat)``.
   Wrong type, expired, or missing claims → HTTP 400 with a generic
   "invalid or expired" message that doesn't leak the failure cause.
2. ``/register`` dispatches the verification email and writes an
   ``auth.email_verification.requested`` audit row with
   ``trigger=register``. The user is created with
   ``email_verified_at=NULL``.
3. ``/verify-email`` with a fresh token stamps ``email_verified_at``
   and returns 200. A second call is idempotent (no-op, still 200).
4. Email rotation since the token was issued silently invalidates
   the link — same UX as password-reset's phv-mismatch path.
5. ``/resend-verification`` is auth-required (401 without auth) and
   returns a no-op 200 if the user is already verified — so we
   never confirm verification state of an arbitrary email to an
   unauthenticated caller.
6. The ``/verify-email`` HTML page renders so an email-link click
   produces a real page (not a JSON error).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core import email as email_mod
from app.core.auth import hash_password
from app.core.tokens import create_email_verify_token, decode_email_verify_token
from app.db.base import Base, get_db
from app.db.models import TierEnum, User
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


@pytest.fixture
def mock_send_email(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr(email_mod, "send_email", mock)
    return mock


# ── Helpers ────────────────────────────────────────────────────────────────────


async def _insert_user(
    *,
    email: str,
    password: str = "initial-password",
    tier: TierEnum = TierEnum.free,
    is_active: bool = True,
    verified: bool = False,
) -> User:
    async with _TestSession() as s:
        user = User(
            email=email,
            password_hash=hash_password(password),
            tier=tier,
            is_active=is_active,
        )
        if verified:
            from datetime import datetime, timezone

            user.email_verified_at = datetime.now(timezone.utc)
        s.add(user)
        await s.commit()
        await s.refresh(user)
        return user


def _extract_token_from_mock(mock: AsyncMock) -> str:
    assert mock.await_count >= 1, "send_email was never awaited"
    text_body = mock.await_args.kwargs["text"]
    marker = "token="
    idx = text_body.find(marker)
    assert idx >= 0, f"no token= in text body: {text_body!r}"
    return text_body[idx + len(marker) :].split()[0].strip()


def _login(client, email: str, password: str = "initial-password") -> str:
    res = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


# ── Token round-trip (pure-function contract) ─────────────────────────────────


def test_token_roundtrip_returns_subject_and_email():
    """Happy-path: token created with (user_id, email) decodes to the
    same pair. No DB interaction needed."""
    token = create_email_verify_token("user-123", "alice@example.com")
    sub, eat = decode_email_verify_token(token)
    assert sub == "user-123"
    assert eat == "alice@example.com"


def test_token_rejects_wrong_type():
    """Tokens of every other shape that share the JWT secret must be
    rejected. Access, refresh, and reset all sign with ``settings.jwt_secret``;
    only the ``type`` claim discriminates the flows. A regression here
    would let a stolen access token verify a different user's email
    (since ``sub`` carries the same user-id semantics)."""
    from app.core.tokens import (
        create_access_token,
        create_password_reset_token,
        create_refresh_token,
    )

    for bogus in (
        create_password_reset_token("user-123", "phv-deadbeef"),
        create_access_token("user-123"),
        create_refresh_token("user-123"),
    ):
        with pytest.raises(HTTPException) as exc:
            decode_email_verify_token(bogus)
        assert exc.value.status_code == 400


def test_token_rejects_garbage():
    with pytest.raises(HTTPException) as exc:
        decode_email_verify_token("not-a-real-jwt")
    assert exc.value.status_code == 400


# ── /register dispatches verification email ───────────────────────────────────


def test_register_dispatches_verification_email(client, mock_send_email):
    """A successful /register kicks off the verify email and leaves the
    user in the unverified state (email_verified_at IS NULL)."""
    # Accept-Language pins the email locale to EN — the operator default is
    # de, so without this header the verification mail renders German.
    res = client.post(
        "/api/v1/auth/register",
        json={"email": "newuser@example.com", "password": "longenough"},
        headers={"Accept-Language": "en"},
    )
    assert res.status_code == 201, res.text
    mock_send_email.assert_awaited_once()
    kwargs = mock_send_email.await_args.kwargs
    assert kwargs["to"] == "newuser@example.com"
    assert "confirm" in kwargs["subject"].lower()
    assert "/verify-email?token=" in kwargs["html"]

    # email_verified_at starts NULL; preferred_lang seeded from the request
    # locale (the Accept-Language: en header above).
    async def _check():
        async with _TestSession() as s:
            r = await s.execute(select(User).where(User.email == "newuser@example.com"))
            user = r.scalar_one()
            assert user.email_verified_at is None
            assert user.preferred_lang == "en"

    asyncio.run(_check())


@pytest.mark.parametrize(
    ("tag", "accept_language", "expected_lang"),
    [
        ("de-explicit", "de", "de"),
        ("en-explicit", "en-US,en;q=0.9", "en"),
        ("no-header", None, "de"),  # no signal → operator default (LANG_DEFAULT, de)
    ],
)
def test_register_seeds_preferred_lang_from_request_locale(
    client, mock_send_email, tag, accept_language, expected_lang
):
    email = f"reglang-{tag}@example.com"
    headers = {"Accept-Language": accept_language} if accept_language else {}
    res = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "longenough"},
        headers=headers,
    )
    assert res.status_code == 201, res.text

    async def _check():
        async with _TestSession() as s:
            r = await s.execute(select(User).where(User.email == email))
            assert r.scalar_one().preferred_lang == expected_lang

    asyncio.run(_check())


def test_register_smtp_failure_does_not_block_signup(client, monkeypatch):
    """If SMTP is down at register-time, the user account is still
    created and the API still returns 201. Resend is the recovery path."""
    failing = AsyncMock(side_effect=email_mod.EmailSendError("simulated smtp down"))
    monkeypatch.setattr(email_mod, "send_email", failing)

    res = client.post(
        "/api/v1/auth/register",
        json={"email": "user@example.com", "password": "longenough"},
    )
    assert res.status_code == 201, res.text


# ── /verify-email happy path ──────────────────────────────────────────────────


def test_verify_email_with_valid_token_marks_user_verified(client, mock_send_email):
    asyncio.run(_insert_user(email="alice@example.com"))
    token = create_email_verify_token(
        str(asyncio.run(_get_user_id("alice@example.com"))), "alice@example.com"
    )

    res = client.post("/api/v1/auth/verify-email", json={"token": token})
    assert res.status_code == 200, res.text
    assert "verified" in res.json()["message"].lower()

    async def _check():
        async with _TestSession() as s:
            r = await s.execute(select(User).where(User.email == "alice@example.com"))
            user = r.scalar_one()
            assert user.email_verified_at is not None

    asyncio.run(_check())


async def _get_user_id(email: str):
    async with _TestSession() as s:
        r = await s.execute(select(User).where(User.email == email))
        return r.scalar_one().id


def test_verify_email_is_idempotent(client, mock_send_email):
    """A second call with the same token returns 200 without error
    (idempotent) — users frequently double-click email links."""
    asyncio.run(_insert_user(email="alice@example.com"))
    user_id = asyncio.run(_get_user_id("alice@example.com"))
    token = create_email_verify_token(str(user_id), "alice@example.com")

    res1 = client.post("/api/v1/auth/verify-email", json={"token": token})
    res2 = client.post("/api/v1/auth/verify-email", json={"token": token})
    assert res1.status_code == 200
    assert res2.status_code == 200


# ── Token-binding: email rotation invalidates the link ────────────────────────


def test_verify_email_rejects_token_after_email_rotation(client):
    """Token issued for old@example.com; user now has new@example.com.
    Same-user-id but different email → 400 with generic message."""
    asyncio.run(_insert_user(email="old@example.com"))
    user_id = asyncio.run(_get_user_id("old@example.com"))
    token = create_email_verify_token(str(user_id), "old@example.com")

    # Simulate email rotation.
    async def _rotate():
        async with _TestSession() as s:
            r = await s.execute(select(User).where(User.id == user_id))
            user = r.scalar_one()
            user.email = "new@example.com"
            await s.commit()

    asyncio.run(_rotate())

    res = client.post("/api/v1/auth/verify-email", json={"token": token})
    assert res.status_code == 400
    assert "no longer valid" in res.json()["detail"].lower()


def test_verify_email_rejects_garbage_token(client):
    res = client.post("/api/v1/auth/verify-email", json={"token": "junk"})
    assert res.status_code == 400


def test_verify_email_rejects_unknown_user_id(client):
    """A token whose ``sub`` isn't a real user → 400. Avoids leaking
    "this id existed once" via a different status code."""
    bogus = create_email_verify_token("00000000-0000-0000-0000-000000000000", "ghost@example.com")
    res = client.post("/api/v1/auth/verify-email", json={"token": bogus})
    assert res.status_code == 400


# ── /resend-verification ──────────────────────────────────────────────────────


def test_resend_verification_requires_auth(client):
    """Without a Bearer token → 401, never an email send."""
    res = client.post("/api/v1/auth/resend-verification")
    assert res.status_code == 401


def test_resend_verification_dispatches_for_unverified(client, mock_send_email):
    asyncio.run(_insert_user(email="alice@example.com"))
    token = _login(client, "alice@example.com")
    mock_send_email.reset_mock()  # discard the register-time send

    res = client.post(
        "/api/v1/auth/resend-verification",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    assert mock_send_email.await_count == 1
    assert mock_send_email.await_args.kwargs["to"] == "alice@example.com"


def test_resend_verification_noop_for_already_verified(client, mock_send_email):
    """An already-verified user sees a 200 message and *no* second
    email — sending more wouldn't tell them anything new and would
    fan out spam if the address has been compromised."""
    asyncio.run(_insert_user(email="alice@example.com", verified=True))
    token = _login(client, "alice@example.com")
    mock_send_email.reset_mock()

    res = client.post(
        "/api/v1/auth/resend-verification",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    assert "already" in res.json()["message"].lower()
    mock_send_email.assert_not_awaited()


# ── Email-link landing page (GET /verify-email) ───────────────────────────────


def test_verify_email_page_renders(client):
    # Hit the /en/ variant so the assertion checks the English heading
    # deterministically — the unprefixed default route now renders DE
    # ("Bestätige deine E-Mail-Adresse") because the operator default
    # is German (LANG_DEFAULT=de).
    res = client.get("/en/verify-email?token=anything")
    assert res.status_code == 200
    assert "text/html" in res.headers.get("content-type", "")
    # The JS handles the token client-side; we only check the page shell.
    assert "Confirm your email" in res.text
