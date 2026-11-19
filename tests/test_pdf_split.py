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

import dataclasses
import io
import json
import os
import sys
import zipfile
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from app.converters.pdf_pages import (
    PageSelectionError,
    TooManyPagesError,
    extract_pages,
    page_file_names,
    parse_page_ranges,
    split_pdf,
)
from app.core import quotas as quotas_module


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
    with pytest.raises(TooManyPagesError):
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


def test_split_writes_one_file_per_page(tmp_path, pdf5):
    pages = tmp_path / "pages"
    pages.mkdir()
    assert split_pdf(pdf5, pages, 10**9) == 5
    names = sorted(p.name for p in pages.iterdir())
    assert names == ["page_1.pdf", "page_2.pdf", "page_3.pdf", "page_4.pdf", "page_5.pdf"]
    # Each file is a real single-page PDF.
    for name in names:
        content = (pages / name).read_bytes()
        assert content[:4] == b"%PDF"
        reader = PdfReader(io.BytesIO(content))
        assert len(reader.pages) == 1


def test_split_zero_padding_width(tmp_path):
    pdf = _make_pdf(tmp_path / "ten.pdf", 10)
    pages = tmp_path / "pages"
    pages.mkdir()
    split_pdf(pdf, pages, 10**9)
    names = page_file_names(10)
    # 10 pages → width 2, so page 1 is "page_01.pdf" and sorts before page 10.
    assert names[0] == "page_01.pdf"
    assert names[-1] == "page_10.pdf"
    assert names == sorted(names)
    assert sorted(p.name for p in pages.iterdir()) == names


