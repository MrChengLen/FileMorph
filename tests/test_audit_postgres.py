# SPDX-License-Identifier: AGPL-3.0-or-later
"""The audit log's append-only trigger, on a real PostgreSQL.

The rest of the suite runs on in-memory SQLite, where the trigger from
migration 005 does not exist. That hid a GDPR Art. 17 bug: the trigger also
refused the ``ON DELETE SET NULL`` cascade that clears
``audit_events.actor_user_id``, so ``DELETE /api/v1/auth/account`` failed on
Postgres for every free account (each has audit rows from registration and
login) and deleted nothing. Migration 012 lets exactly that cascade through.

Migration 013 adds ``hash_version``. Rows that exist when it runs keep
verifying under recipe 1, the trigger guards the new column too, the plain-SQL
check ``VERIFY_CHAIN_SQL`` finds what ``verify_chain`` finds, and the
downgrade refuses once recipe-2 rows exist.

These tests run ``alembic upgrade head`` against the database in
``FILEMORPH_TEST_POSTGRES_URL`` (an asyncpg URL) and skip without it. Every
test empties the tables, so the database name must contain ``test``. CI's
``lint-and-test`` job provides a Postgres service;
``test_ci_runs_these_tests_on_postgres`` keeps it that way.
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import yaml
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core import audit as audit_module
from app.core import email as email_mod
from app.core.audit import (
    GENESIS_PREV_HASH,
    VERIFY_CHAIN_SQL,
    _canonical_payload,
    _compute_hash,
    verify_chain,
)
from app.core.auth import hash_password
from app.db.base import get_db
from app.db.models import AuditEvent, User
from app.main import app

_ROOT = Path(__file__).resolve().parent.parent
_ENV = "FILEMORPH_TEST_POSTGRES_URL"
_URL = os.environ.get(_ENV, "")
_PASSWORD = "initial-password"

needs_postgres = pytest.mark.skipif(not _URL, reason=f"{_ENV} is not set")


@pytest.fixture(scope="module")
def pg_factory():
    """Migrate the database to head; point the app and the audit writer at it."""
    database = make_url(_URL).database or ""
    assert "test" in database, f"{_ENV} must name a throwaway test database, not {database!r}"
    migrated = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=_ROOT,
        env={**os.environ, "DATABASE_URL": _URL},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )
    assert migrated.returncode == 0, migrated.stdout + migrated.stderr

    # NullPool: every session opens its own connection on the event loop that
    # uses it. TestClient's loop and the asyncio.run() loops below differ.
    engine = create_async_engine(_URL, poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def _override_get_db():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_get_db
    original = audit_module.AsyncSessionLocal
    audit_module.AsyncSessionLocal = factory
    yield factory
    audit_module.AsyncSessionLocal = original
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def pg(pg_factory):
    """Empty tables for each test. TRUNCATE fires no row triggers, so the
    append-only trigger does not refuse the cleanup."""

    async def _truncate():
        async with pg_factory() as s:
            await s.execute(text("TRUNCATE audit_events, users RESTART IDENTITY CASCADE"))
            await s.commit()

    asyncio.run(_truncate())
    return pg_factory


@needs_postgres
def test_deleting_a_free_account_nulls_its_audit_actor(client, pg, monkeypatch):
    """Registration, login and the deletion request all name the account in
    the audit log; deleting it must clear that name, keep the rows and leave
    the hash chain intact."""
    monkeypatch.setattr(email_mod, "send_email", AsyncMock())
    email = "erase-me@example.com"
    res = client.post("/api/v1/auth/register", json={"email": email, "password": _PASSWORD})
    assert res.status_code == 201, res.text
    token = res.json()["access_token"]
    res = client.post("/api/v1/auth/login", json={"email": email, "password": _PASSWORD})
    assert res.status_code == 200, res.text

    res = client.request(
        "DELETE",
        "/api/v1/auth/account",
        json={"password": _PASSWORD, "confirm_email": email, "confirm_word": "DELETE"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 204, res.text

    async def _state():
        async with pg() as s:
            users = await s.scalar(select(func.count()).select_from(User))
            events = (await s.execute(select(AuditEvent).order_by(AuditEvent.id))).scalars().all()
            return users, events, await verify_chain(s)

    users, events, broken_at = asyncio.run(_state())
    assert users == 0
    assert {e.event_type for e in events} >= {
        "auth.register.success",
        "auth.login.success",
        "auth.account_deletion.requested",
        "auth.account_deletion.completed",
    }
    assert [e.actor_user_id for e in events] == [None] * len(events)
    assert broken_at is None


@needs_postgres
@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE audit_events SET payload_json = '{}' WHERE id = :id",
        "UPDATE audit_events SET actor_user_id = NULL WHERE id = :id",
        "UPDATE audit_events SET actor_user_id = :other WHERE id = :id",
        "UPDATE audit_events SET hash_version = 1 WHERE id = :id",
        "DELETE FROM audit_events WHERE id = :id",
    ],
    ids=["payload", "null-live-actor", "reassign-actor", "hash-version", "delete"],
)
def test_trigger_refuses_every_other_change(pg, statement):
    """Only the cascade of an account deletion may clear an actor. A direct
    UPDATE that nulls the id of a live account is refused like any other."""

    async def _run():
        async with pg() as s:
            owner = User(email="owner@example.com", password_hash="unused")
            other = User(email="other@example.com", password_hash="unused")
            s.add_all([owner, other])
            await s.commit()
            await audit_module.record_event("auth.login.success", actor_user_id=owner.id, db=s)
            event_id = await s.scalar(select(AuditEvent.id))
            params = (
                {"id": event_id, "other": other.id} if ":other" in statement else {"id": event_id}
            )
            with pytest.raises(DBAPIError, match="append-only"):
                await s.execute(text(statement), params)

    asyncio.run(_run())


@needs_postgres
def test_temporary_users_table_cannot_stand_in(pg):
    """The check looks up public.users. A temporary "users" table, which the
    search path finds first, must not make a live account look deleted."""

    async def _run():
        async with pg() as s:
            owner = User(email="owner@example.com", password_hash="unused")
            s.add(owner)
            await s.commit()
            await audit_module.record_event("auth.login.success", actor_user_id=owner.id, db=s)
            await s.execute(text("CREATE TEMPORARY TABLE users (id uuid)"))
            with pytest.raises(DBAPIError, match="append-only"):
                await s.execute(text("UPDATE audit_events SET actor_user_id = NULL"))

    asyncio.run(_run())


@needs_postgres
def test_cascade_may_change_nothing_but_the_actor(pg):
    """Because of the foreign key, only deleting the account reaches the check
    with the account already gone. A second trigger that alters the row on the
    way stands in for any other change, and the whole deletion is refused."""

    async def _run():
        async with pg() as s:
            owner = User(email="owner@example.com", password_hash="unused")
            s.add(owner)
            await s.commit()
            await audit_module.record_event("auth.login.success", actor_user_id=owner.id, db=s)
            # Rolled back with the failed DELETE below (transactional DDL). Fires
            # before audit_events_no_update: same event, alphabetical order.
            await s.execute(
                text(
                    "CREATE FUNCTION test_touch_audit_event() RETURNS trigger AS $$ BEGIN "
                    "NEW.event_type := 'touched'; RETURN NEW; END; $$ LANGUAGE plpgsql"
                )
            )
            await s.execute(
                text(
                    "CREATE TRIGGER audit_events_a_touch BEFORE UPDATE ON audit_events "
                    "FOR EACH ROW EXECUTE FUNCTION test_touch_audit_event()"
                )
            )
            with pytest.raises(DBAPIError, match="append-only"):
                await s.execute(text("DELETE FROM users WHERE id = :id"), {"id": owner.id})

    asyncio.run(_run())


# ── Migration 013: hash_version ──────────────────────────────────────────────

_BEFORE_013 = "012_audit_actor_erasure"


def _alembic(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=_ROOT,
        env={**os.environ, "DATABASE_URL": _URL},
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
    )


def _upgrade_to_head() -> None:
    up = _alembic("upgrade", "head")
    assert up.returncode == 0, up.stdout + up.stderr


async def _first_broken_row_by_sql(session: AsyncSession) -> int | None:
    # Sent as it stands, the way an auditor would paste it into psql.
    conn = await session.connection()
    return (await conn.exec_driver_sql(VERIFY_CHAIN_SQL)).scalar()


async def _insert_recipe_1_row(session: AsyncSession, prev_hash: str, actor=None) -> str:
    """A row as the code before migration 013 wrote it: no hash_version."""
    canonical = _canonical_payload({"before": 13})
    record_hash = _compute_hash(prev_hash, canonical)
    await session.execute(
        text(
            "INSERT INTO audit_events (event_type, actor_user_id, payload_json, prev_hash, "
            "record_hash) VALUES ('auth.login.success', :actor, :payload, :prev, :record)"
        ),
        {"actor": actor, "payload": canonical, "prev": prev_hash, "record": record_hash},
    )
    return record_hash


@needs_postgres
def test_rows_from_before_013_keep_verifying(pg):
    """The column default labels existing rows recipe 1; the rows written
    after the upgrade are recipe 2 and chain onto them."""
    down = _alembic("downgrade", _BEFORE_013)  # the pg fixture left the table empty
    assert down.returncode == 0, down.stdout + down.stderr
    try:

        async def _write_old_rows():
            async with pg() as s:
                first = await _insert_recipe_1_row(s, GENESIS_PREV_HASH)
                await _insert_recipe_1_row(s, first)
                await s.commit()

        asyncio.run(_write_old_rows())
    finally:
        _upgrade_to_head()

    async def _extend_and_check():
        async with pg() as s:
            for i in range(2):
                await audit_module.record_event("test.event", payload={"i": i}, db=s)
        async with pg() as s:  # read back as asyncpg returns the values
            # A session zone other than UTC: the SQL check must normalise
            # occurred_at itself (``AT TIME ZONE 'UTC'``), as Python does.
            await s.execute(text("SET TIME ZONE INTERVAL '+05:30' HOUR TO MINUTE"))
            versions = (
                (await s.execute(select(AuditEvent.hash_version).order_by(AuditEvent.id)))
                .scalars()
                .all()
            )
            return versions, await verify_chain(s), await _first_broken_row_by_sql(s)

    versions, broken_at, broken_by_sql = asyncio.run(_extend_and_check())
    assert versions == [1, 1, 2, 2]
    assert broken_at is None
    assert broken_by_sql is None


@needs_postgres
def test_verify_chain_sql_finds_the_row_whose_event_type_changed(pg):
    """The plain-SQL check and verify_chain name the same row. The edit
    runs with the table's triggers off, as only its owner can."""

    async def _run():
        async with pg() as s:
            for i in range(3):
                await audit_module.record_event("auth.login.failure", payload={"i": i}, db=s)
            target = await s.scalar(select(AuditEvent.id).order_by(AuditEvent.id).offset(1))
            await s.execute(text("ALTER TABLE audit_events DISABLE TRIGGER USER"))
            await s.execute(
                text("UPDATE audit_events SET event_type = 'auth.login.success' WHERE id = :id"),
                {"id": target},
            )
            await s.execute(text("ALTER TABLE audit_events ENABLE TRIGGER USER"))
            await s.commit()
        async with pg() as s:
            return target, await verify_chain(s), await _first_broken_row_by_sql(s)

    target, broken_at, broken_by_sql = asyncio.run(_run())
    assert broken_at == target
    assert broken_by_sql == target


