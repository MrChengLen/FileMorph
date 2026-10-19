# SPDX-License-Identifier: AGPL-3.0-or-later
"""NEU-C.1.a: PDF/A-2b markup converter (pikepdf).

Pins the structural anchors a PDF/A consumer (or a downstream
veraPDF run from NEU-C.1.c) looks for:

1. The output is a valid PDF that pikepdf can re-open.
2. The XMP metadata declares ``pdfaid:part = 2`` and
   ``pdfaid:conformance = B``.
3. There is exactly one ``OutputIntent`` with subtype
   ``GTS_PDFA1`` and an embedded ICC profile.
4. PDF/A-forbidden surfaces are absent: no ``/JavaScript`` action,
   no ``/EmbeddedFiles`` name tree, no catalog ``/OpenAction``.
5. The conversion is idempotent — running the converter twice on
   the same input produces structurally equivalent output (different
   InstanceID, same conformance markers).

Conformance scope: the slice produces a *markup-only* PDF/A. A
source PDF with unembedded fonts will pass these tests but will
fail veraPDF's "all fonts embedded" check. That gap is closed by
NEU-C.1.b (ghostscript re-render).

Windows local-dev note
----------------------
``pikepdf`` bundles its own libqpdf shared lib. On Windows, if
``app.api.routes.auth`` loads first (it transitively pulls
cryptography + sqlalchemy ORM + Jinja2), the qpdf DLL fails to
initialise and the process segfaults during ``import pikepdf``.
This is a *test-collection* problem on Windows only — Linux CI
loads the libraries cleanly, and production runs on Linux. Tests
import ``pikepdf`` lazily *inside* each test function, gated on
``pytest.importorskip``, so collection on Windows does not
trigger the DLL load. A future investigation may find a clean
import-order fix; until then the skip is the contract.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

# Windows quirk: importing ``pikepdf`` after the auth-route's native
# stack (cryptography + sqlalchemy ORM + Jinja2) is loaded segfaults
# the process during qpdf DLL initialisation. The PDF/A path runs
# fine on Linux (CI + production), so the tests execute there; on
# Windows we skip the whole module rather than crash collection.
# The conftest unconditionally imports ``app.main`` (which loads the
# auth route), so by the time these fixtures run the DLL load order
# is already the broken one.
pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="pikepdf qpdf DLL conflicts with auth-route native deps on Windows; "
    "Linux CI + production are unaffected.",
)

from app.converters.base import InvalidInputError  # noqa: E402
from app.converters.pdfa import PdfToPdfaConverter  # noqa: E402


@pytest.fixture
def simple_pdf(tmp_path) -> Path:
    """Build a small PDF with embedded Helvetica via reportlab.

    reportlab subsets and embeds the standard 14 fonts on output —
    enough to satisfy the "looks like a sane source PDF" precondition
    for the markup-only converter."""
    path = tmp_path / "source.pdf"
    c = canvas.Canvas(str(path))
    c.setFont("Helvetica", 14)
    c.drawString(72, 720, "FileMorph PDF/A test fixture")
    c.drawString(72, 700, "Second line — covers two-content-stream output.")
    c.showPage()
    c.save()
    return path


@pytest.fixture
def converted(tmp_path, simple_pdf) -> Path:
    out = tmp_path / "out.pdf"
    PdfToPdfaConverter().convert(simple_pdf, out)
    return out


def test_output_is_a_valid_pdf(converted):
    """File starts with %PDF and re-opens cleanly with pikepdf."""
    pikepdf = pytest.importorskip("pikepdf")
    assert converted.read_bytes()[:4] == b"%PDF"
    with pikepdf.open(str(converted)) as pdf:
        assert len(pdf.pages) >= 1


def test_xmp_declares_pdfa_part_and_conformance(converted):
    pikepdf = pytest.importorskip("pikepdf")
    with pikepdf.open(str(converted)) as pdf:
        with pdf.open_metadata() as meta:
            part = meta.get("pdfaid:part")
            conformance = meta.get("pdfaid:conformance")
    assert part == "2", f"expected pdfaid:part=2, got {part!r}"
    assert conformance == "B", f"expected pdfaid:conformance=B, got {conformance!r}"


def test_xmp_contains_document_and_instance_ids(converted):
    """DocumentID and InstanceID are mandatory for veraPDF and let
    a downstream auditor correlate copies of the same document."""
    pikepdf = pytest.importorskip("pikepdf")
    with pikepdf.open(str(converted)) as pdf:
        with pdf.open_metadata() as meta:
            doc_id = meta.get("xmpMM:DocumentID")
            instance_id = meta.get("xmpMM:InstanceID")
    assert doc_id and doc_id.startswith("uuid:"), f"DocumentID={doc_id!r}"
    assert instance_id and instance_id.startswith("uuid:"), f"InstanceID={instance_id!r}"


def test_output_intent_is_gts_pdfa1_with_icc(converted):
    """Exactly one OutputIntent of subtype GTS_PDFA1 with an
    embedded ICC profile stream."""
    pikepdf = pytest.importorskip("pikepdf")
    with pikepdf.open(str(converted)) as pdf:
        intents = pdf.Root.get("/OutputIntents")
        assert intents is not None, "no /OutputIntents on catalog"
        assert len(intents) == 1
        oi = intents[0]
        assert str(oi["/S"]) == "/GTS_PDFA1"
        icc = oi["/DestOutputProfile"]
        assert icc is not None
        # ICC stream must declare 3 components for sRGB.
        assert int(icc["/N"]) == 3
        # And carry actual bytes (the sRGB profile is a few hundred bytes).
        assert len(bytes(icc.read_bytes())) > 100


def test_forbidden_surfaces_are_stripped(tmp_path, simple_pdf):
    """Inject a /JavaScript and /OpenAction into a source PDF and
    confirm the converter strips them on output. Guards against a
    silent regression where a future refactor drops the strip pass."""
    pikepdf = pytest.importorskip("pikepdf")
    spiked = tmp_path / "spiked.pdf"
    with pikepdf.open(str(simple_pdf)) as pdf:
        pdf.Root["/OpenAction"] = pikepdf.Dictionary(
            S=pikepdf.Name("/JavaScript"),
            JS=pikepdf.String("app.alert('xss');"),
        )
        names = pdf.Root.get("/Names") or pikepdf.Dictionary()
        names["/JavaScript"] = pikepdf.Dictionary(Names=pikepdf.Array())
        pdf.Root["/Names"] = names
        pdf.save(str(spiked))

    out = tmp_path / "cleaned.pdf"
    PdfToPdfaConverter().convert(spiked, out)

    with pikepdf.open(str(out)) as pdf:
        assert "/OpenAction" not in pdf.Root
        names = pdf.Root.get("/Names")
        if names is not None:
            assert "/JavaScript" not in names
            assert "/EmbeddedFiles" not in names


def _js(code: str):
    from pikepdf import Dictionary, Name, String

    return Dictionary(S=Name("/JavaScript"), JS=String(code))


def _annot(pdf, subtype, **entries):
    from pikepdf import Array, Dictionary, Name

    if isinstance(subtype, str):
        subtype = Name(subtype)
    return pdf.make_indirect(
        Dictionary(Type=Name("/Annot"), Subtype=subtype, Rect=Array([0, 0, 9, 9]), **entries)
    )


def _convert_without_ghostscript(pdf, tmp_path, monkeypatch) -> Path:
    """Save ``pdf`` and convert it on the markup-only path, which also runs
    when Ghostscript fails; return the output's path."""
    from app.converters import _ghostscript

    monkeypatch.setattr(_ghostscript, "is_available", lambda: False)
    src, out = tmp_path / "in.pdf", tmp_path / "out.pdf"
    pdf.save(str(src))
    PdfToPdfaConverter().convert(src, out)
    return out


