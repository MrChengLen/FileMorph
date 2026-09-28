# SPDX-License-Identifier: AGPL-3.0-or-later
"""The tier a key from the API-key file gets (``API_KEYS_FILE_TIER``).

Without ``DATABASE_URL`` there are no accounts, so nothing lifts a caller
above ``anonymous`` on its own — not even a valid key from
``data/api_keys.json``: ``get_db`` yields ``None`` → ``get_optional_user``
returns ``None`` → ``caller_tier`` answers ``anonymous``. The key only gets
past the upload gate (``require_api_key``); the anonymous quotas apply,
whatever ``MAX_UPLOAD_SIZE_MB`` says.

``API_KEYS_FILE_TIER`` names the tier those keys get instead. It reaches the
engine routes (convert, compress, PDF pages) and nothing else: callers
without a key stay anonymous, and the paid AI routes keep asking for an
account.
"""

from __future__ import annotations

import contextlib
import dataclasses
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.datastructures import Headers

from app.api.deps import caller_tier
from app.api.routes import compress as compress_routes
from app.api.routes import convert as convert_routes
from app.api.routes import pdf_pages as pdf_routes
from app.core.config import Settings, settings
from app.core.processing import actor_id
from app.core.quotas import _MB, QUOTAS
from app.db import base as db_base
from app.db.base import get_db
from app.db.models import TierEnum
from app.main import app

_ANONYMOUS = QUOTAS["anonymous"]
_JPEG = b"\xff\xd8\xff\xe0" + bytes(64)


@pytest.fixture
def key_tier(monkeypatch):
    """Keys from the key file run on ``free``, as ``API_KEYS_FILE_TIER=free`` does."""
    monkeypatch.setattr(settings, "api_keys_file_tier", "free")
    return "free"


@pytest.fixture
def slots(monkeypatch):
    """Record the ``(actor_id, tier)`` each engine route asks a concurrency slot for."""
    seen: list[tuple[str, str]] = []

    @contextlib.asynccontextmanager
    async def record(*, actor_id: str, tier: str):
        seen.append((actor_id, tier))
        yield

    for module in (convert_routes, compress_routes, pdf_routes):
        monkeypatch.setattr(module, "acquire_slot", record)
    return seen


def _two_jpegs(sample_jpg):
    jpg = sample_jpg.read_bytes()
    return [("files", ("a.jpg", jpg, "image/jpeg")), ("files", ("b.jpg", jpg, "image/jpeg"))]


# ── Default: the Community Edition chain ──────────────────────────────────────


def test_suite_runs_without_a_database():
    """The default tests below only prove the Community Edition chain if no
    database is configured and no test module left a ``get_db`` override."""
    assert db_base.AsyncSessionLocal is None
    assert get_db not in app.dependency_overrides


def test_default_tier_is_anonymous():
    assert Settings.model_fields["api_keys_file_tier"].default == "anonymous"


def test_file_store_key_gets_the_anonymous_file_size_cap(client, auth_headers, monkeypatch):
    # Lift the whole-request cap far above the file, so only the tier can refuse it.
    monkeypatch.setattr(settings, "max_upload_size_mb", 1000)
    big = b"\xff\xd8\xff\xe0" + b"\x00" * _ANONYMOUS.max_file_size_bytes
    res = client.post(
        "/api/v1/convert",
        headers=auth_headers,
        files={"file": ("big.jpg", big, "image/jpeg")},
        data={"target_format": "png"},
    )
    assert res.status_code == 413
    limit_mb = _ANONYMOUS.max_file_size_bytes // _MB
    assert f"({limit_mb} MB max for anonymous)" in res.json()["detail"]


def test_file_store_key_gets_the_anonymous_batch_cap(client, auth_headers, sample_jpg):
    res = client.post(
        "/api/v1/convert/batch",
        headers=auth_headers,
        files=_two_jpegs(sample_jpg),
        data={"target_formats": ["png", "png"]},
    )
    assert res.status_code == 400
    assert f"tier limit of {_ANONYMOUS.max_files_per_batch}." in res.json()["detail"]


# ── API_KEYS_FILE_TIER set ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path, name, data",
    [
        ("/api/v1/convert", "a.jpg", {"target_format": "png"}),
        ("/api/v1/compress", "a.jpg", {"quality": "80"}),
        ("/api/v1/pdf/extract", "a.pdf", {"pages": "1"}),
        ("/api/v1/pdf/split", "a.pdf", {}),
        ("/api/v1/pdf/compress", "a.pdf", {"target_kb": "100"}),
    ],
    ids=["convert", "compress", "pdf-extract", "pdf-split", "pdf-compress"],
)
def test_key_tier_reaches_every_single_file_route(
    client, auth_headers, monkeypatch, key_tier, slots, path, name, data
):
    """A one-byte cap on ``free`` refuses the file only if the route runs the key
    on ``free`` — the anonymous 30 MB would let it through. The 413 speaks of
    the plan, not of anonymous, and the slot is the key's own."""
    monkeypatch.setitem(QUOTAS, "free", dataclasses.replace(QUOTAS["free"], max_file_size_bytes=1))
    res = client.post(path, headers=auth_headers, files={"file": (name, _JPEG)}, data=data)
    assert res.status_code == 413, res.text
    assert "MB max for your plan)" in res.json()["detail"]
    assert slots == [("ip:testclient:free", "free")]


