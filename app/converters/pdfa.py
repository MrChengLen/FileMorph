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
   and a sweep of the active content PDF/A-2 forbids: additional
   actions (``/AA``), JavaScript and other forbidden actions on the
   document, its pages, annotations, form fields and bookmarks,
   embedded files, and media/3D annotations.

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

from app.converters.base import BaseConverter, InvalidInputError, open_pikepdf
from app.converters.registry import register

if TYPE_CHECKING:
    import pikepdf as pikepdf_mod  # for type hints only

logger = logging.getLogger(__name__)


_PDFA_NAMESPACE = "http://www.aiim.org/pdfa/ns/id/"


# The white-space bytes the PDF spec lists (and that Ghostscript skips) before
# the ``%PDF-`` header: NUL, tab, line feed, form feed, carriage return, space.
# Stripping exactly these — and no other control bytes — before the header check
# keeps an accepted file to ``<white-space>* %PDF-``, which Ghostscript also
# reads as a PDF. See ``_has_pdf_header``.
_PDF_LEADING_WHITESPACE = b"\x00\t\n\f\r "


def _has_pdf_header(path: Path) -> bool:
    """True only if the file's first non-white-space bytes are the ``%PDF-`` header.

    Stage 1 hands the file to Ghostscript, which reads it as a PDF or as a
    PostScript program from its leading bytes, not from the upload's name. A real
    PDF carries ``%PDF-`` first, optionally behind the white-space bytes the PDF
    spec permits there (``_PDF_LEADING_WHITESPACE``). This gate strips exactly
    those bytes and requires ``%PDF-`` immediately after, so every accepted file
    is one Ghostscript also reads as a PDF. A file that places any other byte —
    or a UTF-8 BOM — before the header, or carries no header, is refused even if
    ``%PDF-`` appears later in the window. A damaged PDF keeps the header at the
    front, so Ghostscript still gets its repair pass."""
    with path.open("rb") as fh:
        head = fh.read(1024)
    return head.lstrip(_PDF_LEADING_WHITESPACE)[:5] == b"%PDF-"


def _srgb_icc_bytes() -> bytes:
    """Return the bytes of a baseline sRGB ICC profile.

    Lazy-imports PIL.ImageCms inside the function — keeps module-load
    light and avoids dragging the colour-management lib into every
    process that just wants the route registry."""
    from PIL import ImageCms

    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
    return profile.tobytes()


# Action types PDF/A-2 permits (ISO 19005-2, 6.5.1 forbids Launch, Sound,
# Movie, ResetForm, ImportData, Hide, SetOCGState, Rendition, Trans,
# GoTo3DView and JavaScript); a Named action only for page navigation. Any
# other action — forbidden or unknown — is removed.
_ALLOWED_ACTIONS = {"/GoTo", "/GoToR", "/GoToE", "/Thread", "/URI", "/SubmitForm", "/Named"}
_ALLOWED_NAMED_ACTIONS = {"/NextPage", "/PrevPage", "/FirstPage", "/LastPage"}
# Annotation types PDF/A-2 forbids or that carry an embedded file (6.3.1, 6.8).
_FORBIDDEN_ANNOTATIONS = {"/FileAttachment", "/Sound", "/Movie", "/Screen", "/3D", "/RichMedia"}
# Upper bound on the pages, annotations, form fields and bookmarks one sweep
# looks at. A file with more is refused rather than converted half-swept.
_MAX_SWEEP_OBJECTS = 200_000
_TOO_MANY_OBJECTS = (
    "This PDF has more links, form fields and bookmarks than a PDF/A conversion "
    "can check. Split it into smaller PDFs and convert each one."
)


def _name(value) -> str:
    """``value`` as text for a set lookup: a name as ``"/Link"``, anything else
    (an array, say) as its repr, and a name that isn't UTF-8 as ""."""
    try:
        return str(value)
    except UnicodeDecodeError:
        return ""


def _permitted(action) -> bool:
    """True if ``action`` is an action PDF/A-2 permits."""
    import pikepdf

    if not isinstance(action, pikepdf.Dictionary):
        return False
    kind = _name(action.get("/S"))
    return kind in _ALLOWED_ACTIONS and (
        kind != "/Named" or _name(action.get("/N")) in _ALLOWED_NAMED_ACTIONS
    )


def _clean_action(obj) -> None:
    """Drop ``obj``'s ``/A`` unless PDF/A-2 permits it. A kept action loses
    the actions chained after it (``/Next``), so no chain has to be followed,
    and an embedded copy of the file it opens."""
    import pikepdf

    action = obj.get("/A")
    if action is None:
        return
    if not _permitted(action):
        del obj["/A"]
        return
    if "/Next" in action:
        del action["/Next"]
    target = action.get("/F")
    if isinstance(target, pikepdf.Dictionary):
        for key in ("/EF", "/RF"):
            if key in target:
                del target[key]


