# SPDX-License-Identifier: AGPL-3.0-or-later
"""Compression never hands back a file larger than the original.

A photo from the web or a messenger is often compressed harder already than
the chosen quality: re-encoding it makes it larger. Then the original comes
back instead — without its metadata, put together anew from the parts that
make up the picture (``app/converters/_lossless_strip.py``), so the promise
to strip location and camera data still holds — with the warning token
``original=kept``; the page says so and labels the download "Download the
original without metadata". JPEG, PNG and WebP; TIFF, AVIF and video keep
the re-encode.
"""

import json
import random
import re
import struct
import zipfile
import zlib
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image, ImageCms, PngImagePlugin

from app.api.routes.auth import get_optional_user
from app.api.routes.compress import ORIGINAL_KEPT, keep_original
from app.converters._lossless_strip import original_without_metadata
from app.converters._metadata import ICC_MAX_BYTES
from app.main import app

APP_JS = (Path(__file__).resolve().parent.parent / "app" / "static" / "js" / "app.js").read_text(
    encoding="utf-8"
)
BLOB = re.compile(r'<script id="fm-i18n-strings" type="application/json">(.*?)</script>', re.DOTALL)
SRGB = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
XMP = b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:Description creator="Erika"/></x:xmpmeta>'


def _photo(size=(320, 240)) -> Image.Image:
    """A gradient with fixed grain: its file size follows the quality, as a photo's does."""
    grain = Image.frombytes("L", size, random.Random(7).randbytes(size[0] * size[1]))
    base = Image.linear_gradient("L").resize(size)
    return Image.merge("RGB", (base, grain, base.transpose(Image.Transpose.FLIP_LEFT_RIGHT)))


def _exif(orientation: int | None = None) -> bytes:
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"
    exif[0x8825] = {1: "N", 2: (53.0, 33.0, 12.0)}  # a GPS position
    if orientation:
        exif[0x0112] = orientation
    return exif.tobytes()


def _jpeg(quality=70, img=None, **options) -> bytes:
    buf = BytesIO()
    (img or _photo()).save(buf, format="JPEG", quality=quality, **options)
    return buf.getvalue()


def _encoded(img: Image.Image, fmt: str, **options) -> bytes:
    buf = BytesIO()
    img.save(buf, format=fmt, **options)
    return buf.getvalue()


def _pixels(data: bytes) -> bytes:
    with Image.open(BytesIO(data)) as img:
        return img.tobytes()


def _leaks(data: bytes) -> list[str]:
    found = [
        m.decode()
        for m in (b"PhoneMaker", b"Erika", b"secret", b"Photoshop", b"hidden")
        if m in data
    ]
    with Image.open(BytesIO(data)) as img:
        if 0x8825 in img.getexif():
            found.append("GPS")
    return found


def _segment(marker: int, body: bytes) -> bytes:
    return bytes((0xFF, marker)) + struct.pack(">H", len(body) + 2) + body


def _after_jfif(data: bytes) -> int:
    """Where the JFIF segment Pillow writes first ends."""
    assert data[2:4] == b"\xff\xe0"
    return 4 + struct.unpack(">H", data[4:6])[0]


def _png_chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    chunks, pos = [], 8
    while pos < len(data):
        length = struct.unpack(">I", data[pos : pos + 4])[0]
        chunks.append((data[pos + 4 : pos + 8], data[pos + 8 : pos + 8 + length]))
        pos += 12 + length
    return chunks


def _png(chunks: list[tuple[bytes, bytes]]) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"".join(
        struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        for kind, body in chunks
    )


# ── JPEG ─────────────────────────────────────────────────────────────────────


def test_a_jpeg_loses_its_metadata_and_nothing_else():
    original = _jpeg(exif=_exif(), xmp=XMP, comment=b"secret note", icc_profile=SRGB)
    app13 = b"Photoshop 3.0\x00" + b"8BIM\x04\x04" + b"\x00" * 30
    original = (
        original[:2] + _segment(0xED, app13) + original[2:] + b"a second picture or gain map" * 50
    )
    stripped = original_without_metadata(original, "JPEG")
    assert stripped is not None
    assert len(stripped) < len(original)
    assert _leaks(original) and not _leaks(stripped)
    assert b"second picture" not in stripped
    assert _pixels(stripped) == _pixels(original)
    with Image.open(BytesIO(stripped)) as img:
        assert img.info.get("icc_profile") == SRGB


