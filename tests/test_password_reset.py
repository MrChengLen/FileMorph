# SPDX-License-Identifier: AGPL-3.0-or-later
"""Forgot / reset password flow — JWT+phv token lifecycle, SMTP mocked out.

Database: the shared Cloud test database (``cloud_db``, tests/support/db.py), emptied before every test. No real SMTP traffic leaves the process — the
``app.core.email.send_email`` coroutine is replaced with an
``AsyncMock`` via fixture.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from app.core import email as email_mod
from app.core.auth import hash_password
from app.core.tokens import create_password_reset_token, password_hash_version
from app.db.models import TierEnum, User

from tests.support.db import TestSession, cloud_db

_db = cloud_db()


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
) -> User:
    async with TestSession() as s:
        user = User(
            email=email,
            password_hash=hash_password(password),
            tier=tier,
            is_active=is_active,
        )
        s.add(user)
        await s.commit()
        await s.refresh(user)
        return user


def _extract_token_from_mock(mock: AsyncMock) -> str:
    """Pull the reset URL out of the most-recent ``send_email`` call and
    return just the ``token`` query-parameter value."""
    assert mock.await_count >= 1, "send_email was never awaited"
    kwargs = mock.await_args.kwargs
    text_body = kwargs["text"]
    # The plain-text template has `reset_url` on its own line; scan it.
    marker = "token="
    idx = text_body.find(marker)
    assert idx >= 0, f"no token= in text body: {text_body!r}"
    token = text_body[idx + len(marker) :].split()[0].strip()
    return token


# ── /forgot-password ───────────────────────────────────────────────────────────


def test_forgot_password_unknown_email_still_200(client, mock_send_email):
    res = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "nobody@example.com"},
    )
    assert res.status_code == 200
    assert "if this email exists" in res.json()["message"].lower()
    mock_send_email.assert_not_awaited()


def test_forgot_password_sends_email_when_user_exists(client, mock_send_email):
    asyncio.run(_insert_user(email="real@example.com"))

    # Accept-Language pins the reset-email locale to EN (operator default is de).
    res = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "real@example.com"},
        headers={"Accept-Language": "en"},
    )
    assert res.status_code == 200
    mock_send_email.assert_awaited_once()
    kwargs = mock_send_email.await_args.kwargs
    assert kwargs["to"] == "real@example.com"
    assert "reset" in kwargs["subject"].lower()
    assert "/reset-password#token=" in kwargs["text"]
    assert "/reset-password#token=" in kwargs["html"]
    assert "?token=" not in kwargs["html"] + kwargs["text"]


def test_forgot_password_skips_deactivated_user(client, mock_send_email):
    asyncio.run(_insert_user(email="dead@example.com", is_active=False))

    res = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "dead@example.com"},
    )
    assert res.status_code == 200
    mock_send_email.assert_not_awaited()


# ── /reset-password — happy path ───────────────────────────────────────────────


def test_reset_password_happy_path(client, mock_send_email):
    asyncio.run(_insert_user(email="u@example.com", password="old-password-123"))

    # 1. Request a reset
    client.post("/api/v1/auth/forgot-password", json={"email": "u@example.com"})
    token = _extract_token_from_mock(mock_send_email)

    # 2. Use the token to set a new password
    res = client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "brand-new-pw-456"},
    )
    assert res.status_code == 200
    assert res.json()["message"].lower().startswith("password updated")

    # 3. Login with the new password succeeds, the old one fails
    good = client.post(
        "/api/v1/auth/login",
        json={"email": "u@example.com", "password": "brand-new-pw-456"},
    )
    assert good.status_code == 200

    bad = client.post(
        "/api/v1/auth/login",
        json={"email": "u@example.com", "password": "old-password-123"},
    )
    assert bad.status_code == 401


# ── /reset-password — rejection paths ──────────────────────────────────────────


def test_reset_password_wrong_token_rejected(client):
    res = client.post(
        "/api/v1/auth/reset-password",
        json={"token": "obviously-not-a-jwt", "new_password": "whatever12"},
    )
    assert res.status_code == 400
    assert "invalid" in res.json()["detail"].lower()


def test_reset_password_expired_token_rejected(client):
    user = asyncio.run(_insert_user(email="expired@example.com"))
    phv = password_hash_version(user.password_hash)
    # Negative TTL = already-expired token.
    token = create_password_reset_token(str(user.id), phv, ttl_minutes=-1)
    # Give PyJWT's clock comparison no chance to round the wrong way.
    time.sleep(0.05)

    res = client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "brand-new-pw-789"},
    )
    assert res.status_code == 400


def test_reset_password_is_single_use(client, mock_send_email):
    asyncio.run(_insert_user(email="once@example.com", password="old-pass-789"))

    client.post("/api/v1/auth/forgot-password", json={"email": "once@example.com"})
    token = _extract_token_from_mock(mock_send_email)

    # First use — ok.
    first = client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "fresh-pass-123"},
    )
    assert first.status_code == 200

    # Second use of the same token — the stored password_hash now
    # differs so phv drifts. Must be rejected.
    second = client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "another-pass-123"},
    )
    assert second.status_code == 400
    assert "no longer" in second.json()["detail"].lower()


def test_reset_password_short_password_rejected(client, mock_send_email):
    asyncio.run(_insert_user(email="short@example.com"))
    client.post("/api/v1/auth/forgot-password", json={"email": "short@example.com"})
    token = _extract_token_from_mock(mock_send_email)

    res = client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": "short"},
    )
    # Pydantic validator fails before the route body runs → 422.
    assert res.status_code == 422


# ── /reset-password — sessions ─────────────────────────────────────────────────


def _login(client, email: str, password: str) -> dict:
    res = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res.json()


def _reset_via_email_link(client, mock_send_email, email: str, new_password: str) -> None:
    client.post("/api/v1/auth/forgot-password", json={"email": email})
    token = _extract_token_from_mock(mock_send_email)
    res = client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "new_password": new_password},
    )
    assert res.status_code == 200, res.text


def _bearer(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}"}


def test_reset_password_ends_sessions_from_before_the_reset(client, mock_send_email):
    """A reset signs out every session that existed before it — the access
    token and the refresh token alike, so the refresh token can't mint a new
    access token either."""
    asyncio.run(_insert_user(email="sess@example.com", password="old-password-123"))
    before = _login(client, "sess@example.com", "old-password-123")

    _reset_via_email_link(client, mock_send_email, "sess@example.com", "new-password-456")

    me = client.get("/api/v1/auth/me", headers=_bearer(before["access_token"]))
    assert me.status_code == 401
    refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": before["refresh_token"]})
    assert refreshed.status_code == 401


def test_sessions_started_after_the_reset_work(client, mock_send_email):
    asyncio.run(_insert_user(email="after@example.com", password="old-password-123"))
    _reset_via_email_link(client, mock_send_email, "after@example.com", "new-password-456")

    after = _login(client, "after@example.com", "new-password-456")
    assert client.get("/api/v1/auth/me", headers=_bearer(after["access_token"])).status_code == 200

    refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": after["refresh_token"]})
    assert refreshed.status_code == 200, refreshed.text
    me = client.get("/api/v1/auth/me", headers=_bearer(refreshed.json()["access_token"]))
    assert me.status_code == 200
    assert me.json()["email"] == "after@example.com"


def test_every_new_hash_changes_the_phv():
    """Reset links and sessions both end because a new password hash has a
    new ``phv``. Hashing the same password twice must therefore give two
    fingerprints — a hash format whose first 16 characters never vary (every
    argon2id hash starts ``$argon2id$v=19$m``) would silently keep both
    alive."""
    first = password_hash_version(hash_password("same-password-123"))
    second = password_hash_version(hash_password("same-password-123"))
    assert first != second
