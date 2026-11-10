# SPDX-License-Identifier: AGPL-3.0-or-later
"""An image keeps its resolution.

A fax in normal mode is scanned at 204 dpi across and 98 down: its pixels
are twice as tall as wide, and only its resolution says so. Converted to
PDF, a TIFF page gets the size its resolution gives it — one without, 150
dpi as before — and each page of a multi-page TIFF its own. PNG, JPEG, TIFF
and BMP results keep the resolution, compressed or converted; a quarter turn
swaps it. Any other picture still becomes a 150-dpi PDF page.
"""

import random
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter, apply_configuration
from pypdf.generic import ContentStream

from app.compressors.image import compress_image, compress_image_to_target
from app.converters import image as image_converter
from app.converters._metadata import _DPI_RANGE, strip_metadata
from app.converters.base import OutputTooLargeError

FORMATS_MD = Path(__file__).resolve().parent.parent / "docs" / "formats.md"

NORMAL = (204, 98)  # dpi across, down
FINE = (204, 196)
# A fax page in points: 1 728 dots across at 204 dpi, 1 078 lines down at 98
# (2 156 at 196) — a US letter page, 8.47 × 11 inches.
LETTER = (609.88, 792.0)


def _fax(lines: int = 1078) -> Image.Image:
    return Image.new("1", (1728, lines), 1)


def _tiff(pages: list[Image.Image], dpis: list, **options) -> bytes:
    """A TIFF of ``pages``, each with its resolution (``None``: none)."""
    for page, dpi in zip(pages, dpis, strict=True):
        page.encoderinfo = {"dpi": dpi}
    buf = BytesIO()
    pages[0].save(buf, format="TIFF", save_all=True, append_images=pages[1:], **options)
    return buf.getvalue()


def _tiff_resolutions(data: bytes) -> list[tuple[float, float] | None]:
    """Each page's resolution tags, ``None`` where it has none."""
    found = []
    with Image.open(BytesIO(data)) as img:
        for index in range(img.n_frames):
            img.seek(index)
            tags = img.tag_v2
            found.append((float(tags[282]), float(tags[283])) if 282 in tags else None)
    return found


def _drawn(page) -> tuple[float, float]:
    """The size the page draws its image at: Pillow's page draws it into the
    unit square of the matrices (``cm``) in force, all of them scales."""
    width = height = 1.0
    for operands, operator in ContentStream(page.get_contents(), page.pdf).operations:
        if operator == b"cm":
            width, height = width * float(operands[0]), height * float(operands[3])
        elif operator == b"Do":
            return round(width, 2), round(height, 2)
    raise AssertionError("no image drawn")


def _sizes(pdf: bytes) -> list[tuple[float, float]]:
    """Each page's width and height in points, as viewers show it: its crop
    box, or without one its media box."""
    return [
        (round(float(page.cropbox.width), 2), round(float(page.cropbox.height), 2))
        for page in PdfReader(BytesIO(pdf)).pages
    ]


def _a4_pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    base = BytesIO()
    writer.write(base)
    return base.getvalue()


def _insert(client, auth_headers, data: bytes):
    return client.post(
        "/api/v1/pdf/insert",
        headers=auth_headers,
        files={
            "file": ("report.pdf", _a4_pdf(), "application/pdf"),
            "insert_file": ("fax.tiff", data, "image/tiff"),
        },
    )


def _convert(client, auth_headers, data: bytes, target: str, name: str = "fax.tiff"):
    mime = "image/jpeg" if name.endswith(".jpg") else "image/tiff"
    return client.post(
        "/api/v1/convert",
        headers=auth_headers,
        files={"file": (name, data, mime)},
        data={"target_format": target},
    )


# ── TIFF → PDF ───────────────────────────────────────────────────────────────


def test_a_fax_in_normal_mode_becomes_a_letter_page(client, auth_headers):
    """At 150 dpi each way it was 11.52 × 7.19 inches: on its side, squashed."""
    r = _convert(client, auth_headers, _tiff([_fax()], [NORMAL], compression="group4"), "pdf")
    assert r.status_code == 200, r.text
    assert _sizes(r.content) == [LETTER]


