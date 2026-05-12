# SPDX-License-Identifier: AGPL-3.0-or-later
"""Self-service account deletion — free path (slice c.1) + paid path (slice c.2).

Covers ``docs/gdpr-account-deletion-design.md`` § 11.

Free path (slice c.1):

1. Happy path — free account: ``DELETE /api/v1/auth/account`` with the
   right password, the right ``confirm_email``, ``confirm_word="DELETE"``,
   and a valid bearer JWT returns 204. The user row, related ApiKey rows,
   and any related FileJob/UsageRecord rows are removed (SET NULL
   anonymisation is exercised at the schema level by the migration; only
   the User row is checked here on the free path).
2. Confirmation gate uniformity — wrong password / wrong confirm_email
   both return the same 400; wrong confirm_word is a Pydantic 422.
3. Auth gate — no Authorization header → 401.
4. Last-admin guard — sole active admin → 409.
5. Confirmation email — fire-and-forget; SMTP failure logged, no rollback.
6. Login/forgot-password after deletion are enumeration-safe.
7. Audit / structured-log shape — ``deletion_mode='free'``, ``email_domain``
   only (no plaintext address).

Paid path (slice c.2):

8.  Happy path — Stripe-linked account: ``204``; the ``users`` row is
    **retained** in the restricted state (only ``email`` /
    ``stripe_customer_id`` / ``tier`` / ``created_at`` survive; ``is_active``
    False; ``password_hash`` is the ``DELETED:`` sentinel; ``deleted_at``
    stamped; ``email_verified_at`` / ``preferred_lang`` / ``subscription_status``
    nulled). ApiKey rows are removed; FileJob/UsageRecord ``user_id`` nulled.
    ``cancel_active_subscriptions`` is called once with the customer id.
9.  Role reset — a paid admin with a peer admin: row retained with
    ``role='user'``.
10. Login after a paid-path delete → 401 with any password (the sentinel
    hash + ``is_active``/``deleted_at`` guards block it).
11. Re-registration of the same email after a paid-path delete → 201, a
    fresh row with a new UUID, ``stripe_customer_id`` NULL, ``tier='free'``;
    the old retained row is untouched (the partial unique index
    ``ix_users_email_active`` lets the two coexist).
12. Stripe error during the cancel-first pass → ``500``; the account is
    unchanged and no confirmation email is sent.
13. ``deletion_mode='tax_retained'`` in the structured log + audit payloads;
    ``deleted_password_sentinel`` is bcrypt-rejected.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock

import pytest
import stripe
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core import email as email_mod
from app.core.auth import deleted_password_sentinel, hash_password, verify_password
from app.db.base import Base, get_db
from app.db.models import ApiKey, FileJob, RoleEnum, TierEnum, UsageRecord, User
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
        # Child tables first; the paid path retains the User row, so a bare
        # ``DELETE FROM users`` would leave dangling FKs on SQLite.
        await s.execute(delete(UsageRecord))
        await s.execute(delete(FileJob))
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


@pytest.fixture
def mock_send_email(monkeypatch):
    mock = AsyncMock()
    monkeypatch.setattr(email_mod, "send_email", mock)
    return mock


@pytest.fixture
def mock_cancel_subs(monkeypatch):
    """Mock the Stripe cancel-first pass. Patched where the deletion
    service imports it (``app.core.account_deletion``), not in
    ``app.core.billing`` — the name is already bound into the service
    module's namespace by import time."""
    mock = AsyncMock()
    monkeypatch.setattr("app.core.account_deletion.cancel_active_subscriptions", mock)
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
    subscription_status: str | None = None,
    preferred_lang: str | None = None,
    email_verified_at=None,
) -> User:
    async with _TestSession() as s:
        user = User(
            email=email,
            password_hash=hash_password(password),
            tier=tier,
            role=role,
            is_active=is_active,
            stripe_customer_id=stripe_customer_id,
            subscription_status=subscription_status,
            preferred_lang=preferred_lang,
            email_verified_at=email_verified_at,
        )
        s.add(user)
        await s.commit()
        await s.refresh(user)
        return user


async def _insert_api_key(user_id, key_hash: str = "a" * 64) -> ApiKey:
    async with _TestSession() as s:
        key = ApiKey(user_id=user_id, key_hash=key_hash, label="test")
        s.add(key)
        await s.commit()
        await s.refresh(key)
        return key


async def _insert_file_job(user_id) -> FileJob:
    async with _TestSession() as s:
        job = FileJob(
            user_id=user_id,
            original_name="x.png",
            source_format="png",
            target_format="webp",
            file_size_bytes=123,
        )
        s.add(job)
        await s.commit()
        await s.refresh(job)
        return job


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


