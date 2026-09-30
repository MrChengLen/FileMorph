# SPDX-License-Identifier: AGPL-3.0-or-later
"""A PDF pypdf can't read gets a 400 with a fixed message, never a 500.

pypdf raises ``LimitReachedError`` when a crafted file exceeds one of its
safety limits; it derives from ``PyPdfError``, not from ``PdfReadError``.
pypdf also parses lazily, so most failures (limits, and the plain
``ValueError`` of a damaged object) surface while pages are copied or text
is extracted, not when the file is opened. The PDF paths caught neither
there: a generic 500 plus a logged traceback instead of the clean 400.

Tiny PDFs, built in-process, each fail at one stage:

* a page tree nested deeper than 100 levels (a limit), while the pages
  are counted;
* a stream declaring an 80 MB ``/Length`` (limit 75 MB), while its page is
  copied (extract, split, ``pdf`` → ``pdf``);
* a page object without ``/Type`` (``ValueError``), while it is copied;
* a CID font whose ``/W`` range spans 100 000 glyphs (limit 65 536), during
  text extraction (``pdf`` → ``txt``);
* a content stream that isn't valid ASCII85 (``ValueError``), during text
  extraction.

One more PDF pypdf *can* read: its font map yields an unpaired surrogate,
which made writing the ``txt`` output fail with a 500.
"""

from __future__ import annotations

import io
import logging

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.errors import LimitReachedError

from app.converters.pdf_pages import UnreadablePdfError, extract_pages, split_pdf

_UNREADABLE = "Could not read the PDF. Verify the file is valid."
_CATALOG = b"<< /Type /Catalog /Pages 2 0 R >>"
_ONE_PAGE = b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"
_PAGE_WITH_FONT = (
    b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200]"
    b" /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
)


