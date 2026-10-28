# SPDX-License-Identifier: AGPL-3.0-or-later
"""Insert pages into a PDF — a "Morph > Convert" structural operation.

``POST /api/v1/pdf/insert`` (``app/api/routes/pdf_pages.py``) puts a whole
second file into a PDF — at the start, after a given page or at the end. The
file can be a PDF, a Word document (``.docx``, rendered by LibreOffice:
``word_to_pdf``) or an image (one page: ``image_to_pdf``). Both run in the app
process, like ``/convert``. ``insert_pages`` then reads both PDFs, checks the
position and assembles the result in a child process with memory and time
limits (``app/converters/_isolated.py``), like ``/pdf/compress``: all PDF
work stays within those limits, none runs in the app process. A problem
the user can fix comes back as data (``{"refused": …}``) naming the form
field, so the route can say which input it is about.

The PDF is cloned, not rebuilt: its bookmarks, links, named destinations,
form fields, document info, XMP metadata and language survive, and its
bookmarks still lead to the right pages. Its page labels (printed numbers such
as i, ii, 1, 2) survive only when the pages go at the end — anywhere else
every later label would be wrong, so viewers fall back to plain page numbers.
The inserted file's bookmarks are not taken over, and a link on an inserted
page to a destination name the PDF uses as well is dropped: it would lead
into the PDF. Where the PDF's destination tree has /Kids at its root, the
inserted file's names go and with them all named links on its pages.

An image page gets the size of its neighbour — the page before it, or the
first page when it goes at the start — turned to the image's orientation,
with the image fitted and centred.
"""

from __future__ import annotations

import logging
import subprocess
import zipfile
from pathlib import Path

from app.converters.base import EncryptedPdfError, InvalidInputError, OutputTooLargeError
from app.converters.pdf_pages import (
    _MAX_SELECTION_PAGES,
    UnreadablePdfError,
    _open_reader,
    _reading_pdf,
)
from app.core.image_hardening import _UNREADABLE_IMAGE

logger = logging.getLogger(__name__)

_SAVE_AS_PDF = "In Word, save it as a PDF (File → Save as → PDF) and insert the PDF."
_NOT_CONVERTED = f"The Word file couldn't be converted. {_SAVE_AS_PDF}"
_TOO_MANY_PAGES = (
    f"This PDF has more than {_MAX_SELECTION_PAGES:,} pages, the most an insertion handles. "
    f"Extract up to {_MAX_SELECTION_PAGES:,} pages with /api/v1/pdf/extract first."
)
_TOO_MANY_TOGETHER = (
    f"Together the files have more than {_MAX_SELECTION_PAGES:,} pages, the most an "
    f"insertion handles. Extract fewer pages from either file with /api/v1/pdf/extract first."
)


class WordNotConvertedError(InvalidInputError):
    """A Word file that can't be turned into pages here: no LibreOffice on
    this server (or the operator chose the simple engine), a file that isn't
    a .docx, or LibreOffice failed on it. The message says to insert it as a
    PDF instead."""

    error_code = "word_not_converted"


def image_to_pdf(input_path: Path, output_path: Path) -> None:
    """Write the one-page PDF of an image the way image → PDF does — metadata
    stripped, turned upright, alpha flattened. Past the format check Pillow
    can still fail on a damaged image (a truncated JPEG raises ``OSError``):
    that is the file's fault, so it becomes an ``InvalidInputError``. An
    image over the size limit keeps its own error (``DECOMPRESSION_BOMB``)."""
    from app.converters.image import _ImageToPdfConverter
    from app.core.image_hardening import DECOMPRESSION_BOMB

    try:
        _ImageToPdfConverter().convert(input_path, output_path)
    except (InvalidInputError, *DECOMPRESSION_BOMB):
        raise
    except Exception as exc:
        logger.info("image for insertion unreadable: %s", type(exc).__name__)
        raise InvalidInputError(_UNREADABLE_IMAGE) from None


def _is_docx(path: Path) -> bool:
    """Whether ``path`` looks like a Word document: a ZIP with
    ``word/document.xml``. A ZIP that can't even be listed (a damaged one, a
    member name that isn't valid UTF-8) is none."""
    try:
        with zipfile.ZipFile(path) as archive:
            return "word/document.xml" in archive.namelist()
    except Exception:
        return False


