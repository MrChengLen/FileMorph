# SPDX-License-Identifier: AGPL-3.0-or-later
"""Compliance Edition: tamper-evident audit log with SHA-256 hash chain.

ISO/IEC 27001:2022 A.8.15 (logging) and BSI OPS.1.1.5 both expect
operations on regulated data to leave a record that is provably
unaltered. This module provides that record. The chain is intentionally
simple — a forward SHA-256 chain over each event's record —
because simplicity is what makes it auditable from a SQL dump without
running our code.

Three properties hold:

1. **Append-only at the database layer.** Migration 005 installs a
   Postgres trigger that raises on UPDATE / DELETE, with two
   exceptions: the ``ON DELETE SET NULL`` cascade that clears
   ``actor_user_id`` when that account is deleted (migration 012), and
   deleting an entry older than ``RETENTION_YEARS`` (migration 015),
   which ``delete_expired_events`` does once a day; TRUNCATE is
   refused too (migration 015). SQLite (test
   harness only) skips the trigger; we cover the SQLite path with a
   "verify rejects tampering" test instead.
2. **Forward chain.** ``record_hash[i]`` is the SHA-256 of
   ``record_hash[i-1]`` plus row i's ``event_type``, ``occurred_at`` and
   canonical payload; the exact byte recipe is in ``_compute_hash_v2``.
   The first row uses ``'0' * 64`` as the genesis sentinel; once expired
   entries are deleted, the oldest row left links to a deleted one
   instead, which the deletion's own entry names (``RETENTION_EVENT``,
   ``_vouched_start``). Any
   retroactive edit cascades — every row from the tampered one onward
   fails verification. ``hash_version`` names the recipe per row: 2 for
   rows written by this code, 1 for rows written before the column
   existed (``SHA256(prev_hash || canonical_payload)``,
   ``_compute_hash``); both kinds verify in one pass. ``actor_user_id``
   is not hashed, in either recipe: it is personal data and must stay
   erasable without breaking the chain — account deletion NULLs it
   through ON DELETE SET NULL (the one UPDATE the trigger lets through,
   migration 012).
3. **Fire-and-forget by default.** ``record_event`` never raises into
   the caller. Compliance Edition flips ``settings.audit_fail_closed
   = True`` and the helper raises an ``AuditWriteError`` instead, so a
   convert/compress route can refuse to serve a result it cannot log.

Session ownership mirrors ``app/core/metrics.py``: ``record_event``
opens its own ``AsyncSession`` from ``AsyncSessionLocal`` and commits
in isolation, so an audit-write failure can never clobber a partially
built request transaction. Tests pass an explicit session via
``db=`` for the in-memory SQLite engine.

The verification routine ``verify_chain`` walks the table in id-order
and returns the first id where the recomputed hash differs from the
stored one (or ``None`` if the chain is intact). Use it from a
maintenance CLI or an admin endpoint — never on the request path.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.base import AsyncSessionLocal
from app.db.models import AuditEvent

logger = logging.getLogger(__name__)

# Genesis sentinel — the prev_hash of the very first row. Sixty-four
# zero hex chars so it is a valid SHA-256-shaped value, distinguishable
# from any real hash (which has near-zero probability of being all
# zeros). Verification treats this as "this row is the start of the
# chain"; if it appears in the middle of the table, that itself is
# evidence of tampering.
GENESIS_PREV_HASH = "0" * 64

# Recipe ``_do_record`` writes (``AuditEvent.hash_version``). Rows from
# before the column existed carry 1; see ``_recompute_hash``.
HASH_VERSION = 2

# Entries are kept this many calendar years, then deleted (privacy notice
# § 2h). Migration 015's trigger refuses to delete anything younger; it
# spells the same period in SQL.
RETENTION_YEARS = 3

# The entry ``delete_expired_events`` appends for each run that deleted
# entries, and the payload key that names the hash the oldest entry left
# links to. ``VERIFY_CHAIN_SQL`` spells both out.
RETENTION_EVENT = "audit.retention.deleted"
RETENTION_LINK_KEY = "last_deleted_hash"

# How much older than the deletion record the oldest entry must be for the
# record to vouch for its link: three years less a day, the slack for the
# app's and the database's clocks (three calendar years are 1,095 or
# 1,096 days). ``VERIFY_CHAIN_SQL`` spells it in hours.
RETENTION_MIN_AGE = timedelta(days=RETENTION_YEARS * 365 - 1)

# A deletion record names its link only when its payload is at most this
# long and holds no backslash (the app writes about 100 characters, no
# escapes): anything else could make the SQL check fail on the JSON
# instead of answering. ``VERIFY_CHAIN_SQL`` spells both out.
RETENTION_RECORD_MAX_LENGTH = 200

# Mirror of the metrics-key whitelist: ASCII lower/digit/dot/underscore/
# hyphen, ≤64 chars. Event types are constructed in code, never from
# raw user input — the regex enforces that contract so an upstream
# regression surfaces as a log warning rather than a poisoned chain.
_VALID_EVENT_TYPE = re.compile(r"^[a-z0-9._\-]{1,64}$")

# Lock serialises the read-prev-hash + insert-new-row sequence inside
# one process. The DB-level UNIQUE on record_hash is the second line of
# defence: if two processes try to chain from the same prev_hash, only
# one INSERT can succeed. The loser raises and is logged; the chain
# stays consistent.
_chain_lock = asyncio.Lock()


class AuditWriteError(RuntimeError):
    """Raised by ``record_event`` only when ``audit_fail_closed`` is on
    and the write fails. Compliance-Edition deployments use this to
    refuse serving a result they could not log."""


def _canonical_payload(payload: Mapping[str, Any] | None) -> str:
    """Deterministic JSON serialisation: sorted keys, no whitespace,
    UTF-8. The hash covers exactly this string, so an external auditor
    can recompute the chain from a SQL dump without depending on Python
    or our serialiser version."""
    if payload is None:
        return "{}"
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _compute_hash(prev_hash: str, canonical: str) -> str:
    """Recipe 1: ``SHA-256(prev_hash || canonical_payload)`` as lowercase hex.

    Verifies rows written before ``hash_version`` existed; new rows use
    ``_compute_hash_v2``. Both inputs are ASCII / UTF-8 strings; we encode
    once and feed the bytes into one hash context. No domain-separator is
    needed because ``prev_hash`` is fixed-length (64 hex chars) — the
    boundary is unambiguous to an auditor reading the spec in this docstring.
    """
    h = hashlib.sha256()
    h.update(prev_hash.encode("ascii"))
    h.update(canonical.encode("utf-8"))
    return h.hexdigest()


def _canonical_timestamp(value: datetime) -> str:
    """``occurred_at`` as hashed: UTC, microseconds, fixed width, e.g.
    ``2026-09-29T07:48:13.921000Z``.

    A naive value is UTC: SQLite (test harness) stores the UTC wall clock
    without an offset and returns it naive; Postgres ``timestamptz``
    comes back timezone-aware, possibly in another zone.
    """
    return _as_utc(value).replace(tzinfo=None).isoformat(timespec="microseconds") + "Z"


def _as_utc(value: datetime) -> datetime:
    """``value`` as an aware UTC datetime; a naive one is UTC already."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _compute_hash_v2(prev_hash: str, event_type: str, occurred_at: datetime, canonical: str) -> str:
    r"""Recipe 2: SHA-256, as lowercase hex, of the UTF-8 bytes of
    ``"v2\n" + prev_hash + "\n" + event_type + "\n" + occurred_at +
    "\n" + canonical_payload``, with ``occurred_at`` formatted by
    ``_canonical_timestamp``.

    A message this code writes holds exactly four newlines, the
    separators: ``prev_hash`` is 64 hex chars, ``event_type`` passes
    ``_VALID_EVENT_TYPE``, the timestamp has a fixed format, and
    ``_canonical_payload`` escapes every newline. Any other field values
    either split differently or add a newline, so they cannot produce the
    same bytes. The leading ``v2`` can never start a recipe-1 input,
    which begins with 64 hex chars.

    The same value in Postgres alone (``VERIFY_CHAIN_SQL`` is the
    full-chain query)::

        encode(sha256(convert_to('v2' || chr(10) || prev_hash || chr(10) ||
            event_type || chr(10) || to_char(occurred_at AT TIME ZONE 'UTC',
            'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') || chr(10) || payload_json,
            'UTF8')), 'hex')
    """
    message = "\n".join(("v2", prev_hash, event_type, _canonical_timestamp(occurred_at), canonical))
    return hashlib.sha256(message.encode("utf-8")).hexdigest()


