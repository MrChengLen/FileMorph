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


# ── Deployment-agnosticism regression guards ────────────────────────────────
#
# These tests pin the public OSS repo to deployment-agnostic content. A
# self-hoster who runs the app behind their own domain must not see SaaS-
# specific URLs leak into structured data, sitemaps, or static assets.
# Reasoning behind these guards lives in CLAUDE.md ("Active Scope-Review
# Before Commit"); the original drift was discovered post-S6 commit 8c5bdea.


def test_jsonld_url_built_from_app_base_url_not_hardcoded_saas():
    """``build_site_jsonld(app_base_url)`` must use the passed-in base URL
    in every entry's ``url`` field. Hardcoding ``https://filemorph.io``
    would ship the upstream SaaS origin in every self-hoster's structured
    data — Google's Knowledge Graph would attribute their content to us."""
    from app.core.jsonld import build_site_jsonld

    canonical, _ = build_site_jsonld("https://files.example.com")
    assert "https://files.example.com" in canonical, (
        "JSON-LD must reflect the deployment's own app_base_url"
    )
    assert "filemorph.io" not in canonical, (
        "JSON-LD leaked the upstream SaaS hostname into a self-hosted deployment"
    )


def test_sitemap_omits_pricing_when_pricing_page_disabled(client, monkeypatch):
    """Self-hosters running without the pricing surface enabled don't have
    a /pricing route at all (404 enforced in main.py). Listing it in the
    sitemap would point search engines at a 404."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "pricing_page_enabled", False)
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    assert "/pricing" not in r.text, (
        "sitemap must not advertise /pricing on a deployment with pricing disabled"
    )


def test_sitemap_includes_pricing_when_pricing_page_enabled(client, monkeypatch):
    """When pricing_page_enabled is on (filemorph.io SaaS), /pricing belongs
    in the sitemap regardless of Stripe state — that's the whole point of
    the split, so a 'Coming Soon' pricing page can be indexed before
    Stripe live-mode comes online."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "pricing_page_enabled", True)
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    assert "/pricing" in r.text, "sitemap must list /pricing when pricing_page_enabled is on"


def test_pricing_route_returns_404_when_pricing_disabled(client, monkeypatch):
    """Self-host default — no commercial pricing surface to advertise.
    The route must 404 so search engines don't index a dangling page."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "pricing_page_enabled", False)
    r = client.get("/pricing")
    assert r.status_code == 404


def test_pricing_route_renders_when_pricing_enabled(client, monkeypatch):
    """When pricing_page_enabled is on, the page renders (200) — even if
    Stripe itself is disabled (Coming-Soon mode)."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "pricing_page_enabled", True)
    monkeypatch.setattr(settings, "stripe_secret_key", "")
    r = client.get("/pricing")
    assert r.status_code == 200


def test_pricing_renders_coming_soon_when_stripe_disabled(client, monkeypatch):
    """Coming-Soon mode: pricing page must surface a clear 'coming soon'
    message and disable the upgrade buttons so visitors don't click into
    a checkout that 503s."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "pricing_page_enabled", True)
    monkeypatch.setattr(settings, "stripe_secret_key", "")
    # Re-render globals (they're set at module import) — pull fresh from settings
    from app.main import templates

    templates.env.globals["stripe_enabled"] = False

    r = client.get("/pricing")
    assert r.status_code == 200
    body = r.text.lower()
    assert "coming soon" in body, "Coming-Soon banner missing when Stripe disabled"
    assert "disabled" in body, "upgrade buttons must be disabled in Coming-Soon mode"


def test_pricing_renders_live_buttons_when_stripe_enabled(client, monkeypatch):
    """Live mode: upgrade buttons must NOT carry the disabled attribute, so
    real users can hit the Stripe checkout endpoint."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "pricing_page_enabled", True)
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")
    from app.main import templates

    templates.env.globals["stripe_enabled"] = True

    r = client.get("/pricing")
    assert r.status_code == 200
    # Find the pro button line; it must not include the `disabled` attribute
    # in its tag (the Coming-Soon variant has `disabled` directly on <button>).
    assert 'id="pro-btn"' in r.text
    pro_line = next(
        (line for line in r.text.splitlines() if 'id="pro-btn"' in line),
        "",
    )
    assert "disabled" not in pro_line.lower(), "pro button must be enabled when Stripe is live"


