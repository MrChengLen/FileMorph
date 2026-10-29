# SPDX-License-Identifier: AGPL-3.0-or-later
"""Link previews and icons.

A shared link shows the page's own title and description, with the brand in
og:site_name. The icon paths iOS, browsers and crawlers request on their own
answer with the image instead of the HTML 404 page and don't count as page
views; the web manifest carries PNG icons for Android home screens.
"""

import io
import re

import pytest
from PIL import Image

from app.core.config import settings
from app.main import _PAGE_VIEW_IGNORED_PREFIXES


def _meta(html: str, attr: str, key: str) -> str | None:
    m = re.search(rf'<meta {attr}="{re.escape(key)}" content="([^"]*)"', html)
    return m.group(1) if m else None


@pytest.mark.parametrize("path", ["/", "/de/pdf/insert", "/en/pdf/insert", "/de/contact"])
def test_link_preview_carries_the_page_title_and_description(client, path):
    html = client.get(path).text
    title = re.search(r"<title>(.*?)</title>", html).group(1)
    expected_title = title.removesuffix(" | FileMorph").removesuffix(" — FileMorph")
    assert expected_title != title, "every one of these pages has a title of its own"
    description = _meta(html, "name", "description")
    assert description

    assert _meta(html, "property", "og:site_name") == "FileMorph"
    assert _meta(html, "property", "og:title") == expected_title
    assert _meta(html, "name", "twitter:title") == expected_title
    assert _meta(html, "property", "og:description") == description
    assert _meta(html, "name", "twitter:description") == description


def test_preview_title_drops_only_the_trailing_brand(client, monkeypatch):
    """The brand inside a title stays; only the " | FileMorph" at the end goes."""
    monkeypatch.setattr(settings, "pricing_page_enabled", True)
    html = client.get("/en/pricing").text
    assert re.search(r"<title>Pricing — FileMorph is free \| FileMorph</title>", html)
    assert _meta(html, "property", "og:title") == "Pricing — FileMorph is free"
    assert _meta(html, "name", "twitter:title") == "Pricing — FileMorph is free"


def test_apple_touch_icon_is_an_opaque_180px_png(client):
    r = client.get("/apple-touch-icon.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    img = Image.open(io.BytesIO(r.content))
    assert (img.format, img.size) == ("PNG", (180, 180))
    # iOS paints transparent pixels black — the icon brings its own background.
    assert img.mode == "RGB"


def test_favicon_ico_carries_the_classic_sizes(client):
    r = client.get("/favicon.ico")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/x-icon"
    img = Image.open(io.BytesIO(r.content))
    assert img.format == "ICO"
    assert {(16, 16), (32, 32), (48, 48)} <= set(img.info["sizes"])


@pytest.mark.parametrize("path", ["/apple-touch-icon.png", "/favicon.ico"])
def test_root_icons_are_cached_and_not_counted_as_page_views(client, path):
    assert client.get(path).headers["cache-control"] == "public, max-age=86400"
    assert client.head(path).status_code == 200
    assert path.startswith(_PAGE_VIEW_IGNORED_PREFIXES)


def test_pages_link_the_icons(client):
    html = client.get("/").text
    assert '<link rel="icon" href="/favicon.ico" sizes="32x32" />' in html
    assert '<link rel="icon" href="/static/favicon.svg" type="image/svg+xml" />' in html
    assert '<link rel="apple-touch-icon" href="/apple-touch-icon.png" />' in html


def test_manifest_lists_png_icons_for_android(client):
    icons = client.get("/static/site.webmanifest").json()["icons"]
    pngs = {(i["sizes"], i.get("purpose", "any")) for i in icons if i["type"] == "image/png"}
    assert {("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")} <= pngs
    for icon in icons:
        r = client.get(icon["src"])
        assert r.status_code == 200, icon["src"]
        if icon["type"] == "image/png":
            width, height = (int(n) for n in icon["sizes"].split("x"))
            img = Image.open(io.BytesIO(r.content))
            # Opaque: a maskable icon fills the whole launcher shape.
            assert (img.size, img.mode) == ((width, height), "RGB"), icon["src"]
