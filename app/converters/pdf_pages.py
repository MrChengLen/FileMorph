# SPDX-License-Identifier: AGPL-3.0-or-later
"""PDF page extraction + split — a "Morph > Convert" structural operation.

Two capabilities, both pure pypdf (no native binary, so they run on every
host including Windows local-dev):

* **Extract** — write a new PDF containing a selected page range, e.g.
  ``pages="1-3,5"``. Registered as the ``(pdf, pdf)`` converter so it is a
  first-class registry citizen and unit-testable in isolation; the route
  layer threads the ``pages`` kwarg through ``convert()``.
* **Split** — write one single-page PDF per page into a folder; the route
  bundles them into a ZIP via ``app/core/batch.py``.

Page numbers are **1-based** in the user-facing API (matching how a person
reads a PDF) and converted to 0-based indices internally.

Untrusted-input contract
-------------------------
``parse_page_ranges`` never raises on malformed / empty / out-of-range /
reversed / duplicate input — it raises a single, typed
``PageSelectionError`` carrying a *generic, caller-safe* message (no
pypdf internals, no stack detail). The route maps that to an HTTP 400.
A reversed range (``5-3``) and out-of-range pages are treated as client
errors rather than silently coerced, so a user mistyping a range gets a
clear 400 instead of a surprising empty/partial PDF.

The routes parse the *input* PDF in a child process with memory and time
limits (``app/converters/_isolated.py``), waited for off the event loop:
``/pdf/extract`` and ``/pdf/split`` through :func:`extract_step` and
:func:`split_step`, PDF → PDF on ``/convert`` through ``convert()``. A PDF
pypdf cannot read, or one without pages, raises :class:`UnreadablePdfError`,
a ``PageSelectionError`` that blames the file rather than the selection. One
that needs a password raises :class:`~app.converters.base.EncryptedPdfError`.
A selection, or a PDF to split, over the page cap raises
:class:`TooManyPagesError`. The child passes on the message of a
``PageSelectionError`` but not its class, so the two steps hand the page
routes their error code with it, as data (:func:`_refusal`).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from app.converters.base import (
    BaseConverter,
    EncryptedPdfError,
    InvalidInputError,
    OutputTooLargeError,
    open_pypdf,
)
from app.converters.registry import register

logger = logging.getLogger(__name__)

# Defensive ceiling on how many distinct pages a single selection may
# resolve to. A crafted "1-1000000" against a 2-page PDF is already
# rejected by the page-count bound; this cap is checked on the merged
# ranges, before any page index is materialised.
_MAX_SELECTION_PAGES = 10_000

# Every page up to the cap, listed one by one, is about 49,000 characters;
# a longer selection is refused up front.
_MAX_SELECTION_CHARS = 64 * 1024


class PageSelectionError(InvalidInputError):
    """Malformed or out-of-range page selection (caller-safe message).

    An ``InvalidInputError``, so ``/convert`` and ``/convert/batch``
    (``pdf`` → ``pdf``) answer it as a 400, like the page routes do.
    """


class UnreadablePdfError(PageSelectionError):
    """The input PDF is the problem, not the page selection.

    pypdf could not read it (raised with ``_UNREADABLE_PDF``), or it has no
    pages. ``/pdf/extract`` answers it with ``invalid_pdf``.
    """


class TooManyPagesError(PageSelectionError):
    """More than ``_MAX_SELECTION_PAGES`` pages: a selection, or a PDF to split.

    Neither the file nor the selection's syntax is wrong, so the page routes
    answer it with ``pdf_too_many_pages`` instead of ``invalid_pdf`` /
    ``invalid_page_selection``; the message names the cap and how to stay
    under it.
    """


_UNREADABLE_PDF = "Could not read the PDF. Verify the file is valid."

# PDF → PDF without a selection keeps every page, so it is held to the
# selection cap — but the caller selected nothing, so the message names the
# document's size and where to process it in parts.
_TOO_MANY_PAGES_TO_CONVERT = (
    f"This PDF has more than {_MAX_SELECTION_PAGES:,} pages, the most a PDF-to-PDF "
    f"conversion handles in one request. Process it in parts of up to "
    f"{_MAX_SELECTION_PAGES:,} pages with /api/v1/pdf/extract."
)
_TOO_MANY_PAGES_TO_SPLIT = (
    f"This PDF has more than {_MAX_SELECTION_PAGES:,} pages, the most a split "
    f"handles. Extract up to {_MAX_SELECTION_PAGES:,} pages at a time with "
    f"/api/v1/pdf/extract, then split each part."
)
_TOO_MANY_PAGES_SELECTED = (
    f"You can extract at most {_MAX_SELECTION_PAGES:,} pages at once. Select "
    f"fewer pages, or extract them in several parts."
)
_SELECTION_TOO_LONG = (
    "The page selection is too long. Use ranges such as 1-100 instead of listing pages one by one."
)


def parse_page_ranges(spec: str, page_count: int) -> list[int]:
    """Parse a 1-based page spec into a sorted, de-duplicated 0-based index list.

    Accepts comma-separated singletons and ``a-b`` ranges, e.g.
    ``"1-3,5,8-9"``. Whitespace around tokens is ignored. The result is
    sorted ascending and de-duplicated so overlapping tokens
    (``"1-3,2-4"``) collapse cleanly and output page order is stable; a
    page selected twice counts once against the cap.

    Raises :class:`PageSelectionError` (never a bare ValueError / pypdf
    error) on: empty spec, a spec over ``_MAX_SELECTION_CHARS``, non-numeric
    token, zero/negative page number, reversed range (``b < a``), any page
    beyond ``page_count``, or more than ``_MAX_SELECTION_PAGES`` distinct
    pages (the :class:`TooManyPagesError` subclass). The message is generic
    and safe to return to the client. A ``page_count`` of 0 raises the
    :class:`UnreadablePdfError` subclass: the file is at fault.
    """
    if page_count <= 0:
        raise UnreadablePdfError("The PDF has no pages to extract.")
    if spec is None or not spec.strip():
        raise PageSelectionError("No pages specified.")
    if len(spec) > _MAX_SELECTION_CHARS:
        raise PageSelectionError(_SELECTION_TOO_LONG)

    ranges: list[tuple[int, int]] = []
    for raw_token in spec.split(","):
        token = raw_token.strip()
        if not token:
            # Tolerate stray commas ("1,,3" / trailing ",") rather than
            # 400 on a benign typo — only meaningful tokens matter.
            continue
        if "-" in token:
            start_s, sep, end_s = token.partition("-")
            start_s, end_s = start_s.strip(), end_s.strip()
            if not start_s or not end_s:
                raise PageSelectionError(f"Invalid page range: {token!r}.")
            start = _parse_int(start_s, token)
            end = _parse_int(end_s, token)
            if start > end:
                raise PageSelectionError(f"Invalid page range {token!r}: start is after end.")
            if start < 1:
                raise PageSelectionError("Page numbers start at 1.")
            if end > page_count:
                raise PageSelectionError(
                    f"Page {end} is out of range (the PDF has {page_count} page"
                    f"{'s' if page_count != 1 else ''})."
                )
            ranges.append((start, end))
        else:
            value = _parse_int(token, token)
            if value < 1:
                raise PageSelectionError("Page numbers start at 1.")
            if value > page_count:
                raise PageSelectionError(
                    f"Page {value} is out of range (the PDF has {page_count} page"
                    f"{'s' if page_count != 1 else ''})."
                )
            ranges.append((value, value))

    if not ranges:
        raise PageSelectionError("No pages specified.")
    # Merge overlapping and adjacent ranges, so a page selected twice counts
    # once.
    ranges.sort()
    merged = [ranges[0]]
    for start, end in ranges[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end + 1:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    if sum(end - start + 1 for start, end in merged) > _MAX_SELECTION_PAGES:
        raise TooManyPagesError(_TOO_MANY_PAGES_SELECTED)
    # 1-based inclusive ranges → 0-based indices.
    return [index for start, end in merged for index in range(start - 1, end)]


def _parse_int(value: str, token: str) -> int:
    """Strict positive-int parse; wraps the ValueError as a safe message."""
    try:
        n = int(value)
    except ValueError:
        raise PageSelectionError(f"Invalid page number in {token!r}.") from None
    return n


@contextmanager
def _reading_pdf() -> Iterator[None]:
    """Normalise a pypdf failure on the input PDF to a safe error.

    pypdf raises a small zoo of exception types on a corrupt or non-PDF
    input: those derived from ``PyPdfError`` (``PdfReadError``,
    ``EmptyFileError``, ``LimitReachedError`` when a crafted file trips one
    of its resource limits) and plain ``ValueError`` (the tokenizer, a
    damaged page object). ``PdfReadError`` alone misses
    ``LimitReachedError``. pypdf parses lazily, so they surface while pages
    are copied or written as well as on open: every step that reads the
    input runs under this guard. The magic-byte guard in the route already
    blocks executables; this catch turns a genuinely malformed PDF into a
    single caller-safe error instead of leaking pypdf internals.

    ``OSError`` stays a server error: pypdf reads the whole file into
    memory first, so one can only come from our own disk. Only the
    exception's class is logged — pypdf's messages can quote the file.

    A PDF with a user password is readable, just not by us: pypdf tries
    the empty password on open and raises ``FileNotDecryptedError`` on the
    first object it then reads. That becomes :class:`EncryptedPdfError`,
    whose message tells the user to remove the password.

    An RC4 ``/Encrypt /Length`` that leaves no key bytes is a ``ValueError``
    from ``cryptography``. Where OpenSSL has no RC4, pypdf switches to its own
    RC4 once OpenSSL has refused RC4 in this process, and that one raises
    ``ZeroDivisionError`` instead: the same file, so the same answer.
    """
    from pypdf.errors import FileNotDecryptedError, PyPdfError

    try:
        yield
    except (PyPdfError, ValueError, ZeroDivisionError) as exc:
        logger.info("unreadable PDF: %s", type(exc).__name__)
        if isinstance(exc, FileNotDecryptedError):
            raise EncryptedPdfError() from exc
        raise UnreadablePdfError(_UNREADABLE_PDF) from exc


def _open_reader(input_path: Path):
    """Open a PDF with pypdf under :func:`_reading_pdf`.

    A PDF encrypted other than with a password (e.g. with a certificate)
    raises :class:`~app.converters.base.UnsupportedPdfEncryptionError`.
    """
    with _reading_pdf():
        reader = open_pypdf(input_path)
        # Touch the page tree so a lazily-parsed corrupt xref surfaces here,
        # inside our guarded block, rather than later at iteration time.
        _ = len(reader.pages)
    return reader


def extract_pages(input_path: Path, output_path: Path, pages_spec: str) -> Path:
    """Write a new PDF containing only ``pages_spec`` (1-based) from the input."""
    from pypdf import PdfWriter

    reader = _open_reader(input_path)
    indices = parse_page_ranges(pages_spec, len(reader.pages))

    writer = PdfWriter()
    with _reading_pdf():
        for idx in indices:
            writer.add_page(reader.pages[idx])
        with output_path.open("wb") as f:
            writer.write(f)
    return output_path


def page_file_names(count: int) -> list[str]:
    """The file names of a split's ``count`` pages: ``page_001.pdf`` …,
    zero-padded to the count's width so they sort lexically in the ZIP."""
    width = len(str(count))
    return [f"page_{i:0{width}d}.pdf" for i in range(1, count + 1)]


