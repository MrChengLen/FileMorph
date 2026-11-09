# SPDX-License-Identifier: AGPL-3.0-or-later
"""A multi-page TIFF keeps every page.

Compressing it keeps them all and converting it to PDF makes a page of each;
converting it to a picture format takes the first page and says so
(``X-FileMorph-Warnings: pages=first``). Every page is stripped of its
metadata like a single picture (``strip_pages``), and the pages together may
take as much memory as one colour picture at the size limit — they are in
memory at once.
"""

import json
import random
import re
import zipfile
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image, ImageCms
from pypdf import PdfReader, PdfWriter

from app.api.routes.auth import get_optional_user
from app.compressors.image import compress_image
from app.converters import _metadata
from app.converters._metadata import strip_pages
from app.converters.base import TiffTooLargeError
from app.main import app

APP_JS = (Path(__file__).resolve().parent.parent / "app" / "static" / "js" / "app.js").read_text(
    encoding="utf-8"
)
BLOB = re.compile(r'<script id="fm-i18n-strings" type="application/json">(.*?)</script>', re.DOTALL)
SIZE = (160, 120)
SRGB = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def _page(seed: int, mode: str = "RGB") -> Image.Image:
    """A page of its own: grain from ``seed`` over a gradient."""
    grain = Image.frombytes("L", SIZE, random.Random(seed).randbytes(SIZE[0] * SIZE[1]))
    picture = Image.merge("RGB", (grain, Image.linear_gradient("L").resize(SIZE), grain))
    return picture if mode == "RGB" else picture.convert(mode)


def _tiff(pages: list[Image.Image], **options) -> bytes:
    buf = BytesIO()
    pages[0].save(buf, format="TIFF", save_all=True, append_images=pages[1:], **options)
    return buf.getvalue()


def _read(data: bytes) -> list[tuple]:
    """Each page's mode, size, pixels and packing."""
    found = []
    with Image.open(BytesIO(data)) as img:
        for index in range(img.n_frames):
            img.seek(index)
            info = (img.info.get("compression"), img.tag_v2.get(317, 1))
            found.append((img.mode, img.size, img.tobytes(), info))
    return found


def _compress(tmp_path, data: bytes) -> bytes:
    src, out = tmp_path / "scan.tiff", tmp_path / "out.tiff"
    src.write_bytes(data)
    compress_image(src, out, quality=80)
    return out.read_bytes()


# ── Compress ─────────────────────────────────────────────────────────────────


def test_compressing_keeps_every_page(tmp_path):
    pages = [_page(1), _page(2, "L"), _page(3, "RGBA")]
    result = _read(_compress(tmp_path, _tiff(pages, compression="tiff_lzw")))
    assert [page[:3] for page in result] == [(p.mode, p.size, p.tobytes()) for p in pages]
    assert {page[3] for page in result} == {("tiff_adobe_deflate", 2)}, "Deflate + predictor"


def test_a_palette_page_keeps_the_whole_file_without_the_predictor(tmp_path):
    """The predictor makes a palette page larger; black and white takes none."""
    pages = [_page(1), _page(2, "P"), _page(3, "1")]
    result = _read(_compress(tmp_path, _tiff(pages)))
    assert [page[2] for page in result] == [p.tobytes() for p in pages]
    assert {page[3] for page in result} == {("tiff_adobe_deflate", 1)}


def test_black_and_white_pages_get_the_smaller_packing(tmp_path):
    pages = [_page(seed, "1") for seed in (1, 2, 3)]
    data = _compress(tmp_path, _tiff(pages))
    sizes = {}
    for compression in ("group4", "tiff_adobe_deflate"):
        sizes[compression] = len(_tiff(pages, compression=compression))
    result = _read(data)
    assert len(data) == min(sizes.values())
    assert {page[3][0] for page in result} == {min(sizes, key=sizes.get)}
    assert [page[2] for page in result] == [p.tobytes() for p in pages]


def test_every_page_loses_its_metadata(tmp_path):
    pages = [_page(1), _page(2)]
    original = _tiff(pages, tiffinfo={315: "Erika Mustermann", 270: "secret note"})
    assert original.count(b"Erika") == 2, "on every page"
    result = _compress(tmp_path, original)
    assert b"Erika" not in result and b"secret" not in result
    assert len(_read(result)) == 2


def test_a_single_page_tiff_is_packed_as_before(tmp_path):
    page = _page(1)
    result = _read(_compress(tmp_path, _tiff([page])))
    assert result == [("RGB", SIZE, page.tobytes(), ("tiff_adobe_deflate", 2))]


def _held(pages: int, width: int, height: int, size: int) -> int:
    """The bytes strip_pages counts: the pixels and Pillow's pointer to each row."""
    return pages * (width * size + 8) * height