@pytest.mark.parametrize("first", ["normal", "none"])
def test_each_page_gets_its_own_size(client, auth_headers, first):
    """A fax can mix normal and fine pages. Pillow's PDF writer sizes every
    page by the first page's resolution, so the others are scaled to theirs
    afterwards, their image with them. A page without one is a 150-dpi page,
    as before."""
    pages = [_fax(), _fax(2156), Image.new("1", (300, 150), 1)]
    dpis, sizes = [NORMAL, FINE, None], [LETTER, LETTER, (144.0, 72.0)]
    if first == "none":
        pages, dpis, sizes = pages[::-1], dpis[::-1], sizes[::-1]
    r = _convert(client, auth_headers, _tiff(pages, dpis, compression="group4"), "pdf")
    assert r.status_code == 200, r.text
    assert _sizes(r.content) == sizes
    reader = PdfReader(BytesIO(r.content))
    assert [_drawn(page) for page in reader.pages] == sizes


@pytest.mark.parametrize("dpis", [[NORMAL], [NORMAL, FINE]], ids=["one-page", "normal-and-fine"])
def test_an_inserted_fax_page_stands_upright(client, auth_headers, dpis):
    """An inserted page takes its neighbour's size, turned to the image's
    orientation: a fax page wider than tall turned the A4 page on its side.
    A fine page, scaled to its size first, keeps no box of that size to
    crop it by."""
    pages = [_fax(1078 if dpi == NORMAL else 2156) for dpi in dpis]
    r = _insert(client, auth_headers, _tiff(pages, dpis, compression="group4"))
    assert r.status_code == 200, r.text
    assert _sizes(r.content) == [(595.0, 842.0)] * (1 + len(dpis))


def test_a_page_larger_than_acrobat_shows_is_made_smaller(client, auth_headers):
    """At 10 dpi, 3 000 dots are 300 inches; Acrobat shows 200 at most."""
    data = _tiff([Image.new("1", (3000, 100), 1)], [(10, 10)])
    r = _convert(client, auth_headers, data, "pdf")
    assert r.status_code == 200, r.text
    assert _sizes(r.content) == [(14400.0, 480.0)]


def test_a_thin_crafted_page_is_still_a_page_viewers_read(client, auth_headers):
    """Made smaller, a page one dot high at 10 000 dpi down would be under a
    ten-thousandth of a point, which Pillow writes as 9.6e-05: no PDF number.
    The resolution goes no higher than a measured one; the page stays as
    large as the file says."""
    data = _tiff([Image.new("1", (150_000, 1), 1)], [(10, 10_000)])
    r = _convert(client, auth_headers, data, "pdf")
    assert r.status_code == 200, r.text
    assert _sizes(r.content) == [(1_080_000.0, 0.01)]


def test_a_file_over_the_output_cap_is_not_resized_first(tmp_path, monkeypatch):
    monkeypatch.setattr(
        image_converter, "_size_pages", lambda *a: pytest.fail("resized a refused file")
    )
    src = tmp_path / "fax.tiff"
    src.write_bytes(_tiff([_fax(), _fax(2156)], [NORMAL, FINE], compression="group4"))
    with pytest.raises(OutputTooLargeError):
        image_converter._ImageToPdfConverter().convert(
            src, tmp_path / "out.pdf", max_output_bytes=100
        )


def test_resizing_reads_back_streams_of_any_length(tmp_path):
    """pypdf refuses a stream declared longer than its limit (75 MB, against
    crafted files); a page of the PDF Pillow just wrote may be longer, once
    an operator raises the image size limit."""
    src, out = tmp_path / "fax.tiff", tmp_path / "out.pdf"
    src.write_bytes(_tiff([_fax(), _fax(2156)], [NORMAL, FINE], compression="group4"))
    with apply_configuration(maximum_declared_stream_length=100):
        image_converter._ImageToPdfConverter().convert(src, out)
    assert _sizes(out.read_bytes()) == [LETTER, LETTER]


