# SPDX-License-Identifier: AGPL-3.0-or-later
"""Work limits of the PDF tools.

* Page selections: a page selected twice counts once against the cap, and a
  selection may be at most ``_MAX_SELECTION_CHARS`` long.
* Split stops at the caller's output cap while it writes the pages.
"""

from __future__ import annotations

import dataclasses

import pytest
from pypdf import PdfWriter

from app.converters import pdf_pages
from app.converters.base import OutputTooLargeError
from app.core import quotas as quotas_module

_TEXT = b"BT /F1 12 Tf 20 100 Td (Hello) Tj ET\n"
_PDF_MIME = "application/pdf"


def _stream(data: bytes) -> bytes:
    return b"<< /Length %d >>\nstream\n" % len(data) + data + b"\nendstream"


def _raw_pdf(contents: list[bytes]) -> bytes:
    """One page per entry of ``contents`` (its content stream), Helvetica as /F1."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    resources = b"/Font << /F1 3 0 R >>"
    kids = []
    for content in contents:
        objects.append(_stream(content))
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Resources << %s >> /Contents %d 0 R >>"
            % (resources, len(objects))
        )
        kids.append(b"%d 0 R" % len(objects))
    objects[1] = b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(kids), len(kids))

    out = bytearray(b"%PDF-1.7\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def _post(client, auth_headers, path: str, pdf: bytes, data: dict | None = None):
    return client.post(
        path, headers=auth_headers, files={"file": ("doc.pdf", pdf, _PDF_MIME)}, data=data or {}
    )


# ── Page selections ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("spec", ["1-2,1-2", "1-2,2", "1,2,1"])
def test_a_page_selected_twice_counts_once(monkeypatch, spec):
    monkeypatch.setattr(pdf_pages, "_MAX_SELECTION_PAGES", 2)
    assert pdf_pages.parse_page_ranges(spec, 3) == [0, 1]


def test_every_page_plus_a_repeat_stays_within_the_cap():
    assert len(pdf_pages.parse_page_ranges("1-10000,1-5", 10_000)) == 10_000


def test_adjacent_and_overlapping_ranges_merge_in_order():
    assert pdf_pages.parse_page_ranges("6,3-4,1-2,2-3", 6) == [0, 1, 2, 3, 5]


def test_repeated_ranges_are_expanded_once(monkeypatch):
    # Counts the page indices the parser builds: one per distinct page, however
    # often the selection repeats a range.
    expanded: list[int] = []

    def counting_range(*args):
        pages = range(*args)
        expanded.append(len(pages))
        return pages

    monkeypatch.setattr(pdf_pages, "range", counting_range, raising=False)
    spec = ",".join(["1-5000"] * 9000)
    assert len(spec) <= pdf_pages._MAX_SELECTION_CHARS
    assert pdf_pages.parse_page_ranges(spec, 5000) == list(range(5000))
    assert sum(expanded) == 5000


def test_selection_exactly_at_the_length_limit_is_read():
    spec = "1," * (pdf_pages._MAX_SELECTION_CHARS // 2)
    assert len(spec) == pdf_pages._MAX_SELECTION_CHARS
    assert pdf_pages.parse_page_ranges(spec, 1) == [0]


def test_selection_over_the_length_limit_gets_400(client, auth_headers):
    spec = "1," * (pdf_pages._MAX_SELECTION_CHARS // 2 + 1)
    res = _post(client, auth_headers, "/api/v1/pdf/extract", _raw_pdf([_TEXT]), {"pages": spec})
    assert res.status_code == 400
    assert res.json()["detail"] == pdf_pages._SELECTION_TOO_LONG
    assert res.headers["X-FileMorph-Error-Code"] == "invalid_page_selection"


@pytest.mark.parametrize(
    "spec",
    [
        pytest.param("1," * 20_000, id="longer-than-a-windows-command-line"),
        # U+0661 ARABIC-INDIC DIGIT ONE is a 1 to int(); escaped in JSON it takes
        # six characters, more than a Linux argument may hold in all.
        pytest.param("\u0661," * 30_000, id="longer-than-a-linux-argument-escaped"),
    ],
)
def test_a_selection_within_the_length_limit_reaches_the_child(client, auth_headers, spec):
    """The extraction runs in a child process; the selection goes there in a
    file, as any selection up to the limit may be longer than a command line."""
    assert len(spec) <= pdf_pages._MAX_SELECTION_CHARS
    res = _post(client, auth_headers, "/api/v1/pdf/extract", _raw_pdf([_TEXT]), {"pages": spec})
    assert res.status_code == 200, res.text


# ── Split ────────────────────────────────────────────────────────────────────


def test_split_stops_at_the_cap_while_it_writes_pages(tmp_path, monkeypatch):
    src = tmp_path / "in.pdf"
    src.write_bytes(_raw_pdf([_TEXT] * 6))
    full, capped = tmp_path / "full", tmp_path / "capped"
    full.mkdir()
    capped.mkdir()
    pdf_pages.split_pdf(src, full, 10**9)
    first, second = pdf_pages.page_file_names(6)[:2]
    # two pages fit, a third does not
    cap = (full / first).stat().st_size + (full / second).stat().st_size

    writes = []
    real_write = PdfWriter.write

    def counting_write(self, stream):
        writes.append(stream)
        return real_write(self, stream)

    monkeypatch.setattr(PdfWriter, "write", counting_write)
    with pytest.raises(OutputTooLargeError):
        pdf_pages.split_pdf(src, capped, cap)
    assert len(writes) == 3


def test_split_route_answers_413_once_the_pages_pass_the_cap(client, auth_headers, monkeypatch):
    shrunk = dataclasses.replace(quotas_module.QUOTAS["anonymous"], output_cap_bytes=100)
    monkeypatch.setitem(quotas_module.QUOTAS, "anonymous", shrunk)
    res = _post(client, auth_headers, "/api/v1/pdf/split", _raw_pdf([_TEXT] * 3))
    assert res.status_code == 413
    assert res.headers["X-FileMorph-Error-Code"] == "output_cap_exceeded"
    assert res.json()["detail"].startswith("Output too large (over the ")
