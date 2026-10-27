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
4. The pixels survive in every mode — a palette image (every GIF, 8-bit
   PNGs) keeps its palette, and the transparent colour is kept — so a
   converted or compressed palette image looks the same. Without the
   palette every pixel came out one colour, which size/mode checks alone
   never caught.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageStat
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


def _image(mode: str, colour: bool = False) -> Image.Image:
    """A small image whose pixels differ; for "P" a 256-colour palette
    image, the shape of every GIF and of 8-bit PNGs. Grey unless ``colour``:
    lossy WebP shifts colour noise too far for a pixel comparison."""
    noise = Image.effect_noise((60, 40), 90)
    if colour:
        noise = Image.merge("RGB", [Image.effect_noise((60, 40), 90) for _ in range(3)])
    if mode == "P":
        return noise.convert("RGB").convert("P", palette=Image.Palette.ADAPTIVE)
    return noise.convert(mode)


@pytest.mark.parametrize("mode", ["RGB", "RGBA", "L", "LA", "P", "1", "CMYK", "I;16"])
def test_strip_metadata_keeps_the_pixels(mode):
    """The pixels survive bit for bit — for a palette image with its
    palette, since its pixels are only indices into it. Colour noise, so a
    mixed-up channel order in the palette would show."""
    img = _image(mode, colour=True)

    clean = strip_metadata(img)

    assert (clean.mode, clean.size) == (img.mode, img.size)
    assert clean.tobytes() == img.tobytes()
    if mode == "P":
        assert clean.getpalette() == img.getpalette()
        assert clean.convert("RGB").tobytes() == img.convert("RGB").tobytes()


@pytest.mark.parametrize("mode, transparency", [("P", 7), ("L", 42), ("RGB", (1, 2, 3))])
def test_strip_metadata_keeps_the_transparent_colour(mode, transparency):
    """Which index or colour is transparent is pixel data, not metadata:
    it stays, while EXIF still goes."""
    img = _image(mode)
    img.info["transparency"] = transparency
    img.info["exif"] = b"some-exif"

    clean = strip_metadata(img)

    assert clean.info.get("transparency") == transparency
    assert "exif" not in clean.info


@pytest.mark.parametrize(
    "mode, transparency",
    [("P", 300), ("P", bytes(300)), ("RGB", 5), ("L", (1, 2, 3))],
    ids=["P-index-past-the-palette", "P-table-past-the-palette", "RGB-grey-level", "L-colour"],
)
def test_strip_metadata_drops_a_transparency_that_does_not_fit(mode, transparency):
    """A stale or malformed transparency — a crafted table longer than the
    palette, a grey level left on an RGB image — would make the encoders
    fail: it is dropped, as it always was."""
    img = _image(mode)
    img.info["transparency"] = transparency

    assert "transparency" not in strip_metadata(img).info


def test_palette_png_with_an_alpha_table_converts_to_gif(client, auth_headers):
    """A quantized PNG (pngquant or TinyPNG output) carries an alpha table;
    GIF takes one transparent index, so the converter goes through RGBA and
    the transparent pixels stay transparent."""
    rgba = Image.effect_noise((120, 80), 90).convert("RGBA")
    rgba.paste((0, 0, 0, 0), (0, 0, 60, 40))
    buf = BytesIO()
    rgba.quantize(64).save(buf, format="PNG")
    assert isinstance(Image.open(BytesIO(buf.getvalue())).info["transparency"], bytes), (
        "fixture lost its alpha table — test setup bug"
    )

    resp = client.post(
        "/api/v1/convert",
        files={"file": ("in.png", buf.getvalue(), "image/png")},
        data={"target_format": "gif"},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    transparent_in = Image.open(BytesIO(buf.getvalue())).convert("RGBA").getchannel("A")
    transparent_out = Image.open(BytesIO(resp.content)).convert("RGBA").getchannel("A")
    assert transparent_out.histogram()[0] == transparent_in.histogram()[0] > 0


def test_bilevel_png_with_a_transparent_level_converts_to_ico(client, auth_headers):
    """A 1-bit PNG's transparent level goes stale when the converter turns
    it into RGB: it is dropped instead of breaking the ICO encoder."""
    buf = BytesIO()
    Image.effect_noise((32, 32), 120).convert("1").save(buf, format="PNG", transparency=0)

    resp = client.post(
        "/api/v1/convert",
        files={"file": ("in.png", buf.getvalue(), "image/png")},
        data={"target_format": "ico"},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text


@pytest.mark.parametrize(
    "source, target",
    [("gif", "png"), ("gif", "bmp"), ("gif", "tiff"), ("gif", "webp"), ("png", "gif")],
)
def test_convert_palette_image_keeps_the_picture(client, auth_headers, source, target):
    """Every GIF and every 8-bit PNG is a palette image: converting one
    keeps its colours, not one colour for every pixel."""
    src = _image("P")
    buf = BytesIO()
    src.save(buf, format=source.upper())

    resp = client.post(
        "/api/v1/convert",
        files={"file": (f"in.{source}", buf.getvalue(), f"image/{source}")},
        data={"target_format": target},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    out = Image.open(BytesIO(resp.content)).convert("RGB")
    expected = Image.open(BytesIO(buf.getvalue())).convert("RGB")
    if target == "webp":  # lossy: close to the picture, not bit for bit
        assert ImageStat.Stat(ImageChops.difference(out, expected)).mean[0] < 10
    else:
        assert out.tobytes() == expected.tobytes()


def test_convert_transparent_gif_to_png_keeps_the_transparency(client, auth_headers):
    src = _image("P")
    buf = BytesIO()
    src.save(buf, format="GIF", transparency=0)

    resp = client.post(
        "/api/v1/convert",
        files={"file": ("in.gif", buf.getvalue(), "image/gif")},
        data={"target_format": "png"},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    out = Image.open(BytesIO(resp.content)).convert("RGBA")
    expected = Image.open(BytesIO(buf.getvalue())).convert("RGBA")
    assert out.tobytes() == expected.tobytes()  # alpha included


def test_compress_palette_png_keeps_the_picture(client, auth_headers):
    src = _image("P")
    buf = BytesIO()
    src.save(buf, format="PNG")

    resp = client.post(
        "/api/v1/compress",
        files={"file": ("in.png", buf.getvalue(), "image/png")},
        data={"quality": "85"},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    out = Image.open(BytesIO(resp.content)).convert("RGB")
    assert out.tobytes() == src.convert("RGB").tobytes()


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
