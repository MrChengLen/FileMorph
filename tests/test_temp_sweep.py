# SPDX-License-Identifier: AGPL-3.0-or-later
"""NEU-B.2: temp-dir sweep (startup + periodic).

The convert/compress request paths clean their own ``fm_*`` temp
dirs in ``finally`` blocks, so the only way an ``fm_*`` survives is
a crash mid-conversion (worker killed, OOM, container shutdown
without a clean lifespan). The startup sweep covers process
restarts; the periodic sweep covers long-running workers that stay
up across many incidents.

These tests pin three properties:

1. ``_sweep_stale_temp_dirs`` deletes only old ``fm_*`` dirs and
   leaves recent ones alone (the safety margin for an in-flight
   conversion is 10 minutes by default).
2. It only touches dirs prefixed with ``fm_`` — adjacent unrelated
   tempdirs from other tools are not collateral.
3. The periodic sweep loop wakes up, calls the helper, and shuts
   down cleanly when the stop event is set.
"""

from __future__ import annotations

import asyncio
import os
import time

from app.main import _periodic_temp_sweep, _sweep_stale_temp_dirs


def _make_dir(parent, name: str, *, age_seconds: int) -> str:
    """Create ``parent/name`` and back-date its mtime by ``age_seconds``."""
    p = parent / name
    p.mkdir()
    # Drop a marker so a missing rmtree shows up as a leftover file.
    (p / "marker").write_text("x")
    past = time.time() - age_seconds
    os.utime(p, (past, past))
    return str(p)


def test_sweep_removes_old_fm_dirs(tmp_path, monkeypatch):
    """An old ``fm_*`` dir is removed; a fresh one is kept."""
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    old = _make_dir(tmp_path, "fm_old123", age_seconds=3600)
    fresh = _make_dir(tmp_path, "fm_fresh456", age_seconds=10)

    swept = _sweep_stale_temp_dirs(max_age_seconds=600)

    assert swept == 1
    assert not os.path.exists(old)
    assert os.path.exists(fresh)


def test_sweep_ignores_non_fm_dirs(tmp_path, monkeypatch):
    """A stale dir that does not match the ``fm_`` prefix is left
    alone — the sweep is scoped to FileMorph's own temp namespace
    and must not touch other tools' tempdirs."""
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    other = _make_dir(tmp_path, "pip_build_xyz", age_seconds=3600)
    fm = _make_dir(tmp_path, "fm_old", age_seconds=3600)

    _sweep_stale_temp_dirs(max_age_seconds=600)

    assert os.path.exists(other)
    assert not os.path.exists(fm)


def test_sweep_handles_empty_tempdir(tmp_path, monkeypatch):
    """No ``fm_*`` dirs to sweep → returns 0, raises nothing."""
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    assert _sweep_stale_temp_dirs(max_age_seconds=600) == 0


async def test_periodic_sweep_runs_and_stops_cleanly(tmp_path, monkeypatch):
    """The periodic loop ticks at least once, sweeps real dirs, and
    exits when the stop event is set."""
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    old = _make_dir(tmp_path, "fm_periodic_test", age_seconds=3600)

    stop_event = asyncio.Event()
    # Tiny interval so the loop wakes up quickly inside the test.
    task = asyncio.create_task(
        _periodic_temp_sweep(
            interval_seconds=0,  # wait_for(timeout=0) raises TimeoutError immediately
            max_age_seconds=600,
            stop_event=stop_event,
        )
    )
    # Yield a few times to let the loop run one tick.
    for _ in range(5):
        await asyncio.sleep(0)
        if not os.path.exists(old):
            break

    stop_event.set()
    await asyncio.wait_for(task, timeout=2)

    assert not os.path.exists(old)


async def test_periodic_sweep_stops_immediately_when_event_preset(tmp_path, monkeypatch):
    """If ``stop_event`` is already set before the task starts, the
    loop must exit on the first iteration without sweeping. Pinned
    so a future refactor cannot re-introduce a race that makes the
    sweep run once after shutdown was requested."""
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    old = _make_dir(tmp_path, "fm_should_survive", age_seconds=3600)
    stop_event = asyncio.Event()
    stop_event.set()

    task = asyncio.create_task(
        _periodic_temp_sweep(
            interval_seconds=60,
            max_age_seconds=600,
            stop_event=stop_event,
        )
    )
    await asyncio.wait_for(task, timeout=2)

    # The dir is still there because the loop bailed before sweeping.
    assert os.path.exists(old)