def test_active_content_is_removed_without_ghostscript(tmp_path, monkeypatch):
    """Actions, additional actions and embedded files PDF/A-2 forbids go from
    the document, its page and annotations; the permitted link and page
    navigation stay."""
    pikepdf = pytest.importorskip("pikepdf")
    from pikepdf import Array, Dictionary, Name, String

    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(200, 200))
    page = pdf.pages[0].obj
    page["/AA"] = Dictionary(O=_js("page open"))
    page["/PresSteps"] = Dictionary(Type=Name("/NavNode"), NA=_js("next step"))
    filespec = pdf.make_indirect(
        Dictionary(
            Type=Name("/Filespec"), F=String("a.txt"), EF=Dictionary(F=pdf.make_stream(b"secret"))
        )
    )
    page["/AF"] = Array([filespec])
    attachment = _annot(pdf, "/FileAttachment", FS=filespec, AA=Dictionary(E=_js("enter")))
    uri = Dictionary(S=Name("/URI"), URI=String("https://example.com"))
    uri["/Next"] = Array([_js("then"), Dictionary(S=Name("/URI"), URI=String("https://a.example"))])
    page["/Annots"] = Array(
        [
            _annot(pdf, "/Link", A=_js("link")),
            _annot(pdf, "/Link", A=uri),
            _annot(pdf, "/Link", A=Dictionary(S=Name("/Named"), N=Name("/Print"))),
            _annot(pdf, "/Link", A=Dictionary(S=Name("/Named"), N=Name("/NextPage"))),
            attachment,
            _annot(pdf, "/Popup", Parent=attachment),  # still points at the attachment
            _annot(
                pdf,
                "/Widget",
                FT=Name("/Btn"),
                T=String("send"),
                A=Dictionary(S=Name("/SubmitForm"), F=String("https://example.com/form")),
                AA=Dictionary(D=_js("down")),
            ),
            _annot(
                pdf,
                "/Link",
                A=Dictionary(
                    S=Name("/GoToR"),
                    D=Array([0, Name("/Fit")]),
                    F=Dictionary(
                        Type=Name("/Filespec"),
                        F=String("other.pdf"),
                        EF=Dictionary(F=pdf.make_stream(b"copy")),
                    ),
                ),
            ),
        ]
    )
    widget = page["/Annots"][6]
    pdf.Root["/AcroForm"] = Dictionary(Fields=Array([widget]), XFA=pdf.make_stream(b"<xdp/>"))
    pdf.Root["/NeedsRendering"] = True
    pdf.Root["/OpenAction"] = _js("open")
    pdf.Root["/AF"] = Array([filespec])
    pdf.Root["/Collection"] = Dictionary(Type=Name("/Collection"))
    pdf.Root["/Names"] = Dictionary(
        JavaScript=Dictionary(Names=Array([String("js"), _js("named")])),
        EmbeddedFiles=Dictionary(Names=Array([String("a.txt"), filespec])),
        AlternatePresentations=Dictionary(Names=Array()),
        Renditions=Dictionary(Names=Array()),
        Templates=Dictionary(Names=Array()),
    )
    item = pdf.make_indirect(Dictionary(Title=String("t"), A=_js("bookmark")))
    item["/Next"] = item  # a sibling chain that loops back on itself
    pdf.Root["/Outlines"] = pdf.make_indirect(
        Dictionary(Type=Name("/Outlines"), First=item, Last=item)
    )

    out = _convert_without_ghostscript(pdf, tmp_path, monkeypatch)

    with pikepdf.open(str(out)) as pdf:
        root, page = pdf.Root, pdf.pages[0].obj
        for key in ("/AA", "/PresSteps", "/AF"):
            assert key not in page
        annots = list(page["/Annots"])
        assert [str(a["/Subtype"]) for a in annots] == [
            "/Link",
            "/Link",
            "/Link",
            "/Link",
            "/Popup",
            "/Widget",
            "/Link",
        ]
        assert "/A" not in annots[0]
        assert annots[1]["/A"]["/URI"] == "https://example.com"
        assert "/Next" not in annots[1]["/A"]
        assert "/A" not in annots[2]
        assert annots[3]["/A"]["/N"] == "/NextPage"
        assert "/A" not in annots[5] and "/AA" not in annots[5]
        assert annots[6]["/A"]["/F"]["/F"] == "other.pdf"
        assert not any(
            isinstance(o, pikepdf.Stream) and o.read_bytes() in (b"secret", b"copy", b"<xdp/>")
            for o in pdf.objects
        )
        assert "/XFA" not in root["/AcroForm"]
        for key in ("/NeedsRendering", "/OpenAction", "/AF", "/Collection"):
            assert key not in root
        assert list(root["/Names"].keys()) == []
        assert "/A" not in root["/Outlines"]["/First"]


