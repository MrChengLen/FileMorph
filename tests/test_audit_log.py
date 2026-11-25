# SPDX-License-Identifier: AGPL-3.0-or-later
"""Compliance Edition: audit-log hash-chain tests.

On the shared Cloud test database (``cloud_db``, tests/support/db.py),
emptied before every test: drive ``app.core.audit.record_event`` and
``verify_chain`` through the session-handle path.

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
12. Retention: ``delete_expired_events`` deletes the expired entries at
    the start of the chain, up to the first younger one, keeps the
    newest of them and records the run; the chain verifies, also over
    years of runs. Deleting at the start without that record, beyond it,
    or behind a forged, future-dated or malformed record flips
    ``verify_chain`` to the oldest row left. Nothing is deleted when the
    record fails.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit as audit_module
from app.core.audit import (
    VERIFY_CHAIN_SQL,
    AuditWriteError,
    GENESIS_PREV_HASH,
    HASH_VERSION,
    RETENTION_EVENT,
    RETENTION_LINK_KEY,
    RETENTION_MIN_AGE,
    RETENTION_RECORD_MAX_LENGTH,
    RETENTION_YEARS,
    _canonical_payload,
    _canonical_timestamp,
    _compute_hash,
    _compute_hash_v2,
    _recompute_hash,
    chain_length,
    delete_expired_events,
    record_event,
    verify_chain,
)
from app.core.config import settings
from app.db.models import AuditEvent
from tests.support.audit_records import RECORD_CASES, record_payload
from tests.support.db import TestSession, cloud_db

_db = cloud_db(override_get_db=False)


@pytest.fixture(autouse=True)
def _audit_open_default(monkeypatch):
    """Default tests run with audit_fail_closed=False — the strict
    behaviour is exercised in dedicated tests that flip it."""
    monkeypatch.setattr(settings, "audit_fail_closed", False)


@pytest.fixture
async def audit_session():
    async with TestSession() as s:
        yield s


# ── 1–3. Genesis row, forward chain + recompute ──────────────────────


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
    async with TestSession() as fresh:
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


@pytest.mark.parametrize(
    "doc",
    [
        "dpa-template.md",
        "dpa-tom-annex.md",
        "security-overview.md",
        "vendor-security-questionnaire.md",
    ],
)
def test_compliance_docs_point_to_the_sql_check(doc):
    """These docs send auditors to ``VERIFY_CHAIN_SQL``; renaming it in
    app/core/audit.py must not leave them pointing at nothing."""
    assert hasattr(audit_module, "VERIFY_CHAIN_SQL"), "renamed? update the docs too"
    docs = Path(__file__).resolve().parent.parent / "docs"
    assert "VERIFY_CHAIN_SQL" in (docs / doc).read_text(encoding="utf-8"), doc


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
    async with TestSession() as fresh:
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


# ── 12. Retention: entries older than three years ──────────────────

_EXPIRED = timedelta(days=1100)  # more than three calendar years ago
_KEPT = timedelta(days=1090)  # less than three calendar years ago


async def _append_row_at(
    session: AsyncSession,
    occurred_at: datetime,
    canonical: str,
    event_type: str = "test.event",
) -> AuditEvent:
    """What ``record_event`` writes, stamped ``occurred_at`` instead of now."""
    prev = await session.scalar(
        select(AuditEvent.record_hash).order_by(AuditEvent.id.desc()).limit(1)
    )
    prev_hash = prev or GENESIS_PREV_HASH
    row = AuditEvent(
        occurred_at=occurred_at,
        event_type=event_type,
        payload_json=canonical,
        prev_hash=prev_hash,
        record_hash=_compute_hash_v2(prev_hash, event_type, occurred_at, canonical),
        hash_version=HASH_VERSION,
    )
    session.add(row)
    await session.commit()
    return row


async def _append_aged(session: AsyncSession, ages: list[timedelta]) -> list[AuditEvent]:
    now = datetime.now(timezone.utc)
    return [
        await _append_row_at(session, now - age, _canonical_payload({"i": i}))
        for i, age in enumerate(ages)
    ]


@pytest.mark.asyncio
async def test_retention_keeps_the_newest_expired_entry_and_records_the_run(audit_session):
    expired = await _append_aged(
        audit_session, [_EXPIRED + timedelta(minutes=2 - i) for i in range(3)]
    )
    (kept,) = await _append_aged(audit_session, [_KEPT])
    await record_event("test.event", payload={"i": 4}, db=audit_session)

    assert await delete_expired_events(audit_session) == 2

    rows = await _rows_in_order(audit_session)
    assert [r.id for r in rows[:2]] == [expired[-1].id, kept.id]
    assert rows[-1].event_type == RETENTION_EVENT
    assert json.loads(rows[-1].payload_json) == {
        "deleted": 2,
        RETENTION_LINK_KEY: expired[1].record_hash,
    }
    assert await verify_chain(audit_session) is None


@pytest.mark.asyncio
async def test_retention_stops_at_the_first_entry_that_has_not_expired(audit_session):
    """The clock went back: an expired entry sits behind a younger one. It
    waits for a later run, so the entries left stay one chain."""
    first, second, younger, behind = await _append_aged(
        audit_session, [_EXPIRED, _EXPIRED - timedelta(minutes=1), _KEPT, _EXPIRED]
    )

    assert await delete_expired_events(audit_session) == 1

    rows = await _rows_in_order(audit_session)
    assert [r.id for r in rows[:3]] == [second.id, younger.id, behind.id]
    assert await verify_chain(audit_session) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("ages", [[_KEPT], [_EXPIRED, _KEPT]], ids=["none", "only-the-first"])
async def test_retention_with_nothing_before_the_newest_expired_changes_nothing(
    audit_session, ages
):
    await _append_aged(audit_session, ages)

    assert await delete_expired_events(audit_session) == 0
    assert await chain_length(audit_session) == len(ages)


@pytest.mark.asyncio
async def test_retention_over_the_years_keeps_one_verifiable_chain(audit_session, monkeypatch):
    """Runs every half year for eight years: entries expire, then the
    deletion records themselves; the chain verifies after every run."""
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    clock = [start]

    class _Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock[0]

    monkeypatch.setattr(audit_module, "datetime", _Clock)
    deleted = 0
    for half_year in range(17):
        clock[0] = start + timedelta(days=182 * half_year)
        await record_event("test.event", payload={"half_year": half_year}, db=audit_session)
        deleted += await delete_expired_events(audit_session)
        assert await verify_chain(audit_session) is None, half_year

    oldest = (await _rows_in_order(audit_session))[0]
    age = clock[0] - audit_module._as_utc(oldest.occurred_at)
    assert deleted > 0
    assert timedelta(days=3 * 365) < age < timedelta(days=3 * 365 + 183)


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_closed", [False, True], ids=["open", "fail-closed"])
async def test_retention_deletes_nothing_it_cannot_record(audit_session, monkeypatch, fail_closed):
    await _append_aged(audit_session, [_EXPIRED, _EXPIRED - timedelta(minutes=1), _KEPT])
    monkeypatch.setattr(settings, "audit_fail_closed", fail_closed)

    def _broken(*_args):
        raise RuntimeError("hash failed")

    monkeypatch.setattr(audit_module, "_compute_hash_v2", _broken)
    if fail_closed:
        with pytest.raises(AuditWriteError):
            await delete_expired_events(audit_session)
    else:
        assert await delete_expired_events(audit_session) == 0

    async with TestSession() as fresh:
        assert await chain_length(fresh) == 3


@pytest.mark.asyncio
async def test_a_deleted_start_without_its_record_breaks_verification(audit_session):
    for i in range(3):
        await record_event("test.event", payload={"i": i}, db=audit_session)
    rows = await _rows_in_order(audit_session)
    await audit_session.delete(rows[0])
    await audit_session.commit()

    assert await verify_chain(audit_session) == rows[1].id


@pytest.mark.asyncio
async def test_deleting_beyond_the_recorded_deletion_breaks_verification(audit_session):
    await _append_aged(audit_session, [_EXPIRED, _EXPIRED - timedelta(minutes=1), _KEPT, _KEPT])
    assert await delete_expired_events(audit_session) == 1
    rows = await _rows_in_order(audit_session)
    await audit_session.delete(rows[0])
    await audit_session.commit()

    assert await verify_chain(audit_session) == rows[1].id


@pytest.mark.asyncio
async def test_a_forged_deletion_record_cannot_hide_removed_entries(audit_session):
    """Young entries cut from the start, then a record appended that names
    the cut: the oldest entry left is not three years older than the record."""
    for i in range(6):
        await record_event("test.event", payload={"i": i}, db=audit_session)
    rows = await _rows_in_order(audit_session)
    for row in rows[:4]:
        await audit_session.delete(row)
    await audit_session.commit()
    forged = _canonical_payload({"deleted": 4, RETENTION_LINK_KEY: rows[3].record_hash})
    assert await audit_module._do_record(audit_session, RETENTION_EVENT, None, forged)

    assert await verify_chain(audit_session) == rows[4].id


@pytest.mark.asyncio
@pytest.mark.parametrize("payload, written_in_days, vouches", RECORD_CASES)
async def test_only_a_well_formed_past_record_vouches_for_the_start(
    audit_session, payload, written_in_days, vouches
):
    """An expired entry whose predecessor is gone, and a record of that
    deletion: only the app's own payload, written by now, vouches
    (cases in tests/support/audit_records.py)."""
    first, second, _ = await _append_aged(
        audit_session, [_EXPIRED, _EXPIRED - timedelta(minutes=1), _KEPT]
    )
    await audit_session.delete(first)
    await audit_session.commit()
    await _append_row_at(
        audit_session,
        datetime.now(timezone.utc) + timedelta(days=written_in_days),
        record_payload(payload, first.record_hash),
        RETENTION_EVENT,
    )

    assert await verify_chain(audit_session) == (None if vouches else second.id)


@pytest.mark.asyncio
async def test_retention_counts_calendar_years(audit_session, monkeypatch):
    """29 February goes back to 28 February, as ``interval '3 years'`` in
    migration 015's trigger does."""

    class _LeapDay(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2028, 2, 29, 12, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(audit_module, "datetime", _LeapDay)
    cutoff = await audit_module._retention_cutoff(audit_session)
    assert cutoff == datetime(2025, 2, 28, 12, 0, tzinfo=timezone.utc)


def test_verify_chain_sql_spells_the_retention_rule():
    """The SQL check repeats in literals what the Python check reads from
    constants, and migration 015's trigger spells the period."""
    hours = int(RETENTION_MIN_AGE.total_seconds() // 3600)
    for literal in (
        f"'{RETENTION_EVENT}'",
        f"'{RETENTION_LINK_KEY}'",
        f"interval '{hours} hours'",
        f"length(deletion.payload_json) > {RETENTION_RECORD_MAX_LENGTH}",
        "position(chr(92) in deletion.payload_json)",
    ):
        assert literal in VERIFY_CHAIN_SQL, literal
    migration = (
        Path(__file__).resolve().parent.parent / "alembic" / "versions" / "015_audit_retention.py"
    )
    assert f"interval '{RETENTION_YEARS} years'" in migration.read_text(encoding="utf-8")
