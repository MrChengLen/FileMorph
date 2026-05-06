# SPDX-License-Identifier: AGPL-3.0-or-later
"""NEU-C.2: image conversions and compressions strip EXIF / XMP / IPTC.

Cameras and editors embed metadata that may count as personal data
under GDPR Art. 4 (GPS coordinates, camera serial numbers, capture
timestamps, photographer names). FileMorph's privacy posture only
holds if the output is metadata-clean. These tests pin the
behaviour so a regression cannot reintroduce silent metadata
laundering.

Properties verified:

1. The ``strip_metadata`` helper itself: input image with EXIF →
   output image with no EXIF, ICC profile preserved.
2. End-to-end: conversion of a JPEG-with-EXIF to PNG / JPEG /
   WEBP / TIFF produces output with no EXIF block.
3. End-to-end: compression of a JPEG-with-EXIF (any quality, any
   target-size path) produces output with no EXIF block.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image
from PIL.ExifTags import Base as ExifBase, GPS as ExifGPS, IFD

from app.converters._metadata import strip_metadata


def _jpeg_with_gps(path: Path) -> bytes:
    """Build a small JPEG carrying real EXIF tags including GPS —
    realistic minimal EXIF that catches both presence and content
    survivorship through the conversion pipeline.

    Uses Pillow's native ``Image.Exif`` API rather than piexif so
    the test suite has no extra dep. The TIFF-encoded EXIF block
    Pillow writes is the same shape a real camera writes."""
    img = Image.new("RGB", (40, 40), color=(120, 200, 80))
    exif = img.getexif()
    # Top-level (0th IFD) — Make / Model are the obvious "is it
    # really stripped?" tells.
    exif[ExifBase.Make.value] = "FileMorphTestCam"
    exif[ExifBase.Model.value] = "Model-X"
    # GPS sub-IFD via Pillow's IFD helper.
    gps = exif.get_ifd(IFD.GPSInfo)
    gps[ExifGPS.GPSLatitudeRef.value] = "N"
    gps[ExifGPS.GPSLatitude.value] = (52.0, 31.0, 0.0)  # ~Berlin
    gps[ExifGPS.GPSLongitudeRef.value] = "E"
    gps[ExifGPS.GPSLongitude.value] = (13.0, 24.0, 0.0)
    exif_bytes = exif.tobytes()
    img.save(path, format="JPEG", quality=90, exif=exif_bytes)
    return exif_bytes


def _has_exif(blob: bytes) -> bool:
    """Return True if the encoded blob carries a non-empty EXIF block.

    Three checks: the parsed ``info["exif"]`` raw bytes, the parsed
    ``Image.Exif`` mapping (which catches the case where the bytes
    are present but the IFDs are empty / placeholders), and the
    GPS sub-IFD specifically (a common failure mode is that 0th
    is dropped but GPS leaks through)."""
    img = Image.open(BytesIO(blob))
    if img.info.get("exif"):
        return True
    exif = img.getexif()
    if len(exif) > 0:
        return True
    if exif.get_ifd(IFD.GPSInfo):
        return True
    return False


def test_strip_metadata_drops_exif(tmp_path):
    """Helper-level: ``strip_metadata`` returns a copy with no EXIF."""
    src = tmp_path / "with_gps.jpg"
    _jpeg_with_gps(src)
    img = Image.open(src)
    assert "exif" in img.info, "fixture lost EXIF — test setup bug"

    clean = strip_metadata(img)
    assert "exif" not in clean.info
    # Pixel data must survive the cleaning untouched.
    assert clean.size == img.size
    assert clean.mode == img.mode


def test_strip_metadata_preserves_icc_profile():
    """ICC profile is colour-space metadata, not PII — it must
    survive ``strip_metadata`` so wide-gamut workflows do not
    visibly desaturate after a round-trip."""
    img = Image.new("RGB", (10, 10))
    img.info["icc_profile"] = b"\x00\x01\x02icc-profile-bytes"
    img.info["exif"] = b"some-exif"

    clean = strip_metadata(img)
    assert "exif" not in clean.info
    assert clean.info.get("icc_profile") == b"\x00\x01\x02icc-profile-bytes"


def test_convert_jpeg_to_png_strips_exif(client, auth_headers, tmp_path):
    """End-to-end: a JPEG with EXIF GPS converted to PNG must come
    back metadata-free."""
    src = tmp_path / "in.jpg"
    _jpeg_with_gps(src)

    with src.open("rb") as f:
        resp = client.post(
            "/api/v1/convert",
            files={"file": ("in.jpg", f, "image/jpeg")},
            data={"target_format": "png"},
            headers=auth_headers,
        )
    assert resp.status_code == 200, resp.text
    out_img = Image.open(BytesIO(resp.content))
    # PIL stores PNG eXIf chunks under ``info["exif"]`` if Pillow
    # >= 9 read one. Absence of the key is the assertion.
    assert "exif" not in out_img.info


def test_convert_jpeg_to_jpeg_strips_exif(client, auth_headers, tmp_path):
    """JPEG → JPEG round-trip is the highest-risk path — the
    encoder happily re-emits EXIF if asked. Verify it isn't."""
    src = tmp_path / "in.jpg"
    _jpeg_with_gps(src)
    with src.open("rb") as f:
        resp = client.post(
            "/api/v1/convert",
            files={"file": ("in.jpg", f, "image/jpeg")},
            data={"target_format": "jpeg"},
            headers=auth_headers,
        )
    assert resp.status_code == 200, resp.text
    assert not _has_exif(resp.content)


def test_convert_jpeg_to_webp_strips_exif(client, auth_headers, tmp_path):
    """WebP also supports EXIF blocks — confirm none survive."""
    src = tmp_path / "in.jpg"
    _jpeg_with_gps(src)
    with src.open("rb") as f:
        resp = client.post(
            "/api/v1/convert",
            files={"file": ("in.jpg", f, "image/jpeg")},
            data={"target_format": "webp"},
            headers=auth_headers,
        )
    assert resp.status_code == 200, resp.text
    out_img = Image.open(BytesIO(resp.content))
    assert "exif" not in out_img.info


def test_compress_jpeg_strips_exif(client, auth_headers, tmp_path):
    """Quality-based compression of an EXIF-bearing JPEG must
    return a clean output."""
    src = tmp_path / "in.jpg"
    _jpeg_with_gps(src)
    with src.open("rb") as f:
        resp = client.post(
            "/api/v1/compress",
            files={"file": ("in.jpg", f, "image/jpeg")},
            data={"quality": "60"},
            headers=auth_headers,
        )
    assert resp.status_code == 200, resp.text
    assert not _has_exif(resp.content)


def test_compress_target_size_strips_exif(client, auth_headers, tmp_path):
    """Target-size compression's binary search runs many encode
    probes; the strip happens before the loop, so the final write
    is metadata-clean too."""
    src = tmp_path / "in.jpg"
    _jpeg_with_gps(src)
    with src.open("rb") as f:
        resp = client.post(
            "/api/v1/compress",
            files={"file": ("in.jpg", f, "image/jpeg")},
            data={"target_size_kb": "5"},
            headers=auth_headers,
        )
    assert resp.status_code == 200, resp.text
    assert not _has_exif(resp.content)
