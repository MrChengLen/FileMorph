# SPDX-License-Identifier: AGPL-3.0-or-later
"""S10-lite analytics — atomic per-day counter increments.

Single function: ``increment(db, key)`` adds 1 to the ``daily_metrics`` row
identified by ``(today_utc, key)``, creating it if it doesn't exist. Both
operations happen in a single SQL statement (``INSERT ... ON CONFLICT
... DO UPDATE`` on Postgres, ``INSERT OR IGNORE`` + ``UPDATE`` on SQLite),
so two concurrent requests for the same key on the same day can never
overwrite each other.

The function is intentionally fire-and-forget — never raises into the caller.
A metrics-write failure must not break the user's request, since metrics are
auxiliary observability, not load-bearing for the conversion result. Errors
are logged at WARNING for ops visibility.

Self-host toggle: ``settings.metrics_enabled = False`` makes ``increment``
a no-op (returns immediately without touching the DB).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import DailyMetric

logger = logging.getLogger(__name__)


async def increment(db: AsyncSession | None, key: str, *, by: int = 1) -> None:
    """Add ``by`` to today's counter for ``key`` — atomic UPSERT.

    Behavior:

    - ``db is None`` (self-host without DATABASE_URL): no-op.
    - ``settings.metrics_enabled is False``: no-op.
    - Postgres: ``INSERT ... ON CONFLICT (date, metric_key) DO UPDATE``.
    - SQLite: ``INSERT OR IGNORE`` then ``UPDATE`` — two statements, but the
      composite PK guarantees correctness even under concurrent INSERTs.
    - Any DB error is swallowed and logged; the caller never sees it.

    The ``date`` is computed in UTC. Day boundaries roll over at 00:00 UTC,
    not in local timezone — keeps cross-deployment counters comparable.
    """
    if db is None or not settings.metrics_enabled:
        return

    today = datetime.now(timezone.utc).date()

    try:
        dialect = db.bind.dialect.name if db.bind is not None else "postgresql"
        if dialect == "postgresql":
            stmt = pg_insert(DailyMetric).values(date=today, metric_key=key, count=by)
            stmt = stmt.on_conflict_do_update(
                index_elements=["date", "metric_key"],
                set_={"count": DailyMetric.count + by},
            )
            await db.execute(stmt)
        else:
            # SQLite path used by the test harness (in-memory engine).
            stmt = sqlite_insert(DailyMetric).values(date=today, metric_key=key, count=0)
            stmt = stmt.on_conflict_do_nothing(index_elements=["date", "metric_key"])
            await db.execute(stmt)
            await db.execute(
                update(DailyMetric)
                .where(DailyMetric.date == today, DailyMetric.metric_key == key)
                .values(count=DailyMetric.count + by)
            )
        await db.commit()
    except Exception:
        # Metrics must never break a user's request — log + continue.
        logger.warning("daily_metrics increment failed for key=%s", key, exc_info=True)
        try:
            await db.rollback()
        except Exception:  # rollback can race with cleanup; swallow.
            pass
