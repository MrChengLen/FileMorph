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

router = APIRouter()


# Routes that every deployment serves.
_BASE_ROUTES: list[tuple[str, str]] = [
    ("/", "1.0"),
    ("/privacy", "0.3"),
    ("/terms", "0.3"),
    ("/impressum", "0.3"),
    ("/contact", "0.3"),
]


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


@router.get("/robots.txt", response_class=PlainTextResponse, include_in_schema=False)
async def robots_txt() -> str:
    base = settings.app_base_url.rstrip("/")
    return f"User-agent: *\nAllow: /\n\nSitemap: {base}/sitemap.xml\n"


@router.get("/sitemap.xml", include_in_schema=False)
async def sitemap_xml() -> Response:
    base = settings.app_base_url.rstrip("/")
    urls = "\n".join(
        f"  <url><loc>{base}{path}</loc><priority>{prio}</priority></url>"
        for path, prio in _sitemap_routes()
    )
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}\n"
        "</urlset>\n"
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