def test_navbar_omits_pricing_link_when_pricing_disabled(client, monkeypatch):
    """A self-host build should not advertise a Pricing link in the nav."""
    from app.core.config import settings
    from app.main import templates

    monkeypatch.setattr(settings, "pricing_page_enabled", False)
    templates.env.globals["pricing_enabled"] = False

    r = client.get("/")
    assert r.status_code == 200
    assert 'href="/pricing"' not in r.text, (
        "navbar must hide /pricing link when pricing_page_enabled is off"
    )


def test_navbar_shows_pricing_link_when_pricing_enabled(client, monkeypatch):
    from app.core.config import settings
    from app.main import templates

    monkeypatch.setattr(settings, "pricing_page_enabled", True)
    templates.env.globals["pricing_enabled"] = True

    r = client.get("/")
    assert r.status_code == 200
    assert 'href="/pricing"' in r.text, (
        "navbar must show /pricing link when pricing_page_enabled is on"
    )


# ── /enterprise gating mirrors /pricing — both are commercial-offer surface ──


def test_sitemap_omits_enterprise_when_pricing_page_disabled(client, monkeypatch):
    """Self-host default — neither /pricing nor /enterprise is served, so
    listing /enterprise in the sitemap would point search engines at a 404
    and (worse) leak the upstream enterprise@filemorph.io contact."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "pricing_page_enabled", False)
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    assert "/enterprise" not in r.text


def test_sitemap_includes_enterprise_when_pricing_page_enabled(client, monkeypatch):
    """When the commercial-offer surface is on, /enterprise rides the same
    sitemap gate as /pricing — procurement-driven discovery is the whole
    point of the page."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "pricing_page_enabled", True)
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    assert "/enterprise" in r.text


def test_enterprise_route_returns_404_when_pricing_disabled(client, monkeypatch):
    """Same gating as /pricing — a self-hoster running Community Edition
    must not advertise the upstream enterprise@ contact as if it were
    their own."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "pricing_page_enabled", False)
    r = client.get("/enterprise")
    assert r.status_code == 404


def test_enterprise_route_renders_when_pricing_enabled(client, monkeypatch):
    """When the commercial-offer surface is on, /enterprise renders and
    surfaces the enterprise contact + the Compliance-Edition tier table."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "pricing_page_enabled", True)
    r = client.get("/enterprise")
    assert r.status_code == 200
    body = r.text
    assert "enterprise@filemorph.io" in body, "page must surface the procurement contact"
    assert "Compliance Starter" in body, "tier table must list the entry-level tier"
    assert "Compliance Standard" in body
    assert "Compliance Enterprise" in body


def test_navbar_omits_enterprise_link_when_pricing_disabled(client, monkeypatch):
    """Self-host build hides the Enterprise nav entry too — same reasoning
    as the /pricing nav guard."""
    from app.core.config import settings
    from app.main import templates

    monkeypatch.setattr(settings, "pricing_page_enabled", False)
    templates.env.globals["pricing_enabled"] = False

    r = client.get("/")
    assert r.status_code == 200
    assert 'href="/enterprise"' not in r.text


def test_navbar_shows_enterprise_link_when_pricing_enabled(client, monkeypatch):
    from app.core.config import settings
    from app.main import templates

    monkeypatch.setattr(settings, "pricing_page_enabled", True)
    templates.env.globals["pricing_enabled"] = True

    r = client.get("/")
    assert r.status_code == 200
    assert 'href="/enterprise"' in r.text


# ── security.txt (RFC 9116) + /security policy page ─────────────────────────


def test_security_txt_serves_with_required_rfc9116_fields(client):
    """RFC 9116 requires at minimum Contact + Expires. We additionally pin
    Canonical (must be absolute) and Policy (points at /security)."""
    r = client.get("/.well-known/security.txt")
    assert r.status_code == 200
    body = r.text
    assert body.startswith("Contact:"), "Contact must be the first line per RFC 9116 §2.5.3"
    assert "\nExpires:" in body, "Expires field is mandatory"
    assert "\nCanonical:" in body, "Canonical field anchors the file's identity"
    assert "\nPolicy:" in body, "Policy must point at the human-readable disclosure page"
    assert "/security" in body, "Policy URL must reference /security"