def _limit(monkeypatch, held: int) -> None:
    """Set the size limit so that exactly ``held`` bytes fit (4 bytes a pixel)."""
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", held // 4)


def test_too_many_pages_or_pixels_are_refused(monkeypatch):
    data = _tiff([_page(seed) for seed in range(4)])
    monkeypatch.setattr(_metadata, "MAX_PAGES", 4)
    assert len(strip_pages(Image.open(BytesIO(data)))) == 4, "up to the limit"
    monkeypatch.setattr(_metadata, "MAX_PAGES", 3)
    with pytest.raises(TiffTooLargeError):
        strip_pages(Image.open(BytesIO(data)))
    monkeypatch.setattr(_metadata, "MAX_PAGES", 1000)
    _limit(monkeypatch, _held(4, *SIZE, 4))
    assert len(strip_pages(Image.open(BytesIO(data)))) == 4, "up to the limit"
    _limit(monkeypatch, _held(4, *SIZE, 4) - 4)
    with pytest.raises(TiffTooLargeError):
        strip_pages(Image.open(BytesIO(data)))


def test_black_and_white_and_grey_pages_count_a_quarter_of_colour_ones(monkeypatch):
    """Pillow keeps them at a byte a pixel: a scanned letter of many pages
    fits where as many colour or palette pages don't (a palette page becomes
    RGB on its way to a PDF)."""
    _limit(monkeypatch, _held(4, *SIZE, 1))
    for mode in ("1", "L"):
        assert len(strip_pages(Image.open(BytesIO(_tiff([_page(n, mode) for n in range(4)]))))) == 4
    for mode in ("RGB", "P"):
        with pytest.raises(TiffTooLargeError):
            strip_pages(Image.open(BytesIO(_tiff([_page(n, mode) for n in range(4)]))))


def test_one_page_at_the_size_limit_still_passes(monkeypatch):
    """Pillow checked the first page on opening, as for any image: the rows'
    pointers don't tip it over."""
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", SIZE[0] * SIZE[1])
    assert len(strip_pages(Image.open(BytesIO(_tiff([_page(1)]))))) == 1


def test_a_narrow_page_counts_its_rows(monkeypatch):
    """A page one pixel wide and very tall costs Pillow a pointer for each row."""
    _limit(monkeypatch, 4 * 4000)  # a 1 × 4000 grey page's pixels fit four times over
    narrow = Image.new("L", (1, 4000), 128)
    with pytest.raises(TiffTooLargeError):
        strip_pages(Image.open(BytesIO(_tiff([narrow, narrow]))))  # 8 000 pixels: they'd fit


def _patched(data: bytes, page: int, tag: int, value: int) -> bytes:
    """``data`` (a little-endian TIFF) with ``tag`` of page ``page`` set to ``value``."""
    ifd = int.from_bytes(data[4:8], "little")
    for _ in range(page):
        count = int.from_bytes(data[ifd : ifd + 2], "little")
        ifd = int.from_bytes(data[ifd + 2 + 12 * count : ifd + 6 + 12 * count], "little")
    out = bytearray(data)
    for index in range(int.from_bytes(data[ifd : ifd + 2], "little")):
        entry = ifd + 2 + 12 * index
        if int.from_bytes(data[entry : entry + 2], "little") == tag:
            short = int.from_bytes(data[entry + 2 : entry + 4], "little") == 3
            out[entry + 8 : entry + 12] = value.to_bytes(2 if short else 4, "little").ljust(
                4, b"\0"
            )
            return bytes(out)
    raise AssertionError(f"tag {tag} not on page {page}")


@pytest.mark.parametrize("tag, value", [(256, 0), (258, 99)], ids=["no-width", "unreadable-header"])
def test_a_damaged_later_page_is_said_not_dropped(client, auth_headers, tag, value):
    """Fewer pages without a word would be a success that didn't happen."""
    data = _patched(_tiff([_page(1), _page(2)]), 1, tag, value)
    r = client.post(
        "/api/v1/compress",
        headers=auth_headers,
        files={"file": ("scan.tiff", data, "image/tiff")},
    )
    assert r.status_code == 400, r.text
    assert "A page of this TIFF is damaged" in r.json()["detail"]


def _with_profile(page: Image.Image) -> Image.Image:
    page.info["icc_profile"] = SRGB
    return page


def test_each_page_keeps_its_own_colour_profile(tmp_path, client, auth_headers):
    """Pillow keeps a TIFF page's profile for a later page that has none."""
    result = _compress(tmp_path, _tiff([_with_profile(_page(1)), _page(2)]))
    with Image.open(BytesIO(result)) as img:
        profiles = []
        for index in range(img.n_frames):
            img.seek(index)
            profiles.append(34675 in img.tag_v2)  # the page's own ICC tag
    assert profiles == [True, False]

    r = _convert(client, auth_headers, _tiff([_page(1), _with_profile(_page(2))]), "png")
    assert r.status_code == 200, r.text
    with Image.open(BytesIO(r.content)) as img:
        assert "icc_profile" not in img.info, "not the second page's"


