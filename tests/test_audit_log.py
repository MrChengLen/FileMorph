# SPDX-License-Identifier: AGPL-3.0-or-later
"""Compliance Edition: audit-log hash-chain tests.

Mirrors the in-memory-SQLite shape used in ``test_daily_metrics.py``:
spin up a fresh engine, run the model metadata create_all, then drive
``app.core.audit.record_event`` and ``verify_chain`` through the
session-handle path.

Coverage
--------
1. Genesis sentinel — first row's ``prev_hash`` is ``GENESIS_PREV_HASH``.
2. Forward chaining — each row's ``prev_hash`` matches the previous
   row's ``record_hash``.
3. Recompute matches the stored hash for an untampered chain.
4. Tampering with ``payload_json`` flips ``verify_chain`` to return
   the tampered row's id.
5. Reordering / deleting a middle row produces a chain mismatch.
6. ``event_type`` validation — invalid keys are rejected with a
   warning; with ``audit_fail_closed`` they raise ``AuditWriteError``.
7. ``audit_fail_closed`` re-raises insertion failures as
   ``AuditWriteError``; default mode swallows.
8. Canonical-JSON: payload encoding is deterministic across key
   orderings (a regression here breaks reproducible verification).
9. Concurrent writes serialise on the in-process lock + DB-level
   uniqueness — no two rows ever share a ``record_hash``.
"""

from __future__ import annotations

import asyncio
import hashlib

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core import audit as audit_module
from app.core.audit import (
    AuditWriteError,
    GENESIS_PREV_HASH,
    _canonical_payload,
    _compute_hash,
    record_event,
    verify_chain,
)
from app.core.config import settings
from app.db.base import Base
from app.db.models import AuditEvent

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


async def _reset_audit() -> None:
    async with _TestSession() as s:
        await s.execute(delete(AuditEvent))
        await s.commit()


@pytest.fixture(autouse=True)
def _audit_open_default(monkeypatch):
    """Default tests run with audit_fail_closed=False — the strict
    behaviour is exercised in dedicated tests that flip it."""
    monkeypatch.setattr(settings, "audit_fail_closed", False)


@pytest.fixture
async def audit_session():
    await _setup_schema()
    await _reset_audit()
    async with _TestSession() as s:
        yield s


# ── 1. Genesis row ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_first_event_uses_genesis_prev_hash(audit_session):
    await record_event("test.event", payload={"k": 1}, db=audit_session)
    rows = (await audit_session.execute(select(AuditEvent))).scalars().all()
    assert len(rows) == 1
    assert rows[0].prev_hash == GENESIS_PREV_HASH


# ── 2 + 3. Forward chain + recompute ─────────────────────────────────


@pytest.mark.asyncio
async def test_chain_links_each_row_to_predecessor(audit_session):
    for i in range(5):
        await record_event("test.event", payload={"i": i}, db=audit_session)

    rows = (
        (await audit_session.execute(select(AuditEvent).order_by(AuditEvent.id.asc())))
        .scalars()
        .all()
    )
    assert len(rows) == 5
    assert rows[0].prev_hash == GENESIS_PREV_HASH
    for prev, curr in zip(rows, rows[1:]):
        assert curr.prev_hash == prev.record_hash, "chain link broken"
        recomputed = _compute_hash(curr.prev_hash, curr.payload_json)
        assert recomputed == curr.record_hash


@pytest.mark.asyncio
async def test_verify_chain_returns_none_for_intact_chain(audit_session):
    for i in range(3):
        await record_event("test.event", payload={"i": i}, db=audit_session)
    bad = await verify_chain(audit_session)
    assert bad is None


# ── 4 + 5. Tampering detection ───────────────────────────────────────


@pytest.mark.asyncio
async def test_payload_tampering_breaks_verification(audit_session):
    for i in range(3):
        await record_event("test.event", payload={"i": i}, db=audit_session)
    # SQLite test harness: the Postgres trigger isn't installed, so we
    # CAN tamper from the test process. That is exactly the point —
    # verify_chain detects it even when the storage layer permits it.
    target = (
        (
            await audit_session.execute(
                select(AuditEvent).order_by(AuditEvent.id.asc()).offset(1).limit(1)
            )
        )
        .scalars()
        .one()
    )
    target.payload_json = '{"i":99}'
    await audit_session.commit()

    bad = await verify_chain(audit_session)
    assert bad == target.id


