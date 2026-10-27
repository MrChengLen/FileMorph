# SPDX-License-Identifier: AGPL-3.0-or-later
"""The catalogue of FileMorph's public pages: one entry per page a visitor lands
on, in display order (the account pages and legal entry points such as /cancel
stay outside on purpose; tests/test_catalog.py names them).

The sitemap, ``/llms.txt``, the page routes' whitelist and the "Related tools"
links of the PDF tool pages are filtered views of ``PAGES``. A page added here
shows up on all of them; a public route missing here, or an entry whose page
does not render, fails ``tests/test_catalog.py``. Before this list each of
those surfaces kept its own hand-written copy, and a new page went missing
from some of them.

The page prose (title, meta description, H1, FAQ) stays in the content modules
(``convert_pairs``, ``pdf_tools_content``, ``compress_content``, …). An entry
here only says that a page exists, where it is listed and which switch gates it.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings


@dataclass(frozen=True)
class Page:
    # Canonical path without a locale prefix: the x-default URL.
    path: str
    # home | hub | reference | tool | convert | api | info | legal
    kind: str
    # Sitemap priority; None keeps the page out of the sitemap.
    priority: str | None = None
    # A ``settings`` attribute that must be truthy, else the page is listed
    # nowhere. Its route has to 404 then too (IA rule G5: one flag,
    # identical on every surface); tests/test_catalog.py checks that it does.
    gate: str | None = None
    # The page's ``/llms.txt`` bullet as (link text, description). Convert
    # pages get theirs from the format labels.
    llms: tuple[str, str] | None = None
    # Curated related convert pages (catalogue paths).
    related: tuple[str, ...] = ()
    # Also served under /de and /en.
    localized: bool = True


def _pair(src: str, tgt: str) -> Page:
    return Page(f"/convert/{src}-to-{tgt}", "convert", priority="0.6")


PAGES: tuple[Page, ...] = (
    Page(
        "/",
        "home",
        priority="1.0",
        llms=(
            "Convert & compress files",
            "the main tool — convert and compress files for free, no account",
        ),
    ),
    Page(
        "/tools",
        "hub",
        priority="0.8",
        llms=(
            "All tools",
            "every FileMorph operation in one place — convert, compress, split or extract PDF pages",
        ),
    ),
    Page(
        "/formats",
        "reference",
        priority="0.5",
        llms=(
            "Supported formats",
            "the full list of supported conversions, grouped by category",
        ),
    ),
    # PDF: what produces or changes a PDF.
    Page(
        "/pdf/compress",
        "tool",
        priority="0.7",
        llms=(
            "Compress a PDF",
            "shrink a PDF to at most a target size by recompressing its embedded "
            "images, scaling them down if needed",
        ),
        related=("/convert/docx-to-pdf", "/convert/jpg-to-pdf"),
    ),
    _pair("jpg", "pdf"),
    _pair("png", "pdf"),
    _pair("heic", "pdf"),
    _pair("docx", "pdf"),
    _pair("html", "pdf"),
    _pair("eml", "pdf"),
    Page(
        "/pdf/split",
        "tool",
        priority="0.6",
        llms=(
            "Split a PDF",
            "split a multi-page PDF into one file per page, bundled as a ZIP",
        ),
        related=("/convert/docx-to-pdf",),
    ),
    Page(
        "/pdf/extract",
        "tool",
        priority="0.6",
        llms=(
            "Extract PDF pages",
            "keep only a chosen page range from a PDF, e.g. pages 1-3,5",
        ),
        related=("/convert/docx-to-pdf", "/convert/eml-to-pdf"),
    ),
    # Images.
    Page(
        "/compress",
        "tool",
        priority="0.7",
        llms=(
            "Compress an image or video",
            "shrink a JPEG, WebP or AVIF to at most a target size in MB, or a video by quality",
        ),
    ),
    _pair("heic", "jpg"),
    _pair("png", "jpg"),
    _pair("jpg", "png"),
    _pair("webp", "jpg"),
    _pair("jpg", "webp"),
    _pair("png", "webp"),
    # Privacy: the redaction add-on of the Cloud Edition.
    Page(
        "/redact",
        "tool",
        priority="0.7",
        gate="ai_operations_enabled",
        llms=(
            "Redact PII from documents",
            "detect and remove IBANs, emails, phone numbers, IPv4 addresses and card "
            "numbers from TXT, DOCX and XLSX — free findings preview, no third-party AI",
        ),
    ),
    # Developers, the commercial offer, trust and legal pages. /pricing and
    # /enterprise share the commercial-offer switch; procurement traffic is
    # the higher-revenue funnel, hence 0.8.
    Page(
        "/docs",
        "api",
        localized=False,
        llms=(
            "API documentation",
            "REST API reference for programmatic conversion and compression",
        ),
    ),
    Page("/pricing", "info", priority="0.8", gate="pricing_page_enabled"),
    Page("/enterprise", "info", priority="0.8", gate="pricing_page_enabled"),
    Page("/security", "info"),
    Page("/privacy", "legal", priority="0.3"),
    Page("/terms", "legal", priority="0.3"),
    Page("/impressum", "legal", priority="0.3"),
    Page("/contact", "legal", priority="0.3"),
)

_BY_PATH: dict[str, Page] = {page.path: page for page in PAGES}
assert len(_BY_PATH) == len(PAGES), "a path appears twice in the page catalogue"
# A related link must be a catalogued convert page: anything else would 404
# (G5) or get a broken "X → Y" label.
assert all(
    path in _BY_PATH and _BY_PATH[path].kind == "convert" for page in PAGES for path in page.related
), "a related link must point at a catalogued convert page"


def enabled(page: Page) -> bool:
    """Whether the page exists on this deployment, read at call time."""
    return page.gate is None or bool(getattr(settings, page.gate))


def pages(kind: str | None = None) -> list[Page]:
    """The pages this deployment serves, in display order, optionally of one kind."""
    return [page for page in PAGES if enabled(page) and (kind is None or page.kind == kind)]


def get(path: str) -> Page | None:
    """The page at ``path``, or None when it is unknown or switched off."""
    page = _BY_PATH.get(path)
    return page if page is not None and enabled(page) else None


def pair_of(path: str) -> tuple[str, str]:
    """Source and target format of a convert page path: ``("jpg", "pdf")``."""
    src, _, tgt = path.removeprefix("/convert/").partition("-to-")
    return src, tgt