def split_pdf(input_path: Path, pages_path: Path, max_output_bytes: int) -> int:
    """Split a PDF into one single-page PDF per page and return the page count.

    The pages go into the folder ``pages_path``, under the names
    :func:`page_file_names` gives them. Each single-page PDF carries its own
    copy of the resources it uses. Once they add up to more than
    ``max_output_bytes`` (the caller's output cap),
    :class:`~app.converters.base.OutputTooLargeError` stops the split.
    """
    from pypdf import PdfWriter

    reader = _open_reader(input_path)
    total = len(reader.pages)
    if total == 0:
        raise UnreadablePdfError("The PDF has no pages to split.")
    # Same defensive ceiling extract uses on a selection: a crafted PDF
    # claiming an enormous page count would otherwise have us write that
    # many single-page PDFs. Bail with a clean, caller-safe 400 first.
    if total > _MAX_SELECTION_PAGES:
        raise TooManyPagesError(_TOO_MANY_PAGES_TO_SPLIT)

    total_bytes = 0
    with _reading_pdf():
        for name, page in zip(page_file_names(total), reader.pages, strict=True):
            writer = PdfWriter()
            writer.add_page(page)
            with (pages_path / name).open("wb") as f:
                writer.write(f)
                total_bytes += f.tell()
            if total_bytes > max_output_bytes:
                raise OutputTooLargeError
    return total


