# SPDX-License-Identifier: AGPL-3.0-or-later
"""The in-memory Cloud-Edition database that the account, billing, audit,
quota and cockpit tests share.

A test module opts in with one line at module level, naming the app modules
that open their own sessions (``AsyncSessionLocal``) and should reach the test
database too::

    _db = cloud_db(audit_module)

The result must be bound to a module-level name — pytest finds the fixture
there; a bare ``cloud_db(...)`` call registers nothing. The module then
reaches the database through ``TestSession``. Before each test the fixture
(autouse, so the module needs nothing else) creates the schema once, empties
every table, points ``get_db`` (unless ``override_get_db=False``: for a module
that calls the code directly and wants the routes left as they are) and the
named modules at the test database, and makes bcrypt cheap: a test account
would otherwise cost a 0.17 s cost-12 hash, which was a third of a local run.
Hashes made at import time keep the real cost (see test_auth_lookup.py).
Because of that, real accounts (cost 4) and ``DUMMY_PASSWORD_HASH`` (cost 12)
cost different amounts here: a timing test does not belong in such a module.

One in-memory database per test process is enough because every test starts
from empty tables; each xdist worker is its own process with its own database.

Own databases on purpose: test_audit_no_ip.py and test_audit_no_email.py
drive one module-long flow (a client with a fixed address, rows that build
up), test_audit_postgres.py needs a real PostgreSQL, and one test in
test_daily_metrics.py needs a file database for concurrent writers.
"""

from __future__ import annotations

import asyncio
from types import ModuleType

import bcrypt
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base, get_db
from app.main import app

engine = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

_REAL_GENSALT = bcrypt.gensalt
_schema_ready = False


def _cheap_gensalt(rounds: int = 12, prefix: bytes = b"2b") -> bytes:
    return _REAL_GENSALT(4, prefix)


async def _empty_tables() -> None:
    global _schema_ready
    async with engine.begin() as conn:
        if not _schema_ready:
            await conn.run_sync(Base.metadata.create_all)
            # Every Alembic-managed database still has this column (migration
            # 005) until a later migration drops it; the model no longer maps
            # it. The audit tests that read every stored column (SELECT *)
            # check it holds no client address.
            await conn.execute(text("ALTER TABLE audit_events ADD COLUMN actor_ip VARCHAR(45)"))
            _schema_ready = True
        for table in reversed(Base.metadata.sorted_tables):  # children first
            await conn.execute(table.delete())


async def _test_db():
    async with TestSession() as session:
        yield session


def cloud_db(*session_owners: ModuleType, override_get_db: bool = True):
    """Return the module's autouse fixture for the test database."""

    @pytest.fixture(autouse=True)
    def _cloud_db(monkeypatch):
        asyncio.run(_empty_tables())
        if override_get_db:
            monkeypatch.setitem(app.dependency_overrides, get_db, _test_db)
        for module in session_owners:
            monkeypatch.setattr(module, "AsyncSessionLocal", TestSession)
        monkeypatch.setattr(bcrypt, "gensalt", _cheap_gensalt)
        yield

    return _cloud_db
