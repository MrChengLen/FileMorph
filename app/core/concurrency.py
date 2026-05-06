# SPDX-License-Identifier: AGPL-3.0-or-later
"""NEU-D.1: capacity guard for ``/convert`` and ``/compress``.

Why this exists
---------------
The pricing page advertises monthly call quotas (10.000 Pro,
100.000 Business). That is a **bucket size**, not a guarantee about
parallelism. Without a concurrency cap, a single Pro user can
launch a 25-file batch — which on a 4 GB box is enough to
OOM-kill the Python process and take every other request down
with it. The slowapi rate-limit (10/min/IP) already exists and
defends against unauthenticated abuse; this module adds the second
layer the route needs:

* A **global** semaphore sized to what the box can actually run
  in parallel (``settings.max_global_concurrency``, default 4 for
  a 4 GB host). Anyone past the cap waits ``timeout`` seconds and
  then gets a 503 Service Unavailable with a ``Retry-After`` hint.
* A **per-actor** semaphore so that one tenant cannot occupy every
  global slot at once. The per-actor cap depends on the tier — an
  anonymous caller gets 1, Pro gets 2, Business gets 5. Past the
  cap: 429 Too Many Requests, again with ``Retry-After``.

The "actor" key is the API-key hash for authenticated callers,
the IP for anonymous. That gives a stable identity across
requests within a session without forcing us to hand out keys to
anonymous users.

Why not a job queue (Redis / Celery / RQ)
-----------------------------------------
A queue is the right tool when conversion latency is allowed to
move from "synchronous, low" to "asynchronous, ID-and-poll". The
single-user UX FileMorph ships today is synchronous — drag, drop,
wait, download. A queue would either reproduce the synchronous
contract on top (no behavioural gain) or break the UX (every
caller now has to poll). The semaphore covers the actual failure
mode (OOM under burst) without requiring users to learn a job-id
protocol. A future move to an async-job model is a separate
sprint and depends on actual latency data.

Why an in-process semaphore (single-instance)
---------------------------------------------
Multi-instance deployments need a shared coordinator (Redis,
Postgres advisory lock). FileMorph runs single-instance today;
adding distributed locking now is YAGNI. The module's interface
(``acquire_slot``) is the seam where a future Redis-backed
implementation slots in without touching the route code.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import HTTPException, status

from app.core.config import settings

logger = logging.getLogger(__name__)


# Per-tier concurrency caps. Anonymous and free are tight (1) so
# casual abuse cannot starve paying tiers; Pro and Business get
# more headroom. Numbers are derived from the Pricing-page
# capacity discussion (~4 worker slots on a 4 GB host) — Pro has
# headroom to overlap a small batch with a single follow-up call,
# Business can run a 5-thread parallel-import workflow.
_PER_TIER_CONCURRENCY: dict[str, int] = {
    "anonymous": 1,
    "free": 1,
    "pro": 2,
    "business": 5,
    "enterprise": 10,
}


# Module-level singletons. The semaphores are bound to whatever
# event loop first calls into them; FastAPI keeps a single loop
# per process for the entire app lifetime, so this is safe.
_GLOBAL_SEMAPHORE: asyncio.Semaphore | None = None
_PER_ACTOR_SEMAPHORES: dict[str, asyncio.Semaphore] = {}


class ConcurrencyExhausted(HTTPException):
    """HTTPException subclass so the global FastAPI exception
    handler treats it as a structured rate-limit response rather
    than an unhandled error. Pre-set status + Retry-After header."""

    def __init__(self, *, scope: str, retry_after_seconds: int) -> None:
        if scope == "global":
            sc = status.HTTP_503_SERVICE_UNAVAILABLE
            detail = (
                "FileMorph is at capacity. The request was not processed; retry in a few seconds."
            )
        else:
            sc = status.HTTP_429_TOO_MANY_REQUESTS
            detail = (
                "Concurrency limit for this API key reached. "
                "Lower the parallelism or upgrade the plan."
            )
        super().__init__(
            status_code=sc, detail=detail, headers={"Retry-After": str(retry_after_seconds)}
        )


def _global_semaphore() -> asyncio.Semaphore:
    global _GLOBAL_SEMAPHORE
    if _GLOBAL_SEMAPHORE is None:
        _GLOBAL_SEMAPHORE = asyncio.Semaphore(settings.max_global_concurrency)
    return _GLOBAL_SEMAPHORE


def _per_actor_semaphore(actor_id: str, tier: str) -> asyncio.Semaphore:
    """Return (and lazily create) the per-actor semaphore.

    Sized once on first sight of the actor — a tier upgrade
    mid-conversation is honoured on the next *new* actor key (e.g.
    after the user mints a new API key on the upgraded plan). A
    background sweep of stale entries is not yet implemented; the
    map is bounded by the active-actor count, which on a 4 GB box
    is itself bounded by the global semaphore × turnover rate, so
    the practical ceiling is small.
    """
    sem = _PER_ACTOR_SEMAPHORES.get(actor_id)
    if sem is None:
        limit = _PER_TIER_CONCURRENCY.get(tier, 1)
        sem = asyncio.Semaphore(limit)
        _PER_ACTOR_SEMAPHORES[actor_id] = sem
    return sem


def _reset_for_tests() -> None:
    """Test-only helper: drop the singleton + actor map so the
    next call rebuilds them against the test event loop and
    re-reads ``settings.max_global_concurrency``. Production code
    must never call this."""
    global _GLOBAL_SEMAPHORE
    _GLOBAL_SEMAPHORE = None
    _PER_ACTOR_SEMAPHORES.clear()


@asynccontextmanager
async def acquire_slot(*, actor_id: str, tier: str) -> AsyncIterator[None]:
    """Hold a global + per-actor concurrency slot for the body.

    On entry: wait up to ``settings.concurrency_acquire_timeout_seconds``
    for both semaphores; raise :class:`ConcurrencyExhausted` if either
    times out. On exit: release in reverse order so the global slot
    is the last thing freed (gives a waiter the best chance of seeing
    the actor-slot already free before they grab the global).

    The timeout is small on purpose — it absorbs micro-bursts (two
    requests landing within the same millisecond and racing to grab
    the last slot) without making the user wait long when the system
    is genuinely saturated.
    """
    timeout = settings.concurrency_acquire_timeout_seconds
    retry_after = max(1, settings.concurrency_retry_after_seconds)

    g = _global_semaphore()
    p = _per_actor_semaphore(actor_id, tier)

    try:
        await asyncio.wait_for(g.acquire(), timeout=timeout)
    except asyncio.TimeoutError:
        logger.info(
            "concurrency: global slot exhausted",
            extra={"actor": actor_id, "tier": tier, "scope": "global"},
        )
        raise ConcurrencyExhausted(scope="global", retry_after_seconds=retry_after)

    p_acquired = False
    try:
        try:
            await asyncio.wait_for(p.acquire(), timeout=timeout)
            p_acquired = True
        except asyncio.TimeoutError:
            logger.info(
                "concurrency: per-actor slot exhausted",
                extra={"actor": actor_id, "tier": tier, "scope": "per_actor"},
            )
            raise ConcurrencyExhausted(scope="per_actor", retry_after_seconds=retry_after)
        yield
    finally:
        if p_acquired:
            p.release()
        g.release()
