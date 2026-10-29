# SPDX-License-Identifier: AGPL-3.0-or-later
"""Insert pages into a PDF (``POST /api/v1/pdf/insert``).

Covers the engine (``app/converters/pdf_insert.py``) and the route
(``app/api/routes/pdf_pages.py``):

* the pages go where asked — at the start, after page N, at the end — and the
  PDF keeps its bookmarks (on the right pages), its document info, and its
  page labels when the pages are appended;
* a link on an inserted page that would lead into the PDF is dropped;
* an image page takes its neighbour's size, turned to the image's
  orientation, the image fitted;
* Word files go through LibreOffice only, and the error says what to do
  without it;
* every error about one of the inputs names its form field
  (``X-FileMorph-Error-Field``) next to its code;
* no PDF is read in the app process: the child reads, counts and merges.

Fixtures are built in-process with pypdf and Pillow (page widths tell the
pages apart); LibreOffice is replaced by a stub that writes a PDF.
"""

from __future__ import annotations

import dataclasses
import re
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageFile
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    DictionaryObject,
    NameObject,
    RectangleObject,
    TextStringObject,
)

from app.converters import document, pdf_insert
from app.converters._isolated import TooComplexError
from app.converters.base import OutputTooLargeError
from app.converters.image import _ImageToPdfConverter
from app.converters.pdf_insert import WordNotConvertedError, insert_pages, word_to_pdf
from app.core import quotas as quotas_module

_A4 = (595, 842)


def _writer(widths: list[int], height: int = 200) -> PdfWriter:
    writer = PdfWriter()
    for width in widths:
        writer.add_blank_page(width=width, height=height)
    return writer


def _bytes(writer: PdfWriter) -> bytes:
    buf = BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _pdf(widths: list[int]) -> bytes:
    return _bytes(_writer(widths))


def _widths(data: bytes) -> list[int]:
    return [round(float(p.mediabox.width)) for p in PdfReader(BytesIO(data)).pages]


def _png(size: tuple[int, int]) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buf, format="PNG")
    return buf.getvalue()


def _link(writer: PdfWriter, page_index: int, action: DictionaryObject) -> None:
    page = writer.pages[page_index]
    annot = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Annot"),
            NameObject("/Subtype"): NameObject("/Link"),
            NameObject("/Rect"): RectangleObject((10, 10, 50, 30)),
            NameObject("/A"): action,
        }
    )
    annots = page.get("/Annots", ArrayObject())
    annots.append(writer._add_object(annot))
    page[NameObject("/Annots")] = annots


def _goto(name: str) -> DictionaryObject:
    return DictionaryObject(
        {NameObject("/S"): NameObject("/GoTo"), NameObject("/D"): TextStringObject(name)}
    )


def _uri(url: str) -> DictionaryObject:
    return DictionaryObject(
        {NameObject("/S"): NameObject("/URI"), NameObject("/URI"): TextStringObject(url)}
    )


def _docx() -> bytes:
    """A ZIP with ``word/document.xml``: what the route lets go to LibreOffice."""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("word/document.xml", "<w:document/>")
    return buf.getvalue()


def _insert(base: Path, insert: Path, out: Path, after_page, kind: str = "pdf") -> dict:
    """``insert_pages`` as the route calls it in the child, with a cap no
    fixture reaches."""
    return insert_pages(base, insert, out, after_page, kind, 10**9)


def _files(tmp_path: Path, base: bytes, insert: bytes) -> tuple[Path, Path, Path]:
    (tmp_path / "base.pdf").write_bytes(base)
    (tmp_path / "insert.pdf").write_bytes(insert)
    return tmp_path / "base.pdf", tmp_path / "insert.pdf", tmp_path / "out.pdf"


