# SPDX-License-Identifier: AGPL-3.0-or-later
"""PDF page-extract + split (Morph > Convert).

Covers the engine (``app/converters/pdf_pages.py``) and the dedicated
routes (``app/api/routes/pdf_pages.py``):

* extract a valid range / single page / full-doc range (page counts);
* split → ZIP (valid zip, one entry per page, each entry a real PDF);
* malformed / empty / out-of-range / reversed / non-numeric input →
  graceful 400 (no 500, no stack trace / pypdf internals in the body);
* the magic-byte guard still rejects a disguised executable;
* a non-PDF source is a 422.

Fixtures build multi-page PDFs in-process with pypdf (blank pages via
``add_blank_page``) — no binary fixtures committed.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from app.converters.pdf_pages import (
    PageSelectionError,
    extract_pages,
    parse_page_ranges,
    split_pdf,
)


def _make_pdf(path: Path, num_pages: int) -> Path:
    """Write a ``num_pages``-page PDF (blank A4-ish pages) via pypdf."""
    writer = PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=200, height=200)
    with path.open("wb") as f:
        writer.write(f)
    return path


def _pdf_bytes(num_pages: int) -> bytes:
    writer = PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


@pytest.fixture
def pdf5(tmp_path) -> Path:
    return _make_pdf(tmp_path / "five.pdf", 5)


# ── parse_page_ranges (pure unit) ────────────────────────────────────────────


@pytest.mark.parametrize(
    ("spec", "count", "expected"),
    [
        ("1-3,5", 5, [0, 1, 2, 4]),
        ("1", 5, [0]),
        ("1-5", 5, [0, 1, 2, 3, 4]),
        ("5", 5, [4]),
        ("  2 , 4 ", 5, [1, 3]),  # whitespace tolerance
        ("1-3,2-4", 5, [0, 1, 2, 3]),  # overlap collapses + sorts
        ("3,1", 5, [0, 2]),  # out-of-order singletons sort
        ("1,,3", 5, [0, 2]),  # stray comma tolerated
    ],
)
def test_parse_valid(spec, count, expected):
    assert parse_page_ranges(spec, count) == expected


@pytest.mark.parametrize(
    "spec",
    [
        "",  # empty
        "   ",  # whitespace only
        "0",  # zero (1-based)
        "-1",  # negative-ish / malformed range
        "6",  # out of range (>count)
        "1-6",  # range out of range
        "5-3",  # reversed
        "abc",  # non-numeric
        "1-",  # dangling range
        "-3",  # leading dash
        "2-x",  # non-numeric end
    ],
)
def test_parse_invalid_raises_page_selection_error(spec):
    with pytest.raises(PageSelectionError):
        parse_page_ranges(spec, 5)


def test_parse_zero_page_doc():
    with pytest.raises(PageSelectionError):
        parse_page_ranges("1", 0)


def test_parse_too_many_pages():
    # A huge range against a doc claiming that many pages must be capped.
    with pytest.raises(PageSelectionError):
        parse_page_ranges("1-20000", 20000)


# ── extract_pages (engine) ───────────────────────────────────────────────────


def test_extract_range(tmp_path, pdf5):
    out = tmp_path / "out.pdf"
    extract_pages(pdf5, out, "1-3,5")
    reader = PdfReader(str(out))
    assert len(reader.pages) == 4


def test_extract_single_page(tmp_path, pdf5):
    out = tmp_path / "out.pdf"
    extract_pages(pdf5, out, "2")
    reader = PdfReader(str(out))
    assert len(reader.pages) == 1


def test_extract_full_doc(tmp_path, pdf5):
    out = tmp_path / "out.pdf"
    extract_pages(pdf5, out, "1-5")
    reader = PdfReader(str(out))
    assert len(reader.pages) == 5


def test_extract_out_of_range_raises(tmp_path, pdf5):
    out = tmp_path / "out.pdf"
    with pytest.raises(PageSelectionError):
        extract_pages(pdf5, out, "99")


def test_extract_corrupt_pdf_raises_safe(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4 not really a pdf body")
    out = tmp_path / "out.pdf"
    with pytest.raises(PageSelectionError):
        extract_pages(bad, out, "1")


# ── split_pdf (engine) ───────────────────────────────────────────────────────


def test_split_returns_one_per_page(tmp_path, pdf5):
    outputs = split_pdf(pdf5)
    assert len(outputs) == 5
    names = [n for n, _ in outputs]
    assert names == ["page_1.pdf", "page_2.pdf", "page_3.pdf", "page_4.pdf", "page_5.pdf"]
    # Each chunk is a real single-page PDF.
    for _, content in outputs:
        assert content[:4] == b"%PDF"
        reader = PdfReader(io.BytesIO(content))
        assert len(reader.pages) == 1


def test_split_zero_padding_width(tmp_path):
    pdf = _make_pdf(tmp_path / "ten.pdf", 10)
    outputs = split_pdf(pdf)
    names = [n for n, _ in outputs]
    # 10 pages → width 2, so page 1 is "page_01.pdf" and sorts before page 10.
    assert names[0] == "page_01.pdf"
    assert names[-1] == "page_10.pdf"
    assert names == sorted(names)


def test_split_corrupt_pdf_raises_safe(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4 garbage")
    with pytest.raises(PageSelectionError):
        split_pdf(bad)


def test_split_too_many_pages_raises(tmp_path, monkeypatch, pdf5):
    """A PDF whose page count exceeds the selection ceiling is rejected
    *before* per-page writers are built — guards against a crafted/large
    document OOM-ing the worker.

    Stubs the page count rather than materialising 10 000+ real pages so
    the test stays fast and Windows-safe (pure pypdf, no pikepdf). The
    ceiling check must fire before the split loop ever runs.
    """
    import app.converters.pdf_pages as pp

    class _HugePages:
        def __len__(self) -> int:
            return pp._MAX_SELECTION_PAGES + 1

        def __iter__(self):
            # Must never be reached — the ceiling check precedes iteration.
            raise AssertionError("split_pdf iterated pages despite the ceiling")

    class _FakeReader:
        pages = _HugePages()

    monkeypatch.setattr(pp, "_open_reader", lambda _path: _FakeReader())
    with pytest.raises(PageSelectionError, match="Too many pages to split"):
        split_pdf(pdf5)


# ── route: /pdf/extract ──────────────────────────────────────────────────────

_PDF_MIME = "application/pdf"


def test_route_extract_range(client, auth_headers):
    res = client.post(
        "/api/v1/pdf/extract",
        headers=auth_headers,
        files={"file": ("doc.pdf", _pdf_bytes(5), _PDF_MIME)},
        data={"pages": "1-3,5"},
    )
    assert res.status_code == 200, res.text
    assert res.content[:4] == b"%PDF"
    reader = PdfReader(io.BytesIO(res.content))
    assert len(reader.pages) == 4
    # Download name carries the original stem, sanitised, never a disk path.
    assert "doc_pages.pdf" in res.headers.get("content-disposition", "")


def test_route_extract_single_page(client, auth_headers):
    res = client.post(
        "/api/v1/pdf/extract",
        headers=auth_headers,
        files={"file": ("doc.pdf", _pdf_bytes(3), _PDF_MIME)},
        data={"pages": "2"},
    )
    assert res.status_code == 200, res.text
    reader = PdfReader(io.BytesIO(res.content))
    assert len(reader.pages) == 1


@pytest.mark.parametrize("spec", ["", "0", "99", "5-3", "abc", "1-"])
def test_route_extract_bad_pages_is_400_no_stacktrace(client, auth_headers, spec):
    res = client.post(
        "/api/v1/pdf/extract",
        headers=auth_headers,
        files={"file": ("doc.pdf", _pdf_bytes(3), _PDF_MIME)},
        data={"pages": spec},
    )
    # Empty string is rejected by the engine (Form is required but accepts "");
    # all other specs are invalid selections. Either way: a clean 4xx, not 500.
    assert res.status_code in (400, 422), res.text
    assert res.status_code != 500
    body = res.text.lower()
    assert "traceback" not in body
    assert "pypdf" not in body


def test_route_extract_non_pdf_is_422(client, auth_headers):
    res = client.post(
        "/api/v1/pdf/extract",
        headers=auth_headers,
        files={"file": ("photo.jpg", b"\xff\xd8\xff\xe0fake", "image/jpeg")},
        data={"pages": "1"},
    )
    assert res.status_code == 422, res.text


def test_route_extract_corrupt_pdf_is_400(client, auth_headers):
    res = client.post(
        "/api/v1/pdf/extract",
        headers=auth_headers,
        files={"file": ("doc.pdf", b"%PDF-1.4 not a real pdf", _PDF_MIME)},
        data={"pages": "1"},
    )
    assert res.status_code == 400, res.text
    assert res.status_code != 500


def test_route_extract_blocks_disguised_executable(client, auth_headers):
    # A .pdf filename but PE magic bytes ("MZ") must be rejected by the
    # magic-byte guard before pypdf ever opens it.
    res = client.post(
        "/api/v1/pdf/extract",
        headers=auth_headers,
        files={"file": ("malware.pdf", b"MZ\x90\x00 this is a PE", _PDF_MIME)},
        data={"pages": "1"},
    )
    assert res.status_code == 400, res.text
    assert "not permitted" in res.text.lower()


# ── route: /pdf/split ────────────────────────────────────────────────────────


def test_route_split_returns_valid_zip(client, auth_headers):
    res = client.post(
        "/api/v1/pdf/split",
        headers=auth_headers,
        files={"file": ("doc.pdf", _pdf_bytes(4), _PDF_MIME)},
    )
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("application/zip")
    zf = zipfile.ZipFile(io.BytesIO(res.content))
    # No failures → no manifest.json, just the page PDFs.
    names = zf.namelist()
    assert len(names) == 4
    assert all(n.endswith(".pdf") for n in names)
    # Each entry is a real single-page PDF.
    for n in names:
        data = zf.read(n)
        assert data[:4] == b"%PDF"
        assert len(PdfReader(io.BytesIO(data)).pages) == 1
    assert "doc_pages.zip" in res.headers.get("content-disposition", "")


def test_route_split_single_page(client, auth_headers):
    res = client.post(
        "/api/v1/pdf/split",
        headers=auth_headers,
        files={"file": ("one.pdf", _pdf_bytes(1), _PDF_MIME)},
    )
    assert res.status_code == 200, res.text
    zf = zipfile.ZipFile(io.BytesIO(res.content))
    assert len(zf.namelist()) == 1


def test_route_split_non_pdf_is_422(client, auth_headers):
    res = client.post(
        "/api/v1/pdf/split",
        headers=auth_headers,
        files={"file": ("photo.png", b"\x89PNG\r\n\x1a\nfake", "image/png")},
    )
    assert res.status_code == 422, res.text


def test_route_split_corrupt_pdf_is_400_no_stacktrace(client, auth_headers):
    res = client.post(
        "/api/v1/pdf/split",
        headers=auth_headers,
        files={"file": ("doc.pdf", b"%PDF-1.4 broken", _PDF_MIME)},
    )
    assert res.status_code == 400, res.text
    assert res.status_code != 500
    assert "traceback" not in res.text.lower()


def test_route_split_blocks_disguised_executable(client, auth_headers):
    res = client.post(
        "/api/v1/pdf/split",
        headers=auth_headers,
        files={"file": ("x.pdf", b"\x7fELF this is an elf", _PDF_MIME)},
    )
    assert res.status_code == 400, res.text
    assert "not permitted" in res.text.lower()


# ── registry: pdf→pdf extract is a registry citizen ──────────────────────────


def test_registry_pdf_to_pdf_full_doc_passthrough(client, auth_headers):
    """Bare /convert?target_format=pdf with a PDF returns the whole doc
    (no `pages` param flows through convert, so it's a pass-through)."""
    res = client.post(
        "/api/v1/convert",
        headers=auth_headers,
        files={"file": ("doc.pdf", _pdf_bytes(3), _PDF_MIME)},
        data={"target_format": "pdf"},
    )
    assert res.status_code == 200, res.text
    assert res.content[:4] == b"%PDF"
    assert len(PdfReader(io.BytesIO(res.content)).pages) == 3
