# SPDX-License-Identifier: AGPL-3.0-or-later
"""JWT token primitives — issuance, decoding, and the password-hash-version
fingerprint that binds reset tokens to a specific stored password.

Four token types share the JWT secret and are discriminated only by the
``type`` claim:

- ``access``  — short-lived bearer credential (15 min)
- ``refresh`` — rotating session token (30 d)
- ``reset``   — single-use password-reset link (30 min, bound to ``phv``)
- ``verify``  — email-verification link (7 d, bound to ``eat``)

Splitting these out of ``app/core/auth.py`` keeps password hashing
(``bcrypt``) physically separate from JWT issuance, and gives the upcoming
``iss``/``aud``-claim work (PR-J) a single file to amend.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from jose import JWTError, jwt

from app.core.config import settings

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 30
PASSWORD_RESET_TOKEN_EXPIRE_MINUTES = 30
EMAIL_VERIFY_TOKEN_EXPIRE_DAYS = 7


# ── Access / refresh tokens ───────────────────────────────────────────────────


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


# ── Email-verification tokens ─────────────────────────────────────────────────
#
# A verify token is a JWT bound to the user's email *at issuance time*
# (``eat`` claim — "email at token"). On verify, the route compares the
# claim against the current user.email; a mismatch means the user has
# rotated their email since the token was issued, so the token is
# silently invalidated. This avoids a per-token DB row while keeping
# replay-after-rotation safe.


def create_email_verify_token(
    subject: str,
    email_at_issuance: str,
    ttl_days: int = EMAIL_VERIFY_TOKEN_EXPIRE_DAYS,
) -> str:
    """Mint a JWT for the email-verification link.

    ``email_at_issuance`` is the user's email address at the moment the
    token is created. Stored as the ``eat`` claim and re-checked on
    verification: if the user changed their email after the link was
    sent, the old link no longer auto-verifies the new address."""
    expire = datetime.now(timezone.utc) + timedelta(days=ttl_days)
    return jwt.encode(
        {
            "sub": subject,
            "exp": expire,
            "type": "verify",
            "eat": email_at_issuance,
        },
        settings.jwt_secret,
        algorithm=ALGORITHM,
    )


def decode_email_verify_token(token: str) -> tuple[str, str]:
    """Return ``(user_id, email_at_issuance)``. Raises HTTP 400 on any
    issue — malformed, wrong type, expired, or missing claims — so the
    caller emits a user-friendly "invalid or expired" message without
    branching on the exact cause (and without leaking which token type
    a malformed JWT actually was)."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification link is invalid or has expired.",
        )
    if payload.get("type") != "verify":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification link is invalid or has expired.",
        )
    sub = payload.get("sub")
    eat = payload.get("eat")
    if not sub or not eat:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification link is invalid or has expired.",
        )
    return sub, eat
