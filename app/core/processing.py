# SPDX-License-Identifier: AGPL-3.0-or-later
"""Upload-processing primitives shared by every route that accepts a file.

Three helpers live here:

- ``BLOCKED_MAGIC`` — magic-byte deny-list. PE, ELF, shell, and PHP
  prefixes are rejected before any decoder runs (NEU-A magic-byte
  guard / threat-model § Tampering).
- ``sha256_file(path)`` — streaming SHA-256 used for the
  ``X-Output-SHA256`` integrity header (NEU-B.2). Synchronous; call
  through ``asyncio.to_thread`` from async routes.
- ``actor_id(request, user)`` — stable identity used by the per-actor
  concurrency cap (NEU-D.1) and, soon, the monthly call-count quota
  (PR-M). User-id when authenticated, IP otherwise; the API-key value
  itself is never exposed here.

The duplicated copies that used to live in ``convert.py`` and
``compress.py`` are removed by PR-R2. PR-M will be the third caller —
the comments in compress.py already noted "promote when a third caller
appears", and that moment is here.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import Request

from app.db.models import User

BLOCKED_MAGIC: list[bytes] = [b"MZ", b"\x7fELF", b"#!/", b"<?ph"]


def sha256_file(path: Path, *, chunk_size: int = 64 * 1024) -> str:
    """Streaming SHA-256 over an on-disk file, returned as lowercase hex.

    Used for the ``X-Output-SHA256`` response header (NEU-B.2). Runs
    synchronously — call through ``asyncio.to_thread`` from an async
    route so the read does not block the event loop. ``chunk_size`` is
    64 KiB: enough to keep syscall overhead irrelevant, small enough
    that a 2 GB output costs no measurable RAM.
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def actor_id(request: Request, user: User | None) -> str:
    """Stable identity for per-actor caps (concurrency, quotas).

    Authenticated callers key on the user UUID — the same person across
    IPs, the same cap. Anonymous callers fall back to the remote IP,
    which is the only stable handle we have without making them
    register. The ``X-API-Key`` value itself is never used as the key
    (it's a secret; we don't want it in any log extra dict, even
    hashed)."""
    if user is not None:
        return f"user:{user.id}"
    return f"ip:{request.client.host if request.client else 'unknown'}"
