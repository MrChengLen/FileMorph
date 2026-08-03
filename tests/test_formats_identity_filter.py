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
