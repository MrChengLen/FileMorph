# SPDX-License-Identifier: AGPL-3.0-or-later
"""H7 — Token-type discrimination matrix.

A FileMorph JWT carries a ``type`` claim with four possible values:
``access`` (15 min, full API), ``refresh`` (30 d, mint-new-access),
``reset`` (30 min, password-reset only), ``verify`` (7 d, email-verify
only). Every decoder enforces that the token it receives carries the
expected ``type`` — a refresh token, for example, must never be
accepted on an access-only route, and a verification token must never
double as a password-reset token.

The tokens here carry every type's claims (``phv``, ``eat``, ``role``), so
the ``type`` claim is all a decoder has to refuse them by. With real tokens
half the matrix would pass without any type check: a verify token has no
``phv`` and a reset token no ``eat``, so the missing-claim check refuses them
first.

Why direct decoder calls (no HTTP):
  - The discriminator lives in the decoder, not in the route. A unit
    test asserts the security boundary at its source and runs in
    milliseconds.
  - The HTTP layer's response shape (401 vs 400) is already covered by
    the existing email-verification + password-reset tests; we don't
    duplicate that.
"""

from __future__ import annotations

import datetime as dt

import jwt
import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.core.tokens import (
    ALGORITHM,
    _encode_claims,
    decode_email_verify_token,
    decode_password_reset_token,
    decode_session_token,
)

_TOKEN_TYPES = ("access", "refresh", "reset", "verify")


def _token(token_type: str) -> str:
    """A signed, valid token of ``token_type`` that also carries every other
    type's claims."""
    claims = {
        "sub": "user-id-1",
        "exp": dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5),
        "type": token_type,
        "role": "user",
        "phv": "phv-1",
        "eat": "user@example.com",
    }
    return jwt.encode(_encode_claims(claims), settings.jwt_secret, algorithm=ALGORITHM)


_DECODERS = {
    "access": lambda token: decode_session_token(token, expected_type="access"),
    "refresh": lambda token: decode_session_token(token, expected_type="refresh"),
    "reset": decode_password_reset_token,
    "verify": decode_email_verify_token,
}

# Every (issued_type, decoded_as_type) combination where the two differ.
_MISMATCH_PAIRS = [
    (issued, decoded) for issued in _TOKEN_TYPES for decoded in _TOKEN_TYPES if issued != decoded
]


@pytest.mark.parametrize("issued_type,decoded_as_type", _MISMATCH_PAIRS)
def test_decoder_rejects_wrong_token_type(issued_type: str, decoded_as_type: str) -> None:
    """Every cross-type decode raises HTTPException. A missing
    discriminator would silently let one token type act as another —
    e.g., a long-lived refresh token used to call a protected access
    route, or a still-valid verify token used to bypass the password
    reset flow."""
    with pytest.raises(HTTPException):
        _DECODERS[decoded_as_type](_token(issued_type))


@pytest.mark.parametrize("token_type", _TOKEN_TYPES)
def test_decoder_accepts_its_own_type_with_every_claim(token_type: str) -> None:
    """The extra claims alone don't get a token refused, so every refusal
    above comes from the type check — and a regression that broke every
    decoder can't pass the matrix by raising on every input."""
    _DECODERS[token_type](_token(token_type))  # must not raise
