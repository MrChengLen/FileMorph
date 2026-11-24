# SPDX-License-Identifier: AGPL-3.0-or-later
"""A download keeps its upload's name, in Chromium and in WebKit.

The pages took the name from Content-Disposition with a pattern for
filename="…" alone, so a name the server sends as filename*=UTF-8''… (one
with a letter beyond ASCII) came down as "result.png". Here the real pages
upload such names, and the test reads the name a page gives its download
link. tests/test_download_name_header.py pins the header and the parsing.
"""

from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image
from playwright.sync_api import Page, Route
from pypdf import PdfWriter


def _jpg() -> bytes:
    buf = BytesIO()
    Image.new("RGB", (16, 16), (200, 100, 50)).save(buf, format="JPEG")
    return buf.getvalue()


def _pdf() -> bytes:
    writer = PdfWriter()
    for _ in range(2):
        writer.add_blank_page(width=200, height=200)
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _convert(page: Page, server, name: str) -> str:
    """Convert a JPG named ``name`` to PNG on the pair page; the name of its
    download."""
    page.goto(f"{server.base_url}/de/convert/jpg-to-png")
    # app.js fills the target list from /api/v1/formats: wait until it has
    # the list, or the file finds no target.
    page.wait_for_load_state("networkidle")
    page.set_input_files(
        "#file-input", files=[{"name": name, "mimeType": "image/jpeg", "buffer": _jpg()}]
    )
    page.wait_for_selector("#target-format option[value=png]", state="attached")
    page.click("#convert-btn")
    page.wait_for_selector("#result-section:not(.hidden)")
    return page.get_attribute("#download-link", "download")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Mein Urlaub.jpg", "Mein Urlaub.png"),
        ("Grüße an Oma.jpg", "Grüße an Oma.png"),
        ("Отчёт (1).jpg", "Отчёт (1).png"),
        # The browser sends the quotes as %22 (the HTML form encoding).
        ('Angebot "final".jpg', "Angebot final.png"),
    ],
)
def test_a_converted_file_keeps_its_name(page: Page, server, name: str, expected: str):
    assert _convert(page, server, name) == expected


def test_without_the_header_the_name_comes_from_the_picked_file(page: Page, server):
    """A proxy that drops Content-Disposition: the page names the result the
    way the server does, not "result.png"."""

    def drop_header(route: Route) -> None:
        response = route.fetch()
        headers = {k: v for k, v in response.headers.items() if k != "content-disposition"}
        route.fulfill(response=response, headers=headers)

    page.route("**/api/v1/convert", drop_header)
    assert _convert(page, server, "Grüße an Oma.jpg") == "Grüße an Oma.png"


def test_a_split_pdf_keeps_its_name(page: Page, server):
    """The split PDF's header answered 500 for a name beyond Latin-1."""
    page.goto(f"{server.base_url}/de/pdf/split")
    page.set_input_files(
        "#pdf-file",
        files=[{"name": "Отчёт.pdf", "mimeType": "application/pdf", "buffer": _pdf()}],
    )
    page.click("#pdf-submit")
    page.wait_for_selector("#pdf-result:not(.hidden)")
    assert page.get_attribute("#pdf-download", "download") == "Отчёт_pages.zip"
