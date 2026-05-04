# SPDX-License-Identifier: AGPL-3.0-or-later
"""Acceptance tests for the S6-SEO sprint (AT-1..12).

Mirrors `scripts/audit_seo_basics.py` checks but as pytest assertions, so a
regression that strips a meta tag or removes a JSON-LD block fails CI.
Refer to `runbooks/claims-audit.md` §3 (seo-audit acceptance tests AT-1..12)
for the upstream expected behaviour.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path


# ── AT-01..02 — Endpoints ────────────────────────────────────────────────────


def test_robots_txt_serves_with_sitemap_directive(client):
    r = client.get("/robots.txt")
    assert r.status_code == 200
    body = r.text.lower()
    assert "user-agent:" in body
    assert "sitemap:" in body
    assert "/sitemap.xml" in body


def test_sitemap_xml_serves_valid_with_url_entries(client):
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    assert "xml" in r.headers.get("content-type", "")
    root = ET.fromstring(r.text)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = root.findall("sm:url", ns)
    assert len(urls) >= 1, "sitemap must list at least one URL"
    locs = [(u.find("sm:loc", ns).text or "") for u in urls if u.find("sm:loc", ns) is not None]
    assert any(loc.endswith("/") for loc in locs), (
        f"sitemap must include the homepage; got {locs!r}"
    )


# ── AT-03..05 — Title / description / viewport / canonical ───────────────────


def test_homepage_has_title_in_seo_range(client):
    r = client.get("/")
    assert r.status_code == 200
    m = re.search(r"<title[^>]*>([^<]+)</title>", r.text, re.IGNORECASE)
    assert m, "missing <title>"
    title = m.group(1).strip()
    assert 10 <= len(title) <= 60, f"title length {len(title)} out of SEO range (10-60)"


def test_homepage_has_meta_description_in_seo_range(client):
    r = client.get("/")
    m = re.search(
        r'<meta\s+name=["\']description["\']\s+content=["\']([^"\']+)["\']',
        r.text,
        re.IGNORECASE,
    )
    assert m, "missing meta description"
    desc = m.group(1).strip()
    assert 50 <= len(desc) <= 160, f"description length {len(desc)} out of SEO range (50-160)"


def test_homepage_has_viewport_device_width(client):
    r = client.get("/")
    assert re.search(
        r'<meta\s+name=["\']viewport["\']\s+content=["\'][^"\']*width=device-width',
        r.text,
        re.IGNORECASE,
    ), "missing or non-mobile viewport tag"


def test_homepage_has_canonical_absolute(client):
    r = client.get("/")
    m = re.search(
        r'<link\s+rel=["\']canonical["\']\s+href=["\']([^"\']+)["\']',
        r.text,
        re.IGNORECASE,
    )
    assert m, "missing <link rel=canonical>"
    href = m.group(1).strip()
    assert href.startswith(("http://", "https://")), f"canonical not absolute: {href}"


# ── AT-06..09 — OpenGraph + Twitter Card ─────────────────────────────────────


def _meta_property(html: str, prop: str) -> str | None:
    m = re.search(
        rf'<meta\s+property=["\']{re.escape(prop)}["\']\s+content=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )
    return m.group(1).strip() if m else None


def _meta_name(html: str, name: str) -> str | None:
    m = re.search(
        rf'<meta\s+name=["\']{re.escape(name)}["\']\s+content=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )
    return m.group(1).strip() if m else None


def test_homepage_has_all_required_og_tags(client):
    r = client.get("/")
    for prop in ("og:title", "og:description", "og:type", "og:image", "og:url"):
        assert _meta_property(r.text, prop), f"missing <meta property={prop}>"


def test_homepage_has_twitter_card_summary_large_image(client):
    r = client.get("/")
    card = _meta_name(r.text, "twitter:card")
    assert card == "summary_large_image", f"twitter:card was {card!r}"


def test_og_image_resolves_with_correct_dimensions(client):
    r = client.get("/")
    img_path = _meta_property(r.text, "og:image")
    assert img_path, "no og:image set"
    # og:image is absolute (e.g. http://localhost:8000/static/og-image.png) —
    # follow the path portion against TestClient.
    static_path = re.sub(r"^https?://[^/]+", "", img_path)
    head = client.head(static_path)
    assert head.status_code == 200, f"og-image fetch failed: {head.status_code} for {static_path}"
    asset = Path("app/static/og-image.png")
    assert asset.exists(), "app/static/og-image.png missing on disk"
    from PIL import Image

    with Image.open(asset) as im:
        assert im.size == (1200, 630), f"og-image is {im.size}, expected (1200, 630)"


# ── AT-10..12 — JSON-LD ──────────────────────────────────────────────────────


def test_homepage_has_jsonld_with_webapplication_and_softwareapplication(client):
    r = client.get("/")
    blocks = re.findall(
        r'<script\s+type=["\']application/ld\+json["\'][^>]*>([\s\S]+?)</script>',
        r.text,
        re.IGNORECASE,
    )
    assert blocks, "no JSON-LD <script> blocks on homepage"

    types_found: list[str] = []
    for block in blocks:
        data = json.loads(block)
        items = data if isinstance(data, list) else [data]
        for item in items:
            t = item.get("@type")
            if isinstance(t, str):
                types_found.append(t)
            elif isinstance(t, list):
                types_found.extend(t)

    assert "WebApplication" in types_found, "JSON-LD missing WebApplication"
    assert "SoftwareApplication" in types_found, "JSON-LD missing SoftwareApplication"


def test_jsonld_csp_hash_matches_rendered_block(client):
    """Defence in depth: the SHA-256 hash injected into the CSP must equal the
    hash of the actual JSON-LD bytes rendered on the homepage. If the two
    diverge, browsers block the inline JSON-LD and SEO crawlers see noise."""
    import base64
    import hashlib

    r = client.get("/")
    csp = r.headers.get("content-security-policy", "")
    block_match = re.search(
        r'<script\s+type=["\']application/ld\+json["\'][^>]*>([\s\S]+?)</script>',
        r.text,
        re.IGNORECASE,
    )
    assert block_match, "no JSON-LD block on homepage"
    rendered = block_match.group(1)
    digest = hashlib.sha256(rendered.encode("utf-8")).digest()
    expected_hash = "'sha256-" + base64.b64encode(digest).decode("ascii") + "'"
    assert expected_hash in csp, (
        f"CSP script-src missing hash for rendered JSON-LD.\n"
        f"  expected: {expected_hash}\n"
        f"  CSP: {csp}"
    )
