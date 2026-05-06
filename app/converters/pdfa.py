# SPDX-License-Identifier: AGPL-3.0-or-later
"""PDF → PDF/A-2b converter (NEU-C.1.a markup + NEU-C.1.b re-render).

Goal of this module
-------------------
Produce a PDF that veraPDF accepts at conformance level 2b. Two
paths cooperate:

1. **NEU-C.1.b — ghostscript re-render** (when ``gs`` is on PATH):
   gs's ``pdfwrite`` device with ``-dPDFA=2`` re-rasterises the
   content stream, embeds every font subset, drops PDF/A-forbidden
   features, and writes an ``OutputIntent`` from a generated
   PDFA_def.ps. This is what closes the "fonts must be embedded"
   gap — a source PDF with bare standard-14 references comes out
   with proper subset embeds.

2. **NEU-C.1.a — pikepdf markup pass** (always runs after gs, or
   alone when gs is unavailable): asserts the PDF/A markers
   pikepdf can write deterministically — XMP ``pdfaid:part=2`` /
   ``conformance=B``, ``xmpMM:DocumentID`` / ``InstanceID``, a
   clean ``/ID`` array, ``OutputIntent`` if not already present,
   and a sweep of PDF/A-forbidden surfaces (``/JavaScript``,
   ``/JS``, ``/OpenAction``, ``/EmbeddedFiles``).

Combined behaviour
------------------
Best case (gs available, source well-formed): ``rerender_succeeded``
path produces a veraPDF-2b-clean output.

Common case (gs unavailable on minimal hosts, e.g. Windows local-dev
or a slim container): ``markup-only`` path produces a structurally
valid PDF/A that declares 2b. veraPDF will accept it for sources
that already had embedded fonts; for sources that didn't, veraPDF
flags "fonts not embedded" and the operator knows to install gs
or use the source's authoring tool to re-export.

We never raise on a missing or broken gs install — the markup path
is the floor, gs is the upgrade.

Why pikepdf is imported lazily
------------------------------
pikepdf bundles its own libqpdf shared object. On Windows the
combination of (a) the Python auth-route's transitive native deps
(cryptography + sqlalchemy ORM + Jinja2) loaded first and (b) the
qpdf DLL loaded second produces a process-level segfault during
DLL initialisation. Deferring the ``import pikepdf`` until the
converter actually runs sidesteps the order: by then FastAPI has
finished bootstrapping and qpdf loads cleanly. The cost is one
extra import on the first PDF/A request — negligible compared to
the conversion itself.

The converter is registered as ``(pdf, pdfa)`` so users invoke it
through the existing ``/api/v1/convert?target_format=pdfa`` route
without learning a new endpoint.
"""

from __future__ import annotations

import logging
import tempfile
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from app.converters.base import BaseConverter
from app.converters.registry import register

if TYPE_CHECKING:
    import pikepdf as pikepdf_mod  # for type hints only

logger = logging.getLogger(__name__)


_PDFA_NAMESPACE = "http://www.aiim.org/pdfa/ns/id/"


def _srgb_icc_bytes() -> bytes:
    """Return the bytes of a baseline sRGB ICC profile.

    Lazy-imports PIL.ImageCms inside the function — keeps module-load
    light and avoids dragging the colour-management lib into every
    process that just wants the route registry."""
    from PIL import ImageCms

    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
    return profile.tobytes()


def _strip_forbidden_surfaces(pdf: "pikepdf_mod.Pdf") -> None:
    """Remove every catalog-level surface PDF/A-2b forbids.

    PDF/A-2 §6.1.2 forbids encryption (we never encrypt on output
    anyway, but a source PDF may be encrypted — pikepdf has already
    decrypted it on open, this just makes sure no remnant attribute
    leaks through). §6.6.1 forbids /JavaScript and /JS actions. §6.9
    forbids /EmbeddedFiles. /OpenAction at the catalog level can
    trigger script execution and is removed defensively.
    """
    catalog = pdf.Root

    for key in ("/AA", "/OpenAction", "/JavaScript", "/JS"):
        if key in catalog:
            del catalog[key]

    names = catalog.get("/Names")
    if names is not None:
        for forbidden in ("/JavaScript", "/EmbeddedFiles"):
            if forbidden in names:
                del names[forbidden]


def _ensure_id_array(pdf: "pikepdf_mod.Pdf") -> None:
    """Ensure the document has a /ID array.

    PDF/A wants every file to have an ID array so two copies can
    be compared by their canonical identifier. pikepdf's
    ``generate_appearance_streams`` etc. don't touch /ID; we set it
    explicitly from a fresh UUID so identity is reproducible from
    the conversion act, not inherited from the source's /ID."""
    import pikepdf

    fresh = uuid.uuid4().hex.encode("ascii")
    pdf.trailer["/ID"] = pikepdf.Array([pikepdf.String(fresh), pikepdf.String(fresh)])


