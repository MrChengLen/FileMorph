# SPDX-License-Identifier: AGPL-3.0-or-later
"""PDF page extraction + split — a "Morph > Convert" structural operation.

Two capabilities, both pure pypdf (no native binary, so they run on every
host including Windows local-dev):

* **Extract** — write a new PDF containing a selected page range, e.g.
  ``pages="1-3,5"``. Registered as the ``(pdf, pdf)`` converter so it is a
  first-class registry citizen and unit-testable in isolation; the route
  layer threads the ``pages`` kwarg through ``convert()``.
* **Split** — write one single-page PDF per page. Returns a list of
  ``(name, bytes)`` the route bundles into a ZIP via
  ``app/core/batch.py``.

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

pypdf parsing of the *input* PDF still happens inside ``convert()`` /
``split_pdf()``; the route invokes both through ``asyncio.to_thread`` so
the (synchronous, C-accelerated) parse never blocks the event loop —
identical to every other converter.
"""

from __future__ import annotations

from pathlib import Path

from app.converters.base import BaseConverter
from app.converters.registry import register

# Defensive ceiling on how many distinct pages a single selection may
# resolve to. A crafted "1-1000000" against a 2-page PDF is already
# rejected by the page-count bound, but an explicit cap keeps the parser
# itself from materialising a multi-million-int list before that check
# (the range is expanded lazily up to this many entries).
_MAX_SELECTION_PAGES = 10_000


class PageSelectionError(ValueError):
    """Malformed or out-of-range page selection (caller-safe message)."""


def parse_page_ranges(spec: str, page_count: int) -> list[int]:
    """Parse a 1-based page spec into a sorted, de-duplicated 0-based index list.

    Accepts comma-separated singletons and ``a-b`` ranges, e.g.
    ``"1-3,5,8-9"``. Whitespace around tokens is ignored. The result is
    sorted ascending and de-duplicated so overlapping tokens
    (``"1-3,2-4"``) collapse cleanly and output page order is stable.

    Raises :class:`PageSelectionError` (never a bare ValueError / pypdf
    error) on: empty spec, non-numeric token, zero/negative page number,
    reversed range (``b < a``), any page beyond ``page_count``, or a
    selection that would expand past ``_MAX_SELECTION_PAGES``. The message
    is generic and safe to return to the client.
    """
    if page_count <= 0:
        raise PageSelectionError("The PDF has no pages to extract.")
    if spec is None or not spec.strip():
        raise PageSelectionError("No pages specified.")

    pages: set[int] = set()
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
            if len(pages) + (end - start + 1) > _MAX_SELECTION_PAGES:
                raise PageSelectionError("Too many pages selected.")
            pages.update(range(start - 1, end))  # 1-based inclusive → 0-based
        else:
            value = _parse_int(token, token)
            if value < 1:
                raise PageSelectionError("Page numbers start at 1.")
            if value > page_count:
                raise PageSelectionError(
                    f"Page {value} is out of range (the PDF has {page_count} page"
                    f"{'s' if page_count != 1 else ''})."
                )
            if len(pages) + 1 > _MAX_SELECTION_PAGES:
                raise PageSelectionError("Too many pages selected.")
            pages.add(value - 1)

    if not pages:
        raise PageSelectionError("No pages specified.")
    return sorted(pages)


def _parse_int(value: str, token: str) -> int:
    """Strict positive-int parse; wraps the ValueError as a safe message."""
    try:
        n = int(value)
    except ValueError:
        raise PageSelectionError(f"Invalid page number in {token!r}.") from None
    return n


def _open_reader(input_path: Path):
    """Open a PDF with pypdf, normalising any parse failure to a safe error.

    pypdf raises a small zoo of exception types (``PdfReadError``,
    ``EmptyFileError``, plain ``ValueError`` from the tokenizer) on a
    corrupt or non-PDF input. The magic-byte guard in the route already
    blocks executables; this catch turns a genuinely malformed PDF into a
    single caller-safe error instead of leaking pypdf internals.
    """
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(str(input_path))
        # Touch the page tree so a lazily-parsed corrupt xref surfaces here,
        # inside our guarded block, rather than later at iteration time.
        _ = len(reader.pages)
    except (PdfReadError, ValueError, OSError) as exc:
        raise PageSelectionError("Could not read the PDF. Verify the file is valid.") from exc
    return reader


def extract_pages(input_path: Path, output_path: Path, pages_spec: str) -> Path:
    """Write a new PDF containing only ``pages_spec`` (1-based) from the input."""
    from pypdf import PdfWriter

    reader = _open_reader(input_path)
    indices = parse_page_ranges(pages_spec, len(reader.pages))

    writer = PdfWriter()
    for idx in indices:
        writer.add_page(reader.pages[idx])
    with output_path.open("wb") as f:
        writer.write(f)
    return output_path


def split_pdf(input_path: Path) -> list[tuple[str, bytes]]:
    """Split a PDF into one single-page PDF per page.

    Returns ``[(filename, pdf_bytes), ...]`` with ``page_001.pdf`` style
    names (zero-padded to the page count's width so they sort lexically in
    the ZIP). The route bundles these into a ZIP via
    ``app/core/batch.py``; keeping the bytes in memory here is bounded by
    the same per-tier output cap the route enforces on the assembled ZIP.
    """
    import io

    from pypdf import PdfWriter

    reader = _open_reader(input_path)
    total = len(reader.pages)
    if total == 0:
        raise PageSelectionError("The PDF has no pages to split.")
    # Same defensive ceiling extract uses on a selection: a crafted PDF
    # claiming an enormous page count would otherwise have us build (and
    # hold in memory) that many single-page writers before the route's
    # output-cap check ever runs. Bail with a clean, caller-safe 400 first.
    if total > _MAX_SELECTION_PAGES:
        raise PageSelectionError("Too many pages to split.")

    width = len(str(total))
    outputs: list[tuple[str, bytes]] = []
    for i, page in enumerate(reader.pages, start=1):
        writer = PdfWriter()
        writer.add_page(page)
        buf = io.BytesIO()
        writer.write(buf)
        outputs.append((f"page_{i:0{width}d}.pdf", buf.getvalue()))
    return outputs


@register(("pdf", "pdf"))
class PdfPageExtractConverter(BaseConverter):
    """Extract a page range from a PDF (``pdf`` → ``pdf``).

    Reachable through the dedicated ``/api/v1/pdf/extract`` route, which
    passes the user's ``pages`` selection as the ``pages`` kwarg. Defaults
    to the whole document when no selection is given so a bare
    ``pdf`` → ``pdf`` is a (metadata-light) pass-through rather than an
    error.
    """

    def convert(self, input_path: Path, output_path: Path, **kwargs) -> Path:
        spec = kwargs.get("pages")
        if spec is None or not str(spec).strip():
            # No selection → keep every page. Re-write through pypdf so the
            # output is a freshly-serialised PDF (consistent with the
            # extract path) rather than a byte-copy of the input.
            reader = _open_reader(input_path)
            spec = f"1-{len(reader.pages)}"
        return extract_pages(input_path, output_path, str(spec))