def _recompute_hash(row: AuditEvent) -> str | None:
    """The hash ``row`` should carry under the recipe its ``hash_version``
    names; ``None`` for an unknown version, which never matches."""
    if row.hash_version == 1:
        return _compute_hash(row.prev_hash, row.payload_json)
    if row.hash_version == 2:
        return _compute_hash_v2(row.prev_hash, row.event_type, row.occurred_at, row.payload_json)
    return None


async def record_event(
    event_type: str,
    *,
    actor_user_id: uuid.UUID | None = None,
    payload: Mapping[str, Any] | None = None,
    db: AsyncSession | None = None,
) -> None:
    """Append one entry to the audit log; chain it to the previous row.

    No client IP address is recorded — there is deliberately no
    parameter for one (decided 2026-09-28; guarded by
    ``tests/test_audit_no_ip.py``).

    Behaviour:

    - ``event_type`` failing the safe-key pattern: log + no-op
      (or raise ``AuditWriteError`` under ``audit_fail_closed``).
    - ``db is None`` and ``AsyncSessionLocal is None`` (Community
      Edition without DATABASE_URL): no-op. Audit logging is a
      Compliance-Edition feature; Community deployments don't
      need it and don't have the table.
    - Otherwise: open a fresh ``AsyncSession``, read the most recent
      row's ``record_hash``, compute the next hash, INSERT.
    - Errors are swallowed and logged at WARNING. With
      ``settings.audit_fail_closed = True`` the swallowed error is
      re-raised as ``AuditWriteError`` so the caller can fail the
      whole operation (Compliance-Edition default).

    This function is fire-and-forget by default; the request path can
    `await` it without worrying about exceptions, and Compliance
    deployments opt into the strict variant by flipping the env-var.
    """
    if not isinstance(event_type, str) or not _VALID_EVENT_TYPE.fullmatch(event_type):
        safe_repr = repr(event_type)[:120] if event_type is not None else "None"
        logger.warning("audit: rejected invalid event_type=%s", safe_repr)
        if settings.audit_fail_closed:
            raise AuditWriteError(f"invalid event_type: {safe_repr}")
        return

    canonical = _canonical_payload(payload)

    if db is not None:
        # Test path: caller owns the session.
        await _do_record(db, event_type, actor_user_id, canonical)
        return

    if AsyncSessionLocal is None:
        # Community Edition with no DATABASE_URL — nothing to record to.
        # Compliance Edition wires DATABASE_URL by definition; the
        # fail-closed branch below catches misconfiguration where
        # AUDIT_FAIL_CLOSED is on without a DB.
        if settings.audit_fail_closed:
            raise AuditWriteError("audit_fail_closed=true requires DATABASE_URL; cannot append")
        return

    try:
        async with AsyncSessionLocal() as session:
            await _do_record(session, event_type, actor_user_id, canonical)
    except AuditWriteError:
        raise
    except Exception:
        logger.warning("audit: session-open failed for event_type=%s", event_type, exc_info=True)
        if settings.audit_fail_closed:
            raise AuditWriteError(f"audit write failed for event_type={event_type}")


