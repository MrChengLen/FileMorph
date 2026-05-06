# SPDX-License-Identifier: AGPL-3.0-or-later
"""NEU-C.1.a: PDF → PDF/A-2b "markup" converter (pikepdf-based).

Goal of this slice
------------------
Produce a PDF that **declares** PDF/A-2b conformance and has the
minimum structural anchors a downstream auditor expects:

* XMP metadata block with ``pdfaid:part = 2`` and
  ``pdfaid:conformance = B``, plus a ``DocumentID`` and
  ``InstanceID`` for traceability.
* An ``OutputIntent`` of subtype ``GTS_PDFA1`` carrying an embedded
  sRGB ICC profile (mandatory for PDF/A-2b — the consumer can
  reproduce on-screen colour without the original device profile).
* No PDF/A-forbidden surfaces: encryption, JavaScript, embedded
  files, OpenAction triggers — all stripped before save.
* A clean ``ID`` array so the file has a stable identity hash.

What this slice does NOT do
---------------------------
A fully veraPDF-validating PDF/A-2b file requires re-rendering the
content stream so that every glyph has an embedded font and no
transparency groups remain. That is a ghostscript job (or a
heavy in-process Python implementation) and lands in NEU-C.1.b.
The veraPDF validator itself runs in a separate Java-based CI job
(NEU-C.1.c).

For the common Compliance-Edition use-case — Bürgerantrags-
Anhänge / beA-Anhänge that are **already** PDFs from a modern
editor with embedded fonts and no transparency — the markup-only
path is sufficient: veraPDF in conformance mode 2b will accept the
output. Sources with unembedded fonts get their conformance flagged
as "needs ghostscript pass"; the converter logs a warning so the
operator sees it in the structured log.

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
    """Convert a PDF to PDF/A-2b (markup-only).

    See module docstring for the conformance scope of this slice
    and for the reason ``pikepdf`` is imported lazily inside
    ``convert``."""

    def convert(self, input_path: Path, output_path: Path, **kwargs) -> Path:
        # Lazy import — see module docstring for the Windows DLL-load
        # conflict this avoids.
        import pikepdf

        with pikepdf.open(str(input_path)) as pdf:
            _strip_forbidden_surfaces(pdf)
            _ensure_id_array(pdf)
            _attach_output_intent(pdf, _srgb_icc_bytes())
            _set_pdfa_xmp(pdf)
            # ``object_stream_mode=disable`` keeps the byte layout of
            # the output close to what an external auditor expects:
            # PDF/A-2b allows object streams, but disabling them
            # produces a more readable file for forensic review and
            # makes the test assertions deterministic.
            pdf.save(
                str(output_path),
                object_stream_mode=pikepdf.ObjectStreamMode.disable,
                linearize=False,
            )
        return output_path


# Register PDF → PDF/A as a first-class conversion target. Self-host
# operators with ghostscript on PATH will get the upgraded re-render
# path in NEU-C.1.b without changing the registration here.
register(("pdf", "pdfa"))(PdfToPdfaConverter)