def test_a_progressive_jpeg_keeps_all_its_scans():
    original = _jpeg(progressive=True, exif=_exif())
    stripped = original_without_metadata(original, "JPEG")
    assert stripped is not None and not _leaks(stripped)
    assert _pixels(stripped) == _pixels(original)


def test_restart_markers_and_fill_bytes_are_followed():
    original = _jpeg(restart_marker_blocks=4, exif=_exif())
    tables = original.index(b"\xff\xdb")
    original = original[:tables] + b"\xff\xff\xff" + original[tables:]  # fill bytes
    stripped = original_without_metadata(original, "JPEG")
    assert stripped is not None and not _leaks(stripped)
    assert b"\xff\xd0" in stripped, "the restart markers stay in the scan"
    assert _pixels(stripped) == _pixels(original)


def test_a_turned_photo_keeps_only_its_orientation():
    original = _jpeg(exif=_exif(orientation=6))
    stripped = original_without_metadata(original, "JPEG")
    assert stripped is not None and not _leaks(stripped)
    with Image.open(BytesIO(stripped)) as img:
        assert dict(img.getexif()) == {0x0112: 6}


def test_a_phone_mpo_comes_back_as_its_first_picture():
    """Pillow reads a JPEG with a second view or depth map as MPO."""
    first, second = _photo(), _photo().transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    buf = BytesIO()
    first.save(buf, format="MPO", save_all=True, append_images=[second], exif=_exif())
    original = buf.getvalue()
    with Image.open(BytesIO(original), formats=["JPEG"]) as img:
        assert (img.format, img.n_frames) == ("MPO", 2)
        first_pixels = img.tobytes()
    stripped = original_without_metadata(original, "JPEG")
    assert stripped is not None and not _leaks(stripped)
    with Image.open(BytesIO(stripped)) as img:
        assert img.format == "JPEG" and img.tobytes() == first_pixels


def test_jfif_and_adobe_keep_only_what_libjpeg_reads():
    """No thumbnail in JFIF, nothing past Adobe's colour transform."""
    base = _jpeg()
    jfif = b"JFIF\x00\x01\x02\x00\x00\x01\x00\x01\x04\x04" + b"secret thumb" * 4  # 4 × 4 RGB
    jfxx = b"JFXX\x00\x10" + _jpeg(quality=20, img=_photo((16, 16)), comment=b"secret")
    adobe = b"Adobe\x00\x64\x00\x00\x00\x00\x01" + b"hidden"
    original = (
        base[:2]
        + _segment(0xE0, jfif)
        + _segment(0xE0, jfxx)
        + _segment(0xEE, adobe)
        + base[_after_jfif(base) :]
    )
    stripped = original_without_metadata(original, "JPEG")
    assert stripped is not None and not _leaks(stripped)
    assert stripped[2:20] == b"\xff\xe0\x00\x10" + jfif[:12] + b"\x00\x00"
    assert _segment(0xEE, adobe[:12]) in stripped
    assert _pixels(stripped) == _pixels(original)


def test_a_cmyk_jpeg_keeps_its_colours():
    """Adobe's segment says how to read four colour components."""
    original = _jpeg(img=_photo().convert("CMYK"), exif=_exif())
    stripped = original_without_metadata(original, "JPEG")
    assert stripped is not None and not _leaks(stripped)
    assert b"\xff\xee\x00\x0eAdobe" in stripped
    assert _pixels(stripped) == _pixels(original)


