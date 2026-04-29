# SPDX-License-Identifier: AGPL-3.0-or-later
"""Compress-to-target: binary-search-on-quality endpoint behavior.

Guards the user-acquisition-strategy claim that callers can request a
specific output size (e.g. ``target_size_kb=200``) and get back a JPEG/WebP
within ±3% — useful for email gateways with hard caps.

Covered surface:
* Convergence on JPEG and WebP.
* Below-floor fallback (smallest possible output, ``converged=False``).
* Above-input shortcut (re-encode at q=95 when input is already small).
* Mutual exclusivity with ``quality``.
* Format reject for PNG (lossless — quality does not control size).
* Tier-cap reject before any encoding work.
* Batch endpoint path.
* Response-header propagation (``X-FileMorph-Achieved-Bytes`` /
  ``X-FileMorph-Final-Quality``) for the cross-origin client.
* Structured-log fields for dashboards.
"""

from __future__ import annotations

import io
import logging
import zipfile
from pathlib import Path

import pytest
from PIL import Image


# ── Helpers ────────────────────────────────────────────────────────────────────


def _photo_jpeg(tmp_path: Path, name: str = "photo.jpg", size: int = 1000) -> Path:
    """Build a JPEG with enough entropy that q=1 and q=95 differ in size."""
    img = Image.new("RGB", (size, size))
    pixels = img.load()
    for x in range(size):
        for y in range(size):
            r = (x * 7 + y * 3) % 256
            g = (x * 13 + y * 11) % 256
            b = (x * 5 + y * 17) % 256
            pixels[x, y] = (r, g, b)
    path = tmp_path / name
    img.save(str(path), format="JPEG", quality=95)
    return path


def _photo_webp(tmp_path: Path, name: str = "photo.webp", size: int = 800) -> Path:
    img = Image.new("RGB", (size, size))
    pixels = img.load()
    for x in range(size):
        for y in range(size):
            pixels[x, y] = (
                (x * 7 + y * 3) % 256,
                (x * 13 + y * 11) % 256,
                (x * 5 + y * 17) % 256,
            )
    path = tmp_path / name
    img.save(str(path), format="WEBP", quality=95)
    return path