def _delete(client, email: str, token: str, password: str = "initial-password"):
    return client.request(
        "DELETE",
        "/api/v1/auth/account",
        json=_delete_body(email, password),
        headers={"Authorization": f"Bearer {token}"},
    )


async def _user_exists(email: str) -> bool:
    """Any row with this email (live or tax-retained)."""
    async with _TestSession() as s:
        r = await s.execute(select(User).where(User.email == email))
        return r.scalar_one_or_none() is not None


async def _fetch_retained_user(email: str) -> User | None:
    """The single ``deleted_at IS NOT NULL`` row for this email, if any."""
    async with _TestSession() as s:
        r = await s.execute(select(User).where(User.email == email, User.deleted_at.is_not(None)))
        return r.scalar_one_or_none()


async def _fetch_live_user(email: str) -> User | None:
    """The single ``deleted_at IS NULL`` row for this email, if any."""
    async with _TestSession() as s:
        r = await s.execute(select(User).where(User.email == email, User.deleted_at.is_(None)))
        return r.scalar_one_or_none()


async def _count_users(email: str) -> int:
    async with _TestSession() as s:
        r = await s.execute(select(User).where(User.email == email))
        return len(r.scalars().all())


async def _count_api_keys(user_id) -> int:
    async with _TestSession() as s:
        r = await s.execute(select(ApiKey).where(ApiKey.user_id == user_id))
        return len(r.scalars().all())


async def _file_job_user_id(job_id):
    async with _TestSession() as s:
        r = await s.execute(select(FileJob).where(FileJob.id == job_id))
        return r.scalar_one().user_id


# ── Free path: happy path ─────────────────────────────────────────────────────


def test_delete_account_happy_path_returns_204_and_removes_row(client, mock_send_email):
    asyncio.run(_insert_user(email="alice@example.com"))
    token = _login(client, "alice@example.com")

    res = _delete(client, "alice@example.com", token)
    assert res.status_code == 204, res.text
    assert res.content == b""
    assert asyncio.run(_user_exists("alice@example.com")) is False


# ── Free path: re-confirmation gate uniformity ────────────────────────────────


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
    FastAPI's standard validation pipeline. The handler never runs."""
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


# ── Free path: auth gate ──────────────────────────────────────────────────────


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

    res = _delete(client, "admin@example.com", token)
    assert res.status_code == 409
    assert "admin" in res.json()["detail"].lower()
    assert asyncio.run(_user_exists("admin@example.com")) is True


def test_delete_account_admin_with_peer_succeeds(client, mock_send_email):
    """Promoting a second admin first lets the original admin succeed."""
    asyncio.run(_insert_user(email="admin1@example.com", role=RoleEnum.admin))
    asyncio.run(_insert_user(email="admin2@example.com", role=RoleEnum.admin))
    token = _login(client, "admin1@example.com")

    res = _delete(client, "admin1@example.com", token)
    assert res.status_code == 204
    assert asyncio.run(_user_exists("admin1@example.com")) is False
    assert asyncio.run(_user_exists("admin2@example.com")) is True


# ── Free path: confirmation email ─────────────────────────────────────────────


def test_delete_account_sends_confirmation_email(client, mock_send_email):
    asyncio.run(_insert_user(email="alice@example.com"))
    token = _login(client, "alice@example.com")

    # Accept-Language pins the confirmation-email locale to EN (default is de).
    res = client.request(
        "DELETE",
        "/api/v1/auth/account",
        json=_delete_body("alice@example.com"),
        headers={"Authorization": f"Bearer {token}", "Accept-Language": "en"},
    )
    assert res.status_code == 204
    mock_send_email.assert_awaited_once()
    kwargs = mock_send_email.await_args.kwargs
    assert kwargs["to"] == "alice@example.com"
    assert "deleted" in kwargs["subject"].lower()
    assert "alice@example.com" in kwargs["text"]
    # Free path → no tax-retention paragraph.
    assert "HGB" not in kwargs["text"]
    assert "HGB" not in kwargs["html"]


def test_delete_account_smtp_failure_does_not_roll_back(client, monkeypatch):
    """SMTP down at delete-time → row is still gone. The account was
    already removed before the email send; the email is informational."""
    failing = AsyncMock(side_effect=email_mod.EmailSendError("smtp down"))
    monkeypatch.setattr(email_mod, "send_email", failing)

    asyncio.run(_insert_user(email="alice@example.com"))
    token = _login(client, "alice@example.com")

    res = _delete(client, "alice@example.com", token)
    assert res.status_code == 204
    assert asyncio.run(_user_exists("alice@example.com")) is False


