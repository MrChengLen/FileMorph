# SPDX-License-Identifier: AGPL-3.0-or-later
"""When the app deletes expired audit entries (``app/main.py``).

``_periodic_audit_retention`` runs ``delete_expired_events`` at start-up and
then once per interval, keeps going after a failed run, and stops as soon as
the lifespan sets its event. The lifespan starts it only on a database the
migrations manage: not without a database, and not on the in-memory SQLite
of the test harness. What a run deletes is tested in test_audit_log.py and
test_audit_postgres.py.
"""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from app import main
from app.main import _periodic_audit_retention, lifespan


def _counting(
    calls: list, *, fail_on: int = 0, stop: asyncio.Event | None = None, stop_on: int = 0
):
    async def _delete_expired_events() -> int:
        calls.append(None)
        if len(calls) == fail_on:
            raise RuntimeError("database gone")
        if stop is not None and len(calls) == stop_on:
            stop.set()
        return 0

    return _delete_expired_events


def test_retention_runs_at_once_then_per_interval_and_survives_a_failure(monkeypatch, caplog):
    calls: list = []
    stop = asyncio.Event()
    monkeypatch.setattr(
        main, "delete_expired_events", _counting(calls, fail_on=2, stop=stop, stop_on=3)
    )

    with caplog.at_level(logging.ERROR, logger="filemorph.startup"):
        asyncio.run(
            asyncio.wait_for(_periodic_audit_retention(interval_seconds=0, stop_event=stop), 5)
        )

    assert len(calls) == 3
    assert "Audit retention run raised" in caplog.text


def test_retention_stops_without_waiting_for_the_interval(monkeypatch):
    calls: list = []
    monkeypatch.setattr(main, "delete_expired_events", _counting(calls))

    async def _run():
        stop = asyncio.Event()
        task = asyncio.create_task(
            _periodic_audit_retention(interval_seconds=3600, stop_event=stop)
        )
        for _ in range(3):
            await asyncio.sleep(0)
        stop.set()
        await asyncio.wait_for(task, 1)

    asyncio.run(_run())
    assert len(calls) == 1


@pytest.mark.parametrize(
    "database, runs",
    [
        ("postgresql+asyncpg://filemorph_app@postgres/filemorph", True),
        ("sqlite+aiosqlite:///:memory:", False),
        (None, False),
    ],
    ids=["migrated", "test-harness", "community"],
)
def test_lifespan_runs_retention_only_on_a_migrated_database(monkeypatch, database, runs):
    if database is None:
        engine = None
    elif database.startswith("sqlite"):
        engine = create_async_engine(database)
    else:  # the lifespan only reads its URL; nothing connects
        engine = SimpleNamespace(url=make_url(database))
    calls: list = []
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(main, "delete_expired_events", _counting(calls))

    async def _run():
        async with lifespan(main.app):
            for _ in range(3):
                await asyncio.sleep(0)
        if hasattr(engine, "dispose"):
            await engine.dispose()

    asyncio.run(_run())
    assert bool(calls) is runs
