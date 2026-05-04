"""SEO foundation endpoints: ``/robots.txt`` and ``/sitemap.xml``.

Mounted at the root (no ``/api/v1`` prefix) so search engines find them at
the conventional locations. Both responses are static at this stage — the
sitemap will grow dynamically when S9 (per-pair landing pages) ships.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse, Response

from app.core.config import settings

router = APIRouter()


_SITEMAP_ROUTES: list[tuple[str, str]] = [
    ("/", "1.0"),
    ("/pricing", "0.8"),
    ("/privacy", "0.3"),
    ("/terms", "0.3"),
    ("/impressum", "0.3"),
]


@router.get("/robots.txt", response_class=PlainTextResponse, include_in_schema=False)
async def robots_txt() -> str:
    base = settings.app_base_url.rstrip("/")
    return f"User-agent: *\nAllow: /\n\nSitemap: {base}/sitemap.xml\n"


@router.get("/sitemap.xml", include_in_schema=False)
async def sitemap_xml() -> Response:
    base = settings.app_base_url.rstrip("/")
    urls = "\n".join(
        f"  <url><loc>{base}{path}</loc><priority>{prio}</priority></url>"
        for path, prio in _SITEMAP_ROUTES
    )
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}\n"
        "</urlset>\n"
    )
    return Response(content=body, media_type="application/xml")
