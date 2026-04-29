# SPDX-License-Identifier: AGPL-3.0-or-later
"""Admin cockpit — auth gating, CRUD and timeseries tests.

Self-contained: installs a dedicated in-memory SQLite engine (StaticPool so
all connections see the same DB) and overrides the ``get_db`` /
``get_current_user`` FastAPI dependencies. Other test modules keep their
DB-less fast path unchanged.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.routes.auth import get_current_user
from app.core.auth import hash_password
from app.db.base import Base, get_db
from app.db.models import RoleEnum, TierEnum, UsageRecord, User
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
        await s.execute(delete(UsageRecord))
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
    app.dependency_overrides.pop(get_current_user, None)


# ── helpers ────────────────────────────────────────────────────────────────────


async def _insert_user(
    *,
    email: str,
    role: RoleEnum = RoleEnum.user,
    tier: TierEnum = TierEnum.free,
    is_active: bool = True,
    created_at: datetime | None = None,
) -> User:
    async with _TestSession() as s:
        user = User(
            email=email,
            password_hash=hash_password("test-password"),
            role=role,
            tier=tier,
            is_active=is_active,
        )
        if created_at is not None:
            user.created_at = created_at
        s.add(user)
        await s.commit()
        await s.refresh(user)
        return user


def _act_as(user: User) -> None:
    async def _current_user():
        return user

    app.dependency_overrides[get_current_user] = _current_user


# ── Auth gating ────────────────────────────────────────────────────────────────


def test_stats_unauthenticated_returns_401(client):
    # No override on get_current_user -> real dep runs -> no header -> 401.
    res = client.get("/api/v1/cockpit/stats")
    assert res.status_code == 401


def test_stats_requires_admin_role(client):
    regular = asyncio.run(_insert_user(email="u@x.test", role=RoleEnum.user))
    _act_as(regular)
    res = client.get("/api/v1/cockpit/stats")
    assert res.status_code == 403
    assert "admin" in res.json()["detail"].lower()


def test_stats_admin_ok_shape(client):
    admin = asyncio.run(_insert_user(email="a@x.test", role=RoleEnum.admin))
    _act_as(admin)
    res = client.get("/api/v1/cockpit/stats")
    assert res.status_code == 200
    data = res.json()
    # Admin himself counts: 1 total, 1 admin role.
    assert data["users"]["total"] == 1
    assert data["users"]["by_role"]["admin"] == 1
    assert data["users"]["by_role"]["user"] == 0
    assert data["users"]["by_tier"]["free"] == 1
    assert data["signups_7d"] == 1
    assert data["operations_total"] == 0
    assert data["failed_24h"] == 0
    assert "active_24h" in data


# ── Users list / filters / pagination ──────────────────────────────────────────


def test_users_list_basic(client):
    admin = asyncio.run(_insert_user(email="admin@x.test", role=RoleEnum.admin))
    asyncio.run(_insert_user(email="alice@x.test", tier=TierEnum.pro))
    asyncio.run(_insert_user(email="bob@x.test", tier=TierEnum.business))
    _act_as(admin)

    res = client.get("/api/v1/cockpit/users")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 3
    assert data["page"] == 1
    emails = {u["email"] for u in data["items"]}
    assert emails == {"admin@x.test", "alice@x.test", "bob@x.test"}


def test_users_list_filter_by_tier(client):
    admin = asyncio.run(_insert_user(email="admin@x.test", role=RoleEnum.admin))
    asyncio.run(_insert_user(email="alice@x.test", tier=TierEnum.pro))
    asyncio.run(_insert_user(email="bob@x.test", tier=TierEnum.business))
    _act_as(admin)

    res = client.get("/api/v1/cockpit/users?tier=pro")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["email"] == "alice@x.test"


def test_users_list_search_substring(client):
    admin = asyncio.run(_insert_user(email="admin@x.test", role=RoleEnum.admin))
    asyncio.run(_insert_user(email="alice@x.test"))
    asyncio.run(_insert_user(email="bob@x.test"))
    _act_as(admin)

    res = client.get("/api/v1/cockpit/users?q=alic")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["email"] == "alice@x.test"


def test_users_list_pagination(client):
    admin = asyncio.run(_insert_user(email="admin@x.test", role=RoleEnum.admin))
    for i in range(5):
        asyncio.run(_insert_user(email=f"u{i}@x.test"))
    _act_as(admin)

    page1 = client.get("/api/v1/cockpit/users?page=1&limit=2").json()
    page2 = client.get("/api/v1/cockpit/users?page=2&limit=2").json()
    assert page1["total"] == 6 and len(page1["items"]) == 2
    assert page2["total"] == 6 and len(page2["items"]) == 2
    assert {u["email"] for u in page1["items"]} != {u["email"] for u in page2["items"]}


# ── Patch / soft-delete ────────────────────────────────────────────────────────


def test_patch_user_changes_tier(client):
    admin = asyncio.run(_insert_user(email="admin@x.test", role=RoleEnum.admin))
    target = asyncio.run(_insert_user(email="target@x.test", tier=TierEnum.free))
    _act_as(admin)

    res = client.patch(
        f"/api/v1/cockpit/users/{target.id}",
        json={"tier": "pro"},
    )
    assert res.status_code == 200
    assert res.json()["tier"] == "pro"

    # Re-list and confirm persisted
    listing = client.get("/api/v1/cockpit/users?q=target").json()
    assert listing["items"][0]["tier"] == "pro"


def test_patch_self_demotion_rejected(client):
    admin = asyncio.run(_insert_user(email="admin@x.test", role=RoleEnum.admin))
    _act_as(admin)
    res = client.patch(f"/api/v1/cockpit/users/{admin.id}", json={"role": "user"})
    assert res.status_code == 409
    assert "demote" in res.json()["detail"].lower()


def test_patch_self_deactivate_rejected(client):
    admin = asyncio.run(_insert_user(email="admin@x.test", role=RoleEnum.admin))
    _act_as(admin)
    res = client.patch(f"/api/v1/cockpit/users/{admin.id}", json={"is_active": False})
    assert res.status_code == 409


def test_patch_invalid_uuid_rejected(client):
    admin = asyncio.run(_insert_user(email="admin@x.test", role=RoleEnum.admin))
    _act_as(admin)
    res = client.patch("/api/v1/cockpit/users/not-a-uuid", json={"tier": "pro"})
    assert res.status_code == 400


def test_patch_unknown_user_404(client):
    admin = asyncio.run(_insert_user(email="admin@x.test", role=RoleEnum.admin))
    _act_as(admin)
    res = client.patch(f"/api/v1/cockpit/users/{uuid.uuid4()}", json={"tier": "pro"})
    assert res.status_code == 404


def test_delete_soft_deletes_other_user(client):
    admin = asyncio.run(_insert_user(email="admin@x.test", role=RoleEnum.admin))
    target = asyncio.run(_insert_user(email="target@x.test", is_active=True))
    _act_as(admin)

    res = client.delete(f"/api/v1/cockpit/users/{target.id}")
    assert res.status_code == 200
    assert res.json() == {"id": str(target.id), "is_active": False}

    # is_active should now be false when re-listed without filter
    data = client.get("/api/v1/cockpit/users?q=target").json()
    assert data["items"][0]["is_active"] is False


def test_delete_self_rejected(client):
    admin = asyncio.run(_insert_user(email="admin@x.test", role=RoleEnum.admin))
    _act_as(admin)
    res = client.delete(f"/api/v1/cockpit/users/{admin.id}")
    assert res.status_code == 409


# ── Timeseries ─────────────────────────────────────────────────────────────────


def test_timeseries_signups_by_day(client):
    admin = asyncio.run(_insert_user(email="admin@x.test", role=RoleEnum.admin))
    now = datetime.now(timezone.utc)
    asyncio.run(_insert_user(email="d1@x.test", created_at=now - timedelta(days=1)))
    asyncio.run(_insert_user(email="d2@x.test", created_at=now - timedelta(days=1)))
    asyncio.run(_insert_user(email="d3@x.test", created_at=now - timedelta(days=3)))
    _act_as(admin)

    res = client.get("/api/v1/cockpit/timeseries?metric=signups&bucket=day")
    assert res.status_code == 200
    data = res.json()
    assert data["metric"] == "signups"
    assert data["bucket"] == "day"
    total = sum(p["v"] for p in data["points"])
    # 4 users created in last 30 days (admin + three inserted).
    assert total == 4


def test_timeseries_empty_range_returns_empty(client):
    admin = asyncio.run(_insert_user(email="admin@x.test", role=RoleEnum.admin))
    _act_as(admin)

    past_from = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
    past_to = (datetime.now(timezone.utc) - timedelta(days=300)).isoformat()
    res = client.get(
        "/api/v1/cockpit/timeseries",
        params={"metric": "signups", "bucket": "day", "from": past_from, "to": past_to},
    )
    assert res.status_code == 200
    assert res.json()["points"] == []
