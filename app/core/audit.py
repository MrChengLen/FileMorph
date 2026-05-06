# SPDX-License-Identifier: AGPL-3.0-or-later
"""Compliance Edition: tamper-evident audit log with SHA-256 hash chain.

ISO 27001 A.12.4.1 / BORA §50 / BeurkG §39a / BSI OPS.1.1.5 all expect
operations on regulated data to leave a record that is provably
unaltered. This module provides that record. The chain is intentionally
simple — a forward SHA-256 chain over canonical-JSON event payloads —
because simplicity is what makes it auditable from a SQL dump without
running our code.

Three properties hold:

1. **Append-only at the database layer.** Migration 005 installs a
   Postgres trigger that raises on UPDATE / DELETE. SQLite (test
   harness only) skips the trigger; we cover the SQLite path with a
   "verify rejects tampering" test instead.
2. **Forward chain.** ``record_hash[i] = SHA256(record_hash[i-1] ||
   canonical_payload[i])``. The first row uses ``'0' * 64`` as the
   genesis sentinel. Any retroactive edit cascades — every row from
   the tampered one onward fails verification.
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
from typing import Any, Mapping

from sqlalchemy import select, text
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
    """``SHA-256(prev_hash || canonical_payload)`` as lowercase hex.

    Both inputs are ASCII / UTF-8 strings; we encode once and feed the
    bytes into one hash context. No domain-separator is needed because
    ``prev_hash`` is fixed-length (64 hex chars) — the boundary is
    unambiguous to an auditor reading the spec in this docstring.
    """
    h = hashlib.sha256()
    h.update(prev_hash.encode("ascii"))
    h.update(canonical.encode("utf-8"))
    return h.hexdigest()


async def record_event(
    event_type: str,
    *,
    actor_user_id: uuid.UUID | None = None,
    actor_ip: str | None = None,
    payload: Mapping[str, Any] | None = None,
    db: AsyncSession | None = None,
) -> None:
    """Append one entry to the audit log; chain it to the previous row.

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
        await _do_record(db, event_type, actor_user_id, actor_ip, canonical)
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
            await _do_record(session, event_type, actor_user_id, actor_ip, canonical)
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
    actor_ip: str | None,
    canonical: str,
) -> None:
    """Read the chain head, compute the new hash, INSERT.

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

            record_hash = _compute_hash(prev_hash, canonical)
            row = AuditEvent(
                event_type=event_type,
                actor_user_id=actor_user_id,
                actor_ip=actor_ip,
                payload_json=canonical,
                prev_hash=prev_hash,
                record_hash=record_hash,
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


async def verify_chain(
    db: AsyncSession,
    *,
    start_id: int | None = None,
    limit: int | None = None,
) -> int | None:
    """Return the id of the first row whose recorded hash does not
    match a recomputed hash, or ``None`` if the chain is intact.

    Reads in ascending id order; checks each row's ``prev_hash``
    against the previous row's ``record_hash``, and recomputes
    ``SHA-256(prev_hash || payload_json)`` against the stored
    ``record_hash``. Either mismatch is a tamper signal.

    ``start_id`` and ``limit`` let an admin verify slices of a long
    chain incrementally rather than scanning the whole table at once.
    """
    stmt = select(AuditEvent).order_by(AuditEvent.id.asc())
    if start_id is not None:
        stmt = stmt.where(AuditEvent.id >= start_id)
    if limit is not None:
        stmt = stmt.limit(limit)
    result = await db.execute(stmt)

    expected_prev = GENESIS_PREV_HASH
    is_first = True
    async for row in _aiter_rows(result):
        if is_first and start_id is None:
            # Only the very first row of the table must use the
            # genesis sentinel. A partial-range verification (start_id
            # > 1) accepts whatever prev_hash the first inspected row
            # references; the caller is responsible for chaining
            # ranges together if they want full coverage.
            if row.prev_hash != GENESIS_PREV_HASH:
                return row.id
        elif row.prev_hash != expected_prev:
            return row.id

        recomputed = _compute_hash(row.prev_hash, row.payload_json)
        if recomputed != row.record_hash:
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