@pytest.mark.filterwarnings("ignore:This document has 1 form widget")  # the unlisted one
def test_every_form_field_and_bookmark_is_swept(tmp_path, monkeypatch):
    """Form fields lose their actions wherever the form puts them, a field
    the form lists only through its widget included; a bookmark that is also
    listed as a form field doesn't keep the other bookmarks from the sweep."""
    pikepdf = pytest.importorskip("pikepdf")
    from pikepdf import Array, Dictionary, Name, String

    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(200, 200))

    def field(name, kid):
        parent = pdf.make_indirect(
            Dictionary(
                FT=Name("/Tx"), T=String(name), Kids=Array([kid]), AA=Dictionary(C=_js(name))
            )
        )
        kid["/Parent"] = parent
        return parent

    hidden_widget = _annot(pdf, "/Widget", AA=Dictionary(K=_js("hidden")))  # on no page
    listed = field("listed", hidden_widget)
    page_widget = _annot(pdf, "/Widget", AA=Dictionary(K=_js("visible")))
    field("unlisted", page_widget)  # reached through page_widget only
    pdf.pages[0].obj["/Annots"] = Array([page_widget])

    goto = Dictionary(S=Name("/GoTo"), D=Array([pdf.pages[0].obj, Name("/Fit")]))
    last = pdf.make_indirect(Dictionary(Title=String("last"), A=goto))
    second = pdf.make_indirect(Dictionary(Title=String("second"), A=_js("2"), Next=last))
    child = pdf.make_indirect(Dictionary(Title=String("child"), A=_js("child")))
    first = pdf.make_indirect(Dictionary(Title=String("first"), Next=second, First=child))
    pdf.Root["/Outlines"] = pdf.make_indirect(Dictionary(Type=Name("/Outlines"), First=first))
    pdf.Root["/AcroForm"] = Dictionary(Fields=Array([first, listed]))

    out = _convert_without_ghostscript(pdf, tmp_path, monkeypatch)

    with pikepdf.open(str(out)) as pdf:
        listed = pdf.Root["/AcroForm"]["/Fields"][1]
        page_widget = pdf.pages[0].obj["/Annots"][0]
        for obj in (listed, listed["/Kids"][0], page_widget, page_widget["/Parent"]):
            assert "/AA" not in obj
        first = pdf.Root["/Outlines"]["/First"]
        assert "/A" not in first["/Next"]
        assert "/A" not in first["/First"]
        assert first["/Next"]["/Next"]["/A"]["/S"] == "/GoTo"