def _stray_next_page(data: bytes) -> bytes:
    """A one-page TIFF whose pointer to a next page leads past its end, as
    some scanners write it."""
    ifd = int.from_bytes(data[4:8], "little")
    pointer = ifd + 2 + 12 * int.from_bytes(data[ifd : ifd + 2], "little")
    return data[:pointer] + (len(data) + 1000).to_bytes(4, "little") + data[pointer + 4 :]


def test_a_stray_pointer_to_a_next_page_ends_the_file(tmp_path, client, auth_headers):
    """As in libtiff's readers — and as before, when only the first page counted."""
    data = _stray_next_page(_tiff([_page(1)]))
    assert len(_read(_compress(tmp_path, data))) == 1
    r = _convert(client, auth_headers, data, "pdf")
    assert r.status_code == 200, r.text
    assert len(PdfReader(BytesIO(r.content)).pages) == 1


def test_each_page_is_turned_by_its_own_orientation(tmp_path):
    upright, turned = _page(1), _page(2)
    turned.encoderinfo = {"tiffinfo": {274: 6}}  # this page only: turned 90° clockwise
    result = _read(_compress(tmp_path, _tiff([upright, turned])))
    shown = turned.transpose(Image.Transpose.ROTATE_270)
    assert [page[1:3] for page in result] == [
        (upright.size, upright.tobytes()),
        (shown.size, shown.tobytes()),
    ]


def test_compressing_checks_what_the_file_is(tmp_path):
    """A GIF animation named .tif compresses to its first frame, as before."""
    frames = [_page(seed) for seed in (1, 2, 3)]
    buf = BytesIO()
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:])
    assert len(_read(_compress(tmp_path, buf.getvalue()))) == 1


def test_reading_the_pages_has_a_time_budget(monkeypatch):
    """A crafted file can make each page header slow to read, which no page
    or pixel count catches."""
    data = _tiff([_page(1), _page(2)])
    monkeypatch.setattr(_metadata, "PAGES_SECONDS", -1)
    with pytest.raises(TiffTooLargeError):
        strip_pages(Image.open(BytesIO(data)))


def test_a_damaged_page_is_a_400_not_a_server_error(client, auth_headers):
    data = bytearray(_tiff([_page(1), _page(2)], compression="tiff_adobe_deflate"))
    with Image.open(BytesIO(bytes(data))) as img:
        img.seek(1)
        (start,), (length,) = img.tag_v2[273], img.tag_v2[279]  # page 2's pixel data
    data[start : start + length] = b"\x00" * length
    r = client.post(
        "/api/v1/compress",
        headers=auth_headers,
        files={"file": ("scan.tiff", bytes(data), "image/tiff")},
    )
    assert r.status_code == 400, r.text
    assert r.headers["X-FileMorph-Error-Code"] == "invalid_input"
    assert "A page of this TIFF is damaged" in r.json()["detail"]


@pytest.mark.parametrize("route", ["compress", "convert"])
def test_a_tiff_past_the_limit_gets_its_own_code_and_its_fix(
    client, auth_headers, monkeypatch, route
):
    monkeypatch.setattr(_metadata, "MAX_PAGES", 2)
    data = _tiff([_page(seed) for seed in range(3)])
    if route == "compress":
        r = client.post(
            "/api/v1/compress",
            headers=auth_headers,
            files={"file": ("scan.tiff", data, "image/tiff")},
        )
    else:
        r = _convert(client, auth_headers, data, "pdf")
    assert r.status_code == 400
    assert r.headers["X-FileMorph-Error-Code"] == "tiff_too_large"
    assert r.json()["detail"] == TiffTooLargeError.message


# ── Convert ──────────────────────────────────────────────────────────────────


def _convert(client, auth_headers, data: bytes, target: str):
    return client.post(
        "/api/v1/convert",
        headers=auth_headers,
        files={"file": ("scan.tiff", data, "image/tiff")},
        data={"target_format": target},
    )


