# SPDX-License-Identifier: AGPL-3.0-or-later
"""Homepage "More tools" section + Plans/Developers heading fix — IA rework
PR 3 (docs-internal/ia-navigation-konzept.md).

Guards:
  - The old gated Redact teaser and the ungated PDF-tools teaser are merged
    into one section (single h2 "More tools" / "Weitere Tools"), closed by a
    link to the /tools hub. Redact stays gated on ai_operations_enabled only
    — same rule as the footer's Tools group and the /tools hub's Redact card
    (tests/test_footer_nav_structure.py, tests/test_tools_hub_page.py) — so
    a self-host / inert build (where /redact 404s) never links it.
  - WCAG 1.3.1: the Plans and For-Developers blocks now use a real <h2>
    instead of a decorative eyebrow <p>, with the exact same classes (visual
    no-op, no copy change).
"""

from __future__ import annotations

import re

import pytest

from app.core.config import settings
from app.core.templates import templates


@pytest.fixture
def pricing_enabled(monkeypatch):
    """Mirrors tests/test_footer_nav_structure.py's fixture of the same
    name — flips both the runtime setting and the Jinja global via
    monkeypatch so both revert automatically regardless of test order."""
    monkeypatch.setattr(settings, "pricing_page_enabled", True)
    monkeypatch.setitem(templates.env.globals, "pricing_enabled", True)


def _main(html: str) -> str:
    """Slice the page's <main> block — asserts must not pass just because
    base.html's navbar/footer links the same URL."""
    return html[html.index("<main") : html.index("</main>")]


def _more_tools_section(html: str) -> str:
    """Slice the "More tools" <section> itself — link asserts must not pass
    just because the footer's Tools group links the same URLs. Anchored on
    the section's own (locale-agnostic) class attribute rather than its
    translated heading text, so this works on /de/ too."""
    start = html.index('<section class="border border-gray-800 rounded-xl px-5 py-4 space-y-2">')
    end = html.index("</section>", start)
    section = html[start:end]
    assert "/pdf/split" in section, "anchor matched the wrong section"
    return section


# ── section presence + heading ───────────────────────────────────────────


def test_more_tools_section_renders_with_h2(client):
    main = _main(client.get("/en/").text)
    assert '<h2 class="text-base font-semibold text-white">More tools</h2>' in main


def test_more_tools_section_localized_on_de(client):
    main = _main(client.get("/de/").text)
    assert '<h2 class="text-base font-semibold text-white">Weitere Tools</h2>' in main


# ── links inside the section ─────────────────────────────────────────────


def test_more_tools_section_links_pdf_tools_and_hub(client):
    section = _more_tools_section(client.get("/en/").text)
    for path in ("/en/pdf/split", "/en/pdf/extract", "/en/pdf/compress", "/en/tools"):
        assert f'href="{path}"' in section, f"More-tools section missing {path}"


def test_more_tools_section_localises_links_on_de(client):
    section = _more_tools_section(client.get("/de/").text)
    for path in ("/de/pdf/split", "/de/pdf/extract", "/de/pdf/compress", "/de/tools"):
        assert f'href="{path}"' in section, f"More-tools section missing {path}"


# ── Redact tile — flag-gated only ────────────────────────────────────────


def test_more_tools_section_omits_redact_when_flag_off(client):
    section = _more_tools_section(client.get("/en/").text)
    assert 'href="/en/redact"' not in section


def test_more_tools_section_includes_redact_when_flag_on(client, redact_enabled):
    section = _more_tools_section(client.get("/en/").text)
    assert 'href="/en/redact"' in section


# ── deployment-agnostic ───────────────────────────────────────────────────


def test_more_tools_section_deployment_agnostic(client):
    """Scoped to the new section, not the whole page — the pre-existing "For
    Developers" curl example legitimately hardcodes filemorph.io."""
    section = _more_tools_section(client.get("/en/").text)
    assert "filemorph.io" not in section


# ── heading hierarchy fix (WCAG 1.3.1): Plans + For Developers ───────────


def test_plans_block_uses_h2(client, pricing_enabled):
    html = client.get("/en/").text
    assert (
        '<h2 class="text-xs font-semibold uppercase tracking-wider text-gray-500">'
        "Plans</h2>" in html
    )


def test_for_developers_block_uses_h2(client):
    html = client.get("/en/").text
    assert (
        '<h2 class="text-xs font-semibold uppercase tracking-wider text-gray-500">'
        "For Developers</h2>" in html
    )


def test_homepage_h2_count_default(client):
    """Self-hosted, More tools, For Developers, Comparison, FAQ = 5 h2s with
    pricing/AI both off. A future edit that silently drops or duplicates a
    heading trips this guard."""
    html = client.get("/en/").text
    assert len(re.findall(r"<h2[ >]", html)) == 5, (
        "homepage h2 outline changed — update this guard deliberately"
    )


def test_homepage_h2_count_with_pricing_enabled(client, pricing_enabled):
    """Same 5, plus the Plans block's new h2 = 6."""
    html = client.get("/en/").text
    assert len(re.findall(r"<h2[ >]", html)) == 6, (
        "homepage h2 outline changed — update this guard deliberately"
    )


def test_homepage_h2_count_unaffected_by_redact_flag(client, redact_enabled):
    """Redact is a tile inside the existing More-tools section, not its own
    heading — enabling the flag must not add an h2."""
    html = client.get("/en/").text
    assert len(re.findall(r"<h2[ >]", html)) == 5, (
        "homepage h2 outline changed — update this guard deliberately"
    )
