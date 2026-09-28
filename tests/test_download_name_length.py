# SPDX-License-Identifier: AGPL-3.0-or-later
"""Over-long upload names keep the suffix their route appends.

``safe_download_name`` capped the *finished* name at 200 characters, so a stem
longer than ~185-196 characters lost its extension (``….pn``, ``…_pdfa.pd``)
and the OS could not open the download. Only the stem may be shortened. One
case per call site, so a route that goes back to handing the helper a
pre-concatenated ``stem + suffix`` fails here. PDF/A, PDF compress and AI
redact sit beside their routes' other download-name tests
(``test_convert_download_name.py``, ``test_pdf_compress.py``,
``test_ai_route.py``).
"""

from __future__ import annotations

import io
import zipfile

import pytest
from PIL import Image
from pypdf import PdfWriter

LONG_STEM = "a" * 250
MAX_LEN = 200  # safe_download_name's default cap


def _expected(suffix: str) -> str:
    return "a" * (MAX_LEN - len(suffix)) + suffix


def _jpg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (200, 100, 50)).save(buf, format="JPEG")
    return buf.getvalue()


def _pdf() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


_UPLOADS = {"jpg": (_jpg, "image/jpeg"), "pdf": (_pdf, "application/pdf")}


@pytest.mark.parametrize(
    ("endpoint", "ext", "data", "suffix"),
    [
        ("/api/v1/convert", "jpg", {"target_format": "png"}, ".png"),
        ("/api/v1/compress", "jpg", {}, "_compressed.jpg"),
        ("/api/v1/pdf/extract", "pdf", {"pages": "1"}, "_pages.pdf"),
        ("/api/v1/pdf/split", "pdf", {}, "_pages.zip"),
    ],
)
def test_single_download_keeps_suffix(client, auth_headers, endpoint, ext, data, suffix):
    build, mime = _UPLOADS[ext]
    res = client.post(
        endpoint,
        headers=auth_headers,
        files={"file": (f"{LONG_STEM}.{ext}", build(), mime)},
        data=data,
    )
    assert res.status_code == 200, res.text
    assert f'filename="{_expected(suffix)}"' in res.headers["content-disposition"]


@pytest.mark.parametrize(
    ("endpoint", "data", "suffix"),
    [
        ("/api/v1/convert/batch", {"target_formats": ["png"]}, ".png"),
        ("/api/v1/compress/batch", {}, "_compressed.jpg"),
    ],
)
def test_batch_zip_entry_keeps_suffix(client, auth_headers, endpoint, data, suffix):
    res = client.post(
        endpoint,
        headers=auth_headers,
        files=[("files", (f"{LONG_STEM}.jpg", _jpg(), "image/jpeg"))],
        data=data,
    )
    assert res.status_code == 200, res.text
    assert zipfile.ZipFile(io.BytesIO(res.content)).namelist() == [_expected(suffix)]
