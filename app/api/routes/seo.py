"""SEO foundation endpoints: ``/robots.txt`` and ``/sitemap.xml``.

Mounted at the root (no ``/api/v1`` prefix) so search engines find them at
the conventional locations. The route list is built per-request from
``settings`` so that a self-hoster who has not configured Stripe does not
advertise a ``/pricing`` route they don't actually serve.
"""

from __future__ import annotations

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
]


def _sitemap_routes() -> list[tuple[str, str]]:
    """Resolve the active route list against runtime settings.

    ``/pricing`` is only meaningful when Stripe is configured — listing it
    on a self-hosted Community deployment would point search engines at a
    page that 404s or shows a disabled checkout. Same logic applies to
    future tier-gated pages (e.g. /upgrade).
    """
    routes = list(_BASE_ROUTES)
    if settings.stripe_secret_key:
        routes.insert(1, ("/pricing", "0.8"))
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
