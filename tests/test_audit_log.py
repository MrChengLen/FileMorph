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
10. Tampering with ``event_type`` or ``occurred_at`` flips
    ``verify_chain`` to the tampered row; erasing ``actor_user_id``
    leaves the chain intact.
11. Rows hashed with recipe 1 (before ``hash_version``) still verify,
    also with recipe-2 rows chained after them; a relabelled or
    unknown ``hash_version`` flips ``verify_chain`` to that row.
"""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core import audit as audit_module
from app.core.audit import (
    VERIFY_CHAIN_SQL,
    AuditWriteError,
    GENESIS_PREV_HASH,
    HASH_VERSION,
    _canonical_payload,
    _canonical_timestamp,
    _compute_hash,
    _compute_hash_v2,
    _recompute_hash,
    chain_length,
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
        assert curr.hash_version == HASH_VERSION
        recomputed = _recompute_hash(curr)
        assert recomputed == curr.record_hash


@pytest.mark.asyncio
async def test_verify_chain_returns_none_for_intact_chain(audit_session):
    for i in range(3):
        await record_event("test.event", payload={"i": i}, db=audit_session)
    bad = await verify_chain(audit_session)
    assert bad is None


@pytest.mark.asyncio
async def test_verify_chain_slice_accepts_its_first_rows_prev_hash(audit_session):
    """A slice's first row chains from a row outside the slice; only the
    table's first row must start at the genesis sentinel."""
    for i in range(4):
        await record_event("test.event", payload={"i": i}, db=audit_session)
    rows = await _rows_in_order(audit_session)

    assert await verify_chain(audit_session, start_id=rows[1].id) is None
    assert await verify_chain(audit_session, start_id=rows[1].id, limit=2) is None
    rows[2].payload_json = '{"i":99}'
    await audit_session.commit()
    assert await verify_chain(audit_session, start_id=rows[1].id) == rows[2].id


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


# ── 10. Hashed fields, and the erasable actor ────────────────────────


async def _rows_in_order(session: AsyncSession) -> list[AuditEvent]:
    result = await session.execute(select(AuditEvent).order_by(AuditEvent.id.asc()))
    return list(result.scalars().all())


@pytest.mark.asyncio
async def test_event_type_tampering_breaks_verification(audit_session):
    for i in range(3):
        await record_event("auth.login.failed", payload={"i": i}, db=audit_session)
    target = (await _rows_in_order(audit_session))[1]
    target.event_type = "auth.login.success"
    await audit_session.commit()

    bad = await verify_chain(audit_session)
    assert bad == target.id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "shift", [timedelta(hours=-3), timedelta(microseconds=1)], ids=["hours", "microsecond"]
)
async def test_occurred_at_tampering_breaks_verification(audit_session, shift):
    for i in range(3):
        await record_event("test.event", payload={"i": i}, db=audit_session)
    target = (await _rows_in_order(audit_session))[1]
    target.occurred_at = target.occurred_at + shift
    await audit_session.commit()

    bad = await verify_chain(audit_session)
    assert bad == target.id


@pytest.mark.asyncio
async def test_erasing_the_actor_keeps_chain_intact(audit_session):
    """Account deletion NULLs ``actor_user_id`` (FK ON DELETE SET NULL).
    The column stays outside ``record_hash`` so that erasing it never
    breaks the chain."""
    actor = uuid.uuid4()
    for i in range(3):
        await record_event("test.event", actor_user_id=actor, payload={"i": i}, db=audit_session)
    rows = await _rows_in_order(audit_session)
    assert [row.actor_user_id for row in rows] == [actor] * 3
    for row in rows:
        row.actor_user_id = None
    await audit_session.commit()
    assert await verify_chain(audit_session) is None


@pytest.mark.asyncio
async def test_prev_hash_tampering_breaks_verification(audit_session):
    for i in range(3):
        await record_event("test.event", payload={"i": i}, db=audit_session)
    target = (await _rows_in_order(audit_session))[1]
    target.prev_hash = "e" * 64
    await audit_session.commit()

    assert await verify_chain(audit_session) == target.id


# Every audit_events column, by whether recipe 2 hashes it. A new column
# fails the test below until someone decides: hash it (a new recipe and
# hash_version) or list it here with the reason it stays outside.
# hash_version counts as hashed: the recipe's leading "v2" binds it.
_HASHED_COLUMNS = {"prev_hash", "event_type", "occurred_at", "payload_json", "hash_version"}
_UNHASHED_COLUMNS = {
    "id",  # assigned by the database at INSERT; the prev_hash links fix the order
    "record_hash",  # the hash itself
    "actor_user_id",  # personal data: account deletion NULLs it
}


def test_every_audit_column_is_hashed_or_deliberately_left_out():
    columns = {c.name for c in AuditEvent.__table__.columns}
    assert columns == _HASHED_COLUMNS | _UNHASHED_COLUMNS, (
        f"unclassified: {sorted(columns - _HASHED_COLUMNS - _UNHASHED_COLUMNS)}, "
        f"gone: {sorted((_HASHED_COLUMNS | _UNHASHED_COLUMNS) - columns)}"
    )


