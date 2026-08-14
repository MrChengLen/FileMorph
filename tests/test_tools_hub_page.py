# SPDX-License-Identifier: AGPL-3.0-or-later
"""/tools — the operations-first hub page (IA rework PR 2,
docs-internal/ia-navigation-konzept.md).

Guards: renders in all three locale mounts with a real H1; title/meta stay in
SERP range; content is plain bilingual data (not gettext, see
app/core/tools_content.py), so DE vs EN must genuinely differ; every card
links to its real, working tool page (the Convert & Compress card is the
sole discoverability surface for the target-size-compress and batch modes,
so its description names both); the Redact card is gated on
ai_operations_enabled only (mirrors tests/test_footer_nav_structure.py's
redact_enabled fixture); the page cross-links /formats both ways; stays
deployment-agnostic; and the sitemap / llms.txt discover it.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest

from app.core.config import settings
from app.core.convert_pairs import PAIR_CONTENT
from app.core.templates import templates
from app.core.tools_content import TOOLS_CONTENT


@pytest.fixture
def redact_enabled():
    """Mirrors tests/test_footer_nav_structure.py's fixture of the same
    name — the route's 404-gate (on /redact) reads ``settings`` at request
    time, the template ``{% if %}`` reads the Jinja global set once at
    import; both must flip together."""
    s = settings.__dict__
    saved_s = {k: s.get(k) for k in ("ai_operations_enabled", "ai_eligible_tiers")}
    s.update(ai_operations_enabled=True, ai_eligible_tiers="pro,business,enterprise")
    g = templates.env.globals
    saved_g = {k: g.get(k) for k in ("ai_operations_enabled", "ai_eligible_tiers")}
    g["ai_operations_enabled"] = True
    g["ai_eligible_tiers"] = ["pro", "business", "enterprise"]
    yield
    s.update(saved_s)
    g.update(saved_g)


# ── renders + SERP ────────────────────────────────────────────────────────


@pytest.mark.parametrize("prefix", ["", "/en", "/de"])
def test_tools_page_renders(client, prefix):
    r = client.get(f"{prefix}/tools")
    assert r.status_code == 200, f"{prefix}/tools -> {r.status_code}"
    assert "<h1" in r.text


@pytest.mark.parametrize("prefix", ["/en", "/de"])
def test_tools_title_and_meta_in_serp_range(client, prefix):
    r = client.get(f"{prefix}/tools")
    assert r.status_code == 200
    title = re.search(r"<title[^>]*>([^<]+)</title>", r.text, re.IGNORECASE).group(1).strip()
    meta = (
        re.search(r'<meta\s+name="description"\s+content="([^"]+)"', r.text, re.IGNORECASE)
        .group(1)
        .strip()
    )
    assert len(title) <= 60, f"{prefix}/tools title {len(title)}: {title!r}"
    assert len(meta) <= 160, f"{prefix}/tools meta {len(meta)}: {meta!r}"
    assert len(title) >= 10 and len(meta) >= 50


def test_tools_page_localised(client):
    """Content lives as plain bilingual data (tools_content.py), not gettext
    — h1 must genuinely differ per locale, not just repeat the English
    string on /de/."""
    en = TOOLS_CONTENT["en"]
    de = TOOLS_CONTENT["de"]
    en_html = client.get("/en/tools").text
    de_html = client.get("/de/tools").text
    assert en["h1"] in en_html
    assert de["h1"] in de_html
    assert en["h1"] != de["h1"]


def test_convert_card_mentions_batch_both_locales():
    """The Convert & Compress card is the sole discoverability surface for
    multi-file batch conversion, a mode with no URL of its own — its
    description must name it, in each locale. Compress-to-a-target-size used
    to live here too under the same rule, until IA rework PR 4 gave it a
    dedicated page (/compress) and its own adjacent card — see
    test_compress_page.py::test_compress_target_card_links_compress_page."""
    en = TOOLS_CONTENT["en"]["cards"]["convert"]["desc"]
    de = TOOLS_CONTENT["de"]["cards"]["convert"]["desc"]
    assert "batch" in en
    assert "Stapelverarbeitung" in de


def _main(html: str) -> str:
    """Slice the page's <main> block — card-link asserts must not pass
    just because base.html's navbar/footer links the same URL."""
    return html[html.index("<main") : html.index("</main>")]


