# SPDX-License-Identifier: AGPL-3.0-or-later
"""Compress-to-target: the target size is an upper bound.

Callers request a maximum output size (e.g. ``target_size_kb=200``) and get
back a JPEG/WebP/AVIF of at most that size — upload portals reject 5.1 MB at a
5 MB limit, so "close to it" is not enough.

Covered surface:
* Convergence on JPEG and WebP, never above the target.
* Below the quality floor: the image is scaled down to fit and the response
  says so (``X-FileMorph-Warnings: resized=<w>x<h>``).
* An image that can't be scaled further: smallest output, ``converged=False``,
  ``target=missed``.
* Above-input shortcut (re-encode at q=95 when input is already small).
* Mutual exclusivity with ``quality``.
* Format reject for PNG (lossless — quality does not control size).
* Tier-cap reject before any encoding work.
* Batch endpoint path, with per-file notes (``X-FileMorph-Batch-Notes``,
  ``manifest.json``).
* Response-header propagation (``X-FileMorph-Achieved-Bytes`` /
  ``X-FileMorph-Final-Quality`` / ``X-FileMorph-Converged``) for the
  cross-origin client.
* Structured-log fields for dashboards.
"""

from __future__ import annotations

import io
import json
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


def _noise_jpeg(tmp_path: Path, name: str = "noise.jpg", size=(800, 600)) -> Path:
    """Noise barely compresses: at 800×600 even quality 1 is ~40 KB, so a
    20 KB target can only be met by scaling the image down."""
    path = tmp_path / name
    Image.effect_noise(size, 90).convert("RGB").save(str(path), format="JPEG", quality=95)
    return path


