# SPDX-License-Identifier: AGPL-3.0-or-later
"""NEU-C.1.b: ghostscript-backed re-render path of PdfToPdfaConverter.

Exercises the upgrade path that closes the "fonts must be embedded"
gap in the markup-only slice. Pinned behaviours:

1. After re-render, every font referenced from the page tree carries
   a ``/FontFile*`` byte stream — i.e. nothing is left as a bare
   standard-14 reference.
2. The PDF/A markers from the markup pass survive the gs round-trip
   (XMP ``pdfaid:part=2`` / ``conformance=B``, exactly one
   ``OutputIntent``, ``/ID`` array set).
3. Forbidden surfaces injected on the source still get stripped on
   the output even though gs handled the heavy lift.
4. When the gs invocation fails (simulated subprocess error), the
   converter falls back to the markup-only path and still produces
   a valid output — the gs path is opportunistic, not load-bearing.

Skips
-----
* Windows: pikepdf's bundled qpdf DLL conflicts with the auth-route's
  native deps when imported in the same process. Linux CI and Linux
  production are unaffected. (Same conftest interaction as
  ``test_pdfa.py``.)
* Hosts without ``gs``/``gswin64c`` on PATH: the gs path can't run,
  so the gs-specific assertions would be meaningless. The fallback
  test (4) is also gated on gs availability because it patches the
  gs entry-point — without gs ``is_available()`` returns False at
  import time and the orchestrator never enters the gs branch in the
  first place, making the patch a no-op.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

# See module docstring for why both gates apply.
pytestmark = [
    pytest.mark.skipif(
        sys.platform == "win32",
        reason="pikepdf qpdf DLL conflicts with auth-route native deps on Windows; "
        "Linux CI + production are unaffected.",
    ),
    pytest.mark.skipif(
        shutil.which("gs") is None
        and shutil.which("gswin64c") is None
        and shutil.which("gswin32c") is None,
        reason="ghostscript not on PATH; markup-only path is covered by test_pdfa.py",
    ),
]

from app.converters.pdfa import PdfToPdfaConverter  # noqa: E402


@pytest.fixture
def simple_pdf(tmp_path) -> Path:
    """Build a small PDF with a Helvetica draw call.

    Helvetica is one of PDF's standard 14 fonts — reportlab references
    it by name without embedding glyph data. That is exactly the
    "fonts not embedded" failure mode PDF/A-2b rejects, and what
    NEU-C.1.b's gs re-render is meant to fix."""
    path = tmp_path / "source.pdf"
    c = canvas.Canvas(str(path))
    c.setFont("Helvetica", 14)
    c.drawString(72, 720, "FileMorph PDF/A re-render fixture")
    c.drawString(72, 700, "Two lines, standard-14 reference only.")
    c.showPage()
    c.save()
    return path


def _all_fonts_have_embedded_program(pdf) -> tuple[int, int]:
    """Walk page resources and report (total_fonts, embedded_fonts).

    A font is considered embedded if its ``/FontDescriptor`` carries
    a ``/FontFile``, ``/FontFile2`` (TrueType), or ``/FontFile3``
    (OpenType / Type 1C) stream. Fonts without a descriptor or
    without a font-file entry are the standard-14 references that
    PDF/A-2b rejects."""
    total = 0
    embedded = 0
    for page in pdf.pages:
        resources = page.get("/Resources")
        if resources is None:
            continue
        fonts = resources.get("/Font")
        if fonts is None:
            continue
        for _name, font in fonts.items():
            total += 1
            descriptor = font.get("/FontDescriptor")
            if descriptor is None:
                continue
            if any(k in descriptor for k in ("/FontFile", "/FontFile2", "/FontFile3")):
                embedded += 1
    return total, embedded


def test_rerender_embeds_all_fonts(simple_pdf, tmp_path):
    """Every font reference in the output has its glyph program
    embedded. Without the gs pass, reportlab's Helvetica reference
    would come through as a bare standard-14 entry — gs subset-embeds
    it as part of the PDF/A-2 conversion."""
    pikepdf = pytest.importorskip("pikepdf")
    out = tmp_path / "rerendered.pdf"
    PdfToPdfaConverter().convert(simple_pdf, out)

    with pikepdf.open(str(out)) as pdf:
        total, embedded = _all_fonts_have_embedded_program(pdf)

    assert total > 0, "no fonts found in output — fixture or extractor broke"
    assert embedded == total, (
        f"{embedded}/{total} fonts embedded; PDF/A-2b requires every font to ship its glyph program"
    )


def test_rerender_preserves_pdfa_markers(simple_pdf, tmp_path):
    """gs writes its own OutputIntent via PDFA_def.ps; the pikepdf
    markup pass appends DocumentID/InstanceID/XMP-MM and verifies
    the catalog-level markers are present and singular."""
    pikepdf = pytest.importorskip("pikepdf")
    out = tmp_path / "rerendered.pdf"
    PdfToPdfaConverter().convert(simple_pdf, out)

    with pikepdf.open(str(out)) as pdf:
        with pdf.open_metadata() as meta:
            assert meta.get("pdfaid:part") == "2"
            assert meta.get("pdfaid:conformance") == "B"
            assert meta.get("xmpMM:DocumentID", "").startswith("uuid:")
            assert meta.get("xmpMM:InstanceID", "").startswith("uuid:")
        intents = pdf.Root.get("/OutputIntents")
        assert intents is not None
        assert len(intents) == 1, (
            "expected exactly one OutputIntent — gs writes one via PDFA_def.ps "
            "and the markup pass must not append a second"
        )
        assert str(intents[0]["/S"]) == "/GTS_PDFA1"


def test_rerender_strips_forbidden_surfaces(tmp_path, simple_pdf):
    """Even after gs re-render, the markup pass strips any /OpenAction
    or /JavaScript surfaces that might survive (or that gs left in
    when gs's own filtering is permissive)."""
    pikepdf = pytest.importorskip("pikepdf")
    spiked = tmp_path / "spiked.pdf"
    with pikepdf.open(str(simple_pdf)) as pdf:
        pdf.Root["/OpenAction"] = pikepdf.Dictionary(
            S=pikepdf.Name("/JavaScript"),
            JS=pikepdf.String("app.alert('xss');"),
        )
        pdf.save(str(spiked))

    out = tmp_path / "cleaned.pdf"
    PdfToPdfaConverter().convert(spiked, out)
    with pikepdf.open(str(out)) as pdf:
        assert "/OpenAction" not in pdf.Root


def test_ghostscript_failure_falls_back_to_markup(monkeypatch, simple_pdf, tmp_path):
    """Simulate a gs subprocess failure and confirm the converter
    still emits a valid PDF/A-2b output via the markup-only path."""
    from app.converters import _ghostscript as gs_mod

    pikepdf = pytest.importorskip("pikepdf")

    def boom(*args, **kwargs):
        raise gs_mod.GhostscriptError("simulated subprocess failure")

    monkeypatch.setattr(gs_mod, "rerender_to_pdfa", boom)

    out = tmp_path / "fallback.pdf"
    PdfToPdfaConverter().convert(simple_pdf, out)

    # The output is markup-only — markers present, but fonts are NOT
    # required to be embedded (that's the gap gs would have closed).
    with pikepdf.open(str(out)) as pdf:
        with pdf.open_metadata() as meta:
            assert meta.get("pdfaid:part") == "2"
            assert meta.get("pdfaid:conformance") == "B"
        assert pdf.Root.get("/OutputIntents") is not None