@needs_postgres
def test_deleting_an_account_clears_the_actor_on_rows_from_before_013(client, pg, monkeypatch):
    """Rows that existed when 013 ran read hash_version from the column
    default, not from their stored tuple — the state production is in. The
    deletion cascade must still pass 012's whole-row comparison."""
    monkeypatch.setattr(email_mod, "send_email", AsyncMock())
    email = "before-013@example.com"

    async def _create_owner():
        async with pg() as s:  # at head, so the model matches the users table
            owner = User(email=email, password_hash=hash_password(_PASSWORD))
            s.add(owner)
            await s.commit()
            return owner.id

    owner_id = asyncio.run(_create_owner())
    down = _alembic("downgrade", _BEFORE_013)
    assert down.returncode == 0, down.stdout + down.stderr
    try:

        async def _write_old_row():
            async with pg() as s:
                await _insert_recipe_1_row(s, GENESIS_PREV_HASH, actor=owner_id)
                await s.commit()

        asyncio.run(_write_old_row())
    finally:
        _upgrade_to_head()

    res = client.post("/api/v1/auth/login", json={"email": email, "password": _PASSWORD})
    assert res.status_code == 200, res.text
    res = client.request(
        "DELETE",
        "/api/v1/auth/account",
        json={"password": _PASSWORD, "confirm_email": email, "confirm_word": "DELETE"},
        headers={"Authorization": f"Bearer {res.json()['access_token']}"},
    )
    assert res.status_code == 204, res.text

    async def _state():
        async with pg() as s:
            first = (await s.execute(select(AuditEvent).order_by(AuditEvent.id))).scalars().first()
            return first, await verify_chain(s), await _first_broken_row_by_sql(s)

    first, broken_at, broken_by_sql = asyncio.run(_state())
    assert (first.hash_version, first.actor_user_id) == (1, None)
    assert broken_at is None
    assert broken_by_sql is None