def test_a_photo_is_still_a_150_dpi_page(client, auth_headers):
    """A camera's 72 dpi is a default, not a size: any picture but a TIFF
    page stays a 150-dpi page, as the image → PDF pages say."""
    buf = BytesIO()
    Image.new("RGB", (300, 150)).save(buf, format="JPEG", dpi=(72, 72))
    r = _convert(client, auth_headers, buf.getvalue(), "pdf", name="photo.jpg")
    assert r.status_code == 200, r.text
    assert _sizes(r.content) == [(144.0, 72.0)]


# ── Compress and convert ─────────────────────────────────────────────────────


@pytest.mark.parametrize("mode", ["1", "RGB"])  # the two ways save_tiff packs
def test_compressing_a_tiff_keeps_each_pages_resolution(tmp_path, mode):
    pages = [_fax().convert(mode), _fax(2156).convert(mode), Image.new(mode, (300, 150))]
    src, out = tmp_path / "fax.tiff", tmp_path / "out.tiff"
    src.write_bytes(_tiff(pages, [NORMAL, FINE, None]))
    compress_image(src, out)
    assert _tiff_resolutions(out.read_bytes()) == [NORMAL, FINE, None]


@pytest.mark.parametrize("target", ["tif", "png", "jpg", "bmp"])
def test_a_converted_fax_keeps_its_resolution(client, auth_headers, target):
    r = _convert(client, auth_headers, _tiff([_fax()], [NORMAL], compression="group4"), target)
    assert r.status_code == 200, r.text
    with Image.open(BytesIO(r.content)) as img:
        # PNG and BMP store dots per metre: 204 dpi comes back as 203.99.
        assert img.info["dpi"] == pytest.approx(NORMAL, abs=0.02)


@pytest.mark.parametrize("fmt", ["PNG", "JPEG"])
def test_compressing_a_png_or_jpeg_keeps_its_resolution(tmp_path, fmt):
    """The re-encode writes it back: a PNG's pHYs chunk, a JPEG's JFIF header."""
    src, out = tmp_path / f"scan.{fmt.lower()}", tmp_path / f"out.{fmt.lower()}"
    Image.linear_gradient("L").convert("RGB").save(src, format=fmt, dpi=(300, 300))
    compress_image(src, out, quality=60)
    with Image.open(out) as img:
        assert img.info["dpi"] == pytest.approx((300, 300), abs=0.02)


def test_scaling_to_a_target_size_keeps_the_size_on_paper(tmp_path):
    """Fewer pixels for the same page: the resolution drops with them."""
    src, out = tmp_path / "scan.jpg", tmp_path / "out.jpg"
    noise = random.Random(1).randbytes(800 * 600 * 3)
    Image.frombytes("RGB", (800, 600), noise).save(src, format="JPEG", quality=95, dpi=(300, 300))
    result = compress_image_to_target(src, out, target_bytes=2_000)
    assert result["converged"] and result["resized_to"], result
    width, height = result["resized_to"]
    with Image.open(out) as img:
        assert img.info["dpi"] == (round(300 * width / 800), round(300 * height / 600))


# ── Turned, or no measurement ────────────────────────────────────────────────


def test_a_quarter_turn_swaps_the_resolution(tmp_path, client, auth_headers):
    exif = Image.Exif()
    exif[0x0112] = 6  # orientation: turned a quarter
    src, out = tmp_path / "photo.jpg", tmp_path / "out.jpg"
    Image.new("RGB", (40, 20)).save(src, format="JPEG", dpi=NORMAL, exif=exif.tobytes())
    compress_image(src, out)
    with Image.open(out) as img:
        assert (img.size, img.info["dpi"]) == ((20, 40), NORMAL[::-1])

    # A fax page stored on its side: Pillow turns a TIFF page as it loads
    # it, and as a PNG it is loaded before it is stripped (_usable).
    data = _tiff([Image.new("1", (1078, 1728), 1)], [NORMAL[::-1]], tiffinfo={274: 6})
    r = _convert(client, auth_headers, data, "pdf")
    assert _sizes(r.content) == [LETTER]
    r = _convert(client, auth_headers, data, "png")
    with Image.open(BytesIO(r.content)) as img:
        assert img.size == (1728, 1078)
        assert img.info["dpi"] == pytest.approx(NORMAL, abs=0.02)
    src, out = tmp_path / "fax.tiff", tmp_path / "out.tiff"
    src.write_bytes(data)
    compress_image(src, out)
    assert _tiff_resolutions(out.read_bytes()) == [NORMAL]