def _png_bytes(size: int = 200) -> bytes:
    img = Image.new("RGBA", (size, size), color=(0, 128, 255, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# ── Single-endpoint convergence ────────────────────────────────────────────────


def test_jpeg_target_size_converges(client, auth_headers, tmp_path):
    """200 KB target on a complex 1000×1000 JPEG — output must be at most
    200 KB and the response must carry the achieved-bytes header."""
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
    assert achieved == len(res.content)
    # The search may undershoot (it keeps the best quality that fits), but
    # never overshoot.
    assert achieved <= target_kb * 1024, f"output {achieved} exceeds {target_kb} KB"
    assert res.headers["X-FileMorph-Converged"] == "true"


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
    assert achieved <= target_kb * 1024


# ── Edge cases ─────────────────────────────────────────────────────────────────


def test_target_below_quality_floor_scales_the_image_down(client, auth_headers, tmp_path):
    """Target so small that even q=1 exceeds it → the image is scaled down
    until it fits, and the response names the new pixel size."""
    src = _noise_jpeg(tmp_path)
    target_kb = 20

    res = client.post(
        "/api/v1/compress",
        headers=auth_headers,
        files={"file": ("noise.jpg", src.read_bytes(), "image/jpeg")},
        data={"target_size_kb": str(target_kb)},
    )

    assert res.status_code == 200, res.text
    assert len(res.content) <= target_kb * 1024
    assert res.headers["X-FileMorph-Converged"] == "true"
    warning = res.headers["X-FileMorph-Warnings"]
    assert warning.startswith("resized="), warning
    width, height = (int(n) for n in warning.removeprefix("resized=").split("x"))
    out = Image.open(io.BytesIO(res.content))
    assert out.size == (width, height)
    assert width < 800 and height < 600
    assert abs(width / height - 800 / 600) < 0.02  # the aspect ratio is kept


def test_unit_image_that_cannot_reach_the_target_keeps_its_size(tmp_path):
    """A 20×20 image whose 16×16 quality-1 encoding still exceeds a 200-byte
    target can't reach it at all: a thumbnail that still misses would help no
    one, so the image keeps its size at quality 1, reported as not
    converged."""
    from app.api.routes.compress import target_notes
    from app.compressors.image import compress_image_to_target

    src = _noise_jpeg(tmp_path, name="tiny.jpg", size=(20, 20))
    out = tmp_path / "out.jpg"

    result = compress_image_to_target(src, out, target_bytes=200)

    assert result["converged"] is False
    assert result["resized_to"] is None
    assert result["final_quality"] == 1
    assert out.stat().st_size == result["achieved_bytes"] > 200
    assert Image.open(out).size == (20, 20)
    assert target_notes(result) == ["target=missed"]


def test_unit_thin_image_scales_down_to_the_minimum_edge(tmp_path):
    """A 6000×40 strip doesn't give up when the estimate would cut its short
    edge below 16 px: it scales to the 16 px edge, where it fits."""
    from app.compressors.image import compress_image_to_target

    src = _noise_jpeg(tmp_path, name="strip.jpg", size=(6000, 40))
    out = tmp_path / "out.jpg"

    result = compress_image_to_target(src, out, target_bytes=5 * 1024)

    assert result["converged"] is True
    assert result["resized_to"] == (2400, 16)
    assert out.stat().st_size <= 5 * 1024


def test_unit_scaling_keeps_a_mode_the_format_can_write():
    """Palette and bilevel images resample as RGB, or as RGBA only where the
    format takes alpha and the image has transparency — never RGBA for JPEG,
    and no opaque alpha plane for an image without transparency."""
    from app.compressors.image import _scaled

    palette = (
        Image.effect_noise((200, 100), 90)
        .convert("RGB")
        .convert("P", palette=Image.Palette.ADAPTIVE)
    )
    assert _scaled(palette, "WEBP", 0.5).mode == "RGB"
    assert _scaled(palette, "WEBP", 0.5).size == (100, 50)
    transparent = palette.copy()
    transparent.info["transparency"] = 0
    assert _scaled(transparent, "WEBP", 0.5).mode == "RGBA"
    assert _scaled(transparent, "JPEG", 0.5).mode == "RGB"
    bilevel = Image.effect_noise((200, 100), 120).convert("1")
    assert _scaled(bilevel, "JPEG", 0.5).mode == "RGB"
    # reduce() has no 16-bit modes: a 16-bit greyscale PNG under a .webp name.
    assert _scaled(Image.new("I;16", (200, 100)), "WEBP", 0.5).mode == "RGB"


def test_unit_huge_colour_profile_stops_before_scaling(tmp_path):
    """When a 600 KB colour profile rides along with every AVIF encode, no
    size can fit: the search finds that out from one smallest-size probe
    instead of scaling round after round."""
    import os

    from app.compressors.image import TARGET_SIZE_FORMATS, compress_image_to_target

    if "avif" not in TARGET_SIZE_FORMATS:
        pytest.skip("AVIF encoder not available")
    src = tmp_path / "profile.avif"  # JPEG data under an .avif name, as an upload can be
    Image.effect_noise((400, 300), 90).convert("RGB").save(
        src, format="JPEG", quality=95, icc_profile=os.urandom(600 * 1024)
    )
    out = tmp_path / "out.avif"

    result = compress_image_to_target(src, out, target_bytes=100 * 1024)

    assert result["converged"] is False
    assert result["resized_to"] is None  # unreachable: the image keeps its size
    assert Image.open(out).size == (400, 300)
    # The first search (at most 10 encodes), the smallest-size probe and the
    # unscaled quality-1 encode — no scaling rounds.
    assert result["iterations"] <= 12


def test_bilevel_image_named_jpg_scales_without_error(client, auth_headers, tmp_path):
    """A bilevel PNG uploaded as .jpg that has to be scaled is converted to
    RGB, not RGBA (which JPEG can't write): 200, not 500."""
    src = tmp_path / "bw.png"
    Image.effect_noise((2000, 2000), 120).convert("1").save(src, format="PNG")

    res = client.post(
        "/api/v1/compress",
        headers=auth_headers,
        files={"file": ("bw.jpg", src.read_bytes(), "image/jpeg")},
        data={"target_size_kb": "5"},
    )

    assert res.status_code == 200, res.text
    assert len(res.content) <= 5 * 1024
    assert res.headers["X-FileMorph-Converged"] == "true"
    assert res.headers["X-FileMorph-Warnings"].startswith("resized=")
    assert Image.open(io.BytesIO(res.content)).format == "JPEG"


def test_unit_search_keeps_the_best_quality_that_fits(tmp_path):
    """The result is the highest quality whose output fits — one step up
    would not fit (or the search stopped within 3 % below the target)."""
    from app.compressors.image import _encode_to_bytes, compress_image_to_target
    from app.core.image_hardening import open_image

    src = _photo_jpeg(tmp_path, size=600)
    out = tmp_path / "out.jpg"
    target = 40 * 1024

    result = compress_image_to_target(src, out, target_bytes=target)

    assert result["converged"] is True and result["resized_to"] is None
    q = result["final_quality"]
    assert out.stat().st_size <= target
    if out.stat().st_size < target * 0.97 and q < 95:
        img = open_image(src)
        assert len(_encode_to_bytes(img, "JPEG", q + 1)) > target


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
    assert "JPEG, WebP and AVIF" in res.json()["detail"]


def test_target_size_above_tier_cap_is_rejected(client, auth_headers, tmp_path):
    """Anonymous tier output cap (90 MB) must fence target_size requests
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
    Each output in the ZIP must be ≤ target.

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

    upper = target_kb * 1024
    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        outputs = [n for n in zf.namelist() if n.endswith(".jpg")]
        assert len(outputs) == 2
        for name in outputs:
            data = zf.read(name)
            assert len(data) <= upper, f"{name} = {len(data)} > {upper}"


def test_batch_names_the_files_it_scaled_down(client, auth_headers, tmp_path):
    """A file scaled down to fit is listed in X-FileMorph-Batch-Notes and in
    manifest.json — which the ZIP then carries although nothing failed."""
    from unittest.mock import MagicMock
    from urllib.parse import unquote

    from app.api.routes.auth import get_optional_user
    from app.main import app

    fake_user = MagicMock()
    fake_user.tier.value = "free"
    app.dependency_overrides[get_optional_user] = lambda: fake_user
    try:
        noise = _noise_jpeg(tmp_path)
        small = _photo_jpeg(tmp_path, name="small.jpg", size=100)
        res = client.post(
            "/api/v1/compress/batch",
            headers=auth_headers,
            files=[
                ("files", ("noise.jpg", noise.read_bytes(), "image/jpeg")),
                ("files", ("small.jpg", small.read_bytes(), "image/jpeg")),
            ],
            data={"target_size_kb": "20"},
        )
    finally:
        app.dependency_overrides.pop(get_optional_user, None)

    assert res.status_code == 200, res.text
    assert res.headers["X-FileMorph-Batch-Failed"] == "0"
    name, _, value = res.headers["X-FileMorph-Batch-Notes"].partition("|")
    assert unquote(name) == "noise_compressed.jpg"
    assert unquote(value).startswith("resized=")
    assert ";" not in res.headers["X-FileMorph-Batch-Notes"]  # the small one fits as is
    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        assert all(len(zf.read(n)) <= 20 * 1024 for n in zf.namelist() if n.endswith(".jpg"))
    notes = {f["name"]: f["notes"] for f in manifest["files"]}
    assert notes["small_compressed.jpg"] == []
    assert notes["noise_compressed.jpg"] == [unquote(value)]


def test_batch_list_headers_share_one_budget():
    """Failures and notes together stay within the 4 KB proxies tolerate,
    the failures first; manifest.json keeps the full lists."""
    from app.core.batch import _LIST_HEADERS_MAX_BYTES, BatchFileResult, batch_summary_headers

    failed = [
        BatchFileResult(
            name=f"fehlgeschlagen-{i:03}-ä.png",
            status="error",
            size_in=1,
            error_message="Conversion failed. Verify the file is valid.",
        )
        for i in range(60)
    ]
    scaled = [
        BatchFileResult(
            name=f"verkleinert-{i:03}-ä.jpg",
            status="ok",
            size_in=1,
            size_out=1,
            content=b"x",
            notes=["resized=2400x1600"],
        )
        for i in range(60)
    ]
    headers = batch_summary_headers(failed + scaled, {"total": 120, "succeeded": 60, "failed": 60})

    failures = headers["X-FileMorph-Batch-Failures"]
    notes = headers["X-FileMorph-Batch-Notes"]
    assert failures.endswith("...") and notes.endswith("...")
    assert len(failures) + len(notes) <= _LIST_HEADERS_MAX_BYTES + 2 * len(";...")


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
    assert hasattr(rec, "resized_to")


# ── Compressor unit-level invariants ──────────────────────────────────────────


def test_unit_compressor_rejects_unsupported_format(tmp_path):
    """Defense in depth: even if a caller bypassed the route guard, the
    function itself must refuse PNG."""
    from app.compressors.image import compress_image_to_target

    png = tmp_path / "x.png"
    png.write_bytes(_png_bytes())

    with pytest.raises(ValueError, match="JPEG/WebP"):
        compress_image_to_target(png, tmp_path / "out.png", target_bytes=10_000)
