# SPDX-License-Identifier: AGPL-3.0-or-later
"""NEU-C.3: X-Data-Classification middleware + audit-log propagation.

Pinned contracts:

1. Vocabulary: ``public`` / ``internal`` / ``confidential`` /
   ``restricted``. ``internal`` is the default when the header is
   absent — a service that doesn't know what its caller is sending
   should err on the safer side.
2. Trim + lowercase normalisation: ``"  Confidential  "`` resolves
   to ``"confidential"``. Behörden ETL pipelines often produce
   whitespace-padded headers; rejecting those would be hostile.
3. Invalid value (typo, made-up tier) → fall back to ``internal``,
   echo back ``internal`` on the response, log a warning. We do NOT
   400 the request: a downstream typo should not break a production
   pipeline at the network boundary.
4. Echo on response: every response carries
   ``X-Data-Classification`` with the resolved value, so the caller
   can verify what the server actually used.
5. CORS surface: the response header is listed in
   ``CORSMiddleware.expose_headers`` so cross-origin client JS can
   read it via ``response.headers.get(...)`` (see
   "Network-layer changes quadruple-check" rule in CLAUDE.md).
6. Audit-log propagation: convert/compress ``audit_record`` calls
   include ``data_classification`` in their payload. That value is
   what later powers a "show me every restricted-tier conversion in
   the last 30 days" forensic query.

The unit-level tests cover (1)–(4); a route-level test covers (6)
end-to-end via the existing ``/api/v1/convert`` path.
"""

from __future__ import annotations

import io

import pytest

from app.core.data_classification import (
    DEFAULT_CLASSIFICATION,
    REQUEST_HEADER,
    RESPONSE_HEADER,
    VALID_CLASSIFICATIONS,
    normalize_classification,
)


# ── Pure-function vocabulary contract ──────────────────────────────────────


def test_default_when_header_absent():
    """No header set → default to ``internal``, was_valid=True (silent path)."""
    classification, was_valid = normalize_classification(None)
    assert classification == "internal"
    assert was_valid is True


def test_default_when_header_empty_string():
    """Empty string is treated like absent — same default, no warning."""
    classification, was_valid = normalize_classification("")
    assert classification == "internal"
    assert was_valid is True


@pytest.mark.parametrize("value", sorted(VALID_CLASSIFICATIONS))
def test_each_vocabulary_value_passes_through(value):
    """Every documented value resolves to itself with was_valid=True."""
    resolved, was_valid = normalize_classification(value)
    assert resolved == value
    assert was_valid is True


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("PUBLIC", "public"),
        ("Internal", "internal"),
        ("  Confidential  ", "confidential"),
        ("RESTRICTED", "restricted"),
    ],
)
def test_normalization_is_case_and_whitespace_insensitive(raw, expected):
    """Behörden ETL pipelines produce whitespace and case variation;
    rejecting those would be needless friction."""
    resolved, was_valid = normalize_classification(raw)
    assert resolved == expected
    assert was_valid is True


@pytest.mark.parametrize(
    "raw",
    [
        "secret",  # not in vocab; common typo
        "TOP_SECRET",  # plausible but rejected
        "vertraulich",  # German — out of scope, English vocab
        "1",  # numeric noise
        "x" * 200,  # length spam
    ],
)
def test_invalid_values_fall_back_silently_to_default(raw):
    """Invalid values → default ``internal`` with was_valid=False so the
    middleware can log the rejected raw input for forensics."""
    resolved, was_valid = normalize_classification(raw)
    assert resolved == DEFAULT_CLASSIFICATION
    assert was_valid is False


# ── Middleware: response header echo ────────────────────────────────────────


def test_response_echoes_default_when_no_request_header(client):
    """Every response carries the header even when the caller didn't set
    one — the contract is "you always get a classification back"."""
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    assert res.headers.get(RESPONSE_HEADER) == DEFAULT_CLASSIFICATION


def test_response_echoes_caller_supplied_classification(client):
    """Caller sets ``confidential`` → server echoes ``confidential``."""
    res = client.get("/api/v1/health", headers={REQUEST_HEADER: "confidential"})
    assert res.status_code == 200
    assert res.headers.get(RESPONSE_HEADER) == "confidential"


def test_response_normalises_case_and_whitespace(client):
    """``  Restricted  `` → echoes lowercase ``restricted``."""
    res = client.get("/api/v1/health", headers={REQUEST_HEADER: "  Restricted  "})
    assert res.status_code == 200
    assert res.headers.get(RESPONSE_HEADER) == "restricted"


def test_response_falls_back_on_invalid_input(client):
    """Invalid value → echo default ``internal``; the warning is logged
    server-side but the request itself is not rejected (no 400)."""
    res = client.get("/api/v1/health", headers={REQUEST_HEADER: "top-secret"})
    assert res.status_code == 200
    assert res.headers.get(RESPONSE_HEADER) == DEFAULT_CLASSIFICATION


# ── CORS exposure ─────────────────────────────────────────────────────────


def test_cors_exposes_data_classification_header():
    """Cross-origin client JS must be able to read the response header.
    The CORSMiddleware ``expose_headers`` list is the surface; if a
    refactor drops ``X-Data-Classification`` from it, this fails."""
    from app.main import app
    from fastapi.middleware.cors import CORSMiddleware

    cors = next(
        (m for m in app.user_middleware if m.cls is CORSMiddleware),
        None,
    )
    assert cors is not None, "CORSMiddleware not registered"
    exposed = cors.kwargs.get("expose_headers", [])
    assert "X-Data-Classification" in exposed, (
        "X-Data-Classification missing from CORS expose_headers — "
        "cross-origin clients won't be able to read the echoed value"
    )


# ── Audit-log payload propagation ─────────────────────────────────────────


def test_convert_audit_payload_includes_classification(client, auth_headers, monkeypatch):
    """End-to-end: a convert request with X-Data-Classification carries
    that value into the audit-record call's payload. We patch
    ``audit_record`` to capture the call instead of writing to a real
    DB, since the test harness doesn't run migration 005."""
    from app.api.routes import convert as convert_route

    captured: list[dict] = []

    async def fake_audit(event_type, *, actor_user_id=None, actor_ip=None, payload=None, db=None):
        captured.append({"event": event_type, "payload": payload})

    monkeypatch.setattr(convert_route, "audit_record", fake_audit)

    # Tiny PNG → JPG conversion exercises the audit-record success path
    # without depending on heavy converters (ffmpeg / pikepdf).
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), color=(255, 0, 0)).save(buf, format="PNG")
    buf.seek(0)

    res = client.post(
        "/api/v1/convert",
        files={"file": ("tiny.png", buf, "image/png")},
        data={"target_format": "jpg"},
        headers={**auth_headers, REQUEST_HEADER: "restricted"},
    )
    assert res.status_code == 200, res.text
    assert res.headers.get(RESPONSE_HEADER) == "restricted"

    success_calls = [c for c in captured if c["event"] == "convert.success"]
    assert success_calls, f"no convert.success audit call; captured={captured}"
    assert success_calls[0]["payload"]["data_classification"] == "restricted"