async def _do_record(
    db: AsyncSession,
    event_type: str,
    actor_user_id: uuid.UUID | None,
    canonical: str,
) -> bool:
    """Read the chain head, compute the new hash, INSERT; return whether
    the row was committed. A failure rolls back the whole transaction.

    Held under ``_chain_lock`` so two concurrent recorders inside the
    same process never see the same prev_hash. Cross-process safety is
    provided by the UNIQUE constraint on ``record_hash``: a duplicate
    INSERT raises IntegrityError and the second writer falls into the
    error branch (logged, retried-on-next-event).
    """
    async with _chain_lock:
        try:
            stmt = select(AuditEvent.record_hash).order_by(AuditEvent.id.desc()).limit(1)
            result = await db.execute(stmt)
            prev = result.scalar_one_or_none()
            prev_hash = prev if prev is not None else GENESIS_PREV_HASH

            # Stamped here, not by the column's server default: the hash
            # covers it, so the value must be known before the INSERT.
            occurred_at = datetime.now(timezone.utc)
            record_hash = _compute_hash_v2(prev_hash, event_type, occurred_at, canonical)
            row = AuditEvent(
                occurred_at=occurred_at,
                event_type=event_type,
                actor_user_id=actor_user_id,
                payload_json=canonical,
                prev_hash=prev_hash,
                record_hash=record_hash,
                hash_version=HASH_VERSION,
            )
            db.add(row)
            await db.commit()
        except Exception:
            logger.warning("audit: insert failed for event_type=%s", event_type, exc_info=True)
            try:
                await db.rollback()
            except Exception:
                pass
            if settings.audit_fail_closed:
                raise AuditWriteError(f"audit insert failed for event_type={event_type}")
            return False
    return True