# ── Engine ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "index, expected",
    [
        (0, [300, 301, 200, 201, 202]),
        (1, [200, 300, 301, 201, 202]),
        (3, [200, 201, 202, 300, 301]),
    ],
    ids=["start", "after-1", "end"],
)
def test_pages_go_where_asked(tmp_path, index, expected):
    base, insert, out = _files(tmp_path, _pdf([200, 201, 202]), _pdf([300, 301]))

    result = _insert(base, insert, out, index)

    assert result == {"inserted_pages": 2, "page_count": 5}
    assert _widths(out.read_bytes()) == expected


def test_bookmarks_still_lead_to_their_pages(tmp_path):
    writer = _writer([200, 201, 202])
    for i in range(3):
        writer.add_outline_item(f"Chapter {i + 1}", i)
    writer.add_metadata({"/Title": "Term paper"})
    base, insert, out = _files(tmp_path, _bytes(writer), _pdf([300, 301]))

    _insert(base, insert, out, 1)

    reader = PdfReader(out)
    assert [(o.title, reader.get_destination_page_number(o)) for o in reader.outline] == [
        ("Chapter 1", 0),
        ("Chapter 2", 3),
        ("Chapter 3", 4),
    ]
    assert reader.metadata.title == "Term paper"


@pytest.mark.parametrize("index, kept", [(0, False), (2, False), (3, True)])
def test_page_labels_survive_only_when_appending(tmp_path, index, kept):
    """Printed numbers (i, ii, 1) would be wrong for every later page after an
    insertion before the end; appended pages continue the last range."""
    writer = _writer([200, 201, 202])
    writer.set_page_label(0, 1, style="/r")
    writer.set_page_label(2, 2, style="/D")
    base, insert, out = _files(tmp_path, _bytes(writer), _pdf([300]))

    _insert(base, insert, out, index)

    reader = PdfReader(out)
    assert ("/PageLabels" in reader.trailer["/Root"]) is kept
    if kept:
        assert reader.page_labels == ["i", "ii", "1", "2"]


def test_a_link_that_would_lead_into_the_pdf_is_dropped(tmp_path):
    """The inserted file names a destination "results" as the PDF does: after
    the merge its link would open the PDF's "results". Its other links stay."""
    base = _writer([200, 201, 202])
    base.add_named_destination("results", 2)
    insert = _writer([300, 301])
    insert.add_named_destination("results", 1)
    insert.add_named_destination("appendix", 1)
    for action in (_goto("results"), _goto("appendix"), _uri("https://example.org")):
        _link(insert, 0, action)
    base_path, insert_path, out = _files(tmp_path, _bytes(base), _bytes(insert))

    _insert(base_path, insert_path, out, 1)

    reader = PdfReader(out)
    kept = []
    for annot in reader.pages[1].get("/Annots", []):
        action = annot.get_object()["/A"]
        kept.append(action.get("/D") or action.get("/URI"))
    assert sorted(kept) == ["appendix", "https://example.org"]
    assert reader.get_destination_page_number(reader.named_destinations["results"]) == 4


def test_a_destination_tree_with_kids_keeps_its_names(tmp_path):
    """pdfTeX roots the destination tree in /Kids once a document has more
    than 32 names (most LaTeX theses). merge() would add a /Names array next
    to them, and viewers then find none of the PDF's names: the root keeps
    only its /Kids, the PDF's links still lead where they did, and the
    inserted file's named links go."""
    base = _writer([200, 201, 202])
    target = ArrayObject([base.pages[2].indirect_reference, NameObject("/Fit")])
    leaf = DictionaryObject(
        {
            NameObject("/Names"): ArrayObject([TextStringObject("results"), target]),
            NameObject("/Limits"): ArrayObject(
                [TextStringObject("results"), TextStringObject("results")]
            ),
        }
    )
    dests = DictionaryObject({NameObject("/Kids"): ArrayObject([base._add_object(leaf)])})
    base.root_object[NameObject("/Names")] = DictionaryObject(
        {NameObject("/Dests"): base._add_object(dests)}
    )
    _link(base, 0, _goto("results"))
    insert = _writer([300, 301])
    insert.add_named_destination("appendix", 1)
    _link(insert, 0, _goto("appendix"))
    _link(insert, 0, _uri("https://example.org"))
    base_path, insert_path, out = _files(tmp_path, _bytes(base), _bytes(insert))

    _insert(base_path, insert_path, out, 1)

    reader = PdfReader(out)
    root = reader.trailer["/Root"]["/Names"]["/Dests"]
    assert "/Names" not in root and "/Kids" in root
    assert reader.get_destination_page_number(reader.named_destinations["results"]) == 4
    inserted = [a.get_object()["/A"] for a in reader.pages[1].get("/Annots", [])]
    assert [a.get("/URI") for a in inserted] == ["https://example.org"]


