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


# ── Split ────────────────────────────────────────────────────────────────────


def test_split_stops_at_the_cap_while_it_writes_pages(tmp_path, monkeypatch):
    src = tmp_path / "in.pdf"
    src.write_bytes(_raw_pdf([_TEXT] * 6))
    outputs = pdf_pages.split_pdf(src, 10**9)
    cap = len(outputs[0][1]) + len(outputs[1][1])  # two pages fit, a third does not

    writes = []
    real_write = PdfWriter.write

    def counting_write(self, stream):
        writes.append(stream)
        return real_write(self, stream)

    monkeypatch.setattr(PdfWriter, "write", counting_write)
    with pytest.raises(pdf_pages.SplitOutputTooLargeError) as caught:
        pdf_pages.split_pdf(src, cap)
    assert len(writes) == 3
    assert caught.value.size > cap


def test_split_route_answers_413_once_the_pages_pass_the_cap(client, auth_headers, monkeypatch):
    shrunk = dataclasses.replace(quotas_module.QUOTAS["anonymous"], output_cap_bytes=100)
    monkeypatch.setitem(quotas_module.QUOTAS, "anonymous", shrunk)
    res = _post(client, auth_headers, "/api/v1/pdf/split", _raw_pdf([_TEXT] * 3))
    assert res.status_code == 413
    assert res.headers["X-FileMorph-Error-Code"] == "output_cap_exceeded"
    assert res.json()["detail"].startswith("Output too large (")
