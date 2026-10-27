# SPDX-License-Identifier: AGPL-3.0-or-later
"""SEO + well-known foundation endpoints: ``/robots.txt``, ``/sitemap.xml``,
and ``/.well-known/security.txt``.

Mounted at the root (no ``/api/v1`` prefix) so the conventional discovery
paths are honored. The route list is built per request from the page
catalogue (``app/core/catalog.py``), so a deployment with the commercial
pages switched off (``pricing_page_enabled``) does not advertise a
``/pricing`` route it doesn't serve. The same per-request principle
keeps ``/.well-known/security.txt`` deployment-agnostic — the contact email
and canonical URL are derived from ``app_base_url``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse, Response

from app.core import catalog
from app.core.config import settings
from app.core.convert_pairs import format_label
from app.core.i18n import SUPPORTED_LOCALES, localized_url
from app.core.jsonld import GITHUB_URL

router = APIRouter()

# AI / LLM crawlers we explicitly welcome. The wildcard ``User-agent: *``
# group below already allows them; naming each one is an *intent* signal
# (we want FileMorph surfaced in AI answers) and documents the decision in
# one place. Note robots.txt group-matching is most-specific-wins: a bot
# listed here obeys only its own block, so each must restate ``Allow: /``.
_AI_CRAWLERS: tuple[str, ...] = (
    "GPTBot",  # OpenAI / ChatGPT
    "OAI-SearchBot",  # OpenAI search
    "ChatGPT-User",  # ChatGPT browse-on-demand
    "ClaudeBot",  # Anthropic / Claude
    "PerplexityBot",  # Perplexity
    "Google-Extended",  # Google Gemini / Vertex training + grounding
    "Applebot-Extended",  # Apple Intelligence
)


def _sitemap_routes() -> list[tuple[str, str]]:
    """The catalogue's pages that carry a sitemap priority, in display order.

    Resolved per request: a gated page (``/pricing`` and ``/enterprise``
    behind ``pricing_page_enabled``, ``/redact`` behind
    ``ai_operations_enabled``) drops out where its switch is off, so a
    self-hosted Community deployment never lists its own 404s. Each base
    path becomes three URLs (x-default + one per supported locale) with
    hreflang alternates, so Google treats them as language variants of the
    same page rather than duplicates.
    """
    return [(page.path, page.priority) for page in catalog.pages() if page.priority]


def _alternate_links(base: str, abs_base: str) -> str:
    """Build the ``<xhtml:link rel="alternate" hreflang="...">`` entries
    for a base path. The same set of alternates is emitted on every URL
    variant of the route — Google's sitemap-hreflang protocol requires
    each ``<url>`` to declare its full siblings list, not just point at
    a canonical.

    Uses ``localized_url`` so the impressum/imprint locale-alias map in
    ``app/core/i18n.py`` is honoured automatically (the EN alternate of
    ``/impressum`` is ``/en/imprint``, not ``/en/impressum``).
    """
    parts = [
        f'    <xhtml:link rel="alternate" hreflang="x-default" '
        f'href="{abs_base}{localized_url(base, None)}"/>'
    ]
    for loc in SUPPORTED_LOCALES:
        parts.append(
            f'    <xhtml:link rel="alternate" hreflang="{loc}" '
            f'href="{abs_base}{localized_url(base, loc)}"/>'
        )
    return "\n".join(parts)


def _url_entry(loc_url: str, base: str, prio: str, abs_base: str) -> str:
    """Single ``<url>`` block with its full hreflang alternates."""
    alternates = _alternate_links(base, abs_base)
    return (
        "  <url>\n"
        f"    <loc>{loc_url}</loc>\n"
        f"{alternates}\n"
        f"    <priority>{prio}</priority>\n"
        "  </url>"
    )


@router.get("/robots.txt", response_class=PlainTextResponse, include_in_schema=False)
async def robots_txt() -> str:
    base = settings.app_base_url.rstrip("/")
    lines = ["User-agent: *", "Allow: /", ""]
    lines.append("# AI / LLM crawlers — explicitly welcomed (already covered by * above).")
    for bot in _AI_CRAWLERS:
        lines.append(f"User-agent: {bot}")
        lines.append("Allow: /")
        lines.append("")
    lines.append(f"Sitemap: {base}/sitemap.xml")
    lines.append("")
    return "\n".join(lines)


@router.get("/llms.txt", response_class=PlainTextResponse, include_in_schema=False)
async def llms_txt() -> str:
    """``/llms.txt`` — the emerging convention for giving AI agents a concise,
    curated entry point to a site (https://llmstxt.org). It does nothing for
    Google's AI Overviews (Google has said so explicitly), but ChatGPT,
    Claude, Perplexity et al. increasingly look for it. Cheap to serve, so we
    do. English-only by design: it targets crawlers, not end users.

    The links come from the page catalogue (``app/core/catalog.py``): every
    page with an ``llms`` line under "Core pages", every convert page under
    "Conversions". A gated page is listed only where it exists, and
    ``/pricing`` and ``/enterprise`` carry no line, which keeps the file
    deployment-agnostic.
    """
    base = settings.app_base_url.rstrip("/")
    # Where filemorph.io runs — only on the commercial surface, so a
    # self-hosted instance doesn't claim it. Same wording as
    # partials/hosting_note.html (pinned by tests/test_public_claims.py).
    hosting = (
        " Server at Hetzner in the EU, connections via Cloudflare (USA) — "
        f"[privacy policy § 4]({base}/privacy#hosting)."
        if settings.pricing_page_enabled
        else ""
    )
    core = []
    for page in catalog.pages():
        if page.llms:
            title, description = page.llms
            core.append(f"- [{title}]({base}{page.path}): {description}")
    conversions = []
    for page in catalog.pages(kind="convert"):
        src, tgt = catalog.pair_of(page.path)
        conversions.append(f"- [{format_label(src)} → {format_label(tgt)}]({base}{page.path})")
    lines = [
        "# FileMorph",
        "",
        "> Free, open-source, privacy-respecting file converter and compressor. "
        "Convert and compress images, documents, spreadsheets, audio and video "
        "through a web interface or a REST API — the files are processed on the "
        "server. Self-hostable (AGPLv3), no account required.",
        "",
        "## Core pages",
        "",
        *core,
        "",
        "## Conversions",
        "",
        *conversions,
        "",
        "## About",
        "",
        # The format list must match the converter registry — pinned by
        # tests/test_format_lists_match_registry.py.
        "FileMorph converts images (HEIC, HEIF, JPG, PNG, WebP, AVIF, BMP, TIFF, GIF, "
        "ICO), documents (DOCX, PDF, TXT, Markdown, HTML, EML), spreadsheets (XLSX, "
        "CSV, JSON), audio (MP3, WAV, FLAC, OGG, M4A, AAC, WMA, Opus) and video (MP4, "
        "MOV, AVI, MKV, WebM, FLV, WMV). "
        "It turns short video clips (up to 30 seconds) into animated GIFs. "
        "It can compress JPEG, WebP and AVIF images to at most a target size: it "
        "searches for the best quality that fits and scales an image down if even "
        "the lowest quality is too big. Files are processed server-side and "
        "deleted immediately after conversion, and no account is required." + hosting,
        "",
        f"Open source under AGPLv3: {GITHUB_URL}",
        "",
    ]
    return "\n".join(lines)


@router.get("/sitemap.xml", include_in_schema=False)
async def sitemap_xml() -> Response:
    base = settings.app_base_url.rstrip("/")
    entries: list[str] = []
    for path, prio in _sitemap_routes():
        # x-default URL (unprefixed canonical)
        entries.append(_url_entry(f"{base}{localized_url(path, None)}", path, prio, base))
        # Each supported locale (de, en) gets its own entry with the same
        # alternates list — Google treats them as siblings, not duplicates.
        for loc in SUPPORTED_LOCALES:
            entries.append(_url_entry(f"{base}{localized_url(path, loc)}", path, prio, base))
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"\n'
        '        xmlns:xhtml="http://www.w3.org/1999/xhtml">\n'
        + "\n".join(entries)
        + "\n</urlset>\n"
    )
    return Response(content=body, media_type="application/xml")


# ── /.well-known/security.txt (RFC 9116) ─────────────────────────────────────
#
# The Expires field re-renders on each request: the file is always at most
# ~365 days from the current date, so a forgotten cache or a long-uptime
# instance can't drift into expired-territory and get flagged by automated
# scanners. RFC 9116 §2.5.5 mandates ≤1 year. We pick exactly 365 days from
# *today* on every render — operator just rotates the contact email when
# the alias changes; nothing else needs touching.


@router.get(
    "/.well-known/security.txt",
    response_class=PlainTextResponse,
    include_in_schema=False,
)
async def security_txt() -> str:
    base = settings.app_base_url.rstrip("/")
    expires = (datetime.now(timezone.utc) + timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    contact = settings.security_contact_email
    lines = [
        f"Contact: mailto:{contact}",
        f"Expires: {expires}",
        "Preferred-Languages: en, de",
        f"Canonical: {base}/.well-known/security.txt",
        f"Policy: {base}/security",
        "",
    ]
    return "\n".join(lines)