def _refusal(exc: PageSelectionError) -> dict:
    """What :func:`extract_step` and :func:`split_step` return for a PDF or a
    selection the user can fix: the code the page routes answer it with,
    and its message."""
    if isinstance(exc, UnreadablePdfError):
        code = "invalid_pdf"
    elif isinstance(exc, TooManyPagesError):
        code = "pdf_too_many_pages"
    else:
        code = "invalid_page_selection"
    return {"refused": {"code": code, "message": str(exc)}}


def extract_step(input_path: Path, output_path: Path, selection_path: Path) -> dict:
    """:func:`extract_pages` for ``/pdf/extract``, in the child process (step
    ``pdf-extract``): ``{}``, or :func:`_refusal` data. The page selection
    comes as a JSON string in the file ``selection_path``: it can be longer
    than a command line may be."""
    pages_spec = json.loads(selection_path.read_text(encoding="ascii"))
    try:
        extract_pages(input_path, output_path, pages_spec)
    except PageSelectionError as exc:
        return _refusal(exc)
    return {}


def split_step(input_path: Path, pages_path: Path, max_output_bytes: int) -> dict:
    """:func:`split_pdf` for ``/pdf/split``, in the child process (step
    ``pdf-split``): ``{"pages": <page count>}``, or :func:`_refusal` data."""
    try:
        return {"pages": split_pdf(input_path, pages_path, max_output_bytes)}
    except PageSelectionError as exc:
        return _refusal(exc)


@register(("pdf", "pdf"))
class PdfPageExtractConverter(BaseConverter):
    """Extract a page range from a PDF (``pdf`` → ``pdf``).

    ``/convert`` and ``/convert/batch`` run it in a child process with the
    limits of ``/pdf/extract`` (step ``pdf-to-pdf``), without a ``pages``
    selection. It defaults to the whole document when no selection is given
    so a bare ``pdf`` → ``pdf`` is a (metadata-light) pass-through rather
    than an error.
    """

    isolated = True
    isolated_step = "pdf-to-pdf"

    def convert(self, input_path: Path, output_path: Path, **kwargs) -> Path:
        spec = kwargs.get("pages")
        if spec is None or not str(spec).strip():
            # No selection → keep every page. Re-write through pypdf so the
            # output is a freshly-serialised PDF (consistent with the
            # extract path) rather than a byte-copy of the input.
            page_count = len(_open_reader(input_path).pages)
            if page_count > _MAX_SELECTION_PAGES:
                raise InvalidInputError(_TOO_MANY_PAGES_TO_CONVERT)
            spec = f"1-{page_count}"
        return extract_pages(input_path, output_path, str(spec))
