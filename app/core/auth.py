# SPDX-License-Identifier: AGPL-3.0-or-later
"""JWT authentication utilities."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import bcrypt as _bcrypt
from fastapi import HTTPException, status
from jose import JWTError, jwt

from app.core.config import settings

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 30
PASSWORD_RESET_TOKEN_EXPIRE_MINUTES = 30


def hash_password(password: str) -> str:
    return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return _bcrypt.checkpw(plain.encode(), hashed.encode())


def create_access_token(subject: str, role: str = "user") -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    return jwt.encode(
        {"sub": subject, "exp": expire, "type": "access", "role": role},
        settings.jwt_secret,
        algorithm=ALGORITHM,
    )


def create_refresh_token(subject: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    return jwt.encode(
        {"sub": subject, "exp": expire, "type": "refresh"}, settings.jwt_secret, algorithm=ALGORITHM
    )


def decode_token(token: str, expected_type: str = "access") -> str:
    """Return the subject claim. Use `decode_token_full` if the role claim is needed."""
    sub, _role = decode_token_full(token, expected_type=expected_type)
    return sub


def decode_token_full(token: str, expected_type: str = "access") -> tuple[str, str]:
    """Return ``(subject, role)``. The role defaults to ``"user"`` for legacy tokens."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
        if payload.get("type") != expected_type:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type."
            )
        sub: str | None = payload.get("sub")
        if not sub:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token.")
        role: str = payload.get("role", "user")
        return sub, role
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token."
        )


# ── Password-reset tokens ─────────────────────────────────────────────────────
#
# A reset token is a short-lived JWT bound to a *version* of the user's
# current password hash. Changing the password — either via a successful
# reset or an admin intervention — rotates the version and silently
# invalidates every outstanding reset token. No DB table, no cleanup job,
# and single-use is implicit.


def password_hash_version(password_hash: str) -> str:
    """Return a short stable fingerprint of a password hash.

    We take the SHA-256 of the first 16 characters of the hash so a single
    reset token cannot be replayed after a successful password change. The
    bcrypt string starts with ``$2b$12$`` plus a 22-char salt; these 16
    chars are enough entropy to diverge on any new hash.

    If we ever migrate to argon2 the prefix shape changes — bump the reset
    JWT ``type`` claim (e.g. ``reset`` → ``reset_v2``) at the same time so
    in-flight tokens from the old scheme are rejected, then update this
    function.
    """
    return hashlib.sha256(password_hash[:16].encode()).hexdigest()


def create_password_reset_token(
    subject: str, phv: str, ttl_minutes: int = PASSWORD_RESET_TOKEN_EXPIRE_MINUTES
) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)
    return jwt.encode(
        {"sub": subject, "exp": expire, "type": "reset", "phv": phv},
        settings.jwt_secret,
        algorithm=ALGORITHM,
    )


def decode_password_reset_token(token: str) -> tuple[str, str]:
    """Return ``(user_id, phv)`` from a reset JWT. Raises HTTP 400 on any
    issue — malformed, wrong type, expired, or missing claims — so the
    caller returns a user-friendly "invalid or expired" message without
    branching on the exact cause."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset link is invalid or has expired.",
        )
    if payload.get("type") != "reset":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset link is invalid or has expired.",
        )
    sub = payload.get("sub")
    phv = payload.get("phv")
    if not sub or not phv:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Reset link is invalid or has expired.",
        )
    return sub, phv
