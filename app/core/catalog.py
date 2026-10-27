# SPDX-License-Identifier: AGPL-3.0-or-later
"""The catalogue of FileMorph's public pages: one entry per page a visitor lands
on, in display order (the account pages and legal entry points such as /cancel
stay outside on purpose; tests/test_catalog.py names them).

The sitemap, ``/llms.txt``, the page routes' whitelist, the homepage's quick
actions, the ``/tools`` catalogue, the footer and the "Related tools" links of
the tool pages are filtered views of ``PAGES``. A page added here shows up
on all of them; a public route missing here, or an entry whose page does not
render, fails ``tests/test_catalog.py``. Before this list each of those
surfaces kept its own hand-written copy, so a new page went missing from some
of them and one tool carried four different names.

A tool's ``label`` is its one name: the quick-action chip, the ``/tools`` card
and the footer link all show it. The page prose (title, meta description, H1,
FAQ) stays in the content modules (``convert_pairs``, ``pdf_tools_content``,
``compress_content``, …); a convert page's ``/tools`` card reuses its ``hero``
line from there.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings
from app.core.convert_pairs import format_label


# eq=False: the label dicts make a Page unhashable, and nothing compares pages.
@dataclass(frozen=True, eq=False)
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
    # Curated "Related tools" links (catalogue paths): siblings first, then
    # a next step. Convert pages take theirs from convert_pairs.related_pairs().
    related: tuple[str, ...] = ()
    # Also served under /de and /en.
    localized: bool = True
    # Tools only. The /tools section, one of FAMILIES. A family with fewer
    # than two tools goes under "More tools".
    family: str | None = None
    # The tool's one name, {"de": …, "en": …}: chip, /tools card, footer link.
    label: dict[str, str] | None = None
    # The /tools card text, {"de": …, "en": …}; a convert page uses its hero.
    blurb: dict[str, str] | None = None
    # Position among the homepage's quick actions (at most eight).
    chip: int | None = None
    # The quick action's icon, one of ICONS.
    icon: str | None = None
    # Listed in the footer's "Tools" group.
    footer: bool = False


# The /tools sections in display order (named in templates/tools.html).
FAMILIES: tuple[str, ...] = ("pdf", "image", "video", "privacy")
# The icons templates/_components/icon.html draws.
ICONS: frozenset[str] = frozenset({"compress", "image", "document", "split", "pages"})


# How a format reads in a tool's name where its extension is not what people
# search for: "Word in PDF", not "DOCX in PDF".
_FORMAT_NAMES: dict[str, dict[str, str]] = {
    "docx": {"de": "Word", "en": "Word"},
    "html": {"de": "HTML-Datei", "en": "HTML file"},
    "eml": {"de": "E-Mail (.eml)", "en": "Email (.eml)"},
}


def _name(fmt: str, locale: str) -> str:
    return _FORMAT_NAMES.get(fmt, {}).get(locale) or format_label(fmt)


def _pair(
    src: str, tgt: str, family: str, chip: int | None = None, icon: str | None = None
) -> Page:
    label = {
        "de": f"{_name(src, 'de')} in {_name(tgt, 'de')}",
        "en": f"{_name(src, 'en')} to {_name(tgt, 'en')}",
    }
    return Page(
        f"/convert/{src}-to-{tgt}",
        "convert",
        priority="0.6",
        family=family,
        label=label,
        chip=chip,
        icon=icon,
    )


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
    # PDF: what produces or changes a PDF. Within a family: shrink, convert, edit.
    Page(
        "/pdf/compress",
        "tool",
        priority="0.7",
        llms=(
            "Compress a PDF",
            "shrink a PDF to at most a target size by recompressing its embedded "
            "images, scaling them down if needed",
        ),
        related=("/pdf/split", "/pdf/extract", "/convert/docx-to-pdf", "/convert/jpg-to-pdf"),
        family="pdf",
        label={"de": "PDF verkleinern", "en": "Compress PDF"},
        blurb={
            "de": (
                "Ein PDF durch Rekomprimieren eingebetteter Bilder auf eine Zielgröße "
                "verkleinern — mit ehrlichem Hinweis, wenn nichts zu verkleinern ist."
            ),
            "en": (
                "Shrink a PDF to at most a target size by recompressing its embedded "
                "images — and get an honest note if there's nothing to shrink."
            ),
        },
        chip=1,
        icon="compress",
        footer=True,
    ),
    _pair("jpg", "pdf", "pdf", chip=2, icon="image"),
    _pair("png", "pdf", "pdf"),
    _pair("heic", "pdf", "pdf"),
    _pair("docx", "pdf", "pdf", chip=3, icon="document"),
    _pair("html", "pdf", "pdf"),
    _pair("eml", "pdf", "pdf"),
    Page(
        "/pdf/split",
        "tool",
        priority="0.6",
        llms=(
            "Split a PDF",
            "split a multi-page PDF into one file per page, bundled as a ZIP",
        ),
        related=("/pdf/extract", "/pdf/compress", "/convert/docx-to-pdf"),
        family="pdf",
        label={"de": "PDF aufteilen", "en": "Split PDF"},
        blurb={
            "de": "Ein mehrseitiges PDF in Einzelseiten aufteilen, gebündelt als ZIP.",
            "en": "Turn a multi-page PDF into one file per page, bundled as a ZIP.",
        },
        chip=4,
        icon="split",
        footer=True,
    ),
    Page(
        "/pdf/extract",
        "tool",
        priority="0.6",
        llms=(
            "Extract PDF pages",
            "keep only a chosen page range from a PDF, e.g. pages 1-3,5",
        ),
        related=("/pdf/split", "/pdf/compress", "/convert/docx-to-pdf", "/convert/eml-to-pdf"),
        family="pdf",
        label={"de": "PDF-Seiten extrahieren", "en": "Extract PDF pages"},
        blurb={
            "de": (
                "Nur die gewünschten Seiten behalten, z. B. 1-3,5, und ein einzelnes "
                "kleineres PDF herunterladen."
            ),
            "en": (
                "Keep only the pages you choose, e.g. 1-3,5, and download a single smaller PDF."
            ),
        },
        chip=5,
        icon="pages",
        footer=True,
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
        related=(
            "/convert/jpg-to-webp",
            "/convert/png-to-webp",
            "/pdf/compress",
            "/convert/video-to-gif",
        ),
        family="image",
        label={"de": "Bild verkleinern (KB/MB)", "en": "Compress image (KB/MB)"},
        blurb={
            "de": (
                "Für ein JPEG, WebP oder AVIF eine Zielgröße in MB einstellen, oder ein "
                "Video per Qualität verkleinern — das eigene Tool, mit ehrlichem Hinweis, "
                "welche Formate eine Zielgröße erreichen."
            ),
            "en": (
                "Dial in a target size in MB for a JPEG, WebP or AVIF image, or shrink a "
                "video by quality — the dedicated tool, with honest limits on which "
                "formats hit a target."
            ),
        },
        chip=7,
        icon="compress",
        footer=True,
    ),
    _pair("heic", "jpg", "image", chip=6, icon="image"),
    _pair("png", "jpg", "image"),
    _pair("jpg", "png", "image"),
    _pair("webp", "jpg", "image"),
    _pair("jpg", "webp", "image"),
    _pair("png", "webp", "image"),
    # Video. One page for every video format: the task is the same whatever
    # the container, so seven pair pages would only compete with each other.
    Page(
        "/convert/video-to-gif",
        "tool",
        priority="0.6",
        llms=(
            "Video to GIF",
            "turn a short video clip (up to 30 seconds) into an animated GIF",
        ),
        # /compress shrinks videos too, and links back here.
        related=("/compress",),
        family="video",
        label={"de": "Video in GIF", "en": "Video to GIF"},
        blurb={
            "de": (
                "Einen kurzen Clip bis 30 Sekunden – MP4, MOV, WebM und mehr – in ein "
                "animiertes GIF ohne Ton umwandeln."
            ),
            "en": (
                "Turn a short clip of up to 30 seconds — MP4, MOV, WebM and more — into "
                "an animated GIF without sound."
            ),
        },
        footer=True,
    ),
    # Privacy: the redaction add-on of the Cloud Edition, never a quick action
    # (a paid tool is not an idle-state teaser; product-ux.md #3).
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
        family="privacy",
        # No "(Pro)" in the name: which plans may download is configurable
        # (AI_ELIGIBLE_TIERS); the card text says the download is paid.
        label={"de": "PII schwärzen", "en": "Redact PII"},
        blurb={
            "de": (
                "IBANs, E-Mail-Adressen, Telefonnummern, IP-Adressen und Kartennummern in "
                "TXT, DOCX und XLSX finden und entfernen. Kostenlose Fundstellen-Vorschau, "
                "Download kostenpflichtig."
            ),
            "en": (
                "Find and remove IBANs, emails, phone numbers, IP addresses and "
                "credit-card numbers from TXT, DOCX and XLSX. Free findings preview, "
                "paid file download."
            ),
        },
        footer=True,
    ),
    # Developers, the commercial offer, trust and legal pages. /pricing and
    # /enterprise share the commercial-offer switch and sitemap priority 0.8.
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
# A related link must be a catalogued tool page: anything else would 404 (G5)
# or have no name to show.
assert all(path in _BY_PATH and _BY_PATH[path].label for page in PAGES for path in page.related), (
    "a related link must point at a catalogued tool page"
)
# Every tool is listed on /tools: it needs a known family, a name in both
# languages and, unless a convert page's hero stands in, a card text in both.
assert all(
    page.family in FAMILIES
    and page.label
    and set(page.label) == {"de", "en"}
    and (page.kind == "convert" or (page.blurb and set(page.blurb) == {"de", "en"}))
    for page in PAGES
    if page.kind in ("tool", "convert")
), "a tool in the catalogue lacks its family, its German and English name or its card text"
# The homepage's quick actions: at most eight, one per position, free tools
# only (a paid or gated tool is no idle-state teaser, product-ux.md #3), each
# with an icon the macro draws.
_CHIPS = [page for page in PAGES if page.chip is not None]
assert len(_CHIPS) <= 8 and len({page.chip for page in _CHIPS}) == len(_CHIPS), (
    "at most eight quick actions, one per position"
)
assert all(page.gate is None and page.icon in ICONS for page in _CHIPS), (
    "a quick action must be ungated and have a known icon"
)


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


def quick_actions() -> list[Page]:
    """The homepage's quick actions, in chip order."""
    return sorted((page for page in pages() if page.chip is not None), key=lambda page: page.chip)


def footer_tools() -> list[Page]:
    """The tools linked in the footer's "Tools" group."""
    return [page for page in pages() if page.footer]
