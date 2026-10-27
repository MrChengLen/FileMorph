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
5. A photo comes back upright: phones store it as the sensor saw it and
   note the turn in the EXIF orientation, which goes with the rest of the
   EXIF — so the turn is applied to the pixels first, exactly once.
"""

from __future__ import annotations

import struct
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageOps, ImageStat
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


# --- Orientation: phone photos come back upright -------------------------


def _sideways() -> Image.Image:
    """A landscape image as a phone sensor stored it: red left half, blue
    right half. With EXIF orientation 6 (turn 90° clockwise) viewers show
    it as a portrait with red on top."""
    img = Image.new("RGB", (80, 40), (0, 0, 255))
    img.paste((255, 0, 0), (0, 0, 40, 40))
    return img


def _turn_tag(orientation: int = 6) -> bytes:
    tags = Image.Exif()
    tags[ExifBase.Orientation.value] = orientation
    return tags.tobytes()


def _saved(img: Image.Image, fmt: str, **params) -> bytes:
    buf = BytesIO()
    img.save(buf, format=fmt, **params)
    return buf.getvalue()


def _assert_upright(img: Image.Image) -> None:
    """Portrait, red on top: turned exactly once (lossy formats included)."""
    rgb = img.convert("RGB")
    assert rgb.size == (40, 80)
    top, bottom = rgb.getpixel((20, 10)), rgb.getpixel((20, 70))
    assert top[0] > 200 and top[2] < 60, top
    assert bottom[2] > 200 and bottom[0] < 60, bottom


@pytest.mark.parametrize("orientation", range(1, 9))
def test_strip_metadata_turns_the_photo_upright(orientation):
    """Each of the eight EXIF orientations ends up the way Pillow's own
    ImageOps.exif_transpose (and every viewer) shows it, and the EXIF goes."""
    img = Image.effect_noise((6, 4), 90).convert("RGB")
    img.info["exif"] = _turn_tag(orientation)
    expected = ImageOps.exif_transpose(img)

    clean = strip_metadata(img)

    assert clean.size == expected.size
    assert clean.tobytes() == expected.tobytes()
    assert "exif" not in clean.info


def test_strip_metadata_turned_palette_image_keeps_palette_icc_and_transparency():
    """The turned image is the clean one: its palette, ICC profile and
    transparent index stay, nothing else does. The colours are checked
    against a turn of the RGB picture, which no lost palette could match."""
    img = _image("P")
    img.info.update(transparency=7, icc_profile=b"icc", exif=_turn_tag(), comment=b"by me")
    expected = img.convert("RGB").transpose(Image.Transpose.ROTATE_270)

    clean = strip_metadata(img)

    assert clean.mode == "P" and clean.size == expected.size == (40, 60)
    assert clean.convert("RGB").tobytes() == expected.tobytes()
    assert clean.info == {"icc_profile": b"icc", "transparency": 7}


def test_strip_metadata_reads_the_orientation_from_xmp():
    """Some editors note the turn only in XMP; Pillow reads it there too."""
    xmp = (
        b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF '
        b'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"><rdf:Description '
        b'xmlns:tiff="http://ns.adobe.com/tiff/1.0/" tiff:Orientation="6"/></rdf:RDF></x:xmpmeta>'
    )
    img = Image.open(BytesIO(_saved(_sideways(), "JPEG", quality=95, xmp=xmp)))

    _assert_upright(strip_metadata(img))


def test_strip_metadata_turns_a_tiff_once():
    """Pillow turns a TIFF while loading it and drops the tag: no second turn."""
    tiff = _saved(_sideways(), "TIFF", tiffinfo={ExifBase.Orientation.value: 6})

    _assert_upright(strip_metadata(Image.open(BytesIO(tiff))))


def test_strip_metadata_turns_a_heic_once():
    """pillow-heif applies the HEIF rotation while decoding and resets the
    EXIF orientation: an iPhone photo is not turned a second time."""
    pillow_heif = pytest.importorskip("pillow_heif")
    if not pillow_heif.libheif_info().get("HEIF"):
        pytest.skip("pillow-heif has no HEIF encoder")
    pillow_heif.register_heif_opener()
    heic = _saved(_sideways(), "HEIF", exif=_turn_tag())

    _assert_upright(strip_metadata(Image.open(BytesIO(heic))))


def test_strip_metadata_turns_an_avif():
    """The AVIF decoder reports the file's rotation as the EXIF orientation."""
    pytest.importorskip("pillow_avif")
    avif = _saved(_sideways(), "AVIF", exif=_turn_tag(), quality=90)

    _assert_upright(strip_metadata(Image.open(BytesIO(avif))))


