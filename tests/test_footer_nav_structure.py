# SPDX-License-Identifier: AGPL-3.0-or-later
"""Footer regroup, redact nav-slot removal, mobile nav order, and the
quota-error upsell link — IA-rework PR 1 (docs-internal/ia-navigation-konzept.md).

Guards:
  - G2 (footer-pair-grid invariant): the 12-pair "Popular conversions" grid
    stays server-rendered, untouched by the new Tools/Product/Legal groups
    below it.
  - G5 (gate parity): pricing_enabled / ai_operations_enabled gate the same
    links everywhere; a self-host build never links its own 404.
  - G6 (CSP): every nav/footer link is server-rendered in the raw HTML — the
    old client-side-hydrated #nav-ai-slot / #nav-ai-slot-mobile are gone.
  - Upsell-Regeln: the quota-error upsell link only renders when
    pricing_enabled, and pdf-tools.js/app.js only reveal it for the three
    named limit codes (JS behaviour itself is out of pytest's reach — this
    file pins the server-rendered DOM contract the JS depends on).
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.core.convert_pairs import PAIR_CONTENT
from app.core.templates import templates

_PAIR_COUNT = len(PAIR_CONTENT)


def _footer(html: str) -> str:
    """Slice from the <footer> tag — group assertions must not pass just
    because the same URL is linked in the navbar or a homepage teaser."""
    return html[html.index("<footer") :]


def _nav_hrefs(html: str, start_marker: str, end_marker: str) -> list[str]:
    import re

    segment = html[html.index(start_marker) : html.index(end_marker)]
    return re.findall(r'href="([^"]+)"', segment)


@pytest.fixture
def pricing_enabled(monkeypatch):
    """Same two-surface flip as redact_enabled, for the commercial-offer
    gate — see test_seo_foundation.py's pricing tests for the precedent.
    Uses monkeypatch so both sides revert automatically, regardless of test
    order (unlike the plain-assignment pattern some older tests use)."""
    monkeypatch.setattr(settings, "pricing_page_enabled", True)
    monkeypatch.setitem(templates.env.globals, "pricing_enabled", True)


# ── three named footer groups ────────────────────────────────────────────────


def test_footer_group_headings_render_en(client):
    footer = _footer(client.get("/en/").text)
    # aria-label carries the translated group name — asserting it inside the
    # footer slice pins the *labelled groups*, not any stray page text.
    assert 'aria-label="Tools"' in footer
    assert 'aria-label="Product"' in footer
    assert 'aria-label="Legal"' in footer


def test_footer_group_headings_render_de(client):
    footer = _footer(client.get("/de/").text)
    # "Tools" is the identical loanword in both locales, so only assert the
    # two DE-distinct headings here (an EN-only render would still contain
    # the literal word "Tools", which wouldn't catch a missing catalog).
    assert 'aria-label="Produkt"' in footer
    assert 'aria-label="Rechtliches"' in footer


def test_footer_tools_group_links(client):
    """Split/Extract/Compress PDF + Compress-to-size + Formats are ungated —
    always present. Redact PII is asserted separately (flag-gated). "All
    tools →" (/tools, PR 2) is the first link in the group; "Compress to
    size" (/compress, IA rework PR 4) comes right after the PDF entries."""
    footer = _footer(client.get("/en/").text)
    for path in (
        "/en/pdf/split",
        "/en/pdf/extract",
        "/en/pdf/compress",
        "/en/compress",
        "/en/formats",
    ):
        assert f'href="{path}"' in footer, f"Tools group missing {path}"
    assert 'href="/en/tools"' in footer
    tools_group = footer[footer.index('aria-label="Tools"') :]
    assert tools_group.index('href="/en/tools"') < tools_group.index('href="/en/pdf/split"'), (
        '"All tools →" must be the first link in the Tools group'
    )
    assert tools_group.index('href="/en/pdf/compress"') < tools_group.index(
        'href="/en/compress"'
    ), '"Compress to size" must come after the PDF entries'


def test_footer_product_group_links(client, pricing_enabled):
    footer = _footer(client.get("/en/").text)
    assert 'href="/en/#self-hosted"' in footer
    assert 'href="/en/pricing"' in footer
    assert 'href="/en/enterprise"' in footer
    assert 'href="/docs" target="_blank"' in footer
    assert 'href="https://github.com/MrChengLen/FileMorph"' in footer


def test_footer_product_group_omits_gated_links_when_pricing_disabled(client):
    footer = _footer(client.get("/en/").text)
    assert 'href="/en/pricing"' not in footer
    assert 'href="/en/enterprise"' not in footer
    # Self-Hosted stays — ungated, points at the always-rendered homepage anchor.
    assert 'href="/en/#self-hosted"' in footer


