# SPDX-License-Identifier: AGPL-3.0-or-later
"""Password hashing primitives (bcrypt).

JWT issuance, decoding, and the reset-token ``phv`` fingerprint live in
``app/core/tokens.py``. Keeping bcrypt isolated here means a future
argon2 migration touches one file and doesn't drag JWT code along."""

from __future__ import annotations

from uuid import uuid4

import bcrypt as _bcrypt


def hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt(rounds=12)).decode()


def deleted_password_sentinel() -> str:
    """A non-bcrypt ``password_hash`` value for the paid-path ("tax-retained")
    account delete (``docs/gdpr-account-deletion-design.md`` § 5.B).

    The ``password_hash`` column is ``NOT NULL``, so a tax-retained row can't
    blank it — but the row must never authenticate again. This value is a
    well-known prefix plus a random suffix; it is not a valid bcrypt string,
    so :func:`verify_password` returns ``False`` for any plaintext (via its
    ``ValueError`` guard) without raising. The random suffix means two
    deleted rows never collide on the same hash. ``is_active=False`` and the
    ``deleted_at IS NOT NULL`` guards already block login one layer up; this
    is defence-in-depth."""
    return f"DELETED:{uuid4().hex}"


def verify_password(plain: str, hashed: str) -> bool:
    """Compare a plaintext password against a stored bcrypt hash.

    Returns False on any mismatch *and* on a malformed stored hash —
    bcrypt raises ``ValueError("Invalid salt")`` when the stored hash
    isn't a well-formed bcrypt string, which would otherwise surface as
    a 500 from any path that calls this on a corrupted ``password_hash``
    column (login, reset, delete-account). A False result is the right
    semantics: no plaintext password matches a corrupted hash."""
    try:
        return _bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False