@pytest.mark.parametrize(
    "image, index, neighbour_rotation, expected",
    [
        ((300, 400), 2, 0, _A4),
        ((400, 300), 2, 0, (842, 595)),
        ((300, 400), 0, 0, _A4),
        ((300, 400), 2, 90, _A4),
        ((400, 300), 2, 90, (842, 595)),
        ((300, 300), 2, 90, (842, 595)),
    ],
    ids=[
        "portrait",
        "landscape",
        "at-start",
        "turned-neighbour",
        "turned-neighbour-landscape",
        "square-keeps-the-neighbours-turn",
    ],
)
def test_an_image_page_takes_its_neighbours_size(
    tmp_path, image, index, neighbour_rotation, expected
):
    """A4 neighbour, the image's orientation: a phone photo fills an A4 page,
    a landscape chart a landscape one; a neighbour shown turned counts as
    shown."""
    writer = _writer([_A4[0]] * 2, height=_A4[1])
    if neighbour_rotation:
        writer.pages[max(index - 1, 0)].rotate(neighbour_rotation)
    (tmp_path / "photo.png").write_bytes(_png(image))
    image_pdf = tmp_path / "photo.pdf"
    _ImageToPdfConverter().convert(tmp_path / "photo.png", image_pdf)
    base = tmp_path / "base.pdf"
    base.write_bytes(_bytes(writer))
    out = tmp_path / "out.pdf"

    assert _insert(base, image_pdf, out, index, kind="image") == {
        "inserted_pages": 1,
        "page_count": 3,
    }

    page = PdfReader(out).pages[index]
    assert (round(float(page.mediabox.width)), round(float(page.mediabox.height))) == expected
    # Fitted and centred: one uniform scale, the image touching two opposite edges.
    a, _, _, d, e, f = (
        float(n)
        for n in re.findall(
            rb"(\S+) (\S+) (\S+) (\S+) (\S+) (\S+) cm", page.get_contents().get_data()
        )[0]
    )
    w, h = image[0] * 72 / 150, image[1] * 72 / 150
    assert a == pytest.approx(d)
    assert min(e, f) == pytest.approx(0, abs=0.01)
    assert a * w + 2 * e == pytest.approx(expected[0], abs=0.01)
    assert a * h + 2 * f == pytest.approx(expected[1], abs=0.01)


def test_a_pdf_without_pages_is_refused(tmp_path):
    base, insert, out = _files(tmp_path, _bytes(PdfWriter()), _pdf([300]))

    refused = _insert(base, insert, out, None)["refused"]

    assert (refused["code"], refused["field"]) == ("invalid_pdf", "file")


@pytest.mark.parametrize(
    "base_pages, insert_pages_, field", [(4, 1, "file"), (2, 2, "insert_file")]
)
def test_the_page_cap_names_the_file(tmp_path, monkeypatch, base_pages, insert_pages_, field):
    """Over the cap alone it is the PDF; only together, the file to insert.
    Both messages name the next step."""
    monkeypatch.setattr(pdf_insert, "_MAX_SELECTION_PAGES", 3)
    base, insert, out = _files(tmp_path, _pdf([200] * base_pages), _pdf([300] * insert_pages_))

    refused = _insert(base, insert, out, None)["refused"]

    assert (refused["code"], refused["field"]) == ("pdf_too_many_pages", field)
    assert "/api/v1/pdf/extract" in refused["message"]


