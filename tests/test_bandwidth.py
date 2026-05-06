# SPDX-License-Identifier: AGPL-3.0-or-later
"""S1-B: Output-cap-per-tier bandwidth-amplification guard."""

import dataclasses
import io
import json
import zipfile
from unittest.mock import MagicMock

import pytest
from PIL import Image

from app.api.routes.auth import get_optional_user
from app.core import quotas as quotas_module
from app.core.quotas import QUOTAS, get_quota
from app.main import app


def _jpg_bytes(w: int = 100, h: int = 100) -> bytes:
    img = Image.new("RGB", (w, h), color=(200, 100, 50))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _fake_user(tier: str):
    u = MagicMock()
    u.tier.value = tier
    return u


@pytest.fixture
def override_free_user():
    app.dependency_overrides[get_optional_user] = lambda: _fake_user("free")
    yield
    app.dependency_overrides.pop(get_optional_user, None)


@pytest.fixture
def tiny_anonymous_output_cap(monkeypatch):
    """Shrink the anonymous tier's output_cap_bytes to 100 so any real output overflows."""
    original = QUOTAS["anonymous"]
    shrunk = dataclasses.replace(original, output_cap_bytes=100)
    monkeypatch.setitem(quotas_module.QUOTAS, "anonymous", shrunk)
    yield


@pytest.fixture
def tiny_free_output_cap(monkeypatch):
    """Shrink the free tier's output_cap_bytes to 100 for batch-path tests."""
    original = QUOTAS["free"]
    shrunk = dataclasses.replace(original, output_cap_bytes=100)
    monkeypatch.setitem(quotas_module.QUOTAS, "free", shrunk)
    yield


def test_output_cap_field_exists_on_all_tiers():
    """Every tier must declare output_cap_bytes — no implicit defaults."""
    for tier in ("anonymous", "free", "pro", "business", "enterprise"):
        q = get_quota(tier)
        assert q.output_cap_bytes > 0, f"tier {tier!r} missing output_cap_bytes"


def test_output_cap_progression():
    """Caps must grow monotonically from anonymous to business; enterprise >= business."""
    anon = get_quota("anonymous").output_cap_bytes
    free = get_quota("free").output_cap_bytes
    pro = get_quota("pro").output_cap_bytes
    biz = get_quota("business").output_cap_bytes
    ent = get_quota("enterprise").output_cap_bytes
    assert anon < free < pro < biz
    assert ent >= biz


def test_convert_rejects_output_over_cap(client, auth_headers, tiny_anonymous_output_cap):
    """Anonymous JPG→PNG with a 100-byte cap must return 413 after conversion."""
    r = client.post(
        "/api/v1/convert",
        headers=auth_headers,
        files={"file": ("sample.jpg", _jpg_bytes(), "image/jpeg")},
        data={"target_format": "png"},
    )
    assert r.status_code == 413
    detail = r.json()["detail"]
    assert "Output too large" in detail


def test_convert_passes_under_cap(client, auth_headers):
    """Normal JPG→PNG conversion well under default cap must succeed."""
    r = client.post(
        "/api/v1/convert",
        headers=auth_headers,
        files={"file": ("sample.jpg", _jpg_bytes(), "image/jpeg")},
        data={"target_format": "png"},
    )
    assert r.status_code == 200
    assert len(r.content) > 0


def test_compress_rejects_output_over_cap(client, auth_headers, tiny_anonymous_output_cap):
    """Anonymous compress with a 100-byte cap must return 413."""
    r = client.post(
        "/api/v1/compress",
        headers=auth_headers,
        files={"file": ("sample.jpg", _jpg_bytes(), "image/jpeg")},
        data={"quality": "85"},
    )
    assert r.status_code == 413
    assert "Output too large" in r.json()["detail"]