def test_split_corrupt_pdf_raises_safe(tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4 garbage")
    with pytest.raises(PageSelectionError):
        split_pdf(bad, tmp_path, 10**9)


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
    with pytest.raises(TooManyPagesError) as caught:
        split_pdf(pdf5, tmp_path, 10**9)
    assert str(caught.value) == pp._TOO_MANY_PAGES_TO_SPLIT


# ── the child steps ──────────────────────────────────────────────────────────
# The child passes on an InvalidInputError's message, not its class: the steps
# hand the routes their error code as data.


def _selection(tmp_path: Path, spec: str) -> Path:
    path = tmp_path / "selection.json"
    path.write_text(json.dumps(spec), encoding="ascii")
    return path


@pytest.mark.parametrize(
    ("source", "spec", "code", "message"),
    [
        pytest.param(b"%PDF-1.4 garbage", "1", "invalid_pdf", "Could not read the PDF", id="file"),
        pytest.param(None, "9", "invalid_page_selection", "Page 9 is out of range", id="selection"),
        # The cap is 2 here; the message names the real one, built at import.
        pytest.param(None, "1-5", "pdf_too_many_pages", "at most 10,000 pages", id="cap"),
    ],
)
def test_extract_step_refuses_with_the_routes_code(
    tmp_path, monkeypatch, pdf5, source, spec, code, message
):
    import app.converters.pdf_pages as pp

    monkeypatch.setattr(pp, "_MAX_SELECTION_PAGES", 2)
    src = pdf5
    if source is not None:
        src = tmp_path / "bad.pdf"
        src.write_bytes(source)
    out = tmp_path / "out.pdf"
    refused = pp.extract_step(src, out, _selection(tmp_path, spec))["refused"]
    assert refused["code"] == code
    assert message in refused["message"]
    assert not out.exists()


def test_extract_step_reads_the_selection_from_its_file(tmp_path, pdf5):
    out = tmp_path / "out.pdf"
    from app.converters.pdf_pages import extract_step

    assert extract_step(pdf5, out, _selection(tmp_path, "2-3,5")) == {}
    assert len(PdfReader(out).pages) == 3


def test_split_step_reports_the_page_count(tmp_path, pdf5):
    from app.converters.pdf_pages import split_step

    assert split_step(pdf5, tmp_path, 10**9) == {"pages": 5}
    assert sorted(p.name for p in tmp_path.glob("page_*.pdf")) == page_file_names(5)


@pytest.mark.parametrize(
    ("source", "message"),
    [
        pytest.param(b"%PDF-1.4 garbage", "Could not read the PDF", id="unreadable"),
        pytest.param(None, "The PDF has no pages to split.", id="no-pages"),
    ],
)
def test_split_step_refuses_an_unreadable_pdf(tmp_path, source, message):
    from app.converters.pdf_pages import split_step

    src = tmp_path / "in.pdf"
    src.write_bytes(_pdf_bytes(0) if source is None else source)
    refused = split_step(src, tmp_path, 10**9)["refused"]
    assert refused["code"] == "invalid_pdf"
    assert message in refused["message"]


def test_a_locked_pdf_is_left_to_the_child(tmp_path):
    """``_main`` passes ``EncryptedPdfError`` on as such: the steps don't refuse it."""
    from app.converters.base import EncryptedPdfError
    from app.converters.pdf_pages import extract_step, split_step

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt(user_password="secret", owner_password="owner", algorithm="AES-128")
    src = tmp_path / "locked.pdf"
    with src.open("wb") as f:
        writer.write(f)
    with pytest.raises(EncryptedPdfError):
        extract_step(src, tmp_path / "out.pdf", _selection(tmp_path, "1"))
    with pytest.raises(EncryptedPdfError):
        split_step(src, tmp_path, 10**9)


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
    # The file is the problem, not the selection — the UI says so.
    assert res.headers.get("X-FileMorph-Error-Code") == "invalid_pdf"


def test_route_extract_page_out_of_range_is_invalid_page_selection(client, auth_headers):
    res = client.post(
        "/api/v1/pdf/extract",
        headers=auth_headers,
        files={"file": ("doc.pdf", _pdf_bytes(1), _PDF_MIME)},
        data={"pages": "9"},
    )
    assert res.status_code == 400, res.text
    assert res.headers.get("X-FileMorph-Error-Code") == "invalid_page_selection"


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


# ── the child process ────────────────────────────────────────────────────────

_PAGE_ROUTES = [
    pytest.param("/api/v1/pdf/extract", {"pages": "1-2"}, id="extract"),
    pytest.param("/api/v1/pdf/split", {}, id="split"),
    pytest.param("/api/v1/convert", {"target_format": "pdf"}, id="pdf-to-pdf"),
]


@pytest.mark.parametrize(("path", "data"), _PAGE_ROUTES)
def test_route_reads_no_pdf_in_the_app_process(client, auth_headers, monkeypatch, path, data):
    """pypdf reads the upload within the child's limits only."""

    def no_pdf_here(*args, **kwargs):
        raise AssertionError("a PDF was read in the app process")

    monkeypatch.setattr("app.converters.pdf_pages._open_reader", no_pdf_here)
    res = client.post(
        path,
        headers=auth_headers,
        files={"file": ("doc.pdf", _pdf_bytes(3), _PDF_MIME)},
        data=data,
    )
    assert res.status_code == 200, res.text


def _post_pdf(client, auth_headers, path, data):
    return client.post(
        path, headers=auth_headers, files={"file": ("doc.pdf", _pdf_bytes(1), _PDF_MIME)}, data=data
    )


@pytest.mark.parametrize(
    "result",
    [
        {"refused": {"code": "invalid_pdf\r\nX-Injected: 1", "message": "x"}},
        {"refused": {"code": "some_other_code", "message": "x"}},
        {"refused": {"code": "invalid_pdf", "message": ["not", "text"]}},
        {"refused": "invalid_pdf"},
        ["not", "a", "result"],
    ],
    ids=["code-not-a-name", "unknown-code", "message-not-text", "no-details", "not-a-dict"],
)
@pytest.mark.parametrize(("path", "data"), _PAGE_ROUTES[:2])
def test_route_takes_only_known_codes_and_text_from_the_child(
    client, auth_headers, monkeypatch, path, data, result
):
    """What the sandboxed child reports goes into a header and the answer:
    anything but a known code and a text is a generic failure."""
    monkeypatch.setattr("app.api.routes.pdf_pages.run_isolated", lambda *a, **k: result)
    res = _post_pdf(client, auth_headers, path, data)
    assert res.status_code == 500, res.text
    assert "X-Injected" not in res.headers
    assert "X-FileMorph-Error-Code" not in res.headers


@pytest.mark.parametrize("count", [0, -1, 10_001, True, "1", None], ids=repr)
def test_split_takes_only_a_page_count_within_the_cap_from_the_child(
    client, auth_headers, monkeypatch, count
):
    monkeypatch.setattr("app.api.routes.pdf_pages.run_isolated", lambda *a, **k: {"pages": count})
    res = _post_pdf(client, auth_headers, "/api/v1/pdf/split", {})
    assert res.status_code == 500, res.text


def test_split_reads_the_pages_by_names_it_makes_itself(client, auth_headers, monkeypatch):
    """From the child only the number of pages: a file it writes under any
    other name stays out of the ZIP."""

    def child(*args, pages_path, **kwargs):
        (pages_path / "page_1.pdf").write_bytes(b"%PDF-1.7 the page")
        (pages_path / "notes.txt").write_bytes(b"not a page")
        return {"pages": 1}

    monkeypatch.setattr("app.api.routes.pdf_pages.run_isolated", child)
    res = _post_pdf(client, auth_headers, "/api/v1/pdf/split", {})
    assert res.status_code == 200, res.text
    archive = zipfile.ZipFile(io.BytesIO(res.content))
    assert archive.namelist() == ["page_1.pdf"]
    assert archive.read("page_1.pdf") == b"%PDF-1.7 the page"


def test_split_takes_the_childs_pages_only_up_to_the_output_cap(client, auth_headers, monkeypatch):
    """The child stops at the cap; the route counts again as it reads."""
    shrunk = dataclasses.replace(quotas_module.QUOTAS["anonymous"], output_cap_bytes=100)
    monkeypatch.setitem(quotas_module.QUOTAS, "anonymous", shrunk)

    def child(*args, pages_path, **kwargs):
        (pages_path / "page_1.pdf").write_bytes(b"%PDF" + bytes(200))
        return {"pages": 1}

    monkeypatch.setattr("app.api.routes.pdf_pages.run_isolated", child)
    res = _post_pdf(client, auth_headers, "/api/v1/pdf/split", {})
    assert res.status_code == 413, res.text
    assert res.headers["X-FileMorph-Error-Code"] == "output_cap_exceeded"


@pytest.mark.skipif(sys.platform != "linux", reason="symlinks and FIFOs as on the server")
@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_split_takes_only_plain_files_from_the_child(client, auth_headers, monkeypatch, kind):
    """A link is not followed, and nothing but a file is waited on."""

    def child(*args, pages_path, **kwargs):
        page = pages_path / "page_1.pdf"
        if kind == "symlink":
            target = pages_path.parent / "elsewhere.pdf"
            target.write_bytes(b"%PDF-1.7 not the page")
            os.symlink(target, page)
        else:
            os.mkfifo(page)
        return {"pages": 1}

    monkeypatch.setattr("app.api.routes.pdf_pages.run_isolated", child)
    res = _post_pdf(client, auth_headers, "/api/v1/pdf/split", {})
    assert res.status_code == 500, res.text


def test_the_pages_folder_goes_once_the_pages_are_read(tmp_path):
    from app.api.routes.pdf_pages import _split_pages

    pages = tmp_path / "pages"
    pages.mkdir()
    for name, content in zip(page_file_names(2), (b"one", b"two"), strict=True):
        (pages / name).write_bytes(content)
    assert _split_pages(pages, 2, 6) == [("page_1.pdf", b"one"), ("page_2.pdf", b"two")]
    assert not pages.exists()
