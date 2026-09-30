# SPDX-License-Identifier: AGPL-3.0-or-later
"""The audit log's append-only trigger, on a real PostgreSQL.

The rest of the suite runs on in-memory SQLite, where the trigger from
migration 005 does not exist. That hid a GDPR Art. 17 bug: the trigger also
refused the ``ON DELETE SET NULL`` cascade that clears
``audit_events.actor_user_id``, so ``DELETE /api/v1/auth/account`` failed on
Postgres for every free account (each has audit rows from registration and
login) and deleted nothing. Migration 012 lets exactly that cascade through.

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
from app.core.audit import verify_chain
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
        "DELETE FROM audit_events WHERE id = :id",
    ],
    ids=["payload", "null-live-actor", "reassign-actor", "delete"],
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
