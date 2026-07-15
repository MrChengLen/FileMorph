# SPDX-License-Identifier: AGPL-3.0-or-later
"""AVIF encode + decode support (pillow-avif-plugin).

AVIF rides the existing generic image converter/compressor: registering
``avif`` in both the source and target sets gives every ``*->avif`` and
``avif->*`` pair, and adding it to the compressor's supported / target-size
sets enables quality- and target-size compression. These tests pin:

1. Encode: ``png->avif`` and ``jpg->avif`` produce output that opens as a
   valid AVIF via Pillow (format == "AVIF").
2. Decode + roundtrip: ``avif->png`` returns a valid PNG of the same size.
3. ``avif`` target-size compression converges to <= the requested size.
4. Metadata consistency: AVIF output is EXIF-stripped like every other
   image conversion / compression (NEU-C.2), so the privacy posture holds.

The plugin must be importable for these to run; if it is ever dropped the
import guard below skips the module rather than failing spuriously — but the
shipped dependency makes that a non-event in CI.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from PIL.ExifTags import GPS as ExifGPS, IFD, Base as ExifBase

pytest.importorskip("pillow_avif", reason="pillow-avif-plugin not installed")
import pillow_avif  # noqa: E402,F401  (registers AVIF with Pillow on import)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _entropy_rgb(size: int) -> Image.Image:
    """RGB image with enough entropy that AVIF quality affects output size
    (needed for the target-size binary search to have room to converge)."""
    img = Image.new("RGB", (size, size))
    px = img.load()
    for x in range(size):
        for y in range(size):
            px[x, y] = (
                (x * 7 + y * 3) % 256,
                (x * 13 + y * 11) % 256,
                (x * 5 + y * 17) % 256,
            )
    return img


def _jpeg_with_gps(path: Path) -> None:
    """Small JPEG carrying real EXIF (Make/Model + GPS) — the "is it really
    stripped?" fixture, same shape as tests/test_strip_metadata.py."""
    img = Image.new("RGB", (40, 40), color=(120, 200, 80))
    exif = img.getexif()
    exif[ExifBase.Make.value] = "FileMorphTestCam"
    exif[ExifBase.Model.value] = "Model-X"
    gps = exif.get_ifd(IFD.GPSInfo)
    gps[ExifGPS.GPSLatitudeRef.value] = "N"
    gps[ExifGPS.GPSLatitude.value] = (52.0, 31.0, 0.0)
    gps[ExifGPS.GPSLongitudeRef.value] = "E"
    gps[ExifGPS.GPSLongitude.value] = (13.0, 24.0, 0.0)
    img.save(path, format="JPEG", quality=90, exif=exif.tobytes())


def _has_exif(blob: bytes) -> bool:
    """True if the encoded blob carries a non-empty EXIF block (raw bytes,
    parsed IFDs, or a GPS sub-IFD). Mirrors test_strip_metadata.py."""
    img = Image.open(BytesIO(blob))
    if img.info.get("exif"):
        return True
    exif = img.getexif()
    if len(exif) > 0:
        return True
    if exif.get_ifd(IFD.GPSInfo):
        return True
    return False


# ── Encode: *->avif ──────────────────────────────────────────────────────────


def test_png_to_avif(client, auth_headers, sample_png):
    """PNG (with alpha) -> AVIF; output must open as a valid AVIF image."""
    with sample_png.open("rb") as f:
        res = client.post(
            "/api/v1/convert",
            headers=auth_headers,
            files={"file": ("sample.png", f, "image/png")},
            data={"target_format": "avif"},
        )
    assert res.status_code == 200, res.text
    assert len(res.content) > 0
    out = Image.open(BytesIO(res.content))
    out.load()
    assert out.format == "AVIF"


def test_jpg_to_avif(client, auth_headers, sample_jpg):
    """JPEG -> AVIF; output must open as a valid AVIF image."""
    with sample_jpg.open("rb") as f:
        res = client.post(
            "/api/v1/convert",
            headers=auth_headers,
            files={"file": ("sample.jpg", f, "image/jpeg")},
            data={"target_format": "avif", "quality": "80"},
        )
    assert res.status_code == 200, res.text
    out = Image.open(BytesIO(res.content))
    out.load()
    assert out.format == "AVIF"
    assert out.size == (100, 100)  # sample_jpg fixture is 100x100