def test_the_colour_profile_is_written_anew():
    base = _jpeg()
    end = _after_jfif(base)
    no_profile = _segment(0xE2, b"ICC_PROFILE\x00\x01\x01" + b"secret" * 8)
    two_profiles = _segment(0xE2, b"ICC_PROFILE\x00\x01\x01" + SRGB) + _segment(
        0xE2, b"ICC_PROFILE\x00\x01\x01" + SRGB[:-6] + b"secret"
    )
    for segments in (no_profile, two_profiles):
        stripped = original_without_metadata(base[:end] + segments + base[end:], "JPEG")
        assert stripped is not None and not _leaks(stripped)
        with Image.open(BytesIO(stripped)) as img:
            assert not img.info.get("icc_profile"), "readers find no profile in them"

    large = SRGB + bytes(200_000)  # in four segments
    with Image.open(BytesIO(original_without_metadata(_jpeg(icc_profile=large), "JPEG"))) as img:
        assert img.info["icc_profile"] == large
    huge = SRGB + bytes(ICC_MAX_BYTES)  # dropped, as the re-encode drops it
    with Image.open(BytesIO(original_without_metadata(_jpeg(icc_profile=huge), "JPEG"))) as img:
        assert not img.info.get("icc_profile")


def test_a_jpeg_with_far_more_parts_or_tables_than_a_photo_keeps_the_re_encode():
    """Walking them would cost more than decoding the picture; tables no
    picture needs could carry anything."""
    base = _jpeg()
    end = _after_jfif(base)
    comments = _segment(0xFE, b"")
    assert original_without_metadata(base[:end] + comments * 100 + base[end:], "JPEG")
    assert original_without_metadata(base[:end] + comments * 5000 + base[end:], "JPEG") is None
    assert original_without_metadata(base[:end] + b"\xff" * 5000 + base[end:], "JPEG") is None
    start = base.index(b"\xff\xc4")  # a Huffman table
    table = base[start : start + 2 + struct.unpack(">H", base[start + 2 : start + 4])[0]]
    assert original_without_metadata(base[:end] + table * 3 + base[end:], "JPEG")
    copies = (1 << 16) // len(table) + 1
    assert original_without_metadata(base[:end] + table * copies + base[end:], "JPEG") is None


def test_a_segment_it_does_not_know_keeps_the_re_encode():
    base = _jpeg()
    end = _after_jfif(base)
    assert (
        original_without_metadata(base[:-2] + _segment(0xDC, b"\x00\xf0") + base[-2:], "JPEG")
        is None
    )
    assert original_without_metadata(base[:end] + b"hidden" + base[end:], "JPEG") is None


# ── PNG ──────────────────────────────────────────────────────────────────────


def test_a_png_loses_its_text_and_exif_but_keeps_its_profile():
    info = PngImagePlugin.PngInfo()
    info.add_text("Author", "Erika Mustermann")
    info.add_itxt("Comment", "secret note")
    original = _encoded(
        _photo(), "PNG", pnginfo=info, icc_profile=SRGB, exif=_exif(), dpi=(300, 300)
    )
    stripped = original_without_metadata(original, "PNG")
    assert stripped is not None and not _leaks(stripped)
    assert _pixels(stripped) == _pixels(original)
    with Image.open(BytesIO(stripped)) as img:
        assert img.info.get("icc_profile") == SRGB
        assert round(img.info["dpi"][0]) == 300, "pixel size is not metadata"
        assert not img.getexif()


def test_a_png_profile_loses_its_name():
    """The name of a PNG's profile is text its user chose."""
    chunks = _png_chunks(_encoded(_photo(), "PNG"))
    chunks.insert(1, (b"iCCP", b"Erika's MacBook\x00\x00" + zlib.compress(SRGB)))
    stripped = original_without_metadata(_png(chunks), "PNG")
    assert stripped is not None and not _leaks(stripped)
    with Image.open(BytesIO(stripped)) as img:
        assert img.info["icc_profile"] == SRGB


# Adam7: each pass's first column and row and its steps.
ADAM7 = (
    (0, 0, 8, 8),
    (4, 0, 8, 8),
    (0, 4, 4, 8),
    (2, 0, 4, 4),
    (0, 2, 2, 4),
    (1, 0, 2, 2),
    (0, 1, 1, 2),
)