def test_a_position_past_the_end_names_the_page_count(tmp_path):
    base, insert, out = _files(tmp_path, _pdf([200, 201, 202]), _pdf([300]))

    refused = _insert(base, insert, out, 4)["refused"]

    assert (refused["code"], refused["field"], refused["page_count"]) == (
        "invalid_position",
        "after_page",
        3,
    )
    assert not out.exists()


def test_an_encrypted_pdf_is_counted_by_its_pages(tmp_path):
    """pypdf takes an encrypted PDF's page count from the file unchecked; the
    position check and the headers rest on the pages the clone holds."""
    writer = _writer([200, 201, 202])
    writer.encrypt(user_password="", owner_password="owner")
    claimed_one = re.sub(rb"/Count 3", b"/Count 1", _bytes(writer), count=1)
    base, insert, out = _files(tmp_path, claimed_one, _pdf([300]))

    assert _insert(base, insert, out, 3) == {"inserted_pages": 1, "page_count": 4}


def test_the_result_stops_at_the_output_cap(tmp_path):
    base, insert, out = _files(tmp_path, _pdf([200] * 20), _pdf([300] * 20))

    with pytest.raises(OutputTooLargeError):
        insert_pages(base, insert, out, None, "pdf", 1000)


def test_an_unreadable_word_result_is_the_word_files_problem(tmp_path):
    """What LibreOffice wrote is the Word file's problem, not a "PDF" the
    user never uploaded."""
    base, insert, out = _files(tmp_path, _pdf([200]), b"%PDF-1.7 broken")

    refused = _insert(base, insert, out, None, kind="docx")["refused"]

    assert (refused["code"], refused["field"]) == ("word_not_converted", "insert_file")


def test_word_needs_libreoffice(tmp_path, monkeypatch):
    monkeypatch.setattr(document, "_soffice_available", lambda: False)
    with pytest.raises(WordNotConvertedError, match="save it as a PDF"):
        word_to_pdf(tmp_path / "in.docx", tmp_path / "out.pdf")