def _attach_output_intent(pdf: "pikepdf_mod.Pdf", icc_bytes: bytes) -> None:
    """Embed the sRGB ICC profile as an OutputIntent on the catalog.

    PDF/A-2b §6.2.2 requires exactly one OutputIntent of subtype
    ``GTS_PDFA1`` with a DestOutputProfile. Subtype is "GTS_PDFA1"
    even for PDF/A-2 — the spec inherited the name from PDF/A-1.

    Builds the ICC stream with the correct ``/N`` (number of colour
    components) and ``/Alternate`` device-space hints so a viewer
    that doesn't honour the embedded profile still renders sensible
    colour."""
    import pikepdf

    icc_stream = pdf.make_stream(icc_bytes)
    icc_stream["/N"] = 3
    icc_stream["/Alternate"] = pikepdf.Name("/DeviceRGB")

    output_intent = pikepdf.Dictionary(
        Type=pikepdf.Name("/OutputIntent"),
        S=pikepdf.Name("/GTS_PDFA1"),
        OutputConditionIdentifier=pikepdf.String("sRGB IEC61966-2.1"),
        Info=pikepdf.String("sRGB IEC61966-2.1"),
        DestOutputProfile=icc_stream,
    )
    pdf.Root["/OutputIntents"] = pikepdf.Array([output_intent])


def _set_pdfa_xmp(pdf: "pikepdf_mod.Pdf") -> None:
    """Write the XMP metadata block PDF/A-2b validators look for.

    Two namespaces matter:

    * ``pdfaid`` — declares ``part=2`` and ``conformance=B``. Without
      these tags the file is "just a PDF that happens to be
      well-formed"; with them, a validator treats it as an
      asserted PDF/A.
    * ``xmpMM`` — declares ``DocumentID`` and ``InstanceID``. The
      DocumentID is stable across saves; the InstanceID changes
      every time the file is re-encoded. Both are UUID URNs.
    """
    doc_id = f"uuid:{uuid.uuid4()}"
    instance_id = f"uuid:{uuid.uuid4()}"

    with pdf.open_metadata(set_pikepdf_as_editor=False) as meta:
        meta["pdfaid:part"] = "2"
        meta["pdfaid:conformance"] = "B"
        meta["xmpMM:DocumentID"] = doc_id
        meta["xmpMM:InstanceID"] = instance_id


class PdfToPdfaConverter(BaseConverter):
    """Convert a PDF to PDF/A-2b.

    Tries the ghostscript re-render path first (NEU-C.1.b — embeds
    fonts, drops forbidden features) and falls back to the
    markup-only path (NEU-C.1.a) when gs is not on PATH or the
    invocation fails. Either way the output declares PDF/A-2b
    conformance and carries the structural anchors veraPDF expects.

    See module docstring for the layered conformance scope and for
    the reason ``pikepdf`` is imported lazily inside ``convert``."""

    def convert(self, input_path: Path, output_path: Path, **kwargs) -> Path:
        # Lazy import — see module docstring for the Windows DLL-load
        # conflict this avoids.
        import pikepdf

        from app.converters import _ghostscript as gs

        icc_bytes = _srgb_icc_bytes()

        # Stage 1: optional ghostscript re-render. The gs binary is
        # opportunistic — if it's not on PATH (Windows local-dev,
        # slim container), or if it fails on a degenerate input, we
        # skip it and run the pikepdf markup pass on the original.
        # The gs intermediate goes into a tempfile so the source PDF
        # is never overwritten before the markup pass reads it.
        gs_intermediate: Path | None = None
        source_for_markup = input_path
        rerender_mode = "markup"

        if gs.is_available():
            tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False, prefix="fm_pdfa_gs_")
            tmp.close()
            gs_intermediate = Path(tmp.name)
            try:
                gs.rerender_to_pdfa(input_path, gs_intermediate, icc_bytes=icc_bytes)
                source_for_markup = gs_intermediate
                rerender_mode = "rerender"
                logger.info(
                    "pdfa.convert: ghostscript re-render succeeded for %s",
                    input_path.name,
                )
            except gs.GhostscriptError as exc:
                # Don't fail the whole convert — fall through with the
                # original input. The structured log makes it
                # discoverable which conversions hit this path so the
                # operator can investigate at leisure.
                logger.warning(
                    "pdfa.convert: ghostscript failed for %s (%s); using markup-only path",
                    input_path.name,
                    exc,
                )

        try:
            # Stage 2: pikepdf markup pass. Idempotent — runs whether
            # the input is the original PDF (gs unavailable / failed)
            # or gs's re-rendered intermediate. The OutputIntent guard
            # avoids appending a second one when gs already wrote it
            # via PDFA_def.ps.
            with pikepdf.open(str(source_for_markup)) as pdf:
                _strip_forbidden_surfaces(pdf)
                _ensure_id_array(pdf)
                if pdf.Root.get("/OutputIntents") is None:
                    _attach_output_intent(pdf, icc_bytes)
                _set_pdfa_xmp(pdf)
                # ``object_stream_mode=disable`` keeps the byte layout
                # of the output close to what an external auditor
                # expects: PDF/A-2b allows object streams, but disabling
                # them produces a more readable file for forensic review
                # and makes the test assertions deterministic.
                pdf.save(
                    str(output_path),
                    object_stream_mode=pikepdf.ObjectStreamMode.disable,
                    linearize=False,
                )
        finally:
            if gs_intermediate is not None:
                gs_intermediate.unlink(missing_ok=True)

        logger.info("pdfa.convert: %s mode=%s", output_path.name, rerender_mode)
        return output_path


# Register PDF → PDF/A as a first-class conversion target. Self-host
# operators with ghostscript on PATH will get the upgraded re-render
# path in NEU-C.1.b without changing the registration here.
register(("pdf", "pdfa"))(PdfToPdfaConverter)
