# SPDX-License-Identifier: AGPL-3.0-or-later
"""NEU-D.1: capacity guard for ``/convert`` and ``/compress``.

Pins three properties:

1. ``acquire_slot`` enforces the global cap — the (N+1)-th caller
   when N slots are already held raises ``ConcurrencyExhausted``
   with status 503 and a ``Retry-After`` header.
2. ``acquire_slot`` enforces the per-actor cap independently — a
   single actor cannot hold more slots than their tier permits,
   even when the global pool has free slots.
3. Released slots are reusable — once a holder exits the context
   manager, the next caller acquires immediately.

These run against the raw helper rather than the route so failures
point at the right module. A separate route-level smoke test in
``tests/test_concurrency_route_smoke.py`` would exercise the
HTTP-level wiring; for now the integration is covered by the
existing convert/compress tests passing under the new wrapper.
"""

from __future__ import annotations

import asyncio

import pytest

from app.core import concurrency as concurrency_module
from app.core.concurrency import ConcurrencyExhausted, acquire_slot
from app.core.config import settings


@pytest.fixture(autouse=True)
def _reset_singletons(monkeypatch):
    """Each test starts with a fresh global semaphore + actor map.

    The singletons in the module are bound to whichever loop first
    touched them; without a reset, a previous test's slot held by a
    cancelled task could leak a permit. ``_reset_for_tests`` drops
    both maps so the next ``acquire_slot`` rebuilds them in this
    test's loop with the current settings."""
    concurrency_module._reset_for_tests()
    # Tighten timings so the tests do not block the suite.
    monkeypatch.setattr(settings, "concurrency_acquire_timeout_seconds", 0.05)
    monkeypatch.setattr(settings, "concurrency_retry_after_seconds", 1)
    yield
    concurrency_module._reset_for_tests()


async def test_global_cap_rejects_overflow(monkeypatch):
    """N holders + 1 attempt = ConcurrencyExhausted(503)."""
    monkeypatch.setattr(settings, "max_global_concurrency", 2)
    concurrency_module._reset_for_tests()

    holders_in: list[asyncio.Event] = [asyncio.Event(), asyncio.Event()]
    holders_release: list[asyncio.Event] = [asyncio.Event(), asyncio.Event()]

    async def _hold(idx: int):
        async with acquire_slot(actor_id=f"actor-{idx}", tier="pro"):
            holders_in[idx].set()
            await holders_release[idx].wait()

    held1 = asyncio.create_task(_hold(0))
    held2 = asyncio.create_task(_hold(1))
    await asyncio.wait_for(holders_in[0].wait(), timeout=1)
    await asyncio.wait_for(holders_in[1].wait(), timeout=1)

    with pytest.raises(ConcurrencyExhausted) as excinfo:
        async with acquire_slot(actor_id="actor-3", tier="pro"):
            pass
    assert excinfo.value.status_code == 503
    assert excinfo.value.headers["Retry-After"] == "1"

    for ev in holders_release:
        ev.set()
    await asyncio.gather(held1, held2)


async def test_per_actor_cap_rejects_overflow_for_same_actor(monkeypatch):
    """Pro tier = 2 per actor. The 3rd concurrent slot for the same
    actor returns 429 even though the global pool has room."""
    monkeypatch.setattr(settings, "max_global_concurrency", 10)
    concurrency_module._reset_for_tests()

    in_evs = [asyncio.Event(), asyncio.Event()]
    rel_evs = [asyncio.Event(), asyncio.Event()]

    async def _hold(idx: int):
        async with acquire_slot(actor_id="user:42", tier="pro"):
            in_evs[idx].set()
            await rel_evs[idx].wait()

    h1 = asyncio.create_task(_hold(0))
    h2 = asyncio.create_task(_hold(1))
    await asyncio.wait_for(in_evs[0].wait(), timeout=1)
    await asyncio.wait_for(in_evs[1].wait(), timeout=1)

    with pytest.raises(ConcurrencyExhausted) as excinfo:
        async with acquire_slot(actor_id="user:42", tier="pro"):
            pass
    assert excinfo.value.status_code == 429
    assert excinfo.value.headers["Retry-After"] == "1"

    for ev in rel_evs:
        ev.set()
    await asyncio.gather(h1, h2)


async def test_different_actors_do_not_share_per_actor_cap(monkeypatch):
    """Anonymous tier = 1 per actor. Two distinct actors can each
    hold a slot at the same time — the cap is per actor, not
    aggregated across the IP / key namespace."""
    monkeypatch.setattr(settings, "max_global_concurrency", 5)
    concurrency_module._reset_for_tests()

    in_a = asyncio.Event()
    in_b = asyncio.Event()
    rel = asyncio.Event()

    async def _hold(actor: str, ev: asyncio.Event):
        async with acquire_slot(actor_id=actor, tier="anonymous"):
            ev.set()
            await rel.wait()

    a = asyncio.create_task(_hold("ip:1.2.3.4", in_a))
    b = asyncio.create_task(_hold("ip:5.6.7.8", in_b))
    await asyncio.wait_for(in_a.wait(), timeout=1)
    await asyncio.wait_for(in_b.wait(), timeout=1)

    rel.set()
    await asyncio.gather(a, b)


async def test_released_slots_are_reusable(monkeypatch):
    """After a holder exits the context manager, the next caller
    acquires immediately — pins the release path so a refactor
    cannot orphan a permit."""
    monkeypatch.setattr(settings, "max_global_concurrency", 1)
    concurrency_module._reset_for_tests()

    async with acquire_slot(actor_id="actor", tier="pro"):
        pass
    # Second acquisition must succeed immediately; if the first
    # leaked, this raises.
    async with acquire_slot(actor_id="actor", tier="pro"):
        pass


async def test_global_release_happens_even_on_per_actor_timeout(monkeypatch):
    """If the per-actor acquire times out, the global slot held
    during that wait must be released — otherwise a per-actor
    rejection would leak global permits one at a time."""
    monkeypatch.setattr(settings, "max_global_concurrency", 5)
    concurrency_module._reset_for_tests()

    rel = asyncio.Event()
    in_locked = asyncio.Event()

    async def _occupy_actor():
        async with acquire_slot(actor_id="actor:locked", tier="anonymous"):
            in_locked.set()
            await rel.wait()

    holder = asyncio.create_task(_occupy_actor())
    await asyncio.wait_for(in_locked.wait(), timeout=1)

    # Saturate the actor's own cap so subsequent requests hit per-actor 429.
    # Each of these grabs the global, fails the per-actor, releases the global.
    for _ in range(3):
        with pytest.raises(ConcurrencyExhausted) as excinfo:
            async with acquire_slot(actor_id="actor:locked", tier="anonymous"):
                pass
        assert excinfo.value.status_code == 429

    # Global has 5 slots; one is held by `actor:locked`. The remaining
    # four must still be reachable — if the per-actor timeout had
    # leaked global permits, fewer would succeed.
    in_evs = [asyncio.Event() for _ in range(4)]
    rel_evs = [asyncio.Event() for _ in range(4)]

    async def _hold(idx: int):
        async with acquire_slot(actor_id=f"other:{idx}", tier="anonymous"):
            in_evs[idx].set()
            await rel_evs[idx].wait()

    others = [asyncio.create_task(_hold(i)) for i in range(4)]
    for ev in in_evs:
        await asyncio.wait_for(ev.wait(), timeout=1)

    # Cleanup
    for ev in rel_evs:
        ev.set()
    rel.set()
    await asyncio.gather(holder, *others)