def word_to_pdf(input_path: Path, output_path: Path) -> None:
    """Render a ``.docx`` with LibreOffice. Not with the simple engine
    (mammoth): it drops images and much of the layout, and in the middle of a
    finished document that would look like our mistake. LibreOffice picks its
    import filter from the content, not the name, so only a ZIP holding
    ``word/document.xml`` goes to it: a renamed RTF, DOC or HTML file doesn't
    reach those importers."""
    from app.converters.document import _convert_via_libreoffice, _soffice_available
    from app.core.config import settings

    if settings.office_engine.lower() == "mammoth" or not _soffice_available():
        raise WordNotConvertedError(f"This server doesn't convert Word files. {_SAVE_AS_PDF}")
    if not _is_docx(input_path):
        raise WordNotConvertedError(f"This isn't a Word document in .docx format. {_SAVE_AS_PDF}")
    try:
        _convert_via_libreoffice(
            input_path, output_path, timeout_s=settings.office_subprocess_timeout_seconds
        )
    except (subprocess.TimeoutExpired, RuntimeError) as exc:
        logger.info("word to pdf for insertion failed: %s", type(exc).__name__)
        raise WordNotConvertedError(_NOT_CONVERTED) from None


def _named_target(annot) -> str | None:
    """The destination name a GoTo link leads to; ``None`` for an explicit
    destination, a web link or any other annotation."""
    from pypdf.generic import NameObject, TextStringObject

    if annot.get("/Subtype") != "/Link":
        return None
    dest = annot.get("/Dest")
    if dest is None and "/A" in annot:
        action = annot["/A"].get_object()
        if action.get("/S") == "/GoTo":
            dest = action.get("/D")
    if dest is not None:
        dest = dest.get_object()
    return str(dest) if isinstance(dest, (NameObject, TextStringObject)) else None


def _display_size(page) -> tuple[float, float]:
    """Width and height a viewer shows ``page`` at: its crop box, turned by
    its /Rotate."""
    width, height = abs(float(page.cropbox.width)), abs(float(page.cropbox.height))
    return (height, width) if page.rotation % 180 else (width, height)


def _fit_image_page(page, width: float, height: float):
    """``page`` — the one page Pillow wrote for an image — resized to
    ``width`` × ``height`` turned to the image's orientation, the image fitted
    and centred."""
    from pypdf import Transformation
    from pypdf.generic import RectangleObject

    w, h = float(page.mediabox.width), float(page.mediabox.height)
    if (w - h) * (width - height) < 0:  # a square image keeps the neighbour's turn
        width, height = height, width
    scale = min(width / w, height / h)
    page.add_transformation(
        Transformation().scale(scale).translate((width - w * scale) / 2, (height - h * scale) / 2)
    )
    page.mediabox = RectangleObject((0, 0, width, height))
    return page


def _dests_root(writer):
    """The root node of the PDF's named-destination tree, or ``None``."""
    names = writer.root_object.get("/Names")
    dests = names.get_object().get("/Dests") if names is not None else None
    return dests.get_object() if dests is not None else None


class _CappedFile:
    """The output file, refusing more than ``limit`` bytes: the result stops
    at the caller's output cap instead of being written in full first."""

    def __init__(self, file, limit: int):
        self._file, self._left = file, limit

    def write(self, data: bytes) -> int:
        self._left -= len(data)
        if self._left < 0:
            raise OutputTooLargeError
        return self._file.write(data)

    def tell(self) -> int:
        return self._file.tell()

    def flush(self) -> None:
        self._file.flush()


def _refused(code: str, field: str, message: str, **extra) -> dict:
    """What ``insert_pages`` returns for an input the user can fix: the route
    answers it with a 400 that names ``field``."""
    return {"refused": {"code": code, "field": field, "message": message, **extra}}


def _unreadable(exc: Exception, field: str) -> dict:
    code = exc.error_code if isinstance(exc, EncryptedPdfError) else "invalid_pdf"
    return _refused(code, field, str(exc))