def test_footer_legal_group_links(client):
    footer = _footer(client.get("/en/").text)
    assert 'href="/en/privacy"' in footer
    assert 'href="/en/terms"' in footer
    # /impressum's EN URL alias is /imprint (app/core/i18n.py::_PATH_ALIASES) —
    # NOT /en/impressum.
    assert 'href="/en/imprint"' in footer
    assert 'href="/en/contact"' in footer


def test_footer_groups_localized_on_de(client):
    footer = _footer(client.get("/de/").text)
    assert 'href="/de/pdf/split"' in footer
    assert 'href="/de/privacy"' in footer
    assert 'href="/de/impressum"' in footer  # DE is the canonical spelling


def test_desktop_and_mobile_nav_link_order_identical(client):
    """G5: both nav menus render the same links in the same order (the old
    layout had the language switcher first on mobile, last on desktop)."""
    html = client.get("/en/").text
    desktop = _nav_hrefs(html, 'id="nav-menu"', 'id="nav-mobile-menu"')
    mobile = _nav_hrefs(html, 'id="nav-mobile-menu"', "<main")
    assert desktop, "desktop nav slice yielded no links — marker drift?"
    assert desktop == mobile


# ── G2 regression: the 12-pair "Popular conversions" grid is untouched ──────


def test_popular_conversions_grid_still_has_all_pairs(client):
    html = client.get("/en/").text
    assert _PAIR_COUNT == 12, "spec assumes 12 curated pairs — update this guard if that changes"
    # Count inside the grid's own <nav> slice: a future homepage section
    # linking one pair (PR 3) must not make this guard miscount.
    grid = html[html.index('aria-label="Popular conversions"') :]
    grid = grid[: grid.index("</nav>")]
    assert grid.count('href="/en/convert/') == _PAIR_COUNT


# ── Redact footer link — flag-gated only, not auth-gated ────────────────────


def test_redact_footer_link_present_when_flag_on(client, redact_enabled):
    assert 'href="/en/redact"' in _footer(client.get("/en/").text)


def test_redact_footer_link_absent_when_flag_off(client):
    assert 'href="/en/redact"' not in client.get("/en/").text


# ── nav-ai-slot removal (G6 CSP) ─────────────────────────────────────────────


def test_nav_ai_slot_ids_gone_from_homepage(client):
    r = client.get("/en/").text
    assert "nav-ai-slot" not in r


def test_nav_ai_slot_ids_gone_even_when_ai_enabled(client, redact_enabled):
    """The slot must not reappear now that the flag is on — Redact
    discoverability moved to the footer entirely, there is no nav path left."""
    r = client.get("/en/").text
    assert "nav-ai-slot" not in r


# ── mobile nav order = desktop (language switcher last, before auth) ────────


def test_mobile_nav_language_switcher_immediately_before_auth_block(client):
    r = client.get("/en/").text
    menu_start = r.index('id="nav-mobile-menu"')
    tools_pos = r.index(">Tools<", menu_start)
    switcher_pos = r.index('role="group"', menu_start)
    auth_pos = r.index('id="nav-auth-mobile"', menu_start)
    assert tools_pos < switcher_pos < auth_pos, (
        "mobile nav order must be: menu items, then language switcher, then auth"
    )
    # "immediately": no further menu link renders between switcher and auth.
    between = r[switcher_pos:auth_pos]
    assert "transition-colors py-2.5" not in between, (
        "a menu item slipped between the language switcher and the auth block"
    )


# ── quota-error upsell link (Upsell-Regeln) ──────────────────────────────────


def test_pdf_tool_upsell_link_present_when_pricing_enabled(client, pricing_enabled):
    r = client.get("/en/pdf/compress").text
    assert 'id="pdf-error-upsell"' in r
    assert 'href="/en/pricing"' in r


def test_pdf_tool_upsell_link_absent_when_pricing_disabled(client):
    r = client.get("/en/pdf/compress").text
    assert 'id="pdf-error-upsell"' not in r


@pytest.mark.parametrize("tool", ["split", "extract", "compress"])
def test_pdf_tool_upsell_link_present_on_all_three_tools(client, pricing_enabled, tool):
    """The upsell lives in the shared partial — must render on all three
    /pdf/* pages, not just compress."""
    r = client.get(f"/en/pdf/{tool}").text
    assert 'id="pdf-error-upsell"' in r


def test_convert_tool_upsell_link_present_when_pricing_enabled(client, pricing_enabled):
    r = client.get("/en/").text
    assert 'id="convert-error-upsell"' in r


def test_convert_tool_upsell_link_absent_when_pricing_disabled(client):
    r = client.get("/en/").text
    assert 'id="convert-error-upsell"' not in r
