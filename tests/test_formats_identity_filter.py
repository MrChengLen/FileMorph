# SPDX-License-Identifier: AGPL-3.0-or-later
"""Identity-pair filter: pdf -> pdf hidden from user-facing format listings.

app/converters/pdf_pages.py registers a (pdf, pdf) pair to back the
structural /api/v1/pdf/{extract,split,compress} routes — a legitimate API
capability, but offering "PDF" as a *target* in the generic converter
dropdown or /api/v1/formats would be a silent no-op re-save.
registry.get_public_conversions() filters same-format pairs out of
user-facing listings while leaving the raw registry (and /api/v1/convert
pdf->pdf) untouched — see app/converters/registry.py for the full rationale.
"""

from __future__ import annotations

import app.converters.registry as registry


def test_formats_endpoint_hides_pdf_identity_pair(client):
    r = client.get("/api/v1/formats")
    assert r.status_code == 200
    conversions = r.json()["conversions"]
    assert "pdf" not in conversions["pdf"], (
        "pdf->pdf is a structural morph op, not a user-facing conversion "
        "target — it must not appear in /api/v1/formats"
    )
    assert "txt" in conversions["pdf"]  # a real conversion stays listed


def test_registry_itself_still_carries_the_identity_pair():
    """get_supported_conversions() is the raw, unfiltered registry — so
    /api/v1/convert pdf->pdf keeps working exactly as before the filter."""
    assert "pdf" in registry.get_supported_conversions()["pdf"]


def test_get_public_conversions_drops_identity_only_source(monkeypatch):
    """A source whose ONLY registered target is itself must be dropped
    entirely from the public listing — not left behind with an empty list."""
    monkeypatch.setattr(
        registry,
        "get_supported_conversions",
        lambda: {"pdf": ["pdf"], "jpg": ["jpg", "png"]},
    )
    result = registry.get_public_conversions()
    assert "pdf" not in result
    assert result == {"jpg": ["png"]}


def test_homepage_has_pdf_tools_hint(client):
    """The convert-tool card's hidden PDF-tools hint (shown by app.js once a
    PDF file is picked) must be present in the DOM wherever the generic
    target-format dropdown is shown — homepage only, per this sprint."""
    r = client.get("/en/")
    assert r.status_code == 200
    assert 'id="pdf-tools-hint"' in r.text


# ── /formats matrix chips: curated pairs are links, others stay spans ───────
#
# IA rework PR 2 (docs-internal/ia-navigation-konzept.md): a chip becomes a
# clickable <a> to its /convert/<src>-to-<tgt> page ONLY when PAIR_CONTENT has
# real hand-written content for it — everything else stays a plain <span>
# (honest signal, same anti-thin-content policy this module's other tests
# guard). png->jpg / jpg->bmp are both core Pillow formats with no optional
# codec dependency, so they're always present in the registry regardless of
# which optional converters (e.g. pillow-heif) are installed.


def test_curated_pair_chip_is_a_link(client):
    from app.core.convert_pairs import PAIR_CONTENT

    assert ("png", "jpg") in PAIR_CONTENT, "test assumes png->jpg is curated"
    r = client.get("/en/formats")
    assert r.status_code == 200
    assert '<a href="/en/convert/png-to-jpg"' in r.text


def test_uncurated_pair_chip_stays_a_span(client):
    from app.core.convert_pairs import PAIR_CONTENT

    assert ("jpg", "bmp") not in PAIR_CONTENT, "test assumes jpg->bmp is NOT curated"
    r = client.get("/en/formats")
    assert r.status_code == 200
    assert '<a href="/en/convert/jpg-to-bmp"' not in r.text
    assert "<span" in r.text and ">BMP<" in r.text


def test_formats_page_links_to_tools_hub(client):
    r = client.get("/en/formats")
    assert r.status_code == 200
    main = r.text[r.text.index("<main") : r.text.index("</main>")]
    assert 'href="/en/tools"' in main


def test_tools_hub_links_back_to_formats(client):
    r = client.get("/en/tools")
    assert r.status_code == 200
    main = r.text[r.text.index("<main") : r.text.index("</main>")]
    assert 'href="/en/formats"' in main