# ── Decode + roundtrip: avif->png ────────────────────────────────────────────


def test_avif_to_png_roundtrip(client, auth_headers, tmp_path):
    """An AVIF input decodes and converts to a valid PNG of the same size."""
    src = tmp_path / "in.avif"
    _entropy_rgb(64).save(src, format="AVIF", quality=80)

    with src.open("rb") as f:
        res = client.post(
            "/api/v1/convert",
            headers=auth_headers,
            files={"file": ("in.avif", f, "image/avif")},
            data={"target_format": "png"},
        )
    assert res.status_code == 200, res.text
    out = Image.open(BytesIO(res.content))
    out.load()
    assert out.format == "PNG"
    assert out.size == (64, 64)


# ── Target-size compression on AVIF ──────────────────────────────────────────


def test_avif_compress_to_target(client, auth_headers, tmp_path):
    """AVIF is lossy/quality-controlled, so target-size (binary-search-on-
    quality) compression applies. Output must be <= target * 1.03 and open
    as a valid AVIF."""
    src = tmp_path / "photo.avif"
    # Encode at high quality so the q=95 shortcut overshoots and the binary
    # search actually runs down toward the target.
    _entropy_rgb(400).save(src, format="AVIF", quality=95)

    target_kb = 20
    with src.open("rb") as f:
        res = client.post(
            "/api/v1/compress",
            headers=auth_headers,
            files={"file": ("photo.avif", f, "image/avif")},
            data={"target_size_kb": str(target_kb)},
        )
    assert res.status_code == 200, res.text
    achieved = int(res.headers["X-FileMorph-Achieved-Bytes"])
    assert achieved <= int(target_kb * 1024 * 1.03), f"output {achieved} exceeds {target_kb} KB +3%"
    out = Image.open(BytesIO(res.content))
    out.load()
    assert out.format == "AVIF"


def test_avif_quality_compress(client, auth_headers, tmp_path):
    """Plain quality-based compression of an AVIF input returns a valid AVIF."""
    src = tmp_path / "q.avif"
    _entropy_rgb(200).save(src, format="AVIF", quality=90)

    with src.open("rb") as f:
        res = client.post(
            "/api/v1/compress",
            headers=auth_headers,
            files={"file": ("q.avif", f, "image/avif")},
            data={"quality": "50"},
        )
    assert res.status_code == 200, res.text
    out = Image.open(BytesIO(res.content))
    out.load()
    assert out.format == "AVIF"


# ── Metadata consistency (NEU-C.2) ───────────────────────────────────────────


def test_convert_to_avif_strips_exif(client, auth_headers, tmp_path):
    """A JPEG with EXIF GPS converted to AVIF must come back metadata-free —
    AVIF supports EXIF blocks, so this is the real strip assertion, not a
    format that cannot carry EXIF anyway."""
    src = tmp_path / "in.jpg"
    _jpeg_with_gps(src)
    with src.open("rb") as f:
        res = client.post(
            "/api/v1/convert",
            headers=auth_headers,
            files={"file": ("in.jpg", f, "image/jpeg")},
            data={"target_format": "avif"},
        )
    assert res.status_code == 200, res.text
    assert not _has_exif(res.content)


def test_compress_avif_strips_exif(client, auth_headers, tmp_path):
    """Quality-based AVIF compression of an EXIF-bearing AVIF must return a
    clean output. Build the source by converting an EXIF JPEG to AVIF *with*
    its EXIF intact so the fixture genuinely carries metadata to strip."""
    jpg = tmp_path / "in.jpg"
    _jpeg_with_gps(jpg)
    img = Image.open(jpg)
    src = tmp_path / "with_meta.avif"
    # Preserve the JPEG's EXIF into the AVIF fixture so the strip is meaningful.
    img.save(src, format="AVIF", quality=90, exif=img.info.get("exif", b""))
    assert _has_exif(src.read_bytes()), "fixture lost EXIF — test setup bug"

    with src.open("rb") as f:
        res = client.post(
            "/api/v1/compress",
            headers=auth_headers,
            files={"file": ("with_meta.avif", f, "image/avif")},
            data={"quality": "60"},
        )
    assert res.status_code == 200, res.text
    assert not _has_exif(res.content)