@pytest.mark.parametrize(
    "path, data",
    [
        ("/api/v1/convert/batch", {"target_formats": ["png", "png"]}),
        ("/api/v1/compress/batch", {"quality": "80"}),
    ],
    ids=["convert", "compress"],
)
def test_key_tier_lifts_the_batch_cap(
    client, auth_headers, sample_jpg, key_tier, slots, path, data
):
    res = client.post(path, headers=auth_headers, files=_two_jpegs(sample_jpg), data=data)
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/zip"
    assert slots == [("ip:testclient:free", "free")]


def test_key_tier_leaves_callers_without_a_key_anonymous(client, sample_jpg, key_tier, slots):
    """The web UI sends no key, so its visitors stay anonymous — on the IP's
    anonymous slot, apart from the key's."""
    res = client.post(
        "/api/v1/convert/batch",
        files=_two_jpegs(sample_jpg),
        data={"target_formats": ["png", "png"]},
    )
    assert res.status_code == 400
    assert f"tier limit of {_ANONYMOUS.max_files_per_batch}." in res.json()["detail"]
    assert slots == [("ip:testclient", "anonymous")]


def test_caller_tier_needs_a_valid_key_file_key(key_tier, auth_headers):
    """``caller_tier`` checks the key itself — it does not lean on the upload
    gate having run — and an account's own tier always wins."""

    def tier(headers, user=None):
        return caller_tier(SimpleNamespace(headers=Headers(headers)), user)

    assert tier(auth_headers) == "free"
    assert tier({"X-API-Key": "not-a-real-key"}) == "anonymous"
    assert tier({}) == "anonymous"
    assert tier(auth_headers, SimpleNamespace(tier=TierEnum.pro)) == "pro"


def test_key_tier_output_cap_hint_speaks_of_the_plan(
    client, auth_headers, sample_jpg, key_tier, monkeypatch
):
    """The output-cap hint picks its wording by tier too: a lifted key is not
    told to register."""
    monkeypatch.setitem(QUOTAS, "free", dataclasses.replace(QUOTAS["free"], output_cap_bytes=1))
    res = client.post(
        "/api/v1/convert",
        headers=auth_headers,
        files={"file": ("a.jpg", sample_jpg.read_bytes(), "image/jpeg")},
        data={"target_format": "png"},
    )
    assert res.status_code == 413, res.text
    assert res.json()["detail"].endswith("or upgrade your plan.")
    with pytest.raises(HTTPException) as exc:
        pdf_routes._enforce_output_cap(2, SimpleNamespace(output_cap_bytes=1), "free")
    assert exc.value.detail.endswith("or upgrade your plan.")


def test_key_tier_does_not_unlock_paid_ai(client, auth_headers, redact_enabled, monkeypatch):
    """``business`` is an AI-eligible tier, but the AI routes read the account's
    tier: their credit ledger needs an account, so a key-file key stays out."""
    monkeypatch.setattr(settings, "api_keys_file_tier", "business")
    res = client.post(
        "/api/v1/ai/redact/apply",
        headers=auth_headers,
        files={"file": ("a.txt", b"Call +49 40 1234567.", "text/plain")},
    )
    assert res.status_code == 403
    assert res.headers["X-FileMorph-Error-Code"] == "ai_plan_required"


def test_actor_id_keeps_a_key_tier_apart_from_anonymous_callers():
    """``_per_actor_semaphore`` rebuilds an actor's semaphore whenever its tier
    changes, so an IP whose keyed and keyless requests shared one actor could
    lift its cap by alternating them."""
    request = SimpleNamespace(client=SimpleNamespace(host="203.0.113.7"))
    assert actor_id(request, None, "anonymous") == "ip:203.0.113.7"
    assert actor_id(request, None, "business") == "ip:203.0.113.7:business"
    assert actor_id(request, SimpleNamespace(id="u-1"), "business") == "user:u-1"


def test_unknown_tier_stops_the_start(monkeypatch):
    """``get_quota`` would quietly fall back to anonymous on a typo."""
    monkeypatch.setenv("API_KEYS_FILE_TIER", "gold")
    with pytest.raises(ValidationError, match="must be one of: anonymous, free, pro"):
        Settings(_env_file=None)


@pytest.mark.parametrize("value, tier", [(" Business ", "business"), ("", "anonymous")])
def test_tier_setting_ignores_case_spaces_and_blanks(monkeypatch, value, tier):
    monkeypatch.setenv("API_KEYS_FILE_TIER", value)
    assert Settings(_env_file=None).api_keys_file_tier == tier