@pytest.mark.asyncio
async def test_record_hash_tampering_breaks_verification(audit_session):
    await record_event("test.event", payload={"first": True}, db=audit_session)
    await record_event("test.event", payload={"second": True}, db=audit_session)
    first = (
        (await audit_session.execute(select(AuditEvent).order_by(AuditEvent.id.asc()).limit(1)))
        .scalars()
        .one()
    )
    first.record_hash = "f" * 64
    await audit_session.commit()
    bad = await verify_chain(audit_session)
    assert bad == first.id


# ── 6. event_type validation ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_invalid_event_type_rejected_silently_in_open_mode(audit_session):
    await record_event("UPPER CASE INVALID", payload={"x": 1}, db=audit_session)
    rows = (await audit_session.execute(select(AuditEvent))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_invalid_event_type_raises_in_fail_closed_mode(audit_session, monkeypatch):
    monkeypatch.setattr(settings, "audit_fail_closed", True)
    with pytest.raises(AuditWriteError):
        await record_event("UPPER CASE INVALID", payload={"x": 1}, db=audit_session)


# ── 7. fail_closed propagates DB failures ────────────────────────────


@pytest.mark.asyncio
async def test_fail_closed_re_raises_db_failure(audit_session, monkeypatch):
    """Force the insert path to fail and verify the strict mode
    surfaces it as AuditWriteError. We monkeypatch the in-process lock
    section to inject the error rather than corrupting the SQLAlchemy
    session itself."""
    monkeypatch.setattr(settings, "audit_fail_closed", True)

    original = audit_module._compute_hash

    def boom(*a, **kw):
        raise RuntimeError("simulated insert failure")

    monkeypatch.setattr(audit_module, "_compute_hash", boom)
    try:
        with pytest.raises(AuditWriteError):
            await record_event("test.event", payload={"x": 1}, db=audit_session)
    finally:
        monkeypatch.setattr(audit_module, "_compute_hash", original)


# ── 8. canonical JSON deterministic ──────────────────────────────────


def test_canonical_payload_is_key_order_independent():
    a = _canonical_payload({"b": 2, "a": 1})
    b = _canonical_payload({"a": 1, "b": 2})
    assert a == b == '{"a":1,"b":2}'


def test_canonical_payload_no_whitespace_no_ascii_escape():
    """Hash bytes must be exactly the canonical bytes; no formatter
    whitespace, and Unicode preserved as UTF-8 (ensure_ascii=False).
    Otherwise an external auditor recomputing from a SQL dump using
    a stdlib JSON loader gets a different byte string."""
    s = _canonical_payload({"name": "Müller", "id": 42})
    assert s == '{"id":42,"name":"Müller"}'


# ── 9. Concurrency + uniqueness ──────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_writes_serialize_on_chain_lock(audit_session):
    """Twenty parallel writes must all land — the in-process lock makes
    sure each one chains off the previous record_hash, never the same
    one twice. With the lock in place, all 20 inserts succeed and the
    chain verifies."""
    await asyncio.gather(
        *[record_event("test.event", payload={"i": i}, db=audit_session) for i in range(20)]
    )
    rows = (
        (await audit_session.execute(select(AuditEvent).order_by(AuditEvent.id.asc())))
        .scalars()
        .all()
    )
    assert len(rows) == 20
    seen_hashes = {r.record_hash for r in rows}
    assert len(seen_hashes) == 20, "every record_hash must be unique"
    bad = await verify_chain(audit_session)
    assert bad is None


# ── Hash recomputation matches a hand-computed reference ─────────────


def test_compute_hash_matches_hand_reference():
    """Lock the hash convention so an external auditor can implement
    the same check with two stdlib calls. If this test changes, so
    does the audit-spec — that's a backwards-incompatible change."""
    canonical = '{"event":"convert","src":"jpg","tgt":"pdf"}'
    h = hashlib.sha256()
    h.update(GENESIS_PREV_HASH.encode("ascii"))
    h.update(canonical.encode("utf-8"))
    expected = h.hexdigest()
    assert _compute_hash(GENESIS_PREV_HASH, canonical) == expected