def test_a_png_keeps_each_chunk_once_and_only_what_draws_the_picture():
    chunks = _png_chunks(_encoded(_photo(), "PNG"))
    palette = (b"PLTE", b"hidden" * 128)  # a truecolour picture's suggested palette
    stripped = original_without_metadata(_png([chunks[0], palette, *chunks[1:]]), "PNG")
    assert stripped is not None and not _leaks(stripped)
    gamma = (b"gAMA", struct.pack(">I", 45455))
    assert original_without_metadata(_png([chunks[0], gamma, gamma, *chunks[1:]]), "PNG") is None


def test_every_png_chunk_gets_a_fresh_crc():
    """Pillow doesn't check the pixel stream's CRC: the old one could carry
    four bytes of anything."""
    png = _encoded(_photo(), "PNG")
    start = png.index(b"IDAT")
    length = struct.unpack(">I", png[start - 4 : start])[0]
    crafted = png[: start + 4 + length] + b"\xde\xad\xbe\xef" + png[start + 8 + length :]
    stripped = original_without_metadata(crafted, "PNG")
    assert stripped is not None and b"\xde\xad\xbe\xef" not in stripped
    assert _pixels(stripped) == _pixels(png)


def _interlaced(img: Image.Image) -> bytes:
    """An RGB picture as an Adam7-interlaced PNG, which Pillow doesn't write."""
    width, height = img.size
    pixels = img.tobytes()
    raw = bytearray()
    for left, top, dx, dy in ADAM7:
        for y in range(top, height, dy):
            row = b"".join(pixels[3 * (y * width + x) :][:3] for x in range(left, width, dx))
            if row:
                raw += b"\x00" + row  # filter type 0
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 1)
    chunks = [(b"IHDR", header), (b"tEXt", b"Author\x00Erika"), (b"IDAT", zlib.compress(raw))]
    return _png([*chunks, (b"IEND", b"")])


@pytest.mark.parametrize(
    "original",
    [
        _encoded(_photo().convert("P"), "PNG", transparency=0),
        _encoded(_photo().convert("RGBA"), "PNG"),
        _encoded(_photo().convert("LA"), "PNG"),
        _encoded(_photo().convert("1"), "PNG"),
        _encoded(_photo().convert("L").convert("I;16"), "PNG"),
        _encoded(_photo((1200, 900)), "PNG"),  # several IDAT chunks
        _interlaced(_photo((13, 11))),
    ],
    ids=["palette", "rgba", "grey-alpha", "bilevel", "16-bit", "large", "interlaced"],
)
def test_every_kind_of_png_keeps_its_pixels(original):
    stripped = original_without_metadata(original, "PNG")
    assert stripped is not None and not _leaks(stripped)
    with Image.open(BytesIO(original)) as a, Image.open(BytesIO(stripped)) as b:
        assert (b.mode, b.size, b.tobytes()) == (a.mode, a.size, a.tobytes())
        assert b.info.get("transparency") == a.info.get("transparency")


def test_a_png_holding_more_than_its_picture_keeps_the_re_encode():
    chunks = _png_chunks(_encoded(_photo(), "PNG"))
    last = max(i for i, (kind, _) in enumerate(chunks) if kind == b"IDAT")
    after_stream = [*chunks[:last], (b"IDAT", chunks[last][1] + b"hidden"), *chunks[last + 1 :]]
    extra_idat = [*chunks[: last + 1], (b"IDAT", b"hidden"), *chunks[last + 1 :]]
    rows = zlib.decompress(b"".join(body for kind, body in chunks if kind == b"IDAT"))
    extra_row = rows + b"\x00" + b"hidden".ljust(320 * 3, b"\x00")
    idat = [i for i, (kind, _) in enumerate(chunks) if kind == b"IDAT"]
    more_rows = [*chunks[: idat[0]], (b"IDAT", zlib.compress(extra_row)), *chunks[last + 1 :]]
    long_phys = [chunks[0], (b"pHYs", struct.pack(">IIB", 2835, 2835, 1) + b"hidden"), *chunks[1:]]
    for parts in (after_stream, extra_idat, more_rows, long_phys):
        assert original_without_metadata(_png(parts), "PNG") is None