def insert_pages(
    base_path: Path,
    insert_path: Path,
    output_path: Path,
    after_page: int | None,
    kind: str,
    max_output_bytes: int,
) -> dict:
    """Write ``base_path`` with the pages of ``insert_path`` (a PDF; for
    ``kind`` ``docx`` LibreOffice's, for ``image`` Pillow's one page, fitted to
    its neighbour) after its page ``after_page`` — 0 for the start, ``None``
    for the end.

    Runs in the child process (step ``pdf-insert``). Returns
    ``{"inserted_pages": …, "page_count": …}``, or ``_refused`` data for an
    unreadable or locked file, one without pages or over the page cap, or a
    position past the end. Damage that only shows while copying raises
    ``UnreadablePdfError``; a result past ``max_output_bytes``
    ``OutputTooLargeError``.
    """
    from pypdf import PdfWriter
    from pypdf.generic import ArrayObject, NameObject

    try:
        base = _open_reader(base_path)
        with _reading_pdf():
            writer = PdfWriter(clone_from=base)
            # The pages the clone holds: pypdf takes an encrypted PDF's page
            # count from the file unchecked.
            base_count = len(writer.pages)
            base_names = set(base.named_destinations)
    except (EncryptedPdfError, UnreadablePdfError) as exc:
        return _unreadable(exc, "file")
    if base_count == 0:
        return _refused("invalid_pdf", "file", "The PDF has no pages.")
    if base_count > _MAX_SELECTION_PAGES:
        return _refused("pdf_too_many_pages", "file", _TOO_MANY_PAGES)
    index = base_count if after_page is None else after_page
    if index > base_count:
        plural = "s" if base_count != 1 else ""
        return _refused(
            "invalid_position",
            "after_page",
            f"The PDF has {base_count} page{plural}: insert after a page from 1 to "
            f"{base_count}, or after page 0 for the start.",
            page_count=base_count,
        )

    try:
        insert = _open_reader(insert_path)
        with _reading_pdf():
            claimed = len(insert.pages)
    except (EncryptedPdfError, UnreadablePdfError) as exc:
        if kind == "docx":  # LibreOffice wrote it: the Word file is the problem
            return _refused("word_not_converted", "insert_file", _NOT_CONVERTED)
        return _unreadable(exc, "insert_file")
    if claimed == 0:
        if kind == "docx":
            return _refused("word_not_converted", "insert_file", _NOT_CONVERTED)
        return _refused("invalid_pdf", "insert_file", "The file to insert has no pages.")
    if base_count + claimed > _MAX_SELECTION_PAGES:
        return _refused("pdf_too_many_pages", "insert_file", _TOO_MANY_TOGETHER)

    with _reading_pdf():
        # A destination tree with /Kids at its root (pdfTeX builds one past
        # 32 names, so most LaTeX theses have it) gets a /Names array next to
        # them from merge(), and viewers then find none of the PDF's names.
        # Such a root keeps only its /Kids; the inserted file's names go, and
        # with them every named link on its pages.
        dests = _dests_root(writer)
        kids_root = dests is not None and "/Kids" in dests and "/Names" not in dests
        if kind == "image":
            size = _display_size(writer.pages[max(index - 1, 0)])
            writer.insert_page(insert.pages[0], index)
            _fit_image_page(writer.pages[index], *size)  # in the writer: pypdf 7 wants it there
        else:
            writer.merge(index, insert, import_outline=False)
        added = len(writer.pages) - base_count
        if base_count + added > _MAX_SELECTION_PAGES:
            return _refused("pdf_too_many_pages", "insert_file", _TOO_MANY_TOGETHER)
        if kids_root:
            dests.pop(NameObject("/Names"), None)
        if index < base_count and "/PageLabels" in writer.root_object:
            del writer.root_object["/PageLabels"]
        for page in writer.pages[index : index + added]:
            annots = page.get("/Annots")
            if annots is None:
                continue
            annots = annots.get_object()
            # A link to a name the PDF uses as well would lead into the PDF.
            keep = [
                a
                for a in annots
                if (target := _named_target(a.get_object())) is None
                or (not kids_root and target not in base_names)
            ]
            if len(keep) < len(annots):
                page[NameObject("/Annots")] = ArrayObject(keep)
        with output_path.open("wb") as f:
            writer.write(_CappedFile(f, max_output_bytes))
    return {"inserted_pages": added, "page_count": base_count + added}