def test_annotations_shared_by_pages_stay_one_array(tmp_path, monkeypatch):
    pikepdf = pytest.importorskip("pikepdf")
    from pikepdf import Array

    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(200, 200))
    pdf.add_blank_page(page_size=(200, 200))
    shared = pdf.make_indirect(
        Array([_annot(pdf, "/Link", A=_js("link")), _annot(pdf, "/FileAttachment")])
    )
    for page in pdf.pages:
        page.obj["/Annots"] = shared

    out = _convert_without_ghostscript(pdf, tmp_path, monkeypatch)

    with pikepdf.open(str(out)) as pdf:
        first, second = (page.obj["/Annots"] for page in pdf.pages)
        assert first.is_indirect and first.objgen == second.objgen
        assert [str(a["/Subtype"]) for a in first] == ["/Link"]
        assert "/A" not in first[0]


def test_a_pdf_with_more_than_the_sweep_checks_is_refused(tmp_path, monkeypatch):
    pikepdf = pytest.importorskip("pikepdf")
    from pikepdf import Array

    monkeypatch.setattr("app.converters.pdfa._MAX_SWEEP_OBJECTS", 10)
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(200, 200))
    pdf.pages[0].obj["/Annots"] = Array([_annot(pdf, "/Link") for _ in range(20)])

    with pytest.raises(InvalidInputError, match="Split it into smaller PDFs"):
        _convert_without_ghostscript(pdf, tmp_path, monkeypatch)