def test_security_txt_expires_is_within_365_days(client):
    """The Expires field is regenerated on every request to ~365 days out
    so a forgotten cache or long-running instance can't serve an expired
    file. RFC 9116 §2.5.5 mandates ≤1 year."""
    from datetime import datetime, timezone

    r = client.get("/.well-known/security.txt")
    assert r.status_code == 200
    m = re.search(r"^Expires:\s*(\S+)", r.text, re.MULTILINE)
    assert m, "Expires field missing"
    expires = datetime.fromisoformat(m.group(1).replace("+00:00", "+00:00"))
    delta = expires - datetime.now(timezone.utc)
    assert 364 <= delta.days <= 366, (
        f"Expires should be ~365 days out, got {delta.days} — RFC 9116 §2.5.5 caps at 1 year"
    )


def test_security_txt_contact_uses_configured_email(client, monkeypatch):
    """Self-hosters override SECURITY_CONTACT_EMAIL; the configured value
    must surface in the response. Default points at the upstream so an
    unconfigured deployment is still reachable."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "security_contact_email", "secops@example.com")
    r = client.get("/.well-known/security.txt")
    assert r.status_code == 200
    assert "Contact: mailto:secops@example.com" in r.text


def test_security_txt_canonical_built_from_app_base_url(client, monkeypatch):
    """A self-hosted instance must advertise its OWN canonical URL — leaking
    `https://filemorph.io` into Canonical/Policy would point bug reporters at
    upstream instead of the operator who actually runs the binary. We
    override the contact too so the only filemorph.io reference left in the
    body is the upstream-project comment block, which is intentional."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "app_base_url", "https://files.example.com")
    monkeypatch.setattr(settings, "security_contact_email", "secops@example.com")
    r = client.get("/.well-known/security.txt")
    assert r.status_code == 200
    assert "Canonical: https://files.example.com/.well-known/security.txt" in r.text
    assert "Policy: https://files.example.com/security" in r.text
    # The upstream-project comment intentionally references the GitHub repo
    # — strip that one allowed mention before asserting no leakage.
    sanitized = r.text.replace("github.com/MrChengLen/FileMorph", "")
    assert "filemorph.io" not in sanitized, (
        "Canonical/Policy URLs must follow app_base_url; the only filemorph.io reference "
        "allowed is the upstream-project comment"
    )


def test_security_page_renders_with_contact_email(client, monkeypatch):
    """The /security page is the human-readable Policy referenced from
    security.txt — must always render and surface the same contact email."""
    from app.core.config import settings
    from app.main import templates

    monkeypatch.setattr(settings, "security_contact_email", "secops@example.com")
    templates.env.globals["security_contact_email"] = "secops@example.com"

    r = client.get("/security")
    assert r.status_code == 200
    assert "secops@example.com" in r.text
    assert "/.well-known/security.txt" in r.text, (
        "/security should link back to the machine-readable file"
    )


def test_og_image_carries_no_saas_specific_text():
    """The og-image is a static PNG shipped in the public OSS repo and
    served by every deployment. A baked-in ``filemorph.io`` footer would
    appear in every self-hoster's social embeds — wrong attribution, hard
    to notice (it only shows in shared-link previews, not the live site)."""
    from PIL import Image

    asset = Path("app/static/og-image.png")
    assert asset.exists(), "app/static/og-image.png missing"

    # Visual check: the rendered PNG bytes must not encode the substring
    # "filemorph.io" in any tEXt/iTXt PNG metadata chunk. The raster pixels
    # themselves can't be string-matched, so this guards the metadata
    # surface — which is what social scrapers + image search read.
    raw = asset.read_bytes()
    assert b"filemorph.io" not in raw, (
        "og-image embeds 'filemorph.io' in metadata — re-render with footer_url=None"
    )
    with Image.open(asset) as im:
        assert im.size == (1200, 630)
