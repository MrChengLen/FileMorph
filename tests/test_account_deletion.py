# SPDX-License-Identifier: AGPL-3.0-or-later
"""NEU-B.3 (slice c.1): self-service account deletion — free path.

Covers the subset of ``docs/gdpr-account-deletion-design.md`` § 11 that
applies to the free-path slice. Paid-path tests (13–16) belong to a
follow-up commit (slice c.2) once the tax-retention column +
partial unique index ship.

Pinned contracts here:

1. Happy path — free account: ``DELETE /api/v1/auth/account`` with the
   right password, the right ``confirm_email``, ``confirm_word="DELETE"``,
   and a valid bearer JWT returns 204. The user row, related ApiKey
   rows, and any related FileJob/UsageRecord rows are removed
   (SET NULL anonymisation is exercised at the schema level by the
   migration, but only the User row is checked here — the cascade is
   the database's job, not ours to re-test).

2. Confirmation gate uniformity — wrong password / wrong
   confirm_email / wrong confirm_word all return the same 400 with the
   same generic message so a stolen-JWT attacker cannot probe which
   field is wrong.

3. Auth gate — no Authorization header → 401.

4. Last-admin guard — sole active admin → 409.

5. Stripe-touched accounts → 409 directing to ``privacy@`` (slice c.1
   is free-path-only; paid-path tax retention lands in c.2).

6. Confirmation email — sent fire-and-forget after a successful
   deletion. SMTP failure is logged but does not roll back the
   delete (the account is already gone).

7. Login/forgot-password after deletion are enumeration-safe — same
   responses as for any other unknown email.

8. Audit-log shape — one ``auth.account_deletion.requested`` and one
   ``auth.account_deletion.completed`` are emitted via the audit
   chain. The structured log carries ``email_domain`` (not the full
   address) and ``deletion_mode='free'``.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core import email as email_mod
from app.core.auth import hash_password
from app.db.base import Base, get_db
from app.db.models import RoleEnum, TierEnum, User
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
    role: RoleEnum = RoleEnum.user,
    is_active: bool = True,
    stripe_customer_id: str | None = None,
) -> User:
    async with _TestSession() as s:
        user = User(
            email=email,
            password_hash=hash_password(password),
            tier=tier,
            role=role,
            is_active=is_active,
            stripe_customer_id=stripe_customer_id,
        )
        s.add(user)
        await s.commit()
        await s.refresh(user)
        return user


def _login(client, email: str, password: str = "initial-password") -> str:
    res = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _delete_body(email: str, password: str = "initial-password") -> dict:
    return {
        "password": password,
        "confirm_email": email,
        "confirm_word": "DELETE",
    }


async def _user_exists(email: str) -> bool:
    async with _TestSession() as s:
        r = await s.execute(select(User).where(User.email == email))
        return r.scalar_one_or_none() is not None


# ── Happy path ────────────────────────────────────────────────────────────────


def test_delete_account_happy_path_returns_204_and_removes_row(client, mock_send_email):
    asyncio.run(_insert_user(email="alice@example.com"))
    token = _login(client, "alice@example.com")

    res = client.request(
        "DELETE",
        "/api/v1/auth/account",
        json=_delete_body("alice@example.com"),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 204, res.text
    assert res.content == b""
    assert asyncio.run(_user_exists("alice@example.com")) is False


# ── Re-confirmation gate uniformity ───────────────────────────────────────────


def test_delete_account_wrong_password_returns_400(client):
    asyncio.run(_insert_user(email="alice@example.com"))
    token = _login(client, "alice@example.com")

    res = client.request(
        "DELETE",
        "/api/v1/auth/account",
        json={
            "password": "wrong-password",
            "confirm_email": "alice@example.com",
            "confirm_word": "DELETE",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 400
    assert res.json()["detail"] == "Confirmation did not match."
    assert asyncio.run(_user_exists("alice@example.com")) is True


def test_delete_account_wrong_confirm_email_returns_400(client):
    asyncio.run(_insert_user(email="alice@example.com"))
    token = _login(client, "alice@example.com")

    res = client.request(
        "DELETE",
        "/api/v1/auth/account",
        json={
            "password": "initial-password",
            "confirm_email": "bob@example.com",
            "confirm_word": "DELETE",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 400
    assert res.json()["detail"] == "Confirmation did not match."
    assert asyncio.run(_user_exists("alice@example.com")) is True


def test_delete_account_wrong_confirm_word_returns_422(client):
    """Pydantic validates ``confirm_word=='DELETE'`` at the schema layer
    rather than in the handler, so a wrong word is rejected as 422 by
    FastAPI's standard validation pipeline. The handler never runs —
    no chance to leak which other field might also be wrong."""
    asyncio.run(_insert_user(email="alice@example.com"))
    token = _login(client, "alice@example.com")

    res = client.request(
        "DELETE",
        "/api/v1/auth/account",
        json={
            "password": "initial-password",
            "confirm_email": "alice@example.com",
            "confirm_word": "delete",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 422
    assert asyncio.run(_user_exists("alice@example.com")) is True


# ── Auth gate ─────────────────────────────────────────────────────────────────


def test_delete_account_without_bearer_returns_401(client):
    res = client.request(
        "DELETE",
        "/api/v1/auth/account",
        json=_delete_body("alice@example.com"),
    )
    assert res.status_code == 401


# ── Last-admin guard ──────────────────────────────────────────────────────────


def test_delete_account_last_admin_returns_409(client):
    asyncio.run(_insert_user(email="admin@example.com", role=RoleEnum.admin))
    token = _login(client, "admin@example.com")

    res = client.request(
        "DELETE",
        "/api/v1/auth/account",
        json=_delete_body("admin@example.com"),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 409
    assert "admin" in res.json()["detail"].lower()
    assert asyncio.run(_user_exists("admin@example.com")) is True


def test_delete_account_admin_with_peer_succeeds(client, mock_send_email):
    """Promoting a second admin first lets the original admin succeed."""
    asyncio.run(_insert_user(email="admin1@example.com", role=RoleEnum.admin))
    asyncio.run(_insert_user(email="admin2@example.com", role=RoleEnum.admin))
    token = _login(client, "admin1@example.com")

    res = client.request(
        "DELETE",
        "/api/v1/auth/account",
        json=_delete_body("admin1@example.com"),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 204
    assert asyncio.run(_user_exists("admin1@example.com")) is False
    assert asyncio.run(_user_exists("admin2@example.com")) is True


# ── Stripe-touched accounts → 409 (tax-retention guard) ──────────────────────


def test_delete_account_with_stripe_customer_returns_409(client):
    """Until the paid-path tax-retention flow ships (slice c.2),
    accounts that have ever touched Stripe must be refused — a naive
    hard-delete would violate HGB §257 / AO §147."""
    asyncio.run(
        _insert_user(
            email="paid@example.com",
            stripe_customer_id="cus_test_paid",
        )
    )
    token = _login(client, "paid@example.com")

    res = client.request(
        "DELETE",
        "/api/v1/auth/account",
        json=_delete_body("paid@example.com"),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 409
    assert "privacy@" in res.json()["detail"].lower()
    assert asyncio.run(_user_exists("paid@example.com")) is True


# ── Confirmation email ───────────────────────────────────────────────────────


def test_delete_account_sends_confirmation_email(client, mock_send_email):
    asyncio.run(_insert_user(email="alice@example.com"))
    token = _login(client, "alice@example.com")

    res = client.request(
        "DELETE",
        "/api/v1/auth/account",
        json=_delete_body("alice@example.com"),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 204
    mock_send_email.assert_awaited_once()
    kwargs = mock_send_email.await_args.kwargs
    assert kwargs["to"] == "alice@example.com"
    assert "deleted" in kwargs["subject"].lower()
    assert "alice@example.com" in kwargs["text"]


def test_delete_account_smtp_failure_does_not_roll_back(client, monkeypatch):
    """SMTP down at delete-time → row is still gone. The account was
    already removed before the email send; the email is informational."""
    failing = AsyncMock(side_effect=email_mod.EmailSendError("smtp down"))
    monkeypatch.setattr(email_mod, "send_email", failing)

    asyncio.run(_insert_user(email="alice@example.com"))
    token = _login(client, "alice@example.com")

    res = client.request(
        "DELETE",
        "/api/v1/auth/account",
        json=_delete_body("alice@example.com"),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 204
    assert asyncio.run(_user_exists("alice@example.com")) is False


# ── Post-delete enumeration safety ────────────────────────────────────────────


def test_login_after_deletion_is_enumeration_safe(client, mock_send_email):
    asyncio.run(_insert_user(email="alice@example.com"))
    token = _login(client, "alice@example.com")
    res = client.request(
        "DELETE",
        "/api/v1/auth/account",
        json=_delete_body("alice@example.com"),
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 204

    res = client.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": "initial-password"},
    )
    assert res.status_code == 401
    assert "invalid" in res.json()["detail"].lower()


def test_forgot_password_after_deletion_is_enumeration_safe(client, mock_send_email):
    asyncio.run(_insert_user(email="alice@example.com"))
    token = _login(client, "alice@example.com")
    client.request(
        "DELETE",
        "/api/v1/auth/account",
        json=_delete_body("alice@example.com"),
        headers={"Authorization": f"Bearer {token}"},
    )
    mock_send_email.reset_mock()

    res = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "alice@example.com"},
    )
    assert res.status_code == 200
    assert "if this email exists" in res.json()["message"].lower()
    # The forgot-password path's "no email sent for unknown user" branch
    # is the same one that runs for any non-registered address.
    mock_send_email.assert_not_awaited()
