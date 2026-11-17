# SPDX-License-Identifier: AGPL-3.0-or-later
"""A TIFF page turned by a quarter comes out right from an upload.

Pillow memory-maps an uncompressed image it has a file name for, and Pillow
13.0 maps a TIFF page turned by a quarter (orientation 5–8) at its turned
size, not its stored one: the pixels came out scrambled from every image
path (python-pillow/Pillow#10220). ``open_image`` drops the name, so Pillow
reads the pixels instead.
"""

from contextlib import closing

import pytest
from PIL import Image
from pypdf import PdfReader

from app.compressors.image import compress_image
from app.converters import image as converters_image
from app.converters._metadata import strip_pages
from app.core.image_hardening import open_image

# The modes Pillow maps (``Image._MAPMODES``) that a TIFF stores uncompressed
# in one strip (and I;16B, the same path); "1" and RGB were never mapped.
MODES = ["L", "P", "RGBA", "CMYK", "I;16"]
STORED = (30, 60)  # width, height as the file stores them: on its side


def _turned(tmp_path, mode: str) -> tuple:
    """An uncompressed one-strip TIFF in ``mode`` whose page is turned by a
    quarter (orientation 6), and the picture viewers show of it."""
    grey = Image.radial_gradient("L").resize(STORED)
    stored = grey.convert("I").convert(mode) if mode == "I;16" else grey.convert(mode)
    path = tmp_path / "turned.tif"
    stored.save(path, format="TIFF", tiffinfo={274: 6})
    return path, stored.transpose(Image.Transpose.ROTATE_270)


@pytest.mark.parametrize("mode", MODES)
def test_compressing_keeps_the_pixels(tmp_path, mode):
    path, shown = _turned(tmp_path, mode)
    out = tmp_path / "out.tif"
    compress_image(path, out)
    with Image.open(out) as img:
        assert (img.mode, img.size) == (shown.mode, shown.size)
        assert img.tobytes() == shown.tobytes()


@pytest.mark.parametrize("mode", MODES)
def test_converting_keeps_the_pixels(tmp_path, mode):
    path, shown = _turned(tmp_path, mode)
    out = tmp_path / "out.png"
    converters_image._ImageConverter("png").convert(path, out)
    with Image.open(out) as img:
        expected = converters_image._usable(shown).convert("RGBA")
        assert img.size == shown.size
        assert img.convert("RGBA").tobytes() == expected.tobytes()


@pytest.mark.parametrize("mode", MODES)
def test_a_pdf_page_lies_the_way_the_page_is_turned(tmp_path, mode):
    """60 × 30 dots at 150 dpi: 28.8 × 14.4 points, wider than tall."""
    path, _ = _turned(tmp_path, mode)
    out = tmp_path / "out.pdf"
    converters_image._ImageToPdfConverter().convert(path, out)
    (page,) = PdfReader(out).pages
    size = (round(float(page.mediabox.width), 2), round(float(page.mediabox.height), 2))
    assert size == (28.8, 14.4)


def test_a_later_uncompressed_page_gets_the_size_check(tmp_path, monkeypatch):
    """Pillow checks a TIFF page's size as it reads it — a page it mapped
    skipped that check, so a later page over the limit passed."""
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 1000)
    # 2 500 pixels: past twice the limit, Pillow's error whatever the warning
    # filters; within strip_pages' budget of four bytes a pixel.
    pages = [Image.new("L", (10, 10)), Image.new("L", (50, 50))]
    path = tmp_path / "pages.tif"
    pages[0].save(path, format="TIFF", save_all=True, append_images=pages[1:])
    with closing(open_image(path)) as img, pytest.raises(Image.DecompressionBombError):
        strip_pages(img)


@pytest.mark.parametrize("fmt", ["TIFF", "BMP"])
def test_an_upload_is_read_not_mapped(tmp_path, fmt):
    """An uncompressed TIFF or BMP that Pillow maps when it has the name."""
    path = tmp_path / f"upload.{fmt.lower()}"
    Image.new("L", (40, 20), 128).save(path, format=fmt)
    with closing(open_image(path)) as img:
        img.load()
        assert not img.map