async def delete_expired_events(db: AsyncSession | None = None) -> int:
    """Delete the entries older than ``RETENTION_YEARS``; return how many.

    ``app/main.py`` runs it at start-up and then once a day. It looks at
    the expired entries at the start of the chain, up to the first one
    that has not expired (an expired entry written after a younger one,
    because the clock went back, waits for a later run), keeps the newest
    of them as the new start and deletes the ones before it. The entries
    left form one unbroken chain whose oldest entry is older than three
    years, which ``_vouched_start`` relies on; it goes at the next run
    that finds a younger expired entry. In the same transaction a
    ``RETENTION_EVENT`` entry records the number deleted and the hash the
    kept entry links to (``RETENTION_LINK_KEY``). If that entry can't be
    written, nothing is deleted.

    ``db is None`` opens its own session, like ``record_event``; without
    a database (Community Edition) there is nothing to delete.
    """
    if db is not None:
        return await _delete_expired(db)
    if AsyncSessionLocal is None:
        return 0
    async with AsyncSessionLocal() as session:
        return await _delete_expired(session)


async def _delete_expired(db: AsyncSession) -> int:
    cutoff = await _retention_cutoff(db)
    first_kept = (
        select(func.min(AuditEvent.id)).where(AuditEvent.occurred_at >= cutoff).scalar_subquery()
    )
    newest_expired = (
        await db.execute(
            select(AuditEvent.id, AuditEvent.prev_hash)
            .where(AuditEvent.occurred_at < cutoff)
            .where(or_(first_kept.is_(None), AuditEvent.id < first_kept))
            .order_by(AuditEvent.id.desc())
            .limit(1)
        )
    ).first()
    if newest_expired is None:
        return 0
    deleted = (
        await db.execute(
            delete(AuditEvent).where(AuditEvent.id < newest_expired.id),
            execution_options={"synchronize_session": False},
        )
    ).rowcount
    if not deleted:
        return 0  # nothing before it, or a run in another process was first
    payload = {"deleted": deleted, RETENTION_LINK_KEY: newest_expired.prev_hash}
    if not await _do_record(db, RETENTION_EVENT, None, _canonical_payload(payload)):
        # Rolled back, the deletion with it. Logged as an error: a run that
        # keeps failing leaves entries past the period in the privacy notice.
        logger.error("audit: retention run rolled back; its record could not be written")
        return 0
    logger.info("audit: deleted %d entries older than %d years", deleted, RETENTION_YEARS)
    return deleted