# ── WebP ─────────────────────────────────────────────────────────────────────


def test_a_webp_loses_exif_and_xmp_but_keeps_its_profile():
    original = _encoded(_photo(), "WEBP", quality=70, exif=_exif(), xmp=XMP, icc_profile=SRGB)
    stripped = original_without_metadata(original, "WEBP")
    assert stripped is not None and not _leaks(stripped)
    assert _pixels(stripped) == _pixels(original)
    with Image.open(BytesIO(stripped)) as img:
        assert img.info.get("icc_profile") == SRGB
        assert not img.getexif()
    assert stripped[20] & 0x0C == 0, "the VP8X header no longer announces EXIF or XMP"


@pytest.mark.parametrize(
    "options", [{"lossless": True}, {"quality": 70}], ids=["lossless", "lossy"]
)
def test_a_webp_keeps_its_transparency(options):
    img = _photo().convert("RGBA")
    img.putalpha(Image.linear_gradient("L").resize(img.size))
    original = _encoded(img, "WEBP", exif=_exif(), **options)
    stripped = original_without_metadata(original, "WEBP")
    assert stripped is not None and not _leaks(stripped)
    assert _pixels(stripped) == _pixels(original)


def test_a_webp_with_far_more_chunks_than_a_photo_keeps_the_re_encode():
    original = _encoded(_photo(), "WEBP", quality=70, exif=_exif())

    def padded(count: int) -> bytes:
        body = original[12:] + b"ZZZZ\x00\x00\x00\x00" * count
        return b"RIFF" + struct.pack("<I", len(body) + 4) + b"WEBP" + body

    assert original_without_metadata(padded(100), "WEBP")
    assert original_without_metadata(padded(5000), "WEBP") is None


def test_what_follows_the_riff_end_goes():
    original = _encoded(_photo(), "WEBP", quality=70) + b"ICCP\x06\x00\x00\x00hidden"
    stripped = original_without_metadata(original, "WEBP")
    assert stripped is not None and not _leaks(stripped)
    assert _pixels(stripped) == _pixels(original)


# ── What keeps the re-encode ─────────────────────────────────────────────────


@pytest.mark.parametrize("fmt", ["PNG", "WEBP"])
def test_an_animation_keeps_the_re_encode(fmt):
    """The re-encode keeps only the first frame; there is no picture to compare."""
    frames = [Image.new("RGB", (40, 30), c) for c in ("red", "green", "blue")]
    original = _encoded(frames[0], fmt, save_all=True, append_images=frames[1:], exif=_exif())
    assert original_without_metadata(original, fmt) is None


@pytest.mark.parametrize("fmt", ["PNG", "WEBP"])
def test_a_turned_png_or_webp_is_left_alone(fmt):
    """Dropping the orientation mark would turn the picture."""
    original = _encoded(_photo(), fmt, exif=_exif(orientation=6))
    assert original_without_metadata(original, fmt) is None


def test_what_it_does_not_follow_stays_a_re_encode():
    assert original_without_metadata(b"not an image", "JPEG") is None
    assert original_without_metadata(_jpeg(), "PNG") is None, "the wrong format"
    assert original_without_metadata(_encoded(_photo(), "TIFF"), "TIFF") is None, (
        "no strip for TIFF"
    )
    # An unknown critical PNG chunk is not ours to judge.
    chunks = _png_chunks(_encoded(_photo(), "PNG"))
    assert original_without_metadata(_png([chunks[0], (b"ZZZZ", b""), *chunks[1:]]), "PNG") is None


# ── keep_original ─────────────────────────────────────────────────────────────


def test_keep_original_replaces_only_a_result_that_is_not_smaller(tmp_path):
    src, out = tmp_path / "in.jpg", tmp_path / "out.jpg"
    src.write_bytes(_jpeg(quality=60, exif=_exif()))
    out.write_bytes(_jpeg(quality=95))  # larger than the upload
    size = keep_original(src, out, "jpg", None)
    assert size == out.stat().st_size < src.stat().st_size
    assert not _leaks(out.read_bytes())

    out.write_bytes(_jpeg(quality=20))  # smaller: it stays
    before = out.read_bytes()
    assert keep_original(src, out, "jpg", None) is None
    assert out.read_bytes() == before