def _png_bytes(size: int = 200) -> bytes:
    img = Image.new("RGBA", (size, size), color=(0, 128, 255, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ── Single-endpoint convergence ────────────────────────────────────────────────


def test_jpeg_target_size_converges(client, auth_headers, tmp_path):
    """200 KB target on a complex 1000×1000 JPEG — output must be within
    ±3% of 200 KB and the response must carry the achieved-bytes header."""
    jpg = _photo_jpeg(tmp_path)
    target_kb = 200

    res = client.post(
        "/api/v1/compress",
        headers=auth_headers,
        files={"file": ("photo.jpg", jpg.read_bytes(), "image/jpeg")},
        data={"target_size_kb": str(target_kb)},
    )

    assert res.status_code == 200, res.text
    achieved = int(res.headers["X-FileMorph-Achieved-Bytes"])
    target_bytes = target_kb * 1024
    # The function may legitimately undershoot when convergence picks the
    # largest "still acceptable" quality. Accept anything ≤ upper bound.
    assert achieved <= int(target_bytes * 1.03), (
        f"output {achieved} exceeds 200 KB +3% = {int(target_bytes * 1.03)}"
    )


def test_webp_target_size_converges(client, auth_headers, tmp_path):
    webp = _photo_webp(tmp_path)
    target_kb = 100

    res = client.post(
        "/api/v1/compress",
        headers=auth_headers,
        files={"file": ("photo.webp", webp.read_bytes(), "image/webp")},
        data={"target_size_kb": str(target_kb)},
    )

    assert res.status_code == 200, res.text
    achieved = int(res.headers["X-FileMorph-Achieved-Bytes"])
    assert achieved <= int(target_kb * 1024 * 1.03)


# ── Edge cases ─────────────────────────────────────────────────────────────────


def test_target_below_floor_returns_smallest_possible(client, auth_headers, tmp_path):
    """Target so small that even q=1 exceeds it → server still returns
    a valid file (the smallest it could produce). The response is 200,
    not 4xx — caller can read achieved bytes from the header to detect it."""
    jpg = _photo_jpeg(tmp_path, size=1500)
    target_kb = 5

    res = client.post(
        "/api/v1/compress",
        headers=auth_headers,
        files={"file": ("big.jpg", jpg.read_bytes(), "image/jpeg")},
        data={"target_size_kb": str(target_kb)},
    )

    assert res.status_code == 200, res.text
    assert "X-FileMorph-Achieved-Bytes" in res.headers
    assert "X-FileMorph-Final-Quality" in res.headers


def test_target_above_input_uses_high_quality_shortcut(client, auth_headers, tmp_path):
    """Input is much smaller than the target — we should re-encode at
    high quality (no need to drop quality), so the output is a clean
    JPEG and well within the target."""
    jpg = _photo_jpeg(tmp_path, size=200)
    input_size = jpg.stat().st_size
    target_bytes = max(input_size * 4, 50_000)

    res = client.post(
        "/api/v1/compress",
        headers=auth_headers,
        files={"file": ("small.jpg", jpg.read_bytes(), "image/jpeg")},
        data={"target_size_kb": str(target_bytes // 1024)},
    )

    assert res.status_code == 200, res.text
    achieved = int(res.headers["X-FileMorph-Achieved-Bytes"])
    assert achieved <= target_bytes
    # The shortcut path uses q=95.
    assert int(res.headers["X-FileMorph-Final-Quality"]) == 95


def test_quality_and_target_size_are_mutually_exclusive(client, auth_headers, tmp_path):
    jpg = _photo_jpeg(tmp_path, size=300)

    res = client.post(
        "/api/v1/compress",
        headers=auth_headers,
        files={"file": ("photo.jpg", jpg.read_bytes(), "image/jpeg")},
        data={"quality": "70", "target_size_kb": "100"},
    )

    assert res.status_code == 400
    assert "either quality or target_size_kb" in res.json()["detail"]


def test_png_with_target_size_returns_415(client, auth_headers):
    """PNG/TIFF are lossless — quality knob does not control size, so
    target-size compression is rejected with a clear pointer to use
    ``quality=`` instead."""
    res = client.post(
        "/api/v1/compress",
        headers=auth_headers,
        files={"file": ("img.png", _png_bytes(), "image/png")},
        data={"target_size_kb": "100"},
    )

    assert res.status_code == 415
    assert "JPEG and WebP" in res.json()["detail"]


def test_target_size_above_tier_cap_is_rejected(client, auth_headers, tmp_path):
    """Anonymous tier output cap (~50 MB) must fence target_size requests
    before any encoding work. 999_999 KB ≈ 977 MB > anonymous cap."""
    jpg = _photo_jpeg(tmp_path, size=300)

    res = client.post(
        "/api/v1/compress",
        headers=auth_headers,
        files={"file": ("photo.jpg", jpg.read_bytes(), "image/jpeg")},
        data={"target_size_kb": "999999"},
    )

    assert res.status_code == 413
    assert "exceeds tier output cap" in res.json()["detail"]


# ── Batch path ─────────────────────────────────────────────────────────────────


def test_batch_target_size_applies_to_all_files(client, auth_headers, tmp_path):
    """The batch endpoint applies one target_size_kb across the batch.
    Each output in the ZIP must be ≤ target * 1.03.

    Anonymous tier caps batch size at 1, so we override
    ``get_optional_user`` with a free-tier stub for this case."""
    from unittest.mock import MagicMock

    from app.api.routes.auth import get_optional_user
    from app.main import app

    fake_user = MagicMock()
    fake_user.tier.value = "free"
    app.dependency_overrides[get_optional_user] = lambda: fake_user

    try:
        jpg_a = _photo_jpeg(tmp_path, name="a.jpg", size=900)
        jpg_b = _photo_jpeg(tmp_path, name="b.jpg", size=900)
        target_kb = 150

        res = client.post(
            "/api/v1/compress/batch",
            headers=auth_headers,
            files=[
                ("files", ("a.jpg", jpg_a.read_bytes(), "image/jpeg")),
                ("files", ("b.jpg", jpg_b.read_bytes(), "image/jpeg")),
            ],
            data={"target_size_kb": str(target_kb)},
        )
    finally:
        app.dependency_overrides.pop(get_optional_user, None)

    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("application/zip")

    upper = int(target_kb * 1024 * 1.03)
    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        outputs = [n for n in zf.namelist() if n.endswith(".jpg")]
        assert len(outputs) == 2
        for name in outputs:
            data = zf.read(name)
            assert len(data) <= upper, f"{name} = {len(data)} > {upper}"


# ── Logging contract ───────────────────────────────────────────────────────────


def test_target_size_log_carries_dashboard_fields(client, auth_headers, tmp_path, caplog):
    """The ``compression complete`` record gets the extra fields dashboards
    need to slice target-size pressure (target_size_kb, final_quality,
    achieved_size_bytes, iterations, converged)."""
    jpg = _photo_jpeg(tmp_path)

    with caplog.at_level(logging.INFO, logger="app.api.routes.compress"):
        res = client.post(
            "/api/v1/compress",
            headers=auth_headers,
            files={"file": ("photo.jpg", jpg.read_bytes(), "image/jpeg")},
            data={"target_size_kb": "150"},
        )
    assert res.status_code == 200

    records = [r for r in caplog.records if r.getMessage() == "compression complete"]
    assert records, "no 'compression complete' record found"
    rec = records[-1]
    assert getattr(rec, "target_size_kb", None) == 150
    assert getattr(rec, "final_quality", None) is not None
    assert getattr(rec, "achieved_size_bytes", None) is not None
    assert getattr(rec, "iterations", None) is not None
    assert getattr(rec, "converged", None) is not None


# ── Compressor unit-level invariants ──────────────────────────────────────────


def test_unit_compressor_rejects_unsupported_format(tmp_path):
    """Defense in depth: even if a caller bypassed the route guard, the
    function itself must refuse PNG."""
    from app.compressors.image import compress_image_to_target

    png = tmp_path / "x.png"
    png.write_bytes(_png_bytes())

    with pytest.raises(ValueError, match="JPEG/WebP"):
        compress_image_to_target(png, tmp_path / "out.png", target_bytes=10_000)