def _pdf(*objects: bytes) -> bytes:
    """Number ``objects`` from 1 and add a correct xref table and trailer."""
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for num, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (num, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def _stream(data: bytes, extra: bytes = b"") -> bytes:
    return b"<< /Length %d%s >>\nstream\n%s\nendstream" % (len(data), extra, data)


def _deep_page_tree() -> bytes:
    # Objects 2..121 are /Pages nodes, each the only kid of the one before.
    nodes = [b"<< /Type /Pages /Kids [%d 0 R] /Count 1 >>" % (num + 1) for num in range(2, 122)]
    return _pdf(_CATALOG, *nodes, b"<< /Type /Page /MediaBox [0 0 200 200] >>")


def _oversized_stream() -> bytes:
    return _pdf(
        _CATALOG,
        _ONE_PAGE,
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R >>",
        b"<< /Length 80000000 >>\nstream\nBT ET\nendstream",
    )


def _untyped_page() -> bytes:
    # pypdf lists it as a page; PdfWriter.add_page refuses it ("Invalid page object").
    return _pdf(_CATALOG, _ONE_PAGE, b"<< /Parent 2 0 R /MediaBox [0 0 200 200] >>")


def _huge_font_width_range() -> bytes:
    return _pdf(
        _CATALOG,
        _ONE_PAGE,
        _PAGE_WITH_FONT,
        _stream(b"BT /F1 12 Tf <0041> Tj ET"),
        b"<< /Type /Font /Subtype /Type0 /BaseFont /X /Encoding /Identity-H"
        b" /DescendantFonts [6 0 R] >>",
        b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /X"
        b" /CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >>"
        b" /W [0 99999 500] >>",
    )


def _bad_ascii85_content() -> bytes:
    # The page needs a font, or pypdf skips decoding its content stream.
    return _pdf(
        _CATALOG,
        _ONE_PAGE,
        _PAGE_WITH_FONT,
        _stream(b"vwxyz~>", b" /Filter /ASCII85Decode"),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    )


def _surrogate_font_map() -> bytes:
    # A ToUnicode map sending "A" to U+D800, half of a surrogate pair.
    cmap = (
        b"/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n"
        b"/CMapName /X def /CMapType 2 def\n"
        b"1 begincodespacerange\n<00> <FF>\nendcodespacerange\n"
        b"1 beginbfchar\n<41> <D800>\nendbfchar\nendcmap\nend end\n"
    )
    return _pdf(
        _CATALOG,
        _ONE_PAGE,
        _PAGE_WITH_FONT,
        _stream(b"BT /F1 12 Tf (A) Tj ET"),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /ToUnicode 6 0 R >>",
        _stream(cmap),
    )


def _count_pages(data: bytes) -> None:
    len(PdfReader(io.BytesIO(data)).pages)


def _copy_pages(data: bytes) -> None:
    writer = PdfWriter()
    for page in PdfReader(io.BytesIO(data)).pages:
        writer.add_page(page)
    writer.write(io.BytesIO())


def _extract_text(data: bytes) -> None:
    for page in PdfReader(io.BytesIO(data)).pages:
        page.extract_text()


@pytest.mark.parametrize(
    ("build", "stage", "error"),
    [
        (_deep_page_tree, _count_pages, LimitReachedError),
        (_oversized_stream, _copy_pages, LimitReachedError),
        (_untyped_page, _copy_pages, ValueError),
        (_huge_font_width_range, _extract_text, LimitReachedError),
        (_bad_ascii85_content, _extract_text, ValueError),
    ],
)
def test_each_fixture_trips_pypdf(build, stage, error):
    """Guards the fixtures: should pypdf change, this names the cause
    instead of the route tests failing on a 200."""
    with pytest.raises(error):
        stage(build())


def test_surrogate_fixture_yields_an_unpaired_surrogate():
    assert "\ud800" in PdfReader(io.BytesIO(_surrogate_font_map())).pages[0].extract_text()


# ── engine ───────────────────────────────────────────────────────────────────

# PDFs the page tools (extract, split, pdf → pdf) can't read, and pdf → txt.
_FOR_PAGES = [_deep_page_tree, _oversized_stream, _untyped_page]
_FOR_TEXT = [_deep_page_tree, _huge_font_width_range, _bad_ascii85_content]


@pytest.mark.parametrize("build", _FOR_PAGES)
def test_extract_pages_raises_unreadable(tmp_path, build):
    src = tmp_path / "in.pdf"
    src.write_bytes(build())
    with pytest.raises(UnreadablePdfError, match=_UNREADABLE):
        extract_pages(src, tmp_path / "out.pdf", "1")


@pytest.mark.parametrize("build", _FOR_PAGES)
def test_split_pdf_raises_unreadable(tmp_path, build):
    src = tmp_path / "in.pdf"
    src.write_bytes(build())
    with pytest.raises(UnreadablePdfError, match=_UNREADABLE):
        split_pdf(src)


# ── routes ───────────────────────────────────────────────────────────────────


_ROUTES = [
    ("/api/v1/pdf/extract", {"pages": "1"}, "invalid_pdf", "extract", _FOR_PAGES),
    ("/api/v1/pdf/split", {}, "invalid_pdf", "split", _FOR_PAGES),
    ("/api/v1/convert", {"target_format": "pdf"}, "invalid_input", "pdf", _FOR_PAGES),
    ("/api/v1/convert", {"target_format": "txt"}, "invalid_input", "txt", _FOR_TEXT),
]
_ROUTE_CASES = [
    pytest.param(path, data, build, code, id=f"{name}-{build.__name__}")
    for path, data, code, name, builds in _ROUTES
    for build in builds
]


@pytest.mark.parametrize(("path", "data", "build", "code"), _ROUTE_CASES)
def test_route_answers_400_without_a_logged_traceback(
    client, auth_headers, caplog, path, data, build, code
):
    with caplog.at_level(logging.INFO):
        r = client.post(
            path,
            headers=auth_headers,
            files={"file": ("doc.pdf", build(), "application/pdf")},
            data=data,
        )
    assert r.status_code == 400, r.text
    assert r.headers.get("X-FileMorph-Error-Code") == code
    assert r.json()["detail"] == _UNREADABLE
    assert [rec.getMessage() for rec in caplog.records if rec.exc_info] == []


@pytest.mark.parametrize(
    ("build", "target"),
    [
        pytest.param(_huge_font_width_range, "txt", id="txt-limit"),
        pytest.param(_bad_ascii85_content, "txt", id="txt-valueerror"),
        pytest.param(_oversized_stream, "pdf", id="pdf-limit"),
        pytest.param(_untyped_page, "pdf", id="pdf-valueerror"),
    ],
)
def test_convert_batch_names_the_unreadable_pdf(client, auth_headers, build, target):
    r = client.post(
        "/api/v1/convert/batch",
        headers=auth_headers,
        data={"target_formats": [target]},
        files=[("files", ("doc.pdf", build(), "application/pdf"))],
    )
    assert r.status_code == 422, r.text
    assert r.json()["files"][0]["error_message"] == _UNREADABLE


def test_log_names_the_error_class_not_its_message(client, auth_headers, caplog):
    """pypdf's message can quote the file; the log keeps only the class."""
    with caplog.at_level(logging.INFO):
        client.post(
            "/api/v1/pdf/split",
            headers=auth_headers,
            files={"file": ("doc.pdf", _oversized_stream(), "application/pdf")},
        )
    ours = [rec.getMessage() for rec in caplog.records if rec.name.startswith("app.")]
    assert "unreadable PDF: LimitReachedError" in ours
    assert not [msg for msg in ours if "80000000" in msg]


def test_pdf_to_txt_writes_an_unpaired_surrogate_as_question_mark(client, auth_headers):
    r = client.post(
        "/api/v1/convert",
        headers=auth_headers,
        files={"file": ("doc.pdf", _surrogate_font_map(), "application/pdf")},
        data={"target_format": "txt"},
    )
    assert r.status_code == 200, r.text
    assert r.content.strip() == b"?"