def test_word_never_takes_the_simple_engine(tmp_path, monkeypatch):
    """mammoth drops images and layout: an operator who chose it gets the
    PDF advice, not a rough page in the middle of a finished document."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "office_engine", "mammoth")
    monkeypatch.setattr(document, "_soffice_available", lambda: True)
    with pytest.raises(WordNotConvertedError):
        word_to_pdf(tmp_path / "in.docx", tmp_path / "out.pdf")


def test_word_conversion_failure_names_no_internals(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("soffice exited with status 1: secret path /tmp/x")

    monkeypatch.setattr(document, "_soffice_available", lambda: True)
    monkeypatch.setattr(document, "_convert_via_libreoffice", fail)
    (tmp_path / "in.docx").write_bytes(_docx())
    with pytest.raises(WordNotConvertedError) as info:
        word_to_pdf(tmp_path / "in.docx", tmp_path / "out.pdf")
    assert "soffice" not in str(info.value) and "save it as a PDF" in str(info.value)


def _zip_with_a_bad_name() -> bytes:
    """A ZIP whose member name is flagged UTF-8 but isn't: listing it raises
    UnicodeDecodeError, not BadZipFile."""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("word/document.xml", "<w:document/>")
        archive.writestr("placeholder.xml", "x")
    data = buf.getvalue()
    name = b"placeholder.xml"
    bad = b"\xff" * len(name)
    assert data.count(name) == 2, "ZIP layout changed — test setup bug"
    data = data.replace(name, bad)
    # Set the UTF-8 flag (bit 11) in the member's local and central header.
    for magic, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        start = data.rindex(magic, 0, data.index(bad, data.index(magic)))
        flags = int.from_bytes(data[start + offset : start + offset + 2], "little") | 0x800
        data = data[: start + offset] + flags.to_bytes(2, "little") + data[start + offset + 2 :]
    return data


@pytest.mark.parametrize(
    "content", [b"{\\rtf1 hello}", _zip_with_a_bad_name()], ids=["rtf", "bad-zip-name"]
)
def test_word_refuses_what_is_not_a_docx(tmp_path, monkeypatch, content):
    """Neither a renamed RTF nor a ZIP that can't be listed reaches LibreOffice;
    both get the Word advice, not a 500."""
    called = []
    monkeypatch.setattr(document, "_soffice_available", lambda: True)
    monkeypatch.setattr(document, "_convert_via_libreoffice", lambda *a, **k: called.append(a))
    (tmp_path / "in.docx").write_bytes(content)
    with pytest.raises(WordNotConvertedError, match=".docx format"):
        word_to_pdf(tmp_path / "in.docx", tmp_path / "out.pdf")
    assert called == []


def _post(
    client,
    auth_headers,
    base: bytes,
    insert: bytes,
    insert_name="insert.pdf",
    base_name="report.pdf",
    **data,
):
    return client.post(
        "/api/v1/pdf/insert",
        files={
            "file": (base_name, base, "application/pdf"),
            "insert_file": (insert_name, insert, "application/octet-stream"),
        },
        data={k: str(v) for k, v in data.items()},
        headers=auth_headers,
    )


def _field(response) -> str | None:
    return response.headers.get("X-FileMorph-Error-Field")


def _code(response) -> str | None:
    return response.headers.get("X-FileMorph-Error-Code")


def test_route_inserts_after_the_given_page(client, auth_headers):
    r = _post(client, auth_headers, _pdf([200, 201, 202]), _pdf([300]), after_page=2)

    assert r.status_code == 200, r.text
    assert _widths(r.content) == [200, 201, 300, 202]
    assert r.headers["X-FileMorph-Inserted-Pages"] == "1"
    assert r.headers["X-FileMorph-Page-Count"] == "4"
    assert "report_inserted.pdf" in r.headers["content-disposition"]


@pytest.mark.parametrize(
    "data, expected",
    [
        ({}, [200, 201, 300]),
        ({"after_page": 0}, [300, 200, 201]),
        ({"after_page": 2}, [200, 201, 300]),
    ],
    ids=["end-by-default", "start", "after-the-last"],
)
def test_route_start_and_end(client, auth_headers, data, expected):
    r = _post(client, auth_headers, _pdf([200, 201]), _pdf([300]), **data)

    assert r.status_code == 200, r.text
    assert _widths(r.content) == expected


def test_route_refuses_a_page_past_the_end_and_names_the_count(client, auth_headers):
    r = _post(client, auth_headers, _pdf([200, 201, 202]), _pdf([300]), after_page=4)

    assert r.status_code == 400
    assert (_code(r), _field(r)) == ("invalid_position", "after_page")
    assert r.headers["X-FileMorph-Page-Count"] == "3"


def test_route_fits_an_image_to_its_neighbour(client, auth_headers):
    base = _bytes(_writer([_A4[0]] * 2, height=_A4[1]))

    r = _post(
        client, auth_headers, base, _png((300, 400)), insert_name="signature.png", after_page=1
    )

    assert r.status_code == 200, r.text
    page = PdfReader(BytesIO(r.content)).pages[1]
    assert (round(float(page.mediabox.width)), round(float(page.mediabox.height))) == _A4


def test_route_inserts_a_word_file_through_libreoffice(client, auth_headers, monkeypatch):
    def libreoffice(input_path, output_path, timeout_s):
        output_path.write_bytes(_pdf([400, 401]))

    monkeypatch.setattr(document, "_soffice_available", lambda: True)
    monkeypatch.setattr(document, "_convert_via_libreoffice", libreoffice)
    r = _post(
        client,
        auth_headers,
        _pdf([200, 201]),
        _docx(),
        insert_name="statement.docx",
        after_page=1,
    )

    assert r.status_code == 200, r.text
    assert _widths(r.content) == [200, 400, 401, 201]
    assert r.headers["X-FileMorph-Inserted-Pages"] == "2"


def test_route_word_without_libreoffice_says_what_to_do(client, auth_headers, monkeypatch):
    monkeypatch.setattr(document, "_soffice_available", lambda: False)
    r = _post(client, auth_headers, _pdf([200]), b"PK\x03\x04docx", insert_name="statement.docx")

    assert r.status_code == 400
    assert (_code(r), _field(r)) == ("word_not_converted", "insert_file")
    assert "save it as a PDF" in r.json()["detail"]


@pytest.mark.parametrize(
    "name, hint", [("notes.txt", "can't be inserted"), ("thesis.odt", ".docx")]
)
def test_route_refuses_other_file_types(client, auth_headers, name, hint):
    r = _post(client, auth_headers, _pdf([200]), b"hello", insert_name=name)

    assert r.status_code == 415
    assert (_code(r), _field(r)) == ("unsupported_format", "insert_file")
    assert hint in r.json()["detail"]


def test_route_needs_a_pdf_to_insert_into(client, auth_headers):
    r = _post(client, auth_headers, b"PK\x03\x04", _pdf([300]), base_name="report.docx")

    assert r.status_code == 422
    assert _field(r) == "file"


@pytest.mark.parametrize("field", ["file", "insert_file"])
def test_route_names_the_unreadable_pdf(client, auth_headers, field):
    broken = b"%PDF-1.7\nthis is not a PDF\n%%EOF"
    files = {"file": _pdf([200]), "insert_file": _pdf([300])}
    files[field] = broken

    r = _post(client, auth_headers, files["file"], files["insert_file"])

    assert r.status_code == 400
    assert (_code(r), _field(r)) == ("invalid_pdf", field)
    assert "Traceback" not in r.text


def test_route_names_a_locked_pdf(client, auth_headers):
    writer = _writer([200])
    writer.encrypt("secret")

    r = _post(client, auth_headers, _bytes(writer), _pdf([300]))

    assert r.status_code == 400
    assert (_code(r), _field(r)) == ("pdf_encrypted", "file")


def test_route_blocks_an_executable_as_the_file_to_insert(client, auth_headers):
    r = _post(client, auth_headers, _pdf([200]), b"MZ\x90\x00 not a pdf", insert_name="x.pdf")

    assert r.status_code == 400
    assert (_code(r), _field(r)) == ("file_type_not_permitted", "insert_file")


def test_route_answers_a_refusal_with_its_field(client, auth_headers, monkeypatch):
    """What the child refuses comes back as a 400 that names the field."""

    def refuse(*args, **kwargs):
        return {
            "refused": {
                "code": "pdf_too_many_pages",
                "field": "insert_file",
                "message": "Together the files have too many pages.",
            }
        }

    monkeypatch.setattr("app.api.routes.pdf_pages.run_isolated", refuse)
    r = _post(client, auth_headers, _pdf([200]), _pdf([300]))

    assert r.status_code == 400
    assert (_code(r), _field(r)) == ("pdf_too_many_pages", "insert_file")
    assert r.json()["detail"] == "Together the files have too many pages."


@pytest.mark.parametrize(
    "refused",
    [
        {"code": "invalid_pdf", "field": "file\r\nX-Injected: 1", "message": "x"},
        {"code": "invalid pdf\r\n", "field": "file", "message": "x"},
    ],
    ids=["unknown-field", "code-not-a-name"],
)
def test_route_takes_only_known_fields_and_plain_codes_from_the_child(
    client, auth_headers, monkeypatch, refused
):
    """What the sandboxed child reports goes into headers and logs: anything
    but a known field and a plain code is a generic failure."""
    monkeypatch.setattr(
        "app.api.routes.pdf_pages.run_isolated", lambda *a, **k: {"refused": refused}
    )
    r = _post(client, auth_headers, _pdf([200]), _pdf([300]))

    assert r.status_code == 400
    assert (_code(r), _field(r)) == ("invalid_pdf", None)
    assert "X-Injected" not in r.headers


def test_route_reads_no_pdf_in_the_app_process(client, auth_headers, monkeypatch):
    """All PDF work runs within the child's limits: the app process reads no PDF."""

    def no_pdf_here(*args, **kwargs):
        raise AssertionError("a PDF was read in the app process")

    monkeypatch.setattr("app.converters.pdf_pages._open_reader", no_pdf_here)
    monkeypatch.setattr("app.converters.pdf_insert._open_reader", no_pdf_here)
    r = _post(client, auth_headers, _pdf([200, 201]), _pdf([300]), after_page=1)

    assert r.status_code == 200, r.text
    assert _widths(r.content) == [200, 300, 201]


