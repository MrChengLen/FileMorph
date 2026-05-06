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
