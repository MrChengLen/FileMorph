# SPDX-License-Identifier: AGPL-3.0-or-later
"""/tools — the operations-first hub page (IA rework PR 2,
docs-internal/ia-navigation-konzept.md).

Guards: renders in all three locale mounts with a real H1; title/meta stay in
SERP range; content is plain bilingual data (not gettext, see
app/core/tools_content.py), so DE vs EN must genuinely differ; every tool and
convert page of the page catalogue (app/core/catalog.py) has a card under its
catalogue name, grouped by file type and stating where it runs; the intro
names batch conversion, which has no page of its own; the Redact card is gated
on ai_operations_enabled only (mirrors tests/test_footer_nav_structure.py's
redact_enabled fixture); the page cross-links /formats both ways; stays
deployment-agnostic; and the sitemap / llms.txt discover it.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import pytest
from bs4 import BeautifulSoup

from app.core import catalog
from app.core.config import settings
from app.core.convert_pairs import PAIR_CONTENT
from app.core.templates import templates
from app.core.tools_content import TOOLS_CONTENT


@pytest.fixture
def redact_enabled():
    """Mirrors tests/test_footer_nav_structure.py's fixture of the same
    name — the route's 404-gate (on /redact) reads ``settings`` at request
    time, the footer and /tools read it through the page catalogue, other
    templates' ``{% if %}`` read the Jinja global set once at
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


def test_converter_intro_mentions_batch_both_locales(client):
    """The intro line pointing at the converter on the homepage is the sole
    discoverability surface for multi-file batch conversion, a mode with no
    URL of its own — it must name it, in each locale, and link the converter."""
    for prefix, word in (("/en", "batch"), ("/de", "Stapelverarbeitung")):
        intro = TOOLS_CONTENT[prefix.strip("/")]["intro"]
        assert word in intro
        main = _main(client.get(f"{prefix}/tools").text)
        assert intro in main
        assert f'href="{prefix}/"' in main


def _main(html: str) -> str:
    """Slice the page's <main> block — card-link asserts must not pass
    just because base.html's navbar/footer links the same URL."""
    return html[html.index("<main") : html.index("</main>")]


# ── card links ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("prefix", ["/en", "/de"])
def test_tools_page_has_a_card_for_every_tool_page(client, prefix):
    """/tools is the one complete list: every tool and convert page of the
    page catalogue gets a card under its catalogue name. The convert pages'
    only other inlinks are the footer grid, so this is their hub link."""
    main = _main(client.get(f"{prefix}/tools").text)
    locale = prefix.strip("/")
    for page in catalog.pages():
        if page.kind in ("tool", "convert"):
            assert f'href="{prefix}{page.path}"' in main, f"no /tools card for {page.path}"
            assert page.label[locale] in main, f"{page.path} card lacks its name"


@pytest.mark.parametrize("prefix", ["/en", "/de"])
def test_tools_page_card_is_one_link_named_after_the_tool(client, prefix):
    """The whole card is the link (decided 2026-10-29): its only link sits in
    the h3, so the link text is the tool's name, and the link's after: overlay
    stretches over the card. "Open →" stays as a cue screen readers skip."""
    main = BeautifulSoup(_main(client.get(f"{prefix}/tools").text), "html.parser")
    locale = prefix.strip("/")
    names = {
        f"{prefix}{page.path}": page.label[locale]
        for page in catalog.pages()
        if page.kind in ("tool", "convert")
    }
    cards = main.find_all("div", attrs={"data-component": "card"})
    assert len(cards) == len(names)
    for card in cards:
        (link,) = card.find_all("a")
        assert link.parent.name == "h3"
        assert link.get_text(strip=True) == names[link["href"]]
        assert "after:inset-0" in link["class"]
        # outline-none drops the browser's own outline: the ring is all there is.
        assert "focus-visible:after:ring-2" in link["class"]
        assert "relative" in card["class"]
        cue = card.find("span", attrs={"aria-hidden": "true"})
        assert cue is not None, f"{link['href']}: no Open cue"
        assert cue.get_text(strip=True) == ("Öffnen →" if locale == "de" else "Open →")


def test_tools_page_cards_say_where_they_run(client):
    """G7: every card states, as text, that the tool runs on our server."""
    main = _main(client.get("/de/tools").text)
    cards = sum(1 for page in catalog.pages() if page.kind in ("tool", "convert"))
    assert main.count("Läuft über unseren Server") == cards
    assert main.count('data-location="server"') == cards


def test_tools_page_groups_by_file_type_with_jump_links(client):
    main = _main(client.get("/en/tools").text)
    for anchor, heading in (("pdf", "PDF tools"), ("image", "Images")):
        assert f'id="{anchor}"' in main
        assert f'href="#{anchor}"' in main
        assert heading in main


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
    assert "Redact PII" not in _main(r.text)


def test_redact_card_present_when_flag_on(client, redact_enabled):
    """The only privacy tool so far: below the two-tool threshold for a
    section of its own, it sits under "More tools"."""
    r = client.get("/en/tools")
    assert r.status_code == 200
    main = _main(r.text)
    assert 'href="/en/redact"' in main
    assert "More tools" in main
    assert "Redact PII" in main
    assert "paid file download" in main, "the card must say the download is paid"


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
