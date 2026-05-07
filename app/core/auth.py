# SPDX-License-Identifier: AGPL-3.0-or-later
"""Password hashing primitives (bcrypt).

JWT issuance, decoding, and the reset-token ``phv`` fingerprint live in
``app/core/tokens.py``. Keeping bcrypt isolated here means a future
argon2 migration touches one file and doesn't drag JWT code along."""

from __future__ import annotations

import bcrypt as _bcrypt


def hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt(rounds=12)).decode()


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
