# SPDX-License-Identifier: AGPL-3.0-or-later
"""H7 — Token-type discrimination matrix.

A FileMorph JWT carries a ``type`` claim with four possible values:
``access`` (15 min, full API), ``refresh`` (30 d, mint-new-access),
``reset`` (30 min, password-reset only), ``verify`` (7 d, email-verify
only). Every decoder enforces that the token it receives carries the
expected ``type`` — a refresh token, for example, must never be
accepted on an access-only route, and a verification token must never
double as a password-reset token.

The existing tests cover individual cases (e.g.,
``test_email_verification.py::test_token_rejects_wrong_type``). This
module makes the matrix explicit and parametrised so a missing
discriminator surfaces immediately.

Why direct decoder calls (no HTTP):
  - The discriminator lives in the decoder, not in the route. A unit
    test asserts the security boundary at its source and runs in
    milliseconds.
  - The HTTP layer's response shape (401 vs 400) is already covered by
    the existing email-verification + password-reset tests; we don't
    duplicate that.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core.tokens import (
    create_access_token,
    create_email_verify_token,
    create_password_reset_token,
    create_refresh_token,
    decode_email_verify_token,
    decode_password_reset_token,
    decode_token_full,
    password_hash_version,
)


# Each entry is (token-builder-name, decoder, decoder-arg-marshaller).
# The decoder is the *correct* call for that token type; we then invoke
# every other decoder with the same token and assert it raises.

_TYPES: list[tuple[str, callable]] = [
    ("access", lambda: create_access_token("user-id-1", role="user")),
    ("refresh", lambda: create_refresh_token("user-id-1")),
    (
        "reset",
        lambda: create_password_reset_token(
            "user-id-1", password_hash_version("$2b$12$" + "a" * 22 + "...")
        ),
    ),
    ("verify", lambda: create_email_verify_token("user-id-1", "user@example.com")),
]


def _decode_as_access(token: str) -> None:
    decode_token_full(token, expected_type="access")


def _decode_as_refresh(token: str) -> None:
    decode_token_full(token, expected_type="refresh")


def _decode_as_reset(token: str) -> None:
    decode_password_reset_token(token)


def _decode_as_verify(token: str) -> None:
    decode_email_verify_token(token)


_DECODERS: dict[str, callable] = {
    "access": _decode_as_access,
    "refresh": _decode_as_refresh,
    "reset": _decode_as_reset,
    "verify": _decode_as_verify,
}


# Build the cross-pair matrix: every (issued_type, decoded_as_type)
# combination where the two differ should fail.
_MISMATCH_PAIRS = [
    (issued_type, decoded_type)
    for issued_type, _ in _TYPES
    for decoded_type in _DECODERS.keys()
    if issued_type != decoded_type
]


@pytest.mark.parametrize("issued_type,decoded_as_type", _MISMATCH_PAIRS)
def test_decoder_rejects_wrong_token_type(issued_type: str, decoded_as_type: str) -> None:
    """Every cross-type decode raises HTTPException. A missing
    discriminator would silently let one token type act as another —
    e.g., a long-lived refresh token used to call a protected access
    route, or a still-valid verify token used to bypass the password
    reset flow."""
    builder = dict(_TYPES)[issued_type]
    decoder = _DECODERS[decoded_as_type]
    token = builder()
    with pytest.raises(HTTPException):
        decoder(token)


@pytest.mark.parametrize("token_type", ["access", "refresh", "reset", "verify"])
def test_decoder_accepts_matching_token_type(token_type: str) -> None:
    """Sanity-check the parametrisation: each decoder *does* accept its
    own type. Without this, a regression that broke every decoder would
    pass the negative tests above by raising on every input."""
    builder = dict(_TYPES)[token_type]
    decoder = _DECODERS[token_type]
    token = builder()
    decoder(token)  # must not raise