def _strip_forbidden_surfaces(pdf: "pikepdf_mod.Pdf") -> None:
    """Remove the active content PDF/A-2b forbids and the files attached to
    the document, its pages and annotations.

    From the catalog: additional actions (6.5.2), the open action, associated
    files, a portfolio (``/Collection``), ``/NeedsRendering`` (6.4.2) and the
    ``/JavaScript``, ``/EmbeddedFiles`` (6.8), ``/AlternatePresentations``
    (6.10), ``/Renditions`` and ``/Templates`` name trees. From every page:
    additional actions (6.5.2), presentation steps (6.10), associated files,
    and annotations of a forbidden type (6.3.1, 6.8), which are also emptied
    in case something else still points at them. The other annotations lose
    their additional actions and associated files, form fields and their
    widgets every action (6.4.1), the AcroForm its XFA (6.4.2), and links and
    bookmarks any action PDF/A-2 forbids (6.5.1).
    """
    import pikepdf

    budget = _MAX_SWEEP_OBJECTS

    def spend(count: int = 1) -> None:
        nonlocal budget
        budget -= count
        if budget < 0:
            raise InvalidInputError(_TOO_MANY_OBJECTS)

    def walk(first_items, children_keys: tuple[str, ...]):
        """Yield the dictionaries reachable through ``children_keys``, each once."""
        # Per walk: fields and bookmarks are separate trees. Only indirect
        # objects can close a cycle, so only they are remembered, by object
        # number (pikepdf wraps a direct object anew on every access).
        seen: set[tuple[int, int]] = set()
        pending = list(first_items)
        while pending:
            item = pending.pop()
            if not isinstance(item, pikepdf.Dictionary):
                continue
            if item.is_indirect:
                if item.objgen in seen:
                    continue
                seen.add(item.objgen)
            spend()
            yield item
            for key in children_keys:
                child = item.get(key)
                if isinstance(child, pikepdf.Array):
                    spend(len(child))
                    pending.extend(child)
                elif child is not None:
                    pending.append(child)

    catalog = pdf.Root
    for key in (
        "/AA",
        "/OpenAction",
        "/JavaScript",
        "/JS",
        "/AF",
        "/Collection",
        "/NeedsRendering",
    ):
        if key in catalog:
            del catalog[key]

    names = catalog.get("/Names")
    if isinstance(names, pikepdf.Dictionary):
        for key in (
            "/JavaScript",
            "/EmbeddedFiles",
            "/AlternatePresentations",
            "/Renditions",
            "/Templates",
        ):
            if key in names:
                del names[key]

    widgets = []
    seen_annots: set[tuple[int, int]] = set()
    spend(len(pdf.pages))
    for page in pdf.pages:
        for key in ("/AA", "/PresSteps", "/AF"):
            if key in page.obj:
                del page.obj[key]
        annots = page.obj.get("/Annots")
        if not isinstance(annots, pikepdf.Array):
            continue
        if annots.is_indirect:  # an array several pages share is swept once
            if annots.objgen in seen_annots:
                continue
            seen_annots.add(annots.objgen)
        spend(len(annots))
        kept = []
        for annot in annots:
            if not isinstance(annot, pikepdf.Dictionary):
                continue
            subtype = _name(annot.get("/Subtype"))
            if subtype in _FORBIDDEN_ANNOTATIONS:
                keys = list(annot.keys())
                spend(len(keys))
                for key in keys:  # a popup's /Parent may still point here
                    if key not in ("/Type", "/Subtype"):
                        del annot[key]
                continue
            for key in ("/AA", "/AF"):
                if key in annot:
                    del annot[key]
            if subtype == "/Widget":
                widgets.append(annot)  # loses its actions with the form fields below
            else:
                _clean_action(annot)
            kept.append(annot)
        if len(kept) < len(annots):
            # In place, so a shared array stays one array; clear + extend
            # takes linear time where deleting entry by entry would not.
            annots.clear()
            annots.extend(kept)

    # Form fields and widgets: the walk goes down /Kids and up /Parent, so a
    # field the /Fields tree leaves out is reached through its widgets.
    seeds = widgets
    acroform = catalog.get("/AcroForm")
    if isinstance(acroform, pikepdf.Dictionary):
        if "/XFA" in acroform:
            del acroform["/XFA"]
        for key in ("/Fields", "/CO"):
            fields = acroform.get(key)
            if isinstance(fields, pikepdf.Array):
                spend(len(fields))
                seeds.extend(fields)
    for field in walk(seeds, ("/Kids", "/Parent")):
        for key in ("/AA", "/A"):
            if key in field:
                del field[key]

    outlines = catalog.get("/Outlines")
    if isinstance(outlines, pikepdf.Dictionary):
        for item in walk([outlines.get("/First")], ("/First", "/Next")):
            _clean_action(item)


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

        # Encryption we can't open: refuse before stage 1. Ghostscript
        # doesn't fail on a user password we don't have; it renders the file
        # without it and exits 0, and the markup pass would ship that as a
        # PDF/A. open_pikepdf also refuses a certificate or an unsupported
        # method here, rather than trusting ghostscript to fail on those. Any
        # other open error is left to the stages below: ghostscript repairs
        # some damaged files that pikepdf can't open.
        try:
            open_pikepdf(input_path).close()
        except pikepdf.PdfError:
            pass

        # Only a file that declares itself a PDF may reach stage 1: Ghostscript
        # reads a file by its content, not by the upload's name, so it must
        # only be handed real PDFs, and the pikepdf markup pass cannot open a
        # non-PDF either. A damaged PDF that still carries the header passes
        # this gate so ghostscript keeps its chance to repair it. Refuse with a
        # caller-safe message instead of letting the markup pass fail into a
        # generic 500.
        if not _has_pdf_header(input_path):
            raise InvalidInputError(
                "This file is not a PDF. Convert it to PDF first, then upload "
                "the PDF to create a PDF/A."
            )

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
