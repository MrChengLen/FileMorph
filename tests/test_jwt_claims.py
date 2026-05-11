# SPDX-License-Identifier: AGPL-3.0-or-later
"""PR-J Part A — RFC 7519 ``iss`` / ``aud`` claims on every JWT.

Every token FileMorph mints carries ``iss=settings.jwt_issuer`` and
``aud=settings.jwt_audience``. Every decode path validates them. This is
defense-in-depth: a token forged or replayed with the right HMAC secret
but the wrong issuer/audience (e.g. minted by a sibling FileMorph
deployment, or by another service that shares a leaked secret) is
rejected before any business logic runs.

These tests pin three properties for all four token types
(access, refresh, reset, verify):

1. The minted token actually contains the configured ``iss`` / ``aud``.
2. A token with a *wrong* ``aud`` is rejected (``jose`` raises
   ``JWTClaimsError`` → the decoder turns it into the type-appropriate
   HTTP error).
3. A token with a *wrong* ``iss`` is rejected.
4. A legacy token with **no** ``iss`` / ``aud`` is rejected (so a
   pre-PR-J token can't slip through after the upgrade).

We construct the "wrong" tokens by hand-encoding with ``jose.jwt`` and
the real secret — the signature is valid, only the claims differ — so
the test exercises exactly the validation step PR-J adds, not the
signature check that was already there.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from jose import jwt

from app.core.config import settings
from app.core.tokens import (
    ALGORITHM,
    create_access_token,
    create_email_verify_token,
    create_password_reset_token,
    create_refresh_token,
    decode_email_verify_token,
    decode_password_reset_token,
    decode_token,
)


def _decode_unverified(token: str) -> dict:
    """Read a token's claims without validating iss/aud — used only to
    assert what was minted, never as a production path."""
    return jwt.get_unverified_claims(token)


def _hand_mint(claims: dict) -> str:
    """Sign ``claims`` with the real secret. Used to build tokens whose
    signature is valid but whose iss/aud are wrong/missing."""
    base = {
        "sub": "user-123",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
        "type": "access",
        "role": "user",
    }
    return jwt.encode({**base, **claims}, settings.jwt_secret, algorithm=ALGORITHM)


# ── 1. Minted tokens carry the configured iss/aud ────────────────────────────


def test_access_token_carries_iss_and_aud():
    claims = _decode_unverified(create_access_token("user-1"))
    assert claims["iss"] == settings.jwt_issuer
    assert claims["aud"] == settings.jwt_audience


def test_refresh_token_carries_iss_and_aud():
    claims = _decode_unverified(create_refresh_token("user-1"))
    assert claims["iss"] == settings.jwt_issuer
    assert claims["aud"] == settings.jwt_audience


def test_reset_token_carries_iss_and_aud():
    claims = _decode_unverified(create_password_reset_token("user-1", "phv-abc"))
    assert claims["iss"] == settings.jwt_issuer
    assert claims["aud"] == settings.jwt_audience


def test_verify_token_carries_iss_and_aud():
    claims = _decode_unverified(create_email_verify_token("user-1", "a@example.com"))
    assert claims["iss"] == settings.jwt_issuer
    assert claims["aud"] == settings.jwt_audience


# ── 2. Round-trip still works (regression guard) ─────────────────────────────


def test_access_token_round_trips():
    assert decode_token(create_access_token("user-42")) == "user-42"


def test_refresh_token_round_trips():
    assert decode_token(create_refresh_token("user-42"), expected_type="refresh") == "user-42"


def test_reset_token_round_trips():
    sub, phv = decode_password_reset_token(create_password_reset_token("user-42", "phv-xyz"))
    assert sub == "user-42"
    assert phv == "phv-xyz"


def test_verify_token_round_trips():
    sub, eat = decode_email_verify_token(create_email_verify_token("user-42", "a@example.com"))
    assert sub == "user-42"
    assert eat == "a@example.com"


# ── 3. Wrong audience is rejected ────────────────────────────────────────────


def test_access_decoder_rejects_wrong_audience():
    bad = _hand_mint({"iss": settings.jwt_issuer, "aud": "some-other-service"})
    with pytest.raises(HTTPException) as exc:
        decode_token(bad)
    assert exc.value.status_code == 401


def test_reset_decoder_rejects_wrong_audience():
    bad = _hand_mint({"type": "reset", "phv": "phv-1", "iss": settings.jwt_issuer, "aud": "evil"})
    with pytest.raises(HTTPException) as exc:
        decode_password_reset_token(bad)
    assert exc.value.status_code == 400


def test_verify_decoder_rejects_wrong_audience():
    bad = _hand_mint(
        {"type": "verify", "eat": "a@example.com", "iss": settings.jwt_issuer, "aud": "evil"}
    )
    with pytest.raises(HTTPException) as exc:
        decode_email_verify_token(bad)
    assert exc.value.status_code == 400


# ── 4. Wrong issuer is rejected ──────────────────────────────────────────────


def test_access_decoder_rejects_wrong_issuer():
    bad = _hand_mint({"iss": "not-filemorph", "aud": settings.jwt_audience})
    with pytest.raises(HTTPException) as exc:
        decode_token(bad)
    assert exc.value.status_code == 401


def test_reset_decoder_rejects_wrong_issuer():
    bad = _hand_mint(
        {"type": "reset", "phv": "phv-1", "iss": "not-filemorph", "aud": settings.jwt_audience}
    )
    with pytest.raises(HTTPException) as exc:
        decode_password_reset_token(bad)
    assert exc.value.status_code == 400


# ── 5. Legacy token (no iss/aud at all) is rejected ──────────────────────────


def test_access_decoder_rejects_token_without_iss_or_aud():
    """A pre-PR-J token (signed, valid type, but no iss/aud) must not
    pass — jose raises because we asked for an audience and the token
    has none."""
    legacy = jwt.encode(
        {
            "sub": "user-1",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
            "type": "access",
            "role": "user",
        },
        settings.jwt_secret,
        algorithm=ALGORITHM,
    )
    with pytest.raises(HTTPException) as exc:
        decode_token(legacy)
    assert exc.value.status_code == 401


def test_reset_decoder_rejects_token_without_iss_or_aud():
    legacy = jwt.encode(
        {
            "sub": "user-1",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
            "type": "reset",
            "phv": "phv-1",
        },
        settings.jwt_secret,
        algorithm=ALGORITHM,
    )
    with pytest.raises(HTTPException) as exc:
        decode_password_reset_token(legacy)
    assert exc.value.status_code == 400
