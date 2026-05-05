# SPDX-License-Identifier: AGPL-3.0-or-later
"""S10-lite analytics — atomic per-day counter increments.

Single function: ``increment(key)`` adds 1 to the ``daily_metrics`` row
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

Session ownership
-----------------

``increment`` always opens its own ``AsyncSession`` from the global
``AsyncSessionLocal`` factory and commits in isolation. That keeps the
metrics write off the request transaction — a metrics-write failure cannot
clobber a partially-built user transaction (and vice versa), and the
metrics commit is not visible in the request span if the request later
rolls back.

Tests pass an explicit session via the ``db=`` kwarg (the in-memory
SQLite engine isn't reachable through ``AsyncSessionLocal``); production
callers must NOT pass ``db=`` — they go through the global factory.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.base import AsyncSessionLocal
from app.db.models import DailyMetric

logger = logging.getLogger(__name__)

# Defense in depth against accidental injection / cardinality blow-up. Keys
# are constructed from converter-registry extensions (whitelisted at the
# converter layer) plus literal strings the codebase controls — never raw
# user input. The regex enforces that contract: only ASCII lowercase, digits,
# dot, underscore, hyphen; ≤64 chars to fit the column. Anything else
# (whitespace, slashes, NULs, multi-byte) is dropped with a warning so an
# upstream regression surfaces in logs rather than the database.
_VALID_METRIC_KEY = re.compile(r"^[a-z0-9._\-]{1,64}$")


async def increment(key: str, *, by: int = 1, db: AsyncSession | None = None) -> None:
    """Add ``by`` to today's counter for ``key`` — atomic UPSERT.

    Behavior:

    - ``settings.metrics_enabled is False``: no-op.
    - ``key`` does not match the safe-key pattern: log + no-op.
    - ``db is None`` and ``AsyncSessionLocal is None`` (Community Edition
      with no DATABASE_URL): no-op.
    - Otherwise: open a fresh ``AsyncSession`` (or use the one passed via
      ``db=`` for tests) and run a dialect-aware UPSERT, committing in
      isolation from any caller transaction.
    - Postgres: ``INSERT ... ON CONFLICT (date, metric_key) DO UPDATE``.
    - SQLite: ``INSERT OR IGNORE`` then ``UPDATE`` — two statements, but the
      composite PK guarantees correctness even under concurrent INSERTs.
    - Any DB error is swallowed and logged; the caller never sees it.

    The ``date`` is computed in UTC. Day boundaries roll over at 00:00 UTC,
    not in local timezone — keeps cross-deployment counters comparable.
    """
    if not settings.metrics_enabled:
        return
    if not isinstance(key, str) or not _VALID_METRIC_KEY.fullmatch(key):
        # Don't write a malformed key — surface as a warning so the caller
        # can be fixed. Truncate so logs stay readable on hostile input.
        safe_repr = repr(key)[:120] if key is not None else "None"
        logger.warning("daily_metrics: rejected invalid metric_key=%s", safe_repr)
        return

    if db is not None:
        await _do_increment(db, key, by)
        return

    if AsyncSessionLocal is None:
        # Community Edition without DATABASE_URL — no DB to write to.
        return

    try:
        async with AsyncSessionLocal() as session:
            await _do_increment(session, key, by)
    except Exception:
        logger.warning("daily_metrics: session-open failed for key=%s", key, exc_info=True)


async def _do_increment(db: AsyncSession, key: str, by: int) -> None:
    """Run the UPSERT against ``db``. Swallows + logs all DB errors.

    Splits Postgres and SQLite paths because Postgres has true atomic
    upsert; SQLite needs ``INSERT OR IGNORE`` + ``UPDATE``. The composite
    primary key (date, metric_key) makes the SQLite path safe under
    concurrency: two parallel INSERTs of the same key both see PK conflict
    and one is dropped, then both UPDATEs run sequentially under the
    row-lock and ``count + by`` resolves correctly.
    """
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
        logger.warning("daily_metrics increment failed for key=%s", key, exc_info=True)
        try:
            await db.rollback()
        except Exception:
            pass
