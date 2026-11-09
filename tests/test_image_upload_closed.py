# SPDX-License-Identifier: AGPL-3.0-or-later
"""Image and Word conversions release the uploaded file, however they end.

Pillow keeps an image's file open until the image is closed (a multi-frame GIF
keeps it after loading too, and an uncompressed BMP is mapped into memory
instead of read). When decoding fails (a cut-off JPEG), the exception holds
the image until the request is over, and Windows cannot delete an open file:
the request's temporary folder stayed behind. A spy records every image these
paths open and checks that each one is closed afterwards, file included, on
every platform; python-docx is checked the same way for DOCX to TXT.
"""

from __future__ import annotations

import zipfile
from io import BytesIO

import docx
import pytest
from PIL import Image, ImageFile

from app.compressors import image as compressors_image
from app.converters import document
from app.converters import image as converters_image
from app.core.image_hardening import open_image

_RUNS = {
    "image to image": lambda src, out: converters_image._ImageConverter("png").convert(
        src, out / "out.png"
    ),
    "image to pdf": lambda src, out: converters_image._ImageToPdfConverter().convert(
        src, out / "out.pdf"
    ),
    "compress": lambda src, out: compressors_image.compress_image(src, out / "out.jpg", 60),
    "compress to a size": lambda src, out: compressors_image.compress_image_to_target(
        src, out / "out.jpg", target_bytes=2000
    ),
}
# Compressing to a size takes lossy formats only and refuses the others first.
_CASES = [
    (run, kind)
    for kind in ("jpeg", "cut-off jpeg", "animated gif", "grey bmp")
    for run in _RUNS
    if kind in ("jpeg", "cut-off jpeg") or run != "compress to a size"
]


def _upload(tmp_path, kind):
    if kind in ("jpeg", "cut-off jpeg"):
        buf = BytesIO()
        Image.effect_noise((64, 64), 90).convert("RGB").save(buf, format="JPEG")
        data = buf.getvalue()
        path = tmp_path / "in.jpg"
        path.write_bytes(data[: len(data) // 2] if kind == "cut-off jpeg" else data)
    elif kind == "animated gif":
        path = tmp_path / "in.gif"
        frames = [Image.new("P", (32, 32), shade) for shade in (10, 80, 160)]
        frames[0].save(path, save_all=True, append_images=frames[1:])
    else:  # an uncompressed grey BMP, which Pillow maps into memory
        path = tmp_path / "in.bmp"
        Image.new("L", (64, 64), 128).save(path, format="BMP")
    return path


@pytest.fixture
def opened(monkeypatch):
    """For every image the converters and compressors open: its file, and
    whether ``close()`` ran on it."""
    images = []

    def spy(fp):
        img = open_image(fp)
        entry = {"file": img.fp, "closed": False}
        close = img.close

        def recording_close():
            entry["closed"] = True
            close()

        img.close = recording_close
        images.append(entry)
        return img

    monkeypatch.setattr(converters_image, "open_image", spy)
    monkeypatch.setattr(compressors_image, "open_image", spy)
    return images


@pytest.mark.parametrize(("run", "kind"), _CASES)
def test_the_upload_is_closed_however_the_conversion_ends(monkeypatch, tmp_path, opened, run, kind):
    # Importing WeasyPrint turns on LOAD_TRUNCATED_IMAGES for the whole process
    # (see tests/test_pdf_insert.py); with Pillow's default a cut-off JPEG fails.
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", False)
    src = _upload(tmp_path, kind)

    if kind == "cut-off jpeg":
        with pytest.raises(OSError):
            _RUNS[run](src, tmp_path)
    else:
        _RUNS[run](src, tmp_path)

    assert opened, "the path opened no image"
    # The image, not just its file: close() also lets go of a mapped file.
    assert all(entry["closed"] for entry in opened), "an opened image was not closed"
    assert all(entry["file"].closed for entry in opened), "an upload is still open"
    src.unlink()  # on Windows this fails while the file is open


def test_a_failed_docx_to_txt_closes_the_upload(monkeypatch, tmp_path):
    """python-docx opens a path itself and keeps its ZIP open when the document
    is broken; handed a file, it reads that one, which the converter closes."""
    src = tmp_path / "in.docx"
    with zipfile.ZipFile(src, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types")  # not well-formed
    seen = []
    real = docx.Document

    def spy(arg=None):
        seen.append(arg)
        return real(arg)

    monkeypatch.setattr(docx, "Document", spy)

    with pytest.raises(Exception):  # whatever python-docx raises for it
        document.DocxToTxtConverter().convert(src, tmp_path / "out.txt")

    assert seen and all(getattr(arg, "closed", False) for arg in seen)
    src.unlink()  # on Windows this fails while the file is open