async def _retention_cutoff(db: AsyncSession) -> datetime:
    """``RETENTION_YEARS`` calendar years before now; older entries have
    expired. On Postgres from this transaction's ``now()``, the moment
    migration 015's trigger measures from, so the trigger lets through
    every row ``delete_expired_events`` picks. Elsewhere (the SQLite test
    harness) from Python's clock."""
    if db.get_bind().dialect.name == "postgresql":
        return await db.scalar(
            text("SELECT now() - make_interval(years => :years)"), {"years": RETENTION_YEARS}
        )
    now = datetime.now(timezone.utc)
    try:
        return now.replace(year=now.year - RETENTION_YEARS)
    except ValueError:  # 29 February goes back to 28 February, as in Postgres
        return now.replace(year=now.year - RETENTION_YEARS, day=28)


async def _deletion_records(db: AsyncSession) -> dict[str, list[datetime]]:
    """When each ``RETENTION_EVENT`` entry was written, by the hash it
    names (``_named_link``)."""
    rows = await db.execute(
        select(AuditEvent.payload_json, AuditEvent.occurred_at).where(
            AuditEvent.event_type == RETENTION_EVENT
        )
    )
    records: dict[str, list[datetime]] = {}
    for payload, written in rows:
        link = _named_link(payload)
        if link is not None:
            records.setdefault(link, []).append(_as_utc(written))
    return records


def _named_link(payload: str) -> str | None:
    """The hash a deletion record names, or ``None``: by the rules
    ``VERIFY_CHAIN_SQL`` applies, the payload is at most
    ``RETENTION_RECORD_MAX_LENGTH`` characters, holds no backslash, is
    valid JSON (no NaN or Infinity) and an object with a string under
    ``RETENTION_LINK_KEY``."""
    if len(payload) > RETENTION_RECORD_MAX_LENGTH or "\\" in payload:
        return None
    try:
        named = json.loads(payload, parse_constant=_reject_json_constant)
    except ValueError:
        return None
    link = named.get(RETENTION_LINK_KEY) if isinstance(named, dict) else None
    return link if isinstance(link, str) else None


def _reject_json_constant(name: str) -> None:
    """NaN and Infinity: Python reads them, Postgres JSON does not."""
    raise ValueError(f"not JSON: {name}")


def _vouched_start(row: AuditEvent, records: dict[str, list[datetime]]) -> bool:
    """Whether the oldest row may link to a deleted entry: a deletion
    record names its ``prev_hash``, was written no later than now, and
    is more than ``RETENTION_MIN_AGE`` younger than the row."""
    now = datetime.now(timezone.utc)
    started = _as_utc(row.occurred_at)
    return any(
        written <= now and started < written - RETENTION_MIN_AGE
        for written in records.get(row.prev_hash, ())
    )