def test_malformed_entries_do_not_fail_the_conversion(tmp_path, monkeypatch):
    pikepdf = pytest.importorskip("pikepdf")
    from pikepdf import Array, Dictionary, Name, String

    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(200, 200))
    not_utf8 = pikepdf.Object.parse(b"/#FF")  # a name whose byte isn't UTF-8
    chain = None
    for i in range(3000):  # a long chain of follow-up actions
        action = Dictionary(S=Name("/URI"), URI=String(f"https://example.com/{i}"))
        if chain is not None:
            action["/Next"] = chain
        chain = pdf.make_indirect(action)
    pdf.pages[0].obj["/Annots"] = Array(
        [
            _annot(pdf, "/Link", A=Dictionary(S=Array([Name("/URI")]), URI=String("x"))),
            _annot(pdf, "/Link", A=Dictionary(S=Name("/Named"), N=Array([Name("/NextPage")]))),
            _annot(pdf, Array([Name("/FileAttachment")]), AA=Dictionary(E=_js("enter"))),
            _annot(pdf, "/Link", A=chain),
            _annot(pdf, not_utf8, AA=Dictionary(E=_js("enter"))),
            _annot(pdf, "/Link", A=Dictionary(S=not_utf8)),
            _annot(pdf, "/Link", A=Dictionary(S=Name("/Named"), N=not_utf8)),
        ]
    )
    pdf.Root["/AcroForm"] = Dictionary(Fields=5)

    out = _convert_without_ghostscript(pdf, tmp_path, monkeypatch)

    with pikepdf.open(str(out)) as pdf:
        annots = pdf.pages[0].obj["/Annots"]
        assert "/A" not in annots[0] and "/A" not in annots[1]
        assert "/AA" not in annots[2]
        assert annots[3]["/A"]["/URI"] == "https://example.com/2999"
        assert "/Next" not in annots[3]["/A"]
        assert "/AA" not in annots[4]
        assert "/A" not in annots[5] and "/A" not in annots[6]


def test_id_array_is_set(converted):
    """/ID is mandatory in PDF/A — gives the file a stable identity
    hash a downstream system can compare across copies."""
    pikepdf = pytest.importorskip("pikepdf")
    with pikepdf.open(str(converted)) as pdf:
        ids = pdf.trailer.get("/ID")
        assert ids is not None
        assert len(ids) == 2


def test_idempotent_conformance(tmp_path, simple_pdf):
    """Running the converter on its own output keeps conformance
    intact. InstanceID changes (a new save = a new instance);
    DocumentID and the part/conformance markers stay stable in
    spec terms (DocumentID may change too — that is acceptable for
    a markup-only converter that re-creates the metadata)."""
    pikepdf = pytest.importorskip("pikepdf")
    out1 = tmp_path / "a.pdf"
    out2 = tmp_path / "b.pdf"
    PdfToPdfaConverter().convert(simple_pdf, out1)
    PdfToPdfaConverter().convert(out1, out2)

    with pikepdf.open(str(out2)) as pdf:
        with pdf.open_metadata() as meta:
            assert meta.get("pdfaid:part") == "2"
            assert meta.get("pdfaid:conformance") == "B"
        assert pdf.Root.get("/OutputIntents") is not None


def test_route_accepts_pdf_to_pdfa(client, auth_headers, simple_pdf):
    """End-to-end: /api/v1/convert?target_format=pdfa returns a
    PDF/A-marked output via the existing route — confirms the
    registry wiring picked up the new converter."""
    pikepdf = pytest.importorskip("pikepdf")
    with simple_pdf.open("rb") as f:
        resp = client.post(
            "/api/v1/convert",
            files={"file": ("source.pdf", f, "application/pdf")},
            data={"target_format": "pdfa"},
            headers=auth_headers,
        )
    assert resp.status_code == 200, resp.text
    assert resp.content[:4] == b"%PDF"

    # Materialise the response into pikepdf so we can verify the markers
    # came back through the route, not just the converter unit.
    out_path = simple_pdf.parent / "via_route.pdf"
    out_path.write_bytes(resp.content)
    with pikepdf.open(str(out_path)) as pdf:
        with pdf.open_metadata() as meta:
            assert meta.get("pdfaid:part") == "2"