# ── card links ────────────────────────────────────────────────────────────


def test_tools_page_links_convert_and_pdf_tools(client):
    r = client.get("/en/tools")
    assert r.status_code == 200
    main = _main(r.text)
    assert 'href="/en/"' in main
    for path in ("/en/pdf/split", "/en/pdf/extract", "/en/pdf/compress"):
        assert f'href="{path}"' in main
    # Card bodies render, not just their CTAs.
    from app.core.tools_content import TOOLS_CONTENT

    assert TOOLS_CONTENT["en"]["cards"]["convert"]["desc"][:40] in main


def test_tools_page_localises_card_links_on_de(client):
    r = client.get("/de/tools")
    assert r.status_code == 200
    main = _main(r.text)
    for path in ("/de/pdf/split", "/de/pdf/extract", "/de/pdf/compress"):
        assert f'href="{path}"' in main


# ── Redact card — flag-gated only ────────────────────────────────────────


def test_redact_card_absent_when_flag_off(client):
    r = client.get("/en/tools")
    assert r.status_code == 200
    assert 'href="/en/redact"' not in r.text
    assert "Privacy tools" not in r.text


def test_redact_card_present_when_flag_on(client, redact_enabled):
    r = client.get("/en/tools")
    assert r.status_code == 200
    assert 'href="/en/redact"' in r.text
    assert "Privacy tools" in r.text
    assert TOOLS_CONTENT["en"]["cards"]["redact"]["title"] in r.text


# ── cross-link to /formats ───────────────────────────────────────────────


def test_tools_page_cross_links_to_formats(client):
    r = client.get("/en/tools")
    assert r.status_code == 200
    assert 'href="/en/formats"' in _main(r.text)


# ── deployment-agnostic ──────────────────────────────────────────────────


def test_tools_page_deployment_agnostic(client):
    r = client.get("/en/tools")
    assert "filemorph.io" not in r.text


# ── discovery surfaces ───────────────────────────────────────────────────


def test_sitemap_lists_tools_with_hreflang(client):
    r = client.get("/sitemap.xml")
    assert r.status_code == 200
    root = ET.fromstring(r.text)
    ns = {
        "sm": "http://www.sitemaps.org/schemas/sitemap/0.9",
        "xhtml": "http://www.w3.org/1999/xhtml",
    }
    locs = {
        (u.find("sm:loc", ns).text or "")
        for u in root.findall("sm:url", ns)
        if u.find("sm:loc", ns) is not None
    }
    assert any(loc.endswith("/tools") for loc in locs), "missing x-default /tools"
    assert any(loc.endswith("/en/tools") for loc in locs), "missing /en/tools"
    assert any(loc.endswith("/de/tools") for loc in locs), "missing /de/tools"

    checked = 0
    for u in root.findall("sm:url", ns):
        loc = u.find("sm:loc", ns).text or ""
        if loc.endswith("/tools"):
            hreflangs = {a.attrib.get("hreflang") for a in u.findall("xhtml:link", ns)}
            assert hreflangs == {"x-default", "de", "en"}, f"{loc} hreflangs {hreflangs}"
            checked += 1
    assert checked == 3  # x-default + de + en


def test_llms_txt_lists_tools_and_all_pair_urls(client):
    llms = client.get("/llms.txt").text
    assert "/tools" in llms
    assert "## Conversions" in llms
    for src, tgt in PAIR_CONTENT:
        assert f"/convert/{src}-to-{tgt}" in llms
