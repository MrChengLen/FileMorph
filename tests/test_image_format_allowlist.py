# SPDX-License-Identifier: AGPL-3.0-or-later
"""Uploaded images are opened only with the readers for supported formats.

The image converters and compressors open uploads through
``app/core/image_hardening.py::open_image``, which passes ``formats=`` to
``Image.open``: Pillow tries only the readers in ``IMAGE_INPUT_FORMATS``
(JPEG, PNG, WebP, GIF, BMP, TIFF, ICO, HEIF, AVIF), not the others it ships.
A file none of them reads is an ``InvalidInputError``. The upload routes
answer it with 400 ``invalid_input`` and one fixed message, whether the file
is damaged, not an image, or in another format.

Pinned here:
1. The list names only registered reader IDs (not e.g. "MPO", which opens
   through "JPEG") and covers every image input the converters and
   compressors accept.
2. Every supported input still opens, including multi-picture JPEGs (MPO)
   and animated PNGs, which report a format name of their own.
3. A file in another Pillow format is refused, and no reader outside the
   list is asked about it.
4. The upload routes answer such a file and a non-image the same way.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

from app.compressors.image import _SUPPORTED_FORMATS as COMPRESS_INPUTS
from app.converters import image as image_converters
from app.converters.base import InvalidInputError
from app.core.image_hardening import _UNREADABLE_IMAGE, IMAGE_INPUT_FORMATS, open_image

# Readers Pillow ships for formats FileMorph doesn't accept, each able to
# write a sample in-process.
_OTHER_FORMATS = ("PCX", "TGA", "PPM", "SGI", "QOI")


def _encode(fmt: str, img: Image.Image | None = None, **params) -> bytes:
    img = img if img is not None else Image.new("RGB", (32, 24), (10, 120, 200))
    buf = io.BytesIO()
    img.save(buf, format=fmt, **params)
    return buf.getvalue()


def _two_frames(fmt: str) -> bytes:
    second = Image.new("RGB", (32, 24), (200, 40, 40))
    return _encode(fmt, save_all=True, append_images=[second])


def _avif() -> bytes:
    if not image_converters._avif_available:
        pytest.skip("pillow-avif-plugin not installed")
    return _encode("AVIF")


def _heif() -> bytes:
    if not image_converters._heif_available:
        pytest.skip("pillow-heif not installed")
    import pillow_heif

    if not pillow_heif.libheif_info().get("HEIF"):
        pytest.skip("pillow-heif has no HEIF encoder")
    return _encode("HEIF")


# ── The list itself ──────────────────────────────────────────────────────────


def test_allow_list_names_only_registered_readers():
    """``open_image`` skips names Pillow hasn't registered (``Image.open``
    would raise KeyError on them), so a wrong entry such as "MPO" or "HEIC"
    would silently allow nothing. Multi-picture JPEGs open through "JPEG"."""
    Image.init()
    optional = set() if image_converters._heif_available else {"HEIF"}
    unknown = set(IMAGE_INPUT_FORMATS) - optional - set(Image.OPEN)
    assert not unknown, f"not a Pillow reader ID: {sorted(unknown)}"


def test_allow_list_covers_every_image_input():
    """A format added to the converters or compressors must be added to the
    list too, or its uploads fail to open."""
    extensions = Image.registered_extensions()
    for ext in sorted(set(image_converters._IMAGE_FORMATS) | set(COMPRESS_INPUTS)):
        assert extensions.get(f".{ext}") in IMAGE_INPUT_FORMATS, ext


# ── Supported inputs still open ──────────────────────────────────────────────

_SUPPORTED = [
    pytest.param("JPEG", lambda: _encode("JPEG"), id="jpeg"),
    pytest.param("MPO", lambda: _two_frames("MPO"), id="mpo"),
    pytest.param("PNG", lambda: _encode("PNG"), id="png"),
    pytest.param("PNG", lambda: _two_frames("PNG"), id="apng"),
    pytest.param("GIF", lambda: _encode("GIF"), id="gif"),
    pytest.param("BMP", lambda: _encode("BMP"), id="bmp"),
    pytest.param("TIFF", lambda: _encode("TIFF"), id="tiff"),
    pytest.param("TIFF", lambda: _encode("TIFF", compression="jpeg"), id="tiff-jpeg"),
    pytest.param("WEBP", lambda: _encode("WEBP"), id="webp"),
    pytest.param("ICO", lambda: _encode("ICO", sizes=[(16, 16), (32, 32)]), id="ico-png"),
    pytest.param(
        "ICO", lambda: _encode("ICO", sizes=[(16, 16)], bitmap_format="bmp"), id="ico-bmp"
    ),
    pytest.param("AVIF", _avif, id="avif"),
    pytest.param("HEIF", _heif, id="heif"),
]


@pytest.mark.parametrize(("reported", "make"), _SUPPORTED)
def test_supported_inputs_open(reported, make):
    with open_image(io.BytesIO(make())) as im:
        im.load()
        assert im.format == reported


def test_multi_picture_jpeg_keeps_its_frames():
    with open_image(io.BytesIO(_two_frames("MPO"))) as im:
        assert im.format == "MPO"
        assert im.n_frames == 2


# ── Other formats are refused before their reader runs ──────────────────────


def _record(name: str, seen: list[str]):
    def reader_or_check(*_args, **_kwargs):
        seen.append(name)
        raise SyntaxError(f"{name} was asked")

    return reader_or_check


@pytest.mark.parametrize("fmt", _OTHER_FORMATS)
def test_other_formats_are_refused_unseen(fmt, monkeypatch):
    data = _encode(fmt)
    with Image.open(io.BytesIO(data)) as im:  # a real file of that format
        assert im.format == fmt
    Image.init()
    seen: list[str] = []
    for name in list(Image.OPEN):
        if name not in IMAGE_INPUT_FORMATS:
            spy = _record(name, seen)
            monkeypatch.setitem(Image.OPEN, name, (spy, spy))
    with pytest.raises(InvalidInputError) as refused:
        open_image(io.BytesIO(data))
    assert str(refused.value) == _UNREADABLE_IMAGE
    assert seen == []


def test_non_image_is_refused():
    with pytest.raises(InvalidInputError) as refused:
        open_image(io.BytesIO(b"plain text, not an image"))
    assert str(refused.value) == _UNREADABLE_IMAGE


# ── Routes: one fixed 400 for every unreadable image ─────────────────────────

_UNREADABLE_UPLOADS = [
    pytest.param(_encode("PCX"), id="pcx"),
    pytest.param(_encode("TGA"), id="tga"),
    pytest.param(b"plain text, not an image", id="text"),
]


def _assert_invalid_input(r) -> None:
    assert r.status_code == 400, r.text
    assert r.headers.get("X-FileMorph-Error-Code") == "invalid_input"
    assert r.json()["detail"] == _UNREADABLE_IMAGE


@pytest.mark.parametrize("target", ["jpg", "pdf"])
@pytest.mark.parametrize("payload", _UNREADABLE_UPLOADS)
def test_convert_answers_400(client, auth_headers, payload, target):
    r = client.post(
        "/api/v1/convert",
        headers=auth_headers,
        files={"file": ("photo.png", payload, "image/png")},
        data={"target_format": target},
    )
    _assert_invalid_input(r)


@pytest.mark.parametrize("form", [{"quality": "70"}, {"target_size_kb": "20"}], ids=["q", "kb"])
@pytest.mark.parametrize("payload", _UNREADABLE_UPLOADS)
def test_compress_answers_400(client, auth_headers, payload, form):
    r = client.post(
        "/api/v1/compress",
        headers=auth_headers,
        files={"file": ("photo.jpg", payload, "image/jpeg")},
        data=form,
    )
    _assert_invalid_input(r)


def test_convert_batch_reports_the_message(client, auth_headers):
    r = client.post(
        "/api/v1/convert/batch",
        headers=auth_headers,
        data={"target_formats": ["jpg"]},
        files=[("files", ("other.png", _encode("PCX"), "image/png"))],
    )
    assert r.status_code == 422, r.text
    assert r.json()["files"][0]["error_message"] == _UNREADABLE_IMAGE


def test_compress_batch_reports_the_message(client, auth_headers):
    r = client.post(
        "/api/v1/compress/batch",
        headers=auth_headers,
        data={"quality": "70"},
        files=[("files", ("other.jpg", _encode("TGA"), "image/jpeg"))],
    )
    assert r.status_code == 422, r.text
    assert r.json()["files"][0]["error_message"] == _UNREADABLE_IMAGE


# ── Routes: inputs that report their own format name still work ─────────────


def test_convert_multi_picture_jpeg(client, auth_headers):
    r = client.post(
        "/api/v1/convert",
        headers=auth_headers,
        files={"file": ("phone.jpg", _two_frames("MPO"), "image/jpeg")},
        data={"target_format": "png"},
    )
    assert r.status_code == 200, r.text
    assert Image.open(io.BytesIO(r.content)).format == "PNG"


def test_compress_multi_picture_jpeg(client, auth_headers):
    r = client.post(
        "/api/v1/compress",
        headers=auth_headers,
        files={"file": ("phone.jpg", _two_frames("MPO"), "image/jpeg")},
        data={"quality": "70"},
    )
    assert r.status_code == 200, r.text


def test_convert_heic(client, auth_headers):
    r = client.post(
        "/api/v1/convert",
        headers=auth_headers,
        files={"file": ("photo.heic", _heif(), "image/heic")},
        data={"target_format": "jpg"},
    )
    assert r.status_code == 200, r.text
    assert Image.open(io.BytesIO(r.content)).format == "JPEG"