def test_route_too_complex_points_on(client, auth_headers, monkeypatch):
    def too_complex(*args, too_large, **kwargs):
        raise TooComplexError(too_large)

    monkeypatch.setattr("app.api.routes.pdf_pages.run_isolated", too_complex)
    r = _post(client, auth_headers, _pdf([200]), _pdf([300]))

    assert r.status_code == 400
    assert _code(r) == "pdf_too_complex"
    assert "/api/v1/pdf/extract" in r.json()["detail"]


def test_route_hides_an_unexpected_failure(client, auth_headers, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("isolated pdf-insert failed: KeyError /secret/path")

    monkeypatch.setattr("app.api.routes.pdf_pages.run_isolated", boom)
    r = _post(client, auth_headers, _pdf([200]), _pdf([300]))

    assert r.status_code == 400
    assert _code(r) == "invalid_pdf"
    assert "secret" not in r.text and "KeyError" not in r.text


def test_route_names_a_damaged_image(client, auth_headers, monkeypatch):
    """A truncated JPEG passes the format check and fails while decoding:
    a 400 that names the field, not a bare 500. Importing WeasyPrint sets
    Pillow's LOAD_TRUNCATED_IMAGES for the whole process (then Pillow pads a
    cut-off image instead of failing), and an earlier test may have imported
    it: the test sets Pillow's default itself."""
    monkeypatch.setattr(ImageFile, "LOAD_TRUNCATED_IMAGES", False)
    buf = BytesIO()
    Image.effect_noise((200, 200), 90).convert("RGB").save(buf, format="JPEG")
    truncated = buf.getvalue()[: len(buf.getvalue()) // 2]

    r = _post(client, auth_headers, _pdf([200]), truncated, insert_name="scan.jpg")

    assert r.status_code == 400
    assert (_code(r), _field(r)) == ("invalid_input", "insert_file")


# pytest resets the warning filters per test; apply_hardening turns the warning into
# an error at startup, so do the same here.
@pytest.mark.filterwarnings("error::PIL.Image.DecompressionBombWarning")
@pytest.mark.parametrize("limit", [100, 1000], ids=["over-twice-the-limit", "just-over"])
def test_route_names_an_image_over_the_size_limit(client, auth_headers, monkeypatch, limit):
    """40 x 40 pixels against a limit of 100 raises Pillow's error, against
    1000 its warning (made an error at startup): both are decompression_bomb."""
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", limit)

    r = _post(client, auth_headers, _pdf([200]), _png((40, 40)), insert_name="big.png")

    assert r.status_code == 400
    assert (_code(r), _field(r)) == ("decompression_bomb", "insert_file")


def test_route_turns_a_portrait_photo_upright(client, auth_headers):
    """A phone photo stored landscape with EXIF orientation 6 is a portrait:
    it gets a portrait page next to an A4 page."""
    tags = Image.Exif()
    tags[0x0112] = 6  # Orientation
    buf = BytesIO()
    Image.new("RGB", (400, 300), (200, 30, 30)).save(buf, format="JPEG", exif=tags.tobytes())
    base = _bytes(_writer([_A4[1]] * 2, height=_A4[0]))  # landscape A4 neighbours

    r = _post(client, auth_headers, base, buf.getvalue(), insert_name="photo.jpg", after_page=1)

    assert r.status_code == 200, r.text
    page = PdfReader(BytesIO(r.content)).pages[1]
    assert (round(float(page.mediabox.width)), round(float(page.mediabox.height))) == _A4


def test_route_keeps_to_the_output_cap(client, auth_headers, monkeypatch):
    real = quotas_module.get_quota

    def small_cap(tier):
        return dataclasses.replace(real(tier), output_cap_bytes=100)

    monkeypatch.setattr("app.api.routes.pdf_pages.get_quota", small_cap)
    r = _post(client, auth_headers, _pdf([200]), _pdf([300]))

    assert r.status_code == 413
    assert _code(r) == "output_cap_exceeded"


@pytest.mark.parametrize("field", ["file", "insert_file"])
def test_route_names_the_file_over_the_size_cap(client, auth_headers, monkeypatch, field):
    real = quotas_module.get_quota
    big = _pdf([200] * 40)
    small = _pdf([200])

    def cap(tier):
        return dataclasses.replace(real(tier), max_file_size_bytes=len(small) + 10)

    monkeypatch.setattr("app.api.routes.pdf_pages.get_quota", cap)
    files = {"file": small, "insert_file": small}
    files[field] = big
    r = _post(client, auth_headers, files["file"], files["insert_file"])

    assert r.status_code == 413
    assert (_code(r), _field(r)) == ("input_too_large", field)


def test_insert_headers_are_exposed_cross_origin():
    """Network quadruple (c): a cross-origin page can read what the insertion
    reports — counts, and which field an error belongs to."""
    from starlette.middleware.cors import CORSMiddleware

    from app.main import app

    cors = next(m for m in app.user_middleware if m.cls is CORSMiddleware)
    expose = cors.kwargs["expose_headers"]
    for header in (
        "X-FileMorph-Error-Field",
        "X-FileMorph-Inserted-Pages",
        "X-FileMorph-Page-Count",
    ):
        assert header in expose


def test_docs_quote_the_insert_limits():
    """security-overview.md names the child's limits as _isolated sets them."""
    from app.converters import _isolated

    _, function, memory, seconds, file_bytes = _isolated._STEPS["pdf-insert"]
    assert function == "insert_pages"
    text = (Path(__file__).resolve().parent.parent / "docs" / "security-overview.md").read_text(
        encoding="utf-8"
    )
    expected = (
        f"stopped after {seconds} seconds, capped at {memory // _isolated._GIB} GiB of address "
        f"space and {file_bytes // _isolated._GIB} GiB per file written"
    )
    assert expected in " ".join(text.split())


# ── Page ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "prefix, h1, position_hint",
    [
        ("/en", "Insert pages into a PDF", "not by the printed page numbers"),
        ("/de", "Seiten in ein PDF einfügen", "nicht nach der gedruckten Seitenzahl"),
    ],
)
def test_the_page_offers_both_files_and_the_position(client, prefix, h1, position_hint):
    """The page has the two upload fields, the three positions (the end
    preselected), the counting hint and "Insert something else" — in the
    page's language."""
    html = client.get(f"{prefix}/pdf/insert").text

    assert h1 in html
    assert 'data-endpoint="/api/v1/pdf/insert"' in html
    for dom_id in ("pdf-drop", "pdf-insert-drop", "pdf-after-page", "pdf-insert-more"):
        assert f'id="{dom_id}"' in html
    assert re.search(r'value="end"[^>]*checked', html)
    assert position_hint in html
    accept = re.search(r'id="pdf-insert-file"[^>]*accept="([^"]+)"', html, re.S).group(1)
    assert {".pdf", ".docx", ".jpg", ".png"} <= set(accept.split(","))
