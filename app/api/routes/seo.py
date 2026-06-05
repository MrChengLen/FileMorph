# SPDX-License-Identifier: AGPL-3.0-or-later
"""SEO + well-known foundation endpoints: ``/robots.txt``, ``/sitemap.xml``,
and ``/.well-known/security.txt``.

Mounted at the root (no ``/api/v1`` prefix) so the conventional discovery
paths are honored. The route list is built per-request from ``settings`` so
that a self-hoster who has not configured Stripe does not advertise a
``/pricing`` route they don't actually serve. The same per-request principle
keeps ``/.well-known/security.txt`` deployment-agnostic — the contact email
and canonical URL are derived from ``app_base_url``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse, Response

from app.core.config import settings
from app.core.i18n import SUPPORTED_LOCALES, localized_url
from app.core.jsonld import GITHUB_URL

router = APIRouter()


# Routes that every deployment serves. Each base path becomes three URLs
# in the sitemap (x-default + one per supported locale) with hreflang
# alternates wired up — Google then treats them as language variants of
# the same page rather than duplicates.
_BASE_ROUTES: list[tuple[str, str]] = [
    ("/", "1.0"),
    ("/formats", "0.5"),
    ("/privacy", "0.3"),
    ("/terms", "0.3"),
    ("/impressum", "0.3"),
    ("/contact", "0.3"),
]

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
    """Resolve the active route list against runtime settings.

    ``/pricing`` and ``/enterprise`` share the ``pricing_page_enabled``
    gate — both are part of the commercial-offer surface. A self-hosted
    Community deployment leaves the flag off and neither route is listed
    or rendered, so search engines never index a 404. When enabled, the
    enterprise page sits at priority 0.8 alongside pricing because
    procurement-driven traffic is the higher-revenue funnel.
    """
    routes = list(_BASE_ROUTES)
    if settings.pricing_page_enabled:
        routes.insert(1, ("/pricing", "0.8"))
        routes.insert(2, ("/enterprise", "0.8"))
    return routes


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
    do — listing only routes that exist on *every* deployment (``/pricing``
    and ``/enterprise`` are gated, so they're omitted to stay deployment-
    agnostic). English-only by design: it targets crawlers, not end users.
    """
    base = settings.app_base_url.rstrip("/")
    lines = [
        "# FileMorph",
        "",
        "> Free, open-source, privacy-respecting file converter and compressor. "
        "Convert and compress images, documents, spreadsheets, audio and video in "
        "the browser or via a REST API. Self-hostable (AGPLv3), EU-hosted, no "
        "account required.",
        "",
        "## Core pages",
        "",
        f"- [Convert & compress files]({base}/): the main tool — convert and "
        "compress files for free, no account",
        f"- [Supported formats]({base}/formats): the full list of supported "
        "conversions, grouped by category",
        f"- [API documentation]({base}/docs): REST API reference for "
        "programmatic conversion and compression",
        "",
        "## About",
        "",
        "FileMorph converts images (HEIC, JPG, PNG, WebP, BMP, TIFF, GIF), "
        "documents (DOCX, PDF, TXT, Markdown), spreadsheets (XLSX, CSV, JSON), "
        "audio (MP3, WAV, FLAC, OGG, M4A) and video (MP4, MOV, AVI, MKV, WebM). "
        "It can compress JPEG and WebP images to an exact target size using a "
        "binary search. Files are processed server-side and deleted immediately "
        "after conversion; hosting is in the EU and no account is required.",
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
        "# Reports about FileMorph itself (the open-source software at",
        "# https://github.com/MrChengLen/FileMorph) are also welcome via",
        "# GitHub Security Advisories on the repository.",
        "",
    ]
    return "\n".join(lines)