# ``verify_chain`` in plain Postgres SQL: the id of the first broken row,
# or no row. ``IS DISTINCT FROM``, not ``<>``: an unknown hash_version
# makes the CASE NULL, and ``<>`` would let that row through. The oldest
# row starts at the genesis sentinel or where a deletion record vouches
# for it, as in ``_vouched_start``: 26256 hours are ``RETENTION_MIN_AGE``
# (hours, because day steps would follow the session's daylight-saving
# shifts), and a payload names only by ``_named_link``'s rules. NOT
# EXISTS, unlike NOT IN, cannot turn NULL and pass a row unchecked. It
# takes no parameters and has no backslashes, so it pastes into psql as
# it stands (Postgres 16 or later, for pg_input_is_valid).
VERIFY_CHAIN_SQL = """
SELECT id FROM (
    SELECT *, lag(record_hash) OVER (ORDER BY id) AS expected_prev
    FROM audit_events
) AS chain
WHERE (prev_hash IS DISTINCT FROM coalesce(expected_prev, repeat('0', 64))
       AND (expected_prev IS NOT NULL OR NOT EXISTS (
           SELECT 1 FROM audit_events AS deletion
           WHERE deletion.event_type = 'audit.retention.deleted'
             AND deletion.occurred_at <= now()
             AND chain.occurred_at < deletion.occurred_at - interval '26256 hours'
             AND CASE WHEN length(deletion.payload_json) > 200
                        OR position(chr(92) in deletion.payload_json) > 0 THEN NULL
                      WHEN pg_input_is_valid(deletion.payload_json, 'jsonb')
                      THEN deletion.payload_json::jsonb -> 'last_deleted_hash' END
                 = to_jsonb(chain.prev_hash))))
   OR record_hash IS DISTINCT FROM CASE hash_version
      WHEN 1 THEN encode(sha256(convert_to(prev_hash || payload_json, 'UTF8')), 'hex')
      WHEN 2 THEN encode(sha256(convert_to(
          'v2' || chr(10) || prev_hash || chr(10) || event_type || chr(10)
          || to_char(occurred_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"')
          || chr(10) || payload_json, 'UTF8')), 'hex')
      END
ORDER BY id
LIMIT 1
"""


async def verify_chain(
    db: AsyncSession,
    *,
    start_id: int | None = None,
    limit: int | None = None,
) -> int | None:
    """Return the id of the first row whose recorded hash does not
    match a recomputed hash, or ``None`` if the chain is intact.

    Reads in ascending id order; checks each row's ``prev_hash``
    against the previous row's ``record_hash`` (the oldest row's against
    the genesis sentinel, or ``_vouched_start``),
    and recomputes the hash with the recipe the row's ``hash_version``
    names against the stored ``record_hash``. Either mismatch — or an
    unknown ``hash_version`` — is a tamper signal. ``VERIFY_CHAIN_SQL``
    is the same full-chain check in plain Postgres SQL, for a SQL dump.

    ``start_id`` and ``limit`` let an admin verify slices of a long
    chain incrementally rather than scanning the whole table at once.
    """
    stmt = select(AuditEvent).order_by(AuditEvent.id.asc())
    if start_id is not None:
        stmt = stmt.where(AuditEvent.id >= start_id)
    if limit is not None:
        stmt = stmt.limit(limit)
    result = await db.execute(stmt)
    # Read after the rows, so a retention run that commits in between
    # rarely leaves the oldest row read without its record.
    records = await _deletion_records(db) if start_id is None else {}

    expected_prev = GENESIS_PREV_HASH
    is_first = True
    async for row in _aiter_rows(result):
        if is_first:
            # Only the very first row of the table must start the chain:
            # at the genesis sentinel or, after expired entries were
            # deleted, where a deletion record vouches for it. A
            # partial-range verification (start_id > 1) accepts whatever
            # prev_hash the first inspected row references; the caller
            # is responsible for chaining ranges together if they want
            # full coverage.
            if (
                start_id is None
                and row.prev_hash != GENESIS_PREV_HASH
                and not _vouched_start(row, records)
            ):
                return row.id
        elif row.prev_hash != expected_prev:
            return row.id

        if _recompute_hash(row) != row.record_hash:
            return row.id

        expected_prev = row.record_hash
        is_first = False

    return None


async def _aiter_rows(result):
    """Yield SQLAlchemy result rows one at a time.

    ``result.scalars()`` would materialise all rows in memory;
    ``__aiter__`` over the result keeps the verification loop
    streaming, which matters for long chains. Wrapped in this helper
    so the caller doesn't have to know about ``.scalars()`` vs
    ``.scalar_one()`` semantics.
    """
    for obj in result.scalars():
        yield obj


async def chain_length(db: AsyncSession) -> int:
    """Total number of rows in the audit log. Used by the admin
    cockpit's overview card and by ``verify_chain`` callers who want
    to size their slicing."""
    result = await db.execute(text("SELECT COUNT(*) FROM audit_events"))
    return int(result.scalar() or 0)
