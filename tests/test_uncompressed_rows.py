# SPDX-License-Identifier: AGPL-3.0-or-later
"""An uncompressed picture is read a row or so at a time, however wide.

Pillow reads the pixels of an uncompressed TIFF or BMP in blocks and joins
them until a row is whole, so a very wide row took many reads. ``open_image``
— and ``strip_pages`` for each later page — has every read bring half a row
at least: a row takes a read or two, at any width. A TIFF tile running past
its page's edge is read by its own rows; one far wider than its page is
refused as damaged. Pillow reads an icon's picture while opening the file;
an icon whose BMP picture is wider than an icon can be is refused as damaged
before that.
"""

from __future__ import annotations

import struct
from contextlib import closing
from io import BytesIO

import pytest
from PIL import Image, ImageFile

from app.converters._metadata import strip_pages
from app.converters.base import InvalidInputError
from app.core.image_hardening import open_image

WIDE = 1 << 20  # pixels a row: sixteen blocks of 64 KB at a byte a pixel


class _Upload(BytesIO):
    """An upload that counts the reads of a block or more: Pillow's reads of
    pixels (it reads headers a few bytes at a time)."""

    blocks = 0

    def read(self, size=-1):
        if size is None or size < 0 or size >= ImageFile.MAXBLOCK:
            self.blocks += 1
        return super().read(size)


def _upload(pages: list[Image.Image], fmt: str) -> _Upload:
    buf = BytesIO()
    pages[0].save(buf, format=fmt, save_all=len(pages) > 1, append_images=pages[1:])
    return _Upload(buf.getvalue())


_COLOUR = {"L": 7, "I;16": 300, "RGB": (7, 8, 9), "CMYK": (1, 2, 3, 4)}


@pytest.mark.parametrize(
    ("fmt", "mode"),
    [
        ("TIFF", "L"),
        ("TIFF", "I;16"),
        ("TIFF", "RGB"),
        ("TIFF", "CMYK"),
        ("BMP", "L"),
        ("BMP", "RGB"),
    ],
)
@pytest.mark.parametrize("width", [WIDE, 2 * WIDE])
def test_a_wide_row_takes_a_read_or_two(fmt, mode, width):
    picture = Image.new(mode, (width, 1), _COLOUR[mode])
    upload = _upload([picture], fmt)
    with closing(open_image(upload)) as img:
        upload.blocks = 0
        img.load()
        assert img.convert(mode).tobytes() == picture.tobytes()
    assert upload.blocks <= 2


def test_each_page_of_a_tiff_is_read_by_its_own_rows():
    """Pages differ: a narrow first page, then a wide one."""
    upload = _upload([Image.new("L", (16, 16), 7), Image.new("L", (WIDE, 1), 9)], "TIFF")
    with closing(open_image(upload)) as img:
        upload.blocks = 0
        pages = strip_pages(img)
    assert [(page.size, page.getpixel((page.width - 1, 0))) for page in pages] == [
        ((16, 16), 7),
        ((WIDE, 1), 9),
    ]
    assert upload.blocks <= 2  # a read a page


def test_a_read_for_less_still_brings_half_a_row():
    """A read asked for less than half a row brings half a row all the same."""
    upload = _upload([Image.new("L", (WIDE, 2), 7)], "TIFF")
    with closing(open_image(upload)) as img:
        img.fp.seek(0)
        assert len(img.load_read(1)) >= WIDE // 2


def _tiled(page_width: int, tile_width: int) -> bytes:
    """An uncompressed grey TIFF page ``page_width`` pixels wide and two
    high, stored as one tile ``tile_width`` pixels wide: a tile may run past
    the right edge of its page, its rows in the file as long as it is wide."""
    start = 8 + 2 + 10 * 12 + 4  # the tile: after the header and ten tags
    tags = {
        256: page_width,  # ImageWidth
        257: 2,  # ImageLength
        258: 8,  # BitsPerSample
        259: 1,  # Compression: none
        262: 1,  # PhotometricInterpretation: black is zero
        277: 1,  # SamplesPerPixel
        322: tile_width,  # TileWidth
        323: 2,  # TileLength
        324: start,  # TileOffsets
        325: 2 * tile_width,  # TileByteCounts
    }
    ifd = b"".join(struct.pack("<HHII", tag, 4, 1, value) for tag, value in tags.items())
    head = b"II*\0" + struct.pack("<IH", 8, len(tags)) + ifd + struct.pack("<I", 0)
    return head + bytes([7]) * (2 * tile_width)


def test_a_tile_past_its_page_is_read_by_its_own_rows():
    upload = _Upload(_tiled(WIDE // 2, WIDE))
    with closing(open_image(upload)) as img:
        upload.blocks = 0
        img.load()
        assert img.tobytes() == bytes([7]) * WIDE  # two rows of half as many
    assert upload.blocks <= 2


def test_a_tile_far_wider_than_its_page_is_refused(tmp_path):
    path = tmp_path / "tiled.tif"
    path.write_bytes(_tiled(16, WIDE))
    with pytest.raises(InvalidInputError):
        open_image(path)
    path.unlink()  # on Windows this fails while the upload is open


def _icon(width: int) -> bytes:
    """An icon holding one BMP picture, ``width`` pixels wide and one high."""
    bmp = BytesIO()
    Image.new("L", (width, 1), 7).save(bmp, format="BMP")
    picture = bytearray(bmp.getvalue()[14:])  # without the BMP file header
    picture[8:12] = (2).to_bytes(4, "little")  # its rows and its mask's
    picture += bytes((width + 31) // 32 * 4)  # the mask: a row of bits
    entry = struct.pack("<4B2H2I", width % 256, 1, 0, 0, 1, 8, len(picture), 6 + 16)
    return b"\0\0\1\0\1\0" + entry + bytes(picture)


@pytest.mark.parametrize("given", ["path", "file"])
def test_an_icon_wider_than_an_icon_can_be_is_refused(tmp_path, given):
    """No icon is more than 256 pixels wide: its header has a byte for it."""
    path = tmp_path / "wide.ico"
    path.write_bytes(_icon(257))
    upload = path if given == "path" else BytesIO(path.read_bytes())
    with pytest.raises(InvalidInputError):
        open_image(upload)


@pytest.mark.parametrize("given", ["path", "file"])
def test_an_icon_of_256_pixels_opens(tmp_path, given):
    path = tmp_path / "icon.ico"
    path.write_bytes(_icon(256))
    upload = path if given == "path" else BytesIO(path.read_bytes())
    with closing(open_image(upload)) as img:
        assert (img.format, img.size) == ("ICO", (256, 1))
        assert img.convert("L").getpixel((255, 0)) == 7