@needs_postgres
def test_013_downgrade_refuses_while_recipe_2_rows_exist(pg):
    async def _write():
        async with pg() as s:
            await audit_module.record_event("test.event", payload={"i": 0}, db=s)

    asyncio.run(_write())
    down = _alembic("downgrade", _BEFORE_013)
    try:
        assert down.returncode != 0
        assert "refusing to drop the column" in down.stdout + down.stderr
    finally:
        _upgrade_to_head()


_TEST_JOBS = {"ci.yml": "lint-and-test", "deps-latest.yml": "test-latest"}


def _test_job(workflow: str) -> dict:
    path = _ROOT / ".github" / "workflows" / workflow
    return yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"][_TEST_JOBS[workflow]]


@pytest.mark.parametrize("workflow", sorted(_TEST_JOBS))
def test_ci_runs_these_tests_on_postgres(workflow):
    """Without the service and the URL, every test above skips and nothing
    says so. That is how the trigger went untested until migration 012."""
    job = _test_job(workflow)
    image = job["services"]["postgres"]["image"]
    assert re.fullmatch(r"postgres:[\w.-]+@sha256:[0-9a-f]{64}", image), (
        f"pin the Postgres service image by digest, got {image!r}"
    )
    assert image == _test_job("ci.yml")["services"]["postgres"]["image"], (
        f"{workflow} tests on a different Postgres than ci.yml"
    )
    compose = (_ROOT / "docker-compose.cloud.yml").read_text(encoding="utf-8")
    major = re.search(r"image:\s*postgres:(\d+)", compose).group(1)
    assert image.startswith(f"postgres:{major}."), (
        f"{workflow} tests {image}, docker-compose.cloud.yml runs postgres:{major}"
    )
    pytest_steps = [step for step in job["steps"] if "pytest" in step.get("run", "")]
    assert pytest_steps, f"{workflow} no longer runs pytest"
    for step in pytest_steps:
        assert _ENV in step.get("env", {}), f"{step.get('name')!r} does not set {_ENV}"