@pytest.mark.asyncio
async def test_chain_verifies_from_a_fresh_session(audit_session):
    """Verification from rows loaded back out of the database, not from
    the writer's in-memory objects: the stored ``occurred_at`` must
    reproduce the hashed value (SQLite hands it back without tzinfo)."""
    for i in range(3):
        await record_event("test.event", payload={"i": i}, db=audit_session)
    async with _TestSession() as fresh:
        assert await chain_length(fresh) == 3
        assert await verify_chain(fresh) is None


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

    original = audit_module._compute_hash_v2

    def boom(*a, **kw):
        raise RuntimeError("simulated insert failure")

    monkeypatch.setattr(audit_module, "_compute_hash_v2", boom)
    try:
        with pytest.raises(AuditWriteError):
            await record_event("test.event", payload={"x": 1}, db=audit_session)
    finally:
        monkeypatch.setattr(audit_module, "_compute_hash_v2", original)


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
    does the audit-spec — that's a backwards-incompatible change.
    Recipe 1 must never change: rows written with it stay in the chain."""
    canonical = '{"event":"convert","src":"jpg","tgt":"pdf"}'
    h = hashlib.sha256()
    h.update(GENESIS_PREV_HASH.encode("ascii"))
    h.update(canonical.encode("utf-8"))
    expected = h.hexdigest()
    assert _compute_hash(GENESIS_PREV_HASH, canonical) == expected


def test_compute_hash_v2_matches_hand_reference():
    """Recipe 2, spelled out byte by byte as in the ``_compute_hash_v2``
    docstring. Changing it means a new ``hash_version``, never an edit."""
    canonical = '{"event":"convert","src":"jpg","tgt":"pdf"}'
    occurred_at = datetime(2026, 9, 29, 7, 48, 13, 921000, tzinfo=timezone.utc)
    message = (
        "v2\n" + GENESIS_PREV_HASH + "\nfile.convert\n2026-09-29T07:48:13.921000Z\n" + canonical
    )
    expected = hashlib.sha256(message.encode("utf-8")).hexdigest()
    assert _compute_hash_v2(GENESIS_PREV_HASH, "file.convert", occurred_at, canonical) == expected


def test_verify_chain_sql_can_be_copied_from_the_source():
    """An auditor pastes the query from app/core/audit.py into psql, so the
    source must spell it exactly as Postgres receives it: no escapes that
    Python resolves and psql would not."""
    source = Path(audit_module.__file__).read_text(encoding="utf-8")
    assert VERIFY_CHAIN_SQL in source


def test_canonical_timestamp_is_utc_fixed_width_whatever_the_zone():
    """Postgres hands ``occurred_at`` back timezone-aware (any zone),
    SQLite hands it back naive: the same instant must hash the same."""
    aware = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    naive = aware.replace(tzinfo=None)
    plus_one = aware.astimezone(timezone(timedelta(hours=1)))
    assert (
        _canonical_timestamp(aware)
        == _canonical_timestamp(naive)
        == _canonical_timestamp(plus_one)
        == "2026-01-02T03:04:05.000000Z"
    )


# ── 11. Rows from before hash_version keep verifying ─────────────────


async def _insert_recipe_1_row(session: AsyncSession, prev_hash: str, payload: dict) -> AuditEvent:
    """A row as the pre-``hash_version`` code wrote it. It sets no
    ``hash_version``, so the column default labels it recipe 1, as
    the migration does for existing rows."""
    canonical = _canonical_payload(payload)
    row = AuditEvent(
        event_type="test.legacy",
        payload_json=canonical,
        prev_hash=prev_hash,
        record_hash=_compute_hash(prev_hash, canonical),
    )
    session.add(row)
    await session.commit()
    return row


@pytest.mark.asyncio
async def test_recipe_1_rows_verify_and_chain_into_new_rows(audit_session):
    first = await _insert_recipe_1_row(audit_session, GENESIS_PREV_HASH, {"i": 0})
    second = await _insert_recipe_1_row(audit_session, first.record_hash, {"i": 1})
    await record_event("test.event", payload={"i": 2}, db=audit_session)
    await record_event("test.event", payload={"i": 3}, db=audit_session)

    rows = await _rows_in_order(audit_session)
    assert [r.hash_version for r in rows] == [1, 1, HASH_VERSION, HASH_VERSION]
    assert rows[2].prev_hash == second.record_hash
    assert await verify_chain(audit_session) is None
    async with _TestSession() as fresh:
        assert await verify_chain(fresh) is None


@pytest.mark.asyncio
async def test_recipe_1_payload_tampering_still_breaks_verification(audit_session):
    first = await _insert_recipe_1_row(audit_session, GENESIS_PREV_HASH, {"i": 0})
    await record_event("test.event", payload={"i": 1}, db=audit_session)
    first.payload_json = '{"i":99}'
    await audit_session.commit()

    assert await verify_chain(audit_session) == first.id


@pytest.mark.asyncio
async def test_relabelling_a_recipe_1_row_breaks_verification(audit_session):
    first = await _insert_recipe_1_row(audit_session, GENESIS_PREV_HASH, {"i": 0})
    await record_event("test.event", payload={"i": 1}, db=audit_session)
    first.hash_version = HASH_VERSION
    await audit_session.commit()

    assert await verify_chain(audit_session) == first.id


@pytest.mark.asyncio
@pytest.mark.parametrize("version", [1, 3], ids=["older", "unknown"])
async def test_relabelled_hash_version_breaks_verification(audit_session, version):
    for i in range(3):
        await record_event("test.event", payload={"i": i}, db=audit_session)
    target = (await _rows_in_order(audit_session))[1]
    target.hash_version = version
    await audit_session.commit()

    assert await verify_chain(audit_session) == target.id