def test_strip_metadata_turns_a_photo_whose_exif_cannot_be_written_back():
    """An ImageWidth entry holding a fraction: Pillow reads the block, but
    writing it back fails (ImageOps.exif_transpose raises). The orientation is
    only read, so the photo still turns — and the block still goes."""
    tags = Image.Exif()
    tags[ExifBase.Orientation.value] = 6
    tags[ExifBase.XResolution.value] = 72.0
    block = bytearray(tags.tobytes())
    # Big-endian: the XResolution entry (tag 0x011A, type 5 = a fraction),
    # renumbered to ImageWidth (0x0100).
    entry = block.index(b"\x01\x1a\x00\x05")
    block[entry + 1] = 0x00
    img = _sideways()
    img.info["exif"] = bytes(block)
    with pytest.raises(struct.error):  # the premise: Pillow can't write it back
        ImageOps.exif_transpose(img)

    clean = strip_metadata(img)

    _assert_upright(clean)
    assert "exif" not in clean.info


@pytest.mark.parametrize(
    "block", [b"some-exif", b"Exif\x00\x00II*\x00"], ids=["not-tiff", "cut-short"]
)
def test_strip_metadata_keeps_a_photo_whose_exif_cannot_be_read(block):
    """An EXIF block Pillow can't parse (SyntaxError, struct.error) has no
    turn to apply: the photo stays as stored, as before, and the conversion
    doesn't fail."""
    img = _sideways()
    img.info["exif"] = block

    clean = strip_metadata(img)

    assert clean.tobytes() == img.tobytes()
    assert "exif" not in clean.info


@pytest.mark.parametrize("target", ["png", "jpeg", "webp"])
def test_convert_portrait_photo_comes_back_upright(client, auth_headers, target):
    """End-to-end: a phone's portrait JPEG keeps standing — it came back
    sideways while the stripped EXIF took the turn with it."""
    photo = _saved(_sideways(), "JPEG", quality=95, exif=_turn_tag())
    resp = client.post(
        "/api/v1/convert",
        files={"file": ("photo.jpg", photo, "image/jpeg")},
        data={"target_format": target},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    _assert_upright(Image.open(BytesIO(resp.content)))
    assert not _has_exif(resp.content)


@pytest.mark.parametrize("form", [{"quality": "80"}, {"target_size_kb": "5"}])
def test_compress_portrait_photo_comes_back_upright(client, auth_headers, form):
    photo = _saved(_sideways(), "JPEG", quality=95, exif=_turn_tag())
    resp = client.post(
        "/api/v1/compress",
        files={"file": ("photo.jpg", photo, "image/jpeg")},
        data=form,
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    _assert_upright(Image.open(BytesIO(resp.content)))


@pytest.mark.parametrize("fmt, mode", [("JPEG", "RGB"), ("PNG", "RGBA")])
def test_portrait_photo_to_pdf_gives_a_portrait_page(client, auth_headers, fmt, mode):
    """Image → PDF: the page stands too — also for an image with alpha,
    whose flattening onto white dropped the EXIF before the strip."""
    from pypdf import PdfReader

    photo = _saved(_sideways().convert(mode), fmt, exif=_turn_tag())
    resp = client.post(
        "/api/v1/convert",
        files={"file": (f"photo.{fmt.lower()}", photo, f"image/{fmt.lower()}")},
        data={"target_format": "pdf"},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    box = PdfReader(BytesIO(resp.content)).pages[0].mediabox
    assert box.width < box.height