def test_a_turn_noted_only_in_xmp_swaps_it_too(client, auth_headers):
    """Pillow turns a TIFF page by the orientation of an XMP packet as well,
    when the page has no orientation tag."""
    xmp = b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:Description tiff:Orientation="6"/></x:xmpmeta>'
    data = _tiff([Image.new("1", (1078, 1728), 1)], [NORMAL[::-1]], tiffinfo={700: xmp})
    r = _convert(client, auth_headers, data, "pdf")
    assert r.status_code == 200, r.text
    assert _sizes(r.content) == [LETTER]


@pytest.mark.parametrize("target", [None, 2_000_000], ids=["quality", "target-size"])
def test_a_tiff_named_jpg_is_turned_before_it_is_converted(tmp_path, target):
    """Compressing picks the format by the name, and a page Pillow turns as
    it converts it (here from grey with alpha to RGB) is turned with its
    resolution too."""
    src, out = tmp_path / "scan.jpg", tmp_path / "out.jpg"
    page = Image.new("LA", (1078, 1728), (255, 255))
    src.write_bytes(_tiff([page], [NORMAL[::-1]], tiffinfo={274: 6}))
    if target is None:
        compress_image(src, out)
    else:
        compress_image_to_target(src, out, target_bytes=target)
    with Image.open(out) as img:
        assert (img.size, img.info["dpi"]) == ((1728, 1078), NORMAL)


def test_a_page_without_a_unit_takes_no_other_pages_resolution(tmp_path, client, auth_headers):
    """Pillow sets a page's resolution only in inches or centimetres and
    keeps the one before for a page in no unit (ResolutionUnit 1)."""
    measured, unitless = Image.new("1", (300, 150), 1), Image.new("1", (300, 150), 1)
    measured.encoderinfo = {"dpi": (300, 300)}
    unitless.encoderinfo = {"resolution_unit": 1, "x_resolution": 600, "y_resolution": 600}
    buf = BytesIO()
    measured.save(buf, format="TIFF", save_all=True, append_images=[unitless])
    src, out = tmp_path / "scan.tiff", tmp_path / "out.tiff"
    src.write_bytes(buf.getvalue())
    compress_image(src, out)
    assert _tiff_resolutions(out.read_bytes()) == [(300.0, 300.0), None]
    r = _convert(client, auth_headers, buf.getvalue(), "pdf")
    assert _sizes(r.content) == [(72.0, 36.0), (144.0, 72.0)]

    # The first page, converted on its own once the second was looked at.
    buf = BytesIO()
    unitless.save(buf, format="TIFF", save_all=True, append_images=[measured])
    r = _convert(client, auth_headers, buf.getvalue(), "png")
    with Image.open(BytesIO(r.content)) as img:
        assert "dpi" not in img.info


@pytest.mark.parametrize(
    "dpi",
    [(1, 1), (5, 300), (300, 20_000), (float("nan"), 300), (300,), "300"],
    ids=["one", "too-low", "too-high", "nan", "one-number", "text"],
)
def test_a_resolution_that_is_no_measurement_goes(dpi):
    """Pillow reads a TIFF without a resolution as 1 × 1 dpi: a fax page
    1 728 inches wide."""
    img = Image.new("RGB", (8, 8))
    img.info["dpi"] = dpi
    assert "dpi" not in strip_metadata(img).info
    img.info["dpi"] = (300, 300)
    assert strip_metadata(img).info["dpi"] == (300.0, 300.0)


def test_the_formats_page_names_the_range():
    low, high = _DPI_RANGE
    sentence = f"below {low} or above {high:,} dpi is no measurement".replace(",", " ")
    assert sentence in " ".join(FORMATS_MD.read_text(encoding="utf-8").split())