def test_a_tiff_becomes_a_pdf_with_every_page(client, auth_headers):
    sizes = [(160, 120), (200, 150), (120, 160)]  # tell the pages apart
    modes = ["RGB", "1", "L"]
    pages = [_page(n, mode).resize(size) for n, (mode, size) in enumerate(zip(modes, sizes))]
    r = _convert(client, auth_headers, _tiff(pages), "pdf")
    assert r.status_code == 200, r.text
    reader = PdfReader(BytesIO(r.content))
    found = []
    for page in reader.pages:
        (image,) = page["/Resources"]["/XObject"].values()
        image = image.get_object()
        name = image["/Filter"]  # a name, or a list of them
        space = image.get("/ColorSpace")
        found.append(
            (
                (image["/Width"], image["/Height"]),
                name if isinstance(name, str) else name[0],
                space if isinstance(space, str) else None,
            )
        )
    # Black and white stays so (CCITT Group 4): as RGB, a scanned letter's
    # page takes ten times the bytes. Grey stays grey.
    assert found == [
        (sizes[0], "/DCTDecode", "/DeviceRGB"),
        (sizes[1], "/CCITTFaxDecode", "/DeviceGray"),
        (sizes[2], "/DCTDecode", "/DeviceGray"),
    ]


def test_tif_to_tiff_keeps_every_page(client, auth_headers):
    r = _convert(client, auth_headers, _tiff([_page(1), _page(2)]), "tif")
    assert r.status_code == 200, r.text
    assert "X-FileMorph-Warnings" not in r.headers
    assert len(_read(r.content)) == 2


def test_inserting_a_tiff_into_a_pdf_inserts_every_page(client, auth_headers):
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    base = BytesIO()
    writer.write(base)
    r = client.post(
        "/api/v1/pdf/insert",
        headers=auth_headers,
        files={
            "file": ("report.pdf", base.getvalue(), "application/pdf"),
            "insert_file": ("scan.tiff", _tiff([_page(n) for n in (1, 2, 3)]), "image/tiff"),
        },
    )
    assert r.status_code == 200, r.text
    assert r.headers["X-FileMorph-Inserted-Pages"] == "3"
    assert r.headers["X-FileMorph-Page-Count"] == "4"


@pytest.fixture
def batch_user():
    """A free account: batches of more than one file (tests/test_compress_batch.py)."""
    user = MagicMock()
    user.tier.value = "free"
    app.dependency_overrides[get_optional_user] = lambda: user
    yield
    app.dependency_overrides.pop(get_optional_user, None)


def test_several_files_at_once_note_each_first_page(client, auth_headers, batch_user):
    files = [
        ("files", ("mappe.tiff", _tiff([_page(1), _page(2)]), "image/tiff")),
        ("files", ("einzeln.tiff", _tiff([_page(3)]), "image/tiff")),
    ]
    r = client.post(
        "/api/v1/convert/batch",
        headers=auth_headers,
        files=files,
        data={"target_formats": ["png", "png"]},
    )
    assert r.status_code == 200, r.text
    notes = r.headers.get("X-FileMorph-Batch-Notes", "").replace("%3D", "=")
    assert "|pages=first" in notes and "mappe" in notes and "einzeln" not in notes
    with zipfile.ZipFile(BytesIO(r.content)) as zf:
        manifest = json.loads(zf.read("manifest.json"))
    noted = {f["name"].split(".")[0]: f["notes"] for f in manifest["files"]}
    assert noted == {"mappe": ["pages=first"], "einzeln": []}


def test_a_tiff_as_a_picture_takes_its_first_page_and_says_so(client, auth_headers):
    pages = [_page(1), _page(2)]
    r = _convert(client, auth_headers, _tiff(pages), "png")
    assert r.status_code == 200, r.text
    assert r.headers["X-FileMorph-Warnings"] == "pages=first"
    with Image.open(BytesIO(r.content)) as img:
        assert img.tobytes() == pages[0].tobytes()

    r = _convert(client, auth_headers, _tiff([_page(1)]), "png")
    assert r.status_code == 200
    assert "X-FileMorph-Warnings" not in r.headers, "one page: nothing to say"


# ── The page ─────────────────────────────────────────────────────────────────


def test_the_page_shows_the_note_for_one_file_and_several():
    """targetNoteLabel words the tokens of X-FileMorph-Warnings (one file)
    and of X-FileMorph-Batch-Notes (several)."""
    label = APP_JS.split("function targetNoteLabel(", 1)[1].split("\n}\n", 1)[0]
    assert "key === 'pages' && value === 'first'" in label
    assert "i18n.warningPagesFirst" in label


def test_the_error_text_is_the_server_message_in_english(client):
    en = json.loads(BLOB.search(client.get("/en/").text).group(1))
    assert en["errorTiffTooLarge"] == TiffTooLargeError.message


def test_the_note_is_german_on_de(client):
    de = json.loads(BLOB.search(client.get("/de/").text).group(1))
    assert de["warningPagesFirst"] == (
        "Nur die erste Seite dieses TIFFs wurde umgewandelt. Wandle es in PDF um, um alle "
        "Seiten zu behalten."
    )