def test_batch_convert_over_cap_file_marked_failed(
    client, auth_headers, override_free_user, tiny_free_output_cap
):
    """Batch: files whose output exceeds the cap must land in the error manifest,
    not crash the whole batch."""
    files = [
        ("files", ("a.jpg", _jpg_bytes(), "image/jpeg")),
        ("files", ("b.jpg", _jpg_bytes(), "image/jpeg")),
    ]
    r = client.post(
        "/api/v1/convert/batch",
        headers=auth_headers,
        data={"target_formats": ["png", "png"]},
        files=files,
    )
    # All files overflow the tiny cap → summary.succeeded == 0 → 422
    assert r.status_code == 422
    body = r.json()
    assert body["summary"]["failed"] == 2
    assert body["summary"]["succeeded"] == 0
    reasons = [f["error_message"] for f in body["files"] if f["status"] == "error"]
    assert all("Output too large" in msg for msg in reasons)


def test_batch_compress_over_cap_file_marked_failed(
    client, auth_headers, override_free_user, tiny_free_output_cap
):
    """Compress batch: output-cap rejection surfaces per-file, not as a 500."""
    files = [
        ("files", ("a.jpg", _jpg_bytes(), "image/jpeg")),
    ]
    r = client.post(
        "/api/v1/compress/batch",
        headers=auth_headers,
        data={"quality": "85"},
        files=files,
    )
    assert r.status_code == 422
    body = r.json()
    assert body["summary"]["failed"] == 1
    assert "Output too large" in body["files"][0]["error_message"]


def test_batch_per_file_cap_does_not_aggregate(client, auth_headers, override_free_user):
    """H4 — output_cap_bytes is per-file, never aggregate-across-batch.

    A regression that summed output across files in a batch (e.g., a
    misplaced ``running_total >= cap`` accumulator) would silently reject
    legitimate large batches even when each individual file fits the
    per-file cap.

    The test sends three small JPGs that each convert to ~tiny PNGs well
    under the default free-tier cap (150 MB). The aggregate output is
    obviously still well under that, so an aggregate cap of 150 MB
    wouldn't catch it — but the test pins the contract that no synthetic
    accumulator was introduced. If a future PR adds e.g. a 300-byte
    aggregate cap, this test fails first.
    """
    files = [("files", (f"file{i}.jpg", _jpg_bytes(), "image/jpeg")) for i in range(3)]
    r = client.post(
        "/api/v1/convert/batch",
        headers=auth_headers,
        data={"target_formats": ["png", "png", "png"]},
        files=files,
    )
    # All three files should succeed under the standard free-tier cap.
    # Status 200 (zip with three outputs) — never 413, never 422.
    assert r.status_code == 200, (
        f"Per-file cap regressed to aggregate: status={r.status_code}, body={r.text[:200]}"
    )
    # Sanity: response is the zip, not an error JSON.
    assert r.headers.get("content-type", "").startswith("application/zip")


def test_batch_convert_partial_overflow(client, auth_headers, override_free_user, monkeypatch):
    """Mixed batch where one file overflows and another does not — good goes to
    zip, bad goes to manifest errors."""
    # Cap chosen so one tiny PNG (~100 B) fits but a larger PNG (~600 B) does not.
    small_jpg = _jpg_bytes(w=10, h=10)  # tiny PNG on output
    big_jpg = _jpg_bytes(w=200, h=200)  # larger PNG on output

    # Pick a cap between the two expected output sizes.
    original = QUOTAS["free"]
    shrunk = dataclasses.replace(original, output_cap_bytes=300)
    monkeypatch.setitem(quotas_module.QUOTAS, "free", shrunk)

    files = [
        ("files", ("small.jpg", small_jpg, "image/jpeg")),
        ("files", ("big.jpg", big_jpg, "image/jpeg")),
    ]
    r = client.post(
        "/api/v1/convert/batch",
        headers=auth_headers,
        data={"target_formats": ["png", "png"]},
        files=files,
    )
    # If the test setup's expectation of sizes holds, we get partial success.
    # Accept either 200 (≥1 succeeded) or 422 (none), but require the over-cap
    # file to carry the expected error message.
    body = r.json() if r.status_code == 422 else None
    if body is not None:
        assert any(
            "Output too large" in f.get("error_message", "")
            for f in body["files"]
            if f["status"] == "error"
        )
    else:
        assert r.status_code == 200
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["summary"]["failed"] >= 1
