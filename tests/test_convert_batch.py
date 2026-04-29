# SPDX-License-Identifier: AGPL-3.0-or-later
import io
import json
import zipfile
from unittest.mock import MagicMock

import pytest
from PIL import Image

from app.api.routes.auth import get_optional_user
from app.main import app


def _fake_user(tier: str):
    u = MagicMock()
    u.tier.value = tier
    return u


@pytest.fixture
def override_free_user():
    app.dependency_overrides[get_optional_user] = lambda: _fake_user("free")
    yield
    app.dependency_overrides.pop(get_optional_user, None)


def _jpg_bytes(w: int = 40, h: int = 40) -> bytes:
    img = Image.new("RGB", (w, h), color=(200, 100, 50))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _png_bytes(w: int = 40, h: int = 40) -> bytes:
    img = Image.new("RGB", (w, h), color=(100, 180, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _targets(fmt: str, n: int) -> dict[str, list[str]]:
    """Build a ``target_formats`` form payload for N files — each entry the
    same ``fmt``. The batch endpoint now takes one target per file; httpx
    encodes list values as repeated multipart keys on the wire, which is
    what FastAPI's ``list[str] = Form(...)`` parses."""
    return {"target_formats": [fmt] * n}


def test_batch_anon_one_file_ok(client, auth_headers):
    files = [("files", ("test.jpg", _jpg_bytes(), "image/jpeg"))]
    r = client.post(
        "/api/v1/convert/batch",
        headers=auth_headers,
        data=_targets("png", 1),
        files=files,
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/zip")
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    # All-success batches omit manifest.json — the ZIP contains just the
    # converted files. A normal user never sees a diagnostic manifest they
    # don't need.
    assert "manifest.json" not in names
    assert any(n.endswith(".png") for n in names)


def test_batch_anon_rejects_two_files(client, auth_headers):
    files = [
        ("files", ("a.jpg", _jpg_bytes(), "image/jpeg")),
        ("files", ("b.jpg", _jpg_bytes(), "image/jpeg")),
    ]
    r = client.post(
        "/api/v1/convert/batch",
        headers=auth_headers,
        data=_targets("png", 2),
        files=files,
    )
    assert r.status_code == 400
    assert "exceeds tier limit" in r.json()["detail"]


def test_batch_free_three_files_ok(client, auth_headers, override_free_user):
    files = [("files", (f"img{i}.jpg", _jpg_bytes(), "image/jpeg")) for i in range(3)]
    r = client.post(
        "/api/v1/convert/batch",
        headers=auth_headers,
        data=_targets("png", 3),
        files=files,
    )
    assert r.status_code == 200, r.text
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    assert "manifest.json" not in names
    png_count = sum(1 for n in names if n.endswith(".png"))
    assert png_count == 3


def test_batch_free_six_files_rejected(client, auth_headers, override_free_user):
    files = [("files", (f"img{i}.jpg", _jpg_bytes(), "image/jpeg")) for i in range(6)]
    r = client.post(
        "/api/v1/convert/batch",
        headers=auth_headers,
        data=_targets("png", 6),
        files=files,
    )
    assert r.status_code == 400
    assert "exceeds tier limit" in r.json()["detail"]


def test_batch_partial_failure_continues(client, auth_headers, override_free_user):
    files = [
        ("files", ("good1.jpg", _jpg_bytes(), "image/jpeg")),
        ("files", ("evil.jpg", b"MZ\x90\x00" + b"\x00" * 20, "image/jpeg")),
        ("files", ("good2.jpg", _jpg_bytes(), "image/jpeg")),
    ]
    r = client.post(
        "/api/v1/convert/batch",
        headers=auth_headers,
        data=_targets("png", 3),
        files=files,
    )
    assert r.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    manifest = json.loads(zf.read("manifest.json"))
    assert manifest["summary"]["succeeded"] == 2
    assert manifest["summary"]["failed"] == 1


def test_batch_all_failed_returns_422(client, auth_headers, override_free_user):
    files = [
        ("files", ("a.xyz", b"garbage", "application/octet-stream")),
        ("files", ("b.xyz", b"garbage2", "application/octet-stream")),
    ]
    r = client.post(
        "/api/v1/convert/batch",
        headers=auth_headers,
        data=_targets("png", 2),
        files=files,
    )
    assert r.status_code == 422
    body = r.json()
    assert body["summary"]["succeeded"] == 0
    assert body["summary"]["failed"] == 2


def test_batch_unsafe_filename_sanitized(client, auth_headers, override_free_user):
    files = [("files", ("../evil.jpg", _jpg_bytes(), "image/jpeg"))]
    r = client.post(
        "/api/v1/convert/batch",
        headers=auth_headers,
        data=_targets("png", 1),
        files=files,
    )
    assert r.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    for name in zf.namelist():
        assert ".." not in name
        assert "/" not in name
        assert "\\" not in name


def test_batch_missing_target_formats_422(client, auth_headers, override_free_user):
    files = [("files", ("img.jpg", _jpg_bytes(), "image/jpeg"))]
    r = client.post(
        "/api/v1/convert/batch",
        headers=auth_headers,
        files=files,
    )
    assert r.status_code == 422


def test_batch_mixed_formats_per_file_target(client, auth_headers, override_free_user):
    """Different source formats → each file converted to its own target.

    This is the core motivation for per-file `target_formats`: a user can
    drop a JPG + a PNG in the same batch and route both to PDF (or each to
    a different target). The server must apply `target_formats[i]` to
    `files[i]` and not force a single shared format."""
    files = [
        ("files", ("photo.jpg", _jpg_bytes(), "image/jpeg")),
        ("files", ("logo.png", _png_bytes(), "image/png")),
    ]
    r = client.post(
        "/api/v1/convert/batch",
        headers=auth_headers,
        data={"target_formats": ["webp", "jpg"]},
        files=files,
    )
    assert r.status_code == 200, r.text
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    assert any(n.endswith(".webp") for n in names)
    assert any(n.endswith(".jpg") for n in names)


def test_batch_target_formats_length_mismatch(client, auth_headers, override_free_user):
    """Mismatched list length is a client bug — reject with 422 before we
    touch disk so the user sees a clear error instead of a silent skip."""
    files = [
        ("files", ("a.jpg", _jpg_bytes(), "image/jpeg")),
        ("files", ("b.jpg", _jpg_bytes(), "image/jpeg")),
    ]
    r = client.post(
        "/api/v1/convert/batch",
        headers=auth_headers,
        data={"target_formats": ["png"]},  # only 1 for 2 files
        files=files,
    )
    assert r.status_code == 422
    assert "One target per file" in r.json()["detail"]
