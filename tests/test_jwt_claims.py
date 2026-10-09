# SPDX-License-Identifier: AGPL-3.0-or-later
"""PR-J Part A — RFC 7519 ``iss`` / ``aud`` claims on every JWT.

Every token FileMorph mints carries ``iss=settings.jwt_issuer`` and
``aud=settings.jwt_audience``. Every decode path validates them. This is
defense-in-depth: a token forged or replayed with the right HMAC secret
but the wrong issuer/audience (e.g. minted by a sibling FileMorph
deployment, or by another service that shares a leaked secret) is
rejected before any business logic runs.

These tests pin, across the four token types (access, refresh, reset,
verify):

1. The minted token actually contains the configured ``iss`` / ``aud``.
2. A token with a *wrong* ``aud`` is rejected (PyJWT raises
   ``InvalidAudienceError`` → the decoder turns it into the
   type-appropriate HTTP error).
3. A token with a *wrong* ``iss`` is rejected.
4. A legacy token with **no** ``iss`` / ``aud`` is rejected (so a
   pre-PR-J token can't slip through after the upgrade).
5. A token without ``exp``, ``iss`` or ``aud`` is rejected.
6. A token python-jose minted before the move to PyJWT still decodes.
7. A token longer than ``MAX_TOKEN_LENGTH`` or not ASCII is refused
   before PyJWT parses it.
8. Only HS256 is accepted.

We construct the "wrong" tokens by hand-encoding with PyJWT and the
real secret — the signature is valid, only the claims differ — so
the test exercises exactly the validation step PR-J adds, not the
signature check that was already there.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import partial

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException

from app.core.config import Settings, settings
from app.core.tokens import (
    ALGORITHM,
    MAX_TOKEN_LENGTH,
    create_access_token,
    create_email_verify_token,
    create_password_reset_token,
    create_refresh_token,
    decode_email_verify_token,
    decode_password_reset_token,
    decode_session_token,
    decode_token,
)


def _decode_unverified(token: str) -> dict:
    """Read a token's claims without validating iss/aud — used only to
    assert what was minted, never as a production path."""
    return jwt.decode(token, options={"verify_signature": False})


def _hand_mint(claims: dict, *, drop: str | None = None) -> str:
    """Sign ``claims`` with the real secret. Used to build tokens whose
    signature is valid but whose iss/aud are wrong/missing; ``drop`` leaves
    one claim out entirely."""
    base = {
        "sub": "user-123",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
        "type": "access",
        "role": "user",
        "phv": "phv-1",
    }
    payload = {**base, **claims}
    if drop:
        del payload[drop]
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)


# ── 1. Minted tokens carry the configured iss/aud ────────────────────────────


def test_access_token_carries_iss_and_aud():
    claims = _decode_unverified(create_access_token("user-1", phv="phv-1"))
    assert claims["iss"] == settings.jwt_issuer
    assert claims["aud"] == settings.jwt_audience


def test_refresh_token_carries_iss_and_aud():
    claims = _decode_unverified(create_refresh_token("user-1", phv="phv-1"))
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
    assert decode_token(create_access_token("user-42", phv="phv-1")) == "user-42"


def test_refresh_token_round_trips():
    assert (
        decode_token(create_refresh_token("user-42", phv="phv-1"), expected_type="refresh")
        == "user-42"
    )


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
    pass — ``_decode`` requires both claims, so PyJWT raises
    ``MissingRequiredClaimError``."""
    legacy = jwt.encode(
        {
            "sub": "user-1",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=10),
            "type": "access",
            "role": "user",
            "phv": "phv-1",
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


# Each decoder, with the claims its token type needs and the status it gives a
# token it refuses.
_DECODERS = [
    pytest.param({}, decode_token, 401, id="access"),
    pytest.param({"type": "reset"}, decode_password_reset_token, 400, id="reset"),
    pytest.param(
        {"type": "verify", "eat": "a@example.com"}, decode_email_verify_token, 400, id="verify"
    ),
]


# ── 6. exp, iss and aud are required ─────────────────────────────────────────


@pytest.mark.parametrize("claim", ["exp", "iss", "aud"])
@pytest.mark.parametrize(("claims", "decode", "status"), _DECODERS)
def test_decoders_reject_a_token_without_a_required_claim(claim, claims, decode, status):
    """python-jose let a token without ``aud`` or ``exp`` through, and one
    without ``exp`` never expired. Everything else about this token is right."""
    token = _hand_mint(
        {"iss": settings.jwt_issuer, "aud": settings.jwt_audience, **claims}, drop=claim
    )
    with pytest.raises(HTTPException) as exc:
        decode(token)
    assert exc.value.status_code == status


# ── 7. Tokens minted by python-jose still decode ─────────────────────────────
#
# Minted by app/core/tokens.py as it stood before the move to PyJWT (362cda0,
# python-jose 3.5.0), with its clock set to 2099-12-01 so that they don't
# expire, under the code defaults for JWT_SECRET, JWT_ISSUER and JWT_AUDIENCE.
# That secret is published in this repository and the Cloud Edition refuses to
# start with it (``jwt_secret_error``), so none of these is a credential.
_JOSE_ACCESS = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyLTEiLCJleHAiOjQwOTk3NjczMDAsInR5cGUiOiJhY2Nlc3MiLCJyb2xlIjoidXNlciIsInBodiI6InBodi0xIiwiaXNzIjoiZmlsZW1vcnBoIiwiYXVkIjoiZmlsZW1vcnBoLWFwaSJ9.Cdz1SodaKBcE_xwgi4JCrEXYRj6ywDdPo_WVSGjkhKw"  # gitleaks:allow
_JOSE_REFRESH = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyLTEiLCJleHAiOjQxMDIzNTg0MDAsInR5cGUiOiJyZWZyZXNoIiwicGh2IjoicGh2LTEiLCJpc3MiOiJmaWxlbW9ycGgiLCJhdWQiOiJmaWxlbW9ycGgtYXBpIn0.VJN48yCMIRmQ6QN670V6nz3nocDcmvPpceUVWw1LCSE"  # gitleaks:allow
_JOSE_RESET = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyLTEiLCJleHAiOjQwOTk3NjgyMDAsInR5cGUiOiJyZXNldCIsInBodiI6InBodi0xIiwiaXNzIjoiZmlsZW1vcnBoIiwiYXVkIjoiZmlsZW1vcnBoLWFwaSJ9.Eirp8oL5KkkA7QvHNNTeYRLETfs6qaq7-EunlwoecJY"  # gitleaks:allow
_JOSE_VERIFY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyLTEiLCJleHAiOjQxMDAzNzEyMDAsInR5cGUiOiJ2ZXJpZnkiLCJlYXQiOiJhQGV4YW1wbGUuY29tIiwiaXNzIjoiZmlsZW1vcnBoIiwiYXVkIjoiZmlsZW1vcnBoLWFwaSJ9.2V1TSqSs_EaWztqhDlE2KwAYeYpR0-MFzhlCWa2xQ6M"  # gitleaks:allow


@pytest.fixture
def code_default_jwt_settings(monkeypatch):
    """The settings the tokens above were minted under; a local .env may differ."""
    for name in ("jwt_secret", "jwt_issuer", "jwt_audience"):
        monkeypatch.setattr(settings, name, Settings.model_fields[name].default)


@pytest.mark.usefixtures("code_default_jwt_settings")
@pytest.mark.parametrize(
    ("token", "decode", "expected"),
    [
        pytest.param(_JOSE_ACCESS, decode_session_token, ("user-1", "phv-1"), id="access"),
        pytest.param(
            _JOSE_REFRESH,
            partial(decode_session_token, expected_type="refresh"),
            ("user-1", "phv-1"),
            id="refresh",
        ),
        pytest.param(_JOSE_RESET, decode_password_reset_token, ("user-1", "phv-1"), id="reset"),
        pytest.param(
            _JOSE_VERIFY, decode_email_verify_token, ("user-1", "a@example.com"), id="verify"
        ),
    ],
)
def test_tokens_minted_by_python_jose_still_decode(token, decode, expected):
    """The move to PyJWT keeps the token format (HS256, secret, claims), so
    signed-in sessions and the reset and verify links already sent stay valid."""
    assert decode(token) == expected


# ── 8. Oversized or non-ASCII tokens are refused before parsing ──────────────


def test_the_longest_minted_token_stays_far_below_the_length_limit():
    """A verify token for an address at the 254-byte maximum is the longest
    token FileMorph mints, and non-ASCII addresses (``EmailStr`` accepts
    them) make it longest: JSON writes each such character as a six-character
    escape."""
    address = "ü" * 32 + "@" + "ä" * 93 + ".de"  # 254 bytes in UTF-8
    assert len(create_email_verify_token("u" * 36, address)) < MAX_TOKEN_LENGTH // 2


@pytest.mark.parametrize(("claims", "decode", "status"), _DECODERS)
def test_decoders_refuse_a_token_over_the_length_limit(claims, decode, status):
    """Signed with the real secret and every claim right, so only the length
    check can refuse it."""
    pad = {"pad": "x" * MAX_TOKEN_LENGTH}
    token = _hand_mint({"iss": settings.jwt_issuer, "aud": settings.jwt_audience, **pad, **claims})
    with pytest.raises(HTTPException) as exc:
        decode(token)
    assert exc.value.status_code == status


@pytest.mark.parametrize(("claims", "decode", "status"), _DECODERS)
def test_decoders_refuse_a_token_that_is_not_ascii(claims, decode, status):
    """A lone surrogate made PyJWT raise ``UnicodeEncodeError``: a 500 on the
    refresh, reset and verify routes, which take the token from a JSON body."""
    token = _hand_mint({"iss": settings.jwt_issuer, "aud": settings.jwt_audience, **claims})
    with pytest.raises(HTTPException) as exc:
        decode(token + "\ud800")
    assert exc.value.status_code == status


# ── 9. Only HS256 is accepted ────────────────────────────────────────────────


@pytest.mark.parametrize("algorithm", ["none", "RS256"])
def test_access_decoder_accepts_hs256_only(algorithm):
    """The claims of a valid token, signed another way: ``none`` carries no
    signature, RS256 one made with a key of the caller's choosing."""
    claims = _decode_unverified(
        _hand_mint({"iss": settings.jwt_issuer, "aud": settings.jwt_audience})
    )
    key = None
    if algorithm == "RS256":
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(HTTPException) as exc:
        decode_token(jwt.encode(claims, key, algorithm=algorithm))
    assert exc.value.status_code == 401