# ── Post-delete enumeration safety (free path) ────────────────────────────────


def test_login_after_deletion_is_enumeration_safe(client, mock_send_email):
    asyncio.run(_insert_user(email="alice@example.com"))
    token = _login(client, "alice@example.com")
    assert _delete(client, "alice@example.com", token).status_code == 204

    res = client.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": "initial-password"},
    )
    assert res.status_code == 401
    assert "invalid" in res.json()["detail"].lower()


def test_forgot_password_after_deletion_is_enumeration_safe(client, mock_send_email):
    asyncio.run(_insert_user(email="alice@example.com"))
    token = _login(client, "alice@example.com")
    _delete(client, "alice@example.com", token)
    mock_send_email.reset_mock()

    res = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "alice@example.com"},
    )
    assert res.status_code == 200
    assert "if this email exists" in res.json()["message"].lower()
    mock_send_email.assert_not_awaited()


# ── Free path: structured-log shape ───────────────────────────────────────────


def test_free_path_logs_deletion_mode_free(client, mock_send_email, caplog):
    asyncio.run(_insert_user(email="alice@example.com"))
    token = _login(client, "alice@example.com")
    with caplog.at_level(logging.INFO):
        assert _delete(client, "alice@example.com", token).status_code == 204

    recs = [r for r in caplog.records if r.getMessage() == "account_deletion"]
    assert len(recs) == 1
    assert recs[0].deletion_mode == "free"
    assert recs[0].email_domain == "example.com"
    # No plaintext address anywhere in the record.
    assert "alice@example.com" not in str(recs[0].__dict__)


# ── Paid path: happy path (restricted/tax-retained delete) ────────────────────


def test_paid_path_retains_restricted_row(client, mock_send_email, mock_cancel_subs):
    user = asyncio.run(
        _insert_user(
            email="paid@example.com",
            tier=TierEnum.pro,
            stripe_customer_id="cus_test_paid",
            subscription_status="active",
            preferred_lang="en",
        )
    )
    api_key = asyncio.run(_insert_api_key(user.id))
    job = asyncio.run(_insert_file_job(user.id))
    token = _login(client, "paid@example.com")

    res = _delete(client, "paid@example.com", token)
    assert res.status_code == 204, res.text

    # Stripe cancel-first ran exactly once with the customer id.
    mock_cancel_subs.assert_awaited_once_with("cus_test_paid")

    # The users row is RETAINED in the restricted state.
    retained = asyncio.run(_fetch_retained_user("paid@example.com"))
    assert retained is not None
    assert retained.id == user.id
    assert retained.is_active is False
    assert retained.password_hash.startswith("DELETED:")
    assert retained.deleted_at is not None
    assert retained.role == RoleEnum.user
    # Kept for the HGB §257 / AO §147 record:
    assert retained.email == "paid@example.com"
    assert retained.stripe_customer_id == "cus_test_paid"
    assert retained.tier == TierEnum.pro
    # Nulled:
    assert retained.email_verified_at is None
    assert retained.preferred_lang is None
    assert retained.subscription_status is None

    # ApiKeys removed; FileJob anonymised.
    assert asyncio.run(_count_api_keys(user.id)) == 0
    assert asyncio.run(_file_job_user_id(job.id)) is None
    # ApiKey row itself is gone (CASCADE equivalent done explicitly).
    assert api_key.id is not None  # sanity: it existed before

    # Confirmation email includes the tax-retention paragraph.
    mock_send_email.assert_awaited_once()
    assert "HGB" in mock_send_email.await_args.kwargs["text"]


def test_paid_path_admin_with_peer_resets_role(client, mock_send_email, mock_cancel_subs):
    asyncio.run(
        _insert_user(
            email="paidadmin@example.com",
            role=RoleEnum.admin,
            stripe_customer_id="cus_admin",
        )
    )
    asyncio.run(_insert_user(email="keeper@example.com", role=RoleEnum.admin))
    token = _login(client, "paidadmin@example.com")

    assert _delete(client, "paidadmin@example.com", token).status_code == 204

    retained = asyncio.run(_fetch_retained_user("paidadmin@example.com"))
    assert retained is not None
    assert retained.role == RoleEnum.user
    # The peer admin is untouched.
    keeper = asyncio.run(_fetch_live_user("keeper@example.com"))
    assert keeper is not None and keeper.role == RoleEnum.admin and keeper.is_active is True