def test_keep_original_respects_the_target_and_the_format(tmp_path):
    src, out = tmp_path / "in.jpg", tmp_path / "out.jpg"
    src.write_bytes(_jpeg(quality=60))
    out.write_bytes(_jpeg(quality=95))
    assert keep_original(src, out, "jpg", target_bytes=100) is None, (
        "the original misses the target"
    )
    tif_in, tif_out = tmp_path / "in.tif", tmp_path / "out.tif"
    _photo().save(tif_in, format="TIFF", compression="jpeg")
    _photo().save(tif_out, format="TIFF")
    assert keep_original(tif_in, tif_out, "tif", None) is None


# ── The routes ───────────────────────────────────────────────────────────────


def test_compressing_an_already_compressed_photo_returns_the_original(client, auth_headers):
    original = _jpeg(quality=60, exif=_exif(), comment=b"secret note")
    r = client.post(
        "/api/v1/compress",
        headers=auth_headers,
        files={"file": ("photo.jpg", original, "image/jpeg")},
        data={"quality": "90"},
    )
    assert r.status_code == 200, r.text
    assert ORIGINAL_KEPT in r.headers.get("X-FileMorph-Warnings", "").split(",")
    assert len(r.content) < len(original)
    assert _pixels(r.content) == _pixels(original)
    assert not _leaks(r.content)


def test_a_photo_that_does_get_smaller_is_re_encoded(client, auth_headers):
    original = _jpeg(quality=98, exif=_exif())
    r = client.post(
        "/api/v1/compress",
        headers=auth_headers,
        files={"file": ("photo.jpg", original, "image/jpeg")},
        data={"quality": "60"},
    )
    assert r.status_code == 200
    assert ORIGINAL_KEPT not in r.headers.get("X-FileMorph-Warnings", "")
    assert len(r.content) < len(original) and not _leaks(r.content)


def test_a_png_that_would_grow_comes_back_without_its_text(client, auth_headers, monkeypatch):
    """A PNG packed tighter already (zopfli, oxipng) grows when repacked."""

    def repack_loosely(input_path, output_path, quality=85):
        with Image.open(input_path) as img:
            img.save(output_path, format="PNG", compress_level=0)
        return output_path

    monkeypatch.setattr("app.api.routes.compress.compress_image", repack_loosely)
    info = PngImagePlugin.PngInfo()
    info.add_text("Author", "Erika Mustermann")
    original = _encoded(_photo(), "PNG", pnginfo=info)
    r = client.post(
        "/api/v1/compress",
        headers=auth_headers,
        files={"file": ("shot.png", original, "image/png")},
    )
    assert r.status_code == 200, r.text
    assert r.headers["X-FileMorph-Warnings"] == ORIGINAL_KEPT
    assert not _leaks(r.content) and _pixels(r.content) == _pixels(original)


def test_target_size_returns_the_original_when_it_already_fits(client, auth_headers):
    """The search's quality-95 shortcut would hand back a larger file."""
    original = _jpeg(quality=60, exif=_exif())
    r = client.post(
        "/api/v1/compress",
        headers=auth_headers,
        files={"file": ("photo.jpg", original, "image/jpeg")},
        data={"target_size_kb": "500"},
    )
    assert r.status_code == 200
    assert r.headers["X-FileMorph-Warnings"] == ORIGINAL_KEPT
    assert r.headers["X-FileMorph-Achieved-Bytes"] == str(len(r.content))
    assert r.headers["X-FileMorph-Converged"] == "true"
    assert "X-FileMorph-Final-Quality" not in r.headers, "no quality was chosen"
    assert len(r.content) < len(original)