def test_login_after_paid_path_delete_returns_401(client, mock_send_email, mock_cancel_subs):
    asyncio.run(_insert_user(email="paid@example.com", stripe_customer_id="cus_x"))
    token = _login(client, "paid@example.com")
    assert _delete(client, "paid@example.com", token).status_code == 204

    # Old correct password — still 401 (sentinel hash + is_active/deleted_at guards).
    res = client.post(
        "/api/v1/auth/login",
        json={"email": "paid@example.com", "password": "initial-password"},
    )
    assert res.status_code == 401
    # Any password — also 401.
    res = client.post(
        "/api/v1/auth/login",
        json={"email": "paid@example.com", "password": "whatever-else"},
    )
    assert res.status_code == 401


def test_reregister_same_email_after_paid_path_delete(client, mock_send_email, mock_cancel_subs):
    old = asyncio.run(_insert_user(email="paid@example.com", stripe_customer_id="cus_old"))
    token = _login(client, "paid@example.com")
    assert _delete(client, "paid@example.com", token).status_code == 204

    # Re-register the same email — allowed by the partial unique index.
    res = client.post(
        "/api/v1/auth/register",
        json={"email": "paid@example.com", "password": "brand-new-pw-123"},
    )
    assert res.status_code == 201, res.text

    # Two rows now: the retained old one + the fresh live one.
    assert asyncio.run(_count_users("paid@example.com")) == 2
    fresh = asyncio.run(_fetch_live_user("paid@example.com"))
    assert fresh is not None
    assert fresh.id != old.id
    assert fresh.stripe_customer_id is None
    assert fresh.tier == TierEnum.free
    assert fresh.deleted_at is None
    # The retained row is untouched.
    retained = asyncio.run(_fetch_retained_user("paid@example.com"))
    assert (
        retained is not None and retained.id == old.id and retained.stripe_customer_id == "cus_old"
    )

    # The fresh account can log in with its new password.
    assert (
        client.post(
            "/api/v1/auth/login",
            json={"email": "paid@example.com", "password": "brand-new-pw-123"},
        ).status_code
        == 200
    )


# ── Paid path: Stripe error aborts the whole thing ───────────────────────────


def test_paid_path_stripe_error_returns_500_and_leaves_account_unchanged(
    client, mock_send_email, monkeypatch
):
    monkeypatch.setattr(
        "app.core.account_deletion.cancel_active_subscriptions",
        AsyncMock(side_effect=stripe.error.StripeError("boom")),
    )
    user = asyncio.run(_insert_user(email="paid@example.com", stripe_customer_id="cus_fail"))
    api_key = asyncio.run(_insert_api_key(user.id))
    token = _login(client, "paid@example.com")

    res = _delete(client, "paid@example.com", token)
    assert res.status_code == 500
    assert "unchanged" in res.json()["detail"].lower()

    # Nothing was written: the row is exactly as before.
    live = asyncio.run(_fetch_live_user("paid@example.com"))
    assert live is not None
    assert live.is_active is True
    assert live.deleted_at is None
    assert not live.password_hash.startswith("DELETED:")
    assert live.stripe_customer_id == "cus_fail"
    assert asyncio.run(_count_api_keys(user.id)) == 1
    assert api_key.id is not None
    # No confirmation email on the abort path.
    mock_send_email.assert_not_awaited()


# ── Paid path: structured-log shape ───────────────────────────────────────────


def test_paid_path_logs_deletion_mode_tax_retained(
    client, mock_send_email, mock_cancel_subs, caplog
):
    asyncio.run(_insert_user(email="paid@example.com", stripe_customer_id="cus_log"))
    token = _login(client, "paid@example.com")
    with caplog.at_level(logging.INFO):
        assert _delete(client, "paid@example.com", token).status_code == 204

    recs = [r for r in caplog.records if r.getMessage() == "account_deletion"]
    assert len(recs) == 1
    assert recs[0].deletion_mode == "tax_retained"
    assert recs[0].email_domain == "example.com"
    assert "paid@example.com" not in str(recs[0].__dict__)


# ── Unit: the deleted-password sentinel ───────────────────────────────────────


def test_deleted_password_sentinel_is_bcrypt_rejected():
    s1 = deleted_password_sentinel()
    s2 = deleted_password_sentinel()
    assert s1.startswith("DELETED:")
    assert s1 != s2  # random suffix — two deleted rows never collide
    # bcrypt cannot parse it → verify returns False without raising.
    assert verify_password("anything", s1) is False
    assert verify_password("", s1) is False