def test_a_missed_target_keeps_the_re_encode(client, auth_headers, monkeypatch):
    """The original comes back only if it fits the target."""

    def missed(input_path, output_path, target_bytes):
        output_path.write_bytes(_jpeg(quality=95))  # larger than the upload and the target
        size = output_path.stat().st_size
        return {
            "final_quality": 1,
            "achieved_bytes": size,
            "iterations": 9,
            "converged": False,
            "resized_to": None,
        }

    monkeypatch.setattr("app.api.routes.compress.compress_image_to_target", missed)
    r = client.post(
        "/api/v1/compress",
        headers=auth_headers,
        files={"file": ("photo.jpg", _jpeg(quality=60, exif=_exif()), "image/jpeg")},
        data={"target_size_kb": "5"},
    )
    assert r.status_code == 200
    assert r.headers["X-FileMorph-Warnings"] == "target=missed"
    assert r.headers["X-FileMorph-Final-Quality"] == "1"
    assert r.headers["X-FileMorph-Converged"] == "false"


@pytest.fixture
def batch_user():
    """A free account: batches of more than one file (tests/test_compress_batch.py)."""
    user = MagicMock()
    user.tier.value = "free"
    app.dependency_overrides[get_optional_user] = lambda: user
    yield
    app.dependency_overrides.pop(get_optional_user, None)


def test_a_batch_notes_each_kept_original(client, auth_headers, batch_user):
    files = [
        ("files", ("web.jpg", _jpeg(quality=60, exif=_exif()), "image/jpeg")),
        ("files", ("camera.jpg", _jpeg(quality=98), "image/jpeg")),
    ]
    r = client.post(
        "/api/v1/compress/batch", headers=auth_headers, files=files, data={"quality": "85"}
    )
    assert r.status_code == 200
    notes = r.headers.get("X-FileMorph-Batch-Notes", "")
    assert "web_compressed.jpg|" + ORIGINAL_KEPT in notes.replace("%3D", "=")
    assert "camera" not in notes
    with zipfile.ZipFile(BytesIO(r.content)) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        assert not _leaks(zf.read("web_compressed.jpg"))
    assert {f["name"]: f["notes"] for f in manifest["files"]} == {
        "web_compressed.jpg": [ORIGINAL_KEPT],
        "camera_compressed.jpg": [],
    }


# ── The page ─────────────────────────────────────────────────────────────────


def test_the_page_says_the_original_came_back():
    label = APP_JS.split("function targetNoteLabel(", 1)[1].split("\n}\n", 1)[0]
    assert "key === 'original' && value === 'kept'" in label
    assert "i18n.warningOriginalKept" in label
    result = APP_JS.split("const keptOriginal = !isBatch", 1)[1].split("} else {", 1)[0]
    assert ".split(',').includes('original=kept')" in result
    assert "i18nText('downloadOriginal'" in result
    assert "i18nText('downloadOriginalSize'" in result


def test_the_note_box_does_not_say_compressed_for_the_original():
    """No success that didn't happen (.claude/rules/product-ux.md)."""
    box = APP_JS.split("function showConversionWarnings(", 1)[1].split("\n}\n", 1)[0]
    kept = box.index("rawHeader.split(',').includes('original=kept')")
    assert (
        kept
        < box.index("i18n.compressionOriginalTitle")
        < box.index("i18n.compressionWarningTitle")
    )


def test_the_estimate_says_the_original_would_come_back():
    show = APP_JS.split("function showSizeEstimate(", 1)[1].split("\n}\n", 1)[0]
    branch = show.index("state === 'value' && sizes.after >= sizes.before")
    assert branch < show.index("i18nText('sizeEstimateOriginal'")
    assert branch < show.index("i18nText('sizeEstimate', ")


def test_the_texts_are_german_on_de(client):
    de = json.loads(BLOB.search(client.get("/de/compress").text).group(1))
    assert de["downloadOriginal"] == "Original ohne Metadaten herunterladen"
    assert de["compressionOriginalTitle"] == "Dein Original, ohne Metadaten"
    assert de["warningOriginalKept"] == (
        "Mit dieser Einstellung wäre die Datei nicht kleiner geworden. Du bekommst dein "
        "Original zurück, ohne Orts- und Kameradaten."
    )
    assert de["sizeEstimateOriginal"] == "Mit dieser Qualität wird die Datei nicht kleiner"
