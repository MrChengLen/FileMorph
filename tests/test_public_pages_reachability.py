# SPDX-License-Identifier: AGPL-3.0-or-later
"""H5 — Public legal/security page reachability regression guard.

The /enterprise + /privacy pages make compliance promises that depend on
adjacent legal pages being reachable. If a route registration goes stale
or a template gets renamed, the public claim ("see /privacy for details")
silently breaks. These tests assert each commitment surface is live.

Why presence-tests rather than content-snapshots:
  Snapshot tests would force every typo-fix to update a fixture. Instead
  we assert the route returns 200 and contains the canonical heading,
  which is robust to copy edits but catches deletion/rename regressions.

Out of scope:
  - Pricing-specific page tests (already in tests/test_pricing_limits_visible.py)
  - SEO-foundation tests (sitemap, robots, JSON-LD — already in tests/test_seo_foundation.py)
"""

from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    "path,expected_marker",
    [
        # /privacy and /terms are now i18n-wrapped (PR-i18n-2c) — DE is the
        # legal-authoritative version with EN footer. Default route renders DE
        # so we hit /en/ for the EN marker. /impressum stays raw German (TMG-
        # bound legal text); the word "Impressum" appears in both locales.
        # /security was wrapped earlier and uses the same /en/ rule.
        ("/en/privacy", "Privacy Policy"),
        ("/en/terms", "Terms of Use"),
        ("/impressum", "Impressum"),
        ("/en/security", "Reporting a vulnerability"),
    ],
)
def test_public_legal_page_reachable(client, path: str, expected_marker: str) -> None:
    """Each compliance/legal page returns 200 and contains its canonical marker."""
    res = client.get(path)
    assert res.status_code == 200, f"{path} returned {res.status_code}: {res.text[:200]}"
    assert expected_marker in res.text, (
        f"{path} reachable but missing canonical marker '{expected_marker}'"
    )


def test_security_txt_well_known_returns_required_rfc9116_fields(client) -> None:
    """RFC 9116 mandates Contact + Expires; we also pin Canonical + Policy
    so the file matches what's referenced from /security."""
    res = client.get("/.well-known/security.txt")
    assert res.status_code == 200, res.text
    body = res.text
    # RFC 9116 § 2.5 — required fields
    assert "Contact:" in body, "security.txt missing required Contact field"
    assert "Expires:" in body, "security.txt missing required Expires field"
    # Pinned by our /security page link consistency (`runbooks` reference)
    assert "Canonical:" in body or "Policy:" in body, (
        "security.txt should reference at least one of Canonical/Policy"
    )
    # Disclosure policy /security must be linkable from security.txt
    assert "/security" in body or "Policy:" in body


def test_security_txt_contact_is_email_or_https(client) -> None:
    """Contact: must be a mailto: or https: URI per RFC 9116 § 2.5.3.
    Plain text addresses are not allowed."""
    res = client.get("/.well-known/security.txt")
    assert res.status_code == 200
    contact_lines = [line for line in res.text.splitlines() if line.lower().startswith("contact:")]
    assert contact_lines, "security.txt has no Contact field"
    for line in contact_lines:
        value = line.split(":", 1)[1].strip()
        assert value.startswith(("mailto:", "https://")), (
            f"Contact field value must start with mailto: or https://: {value!r}"
        )


def test_impressum_credits_responsible_party(client) -> None:
    """§ 5 DDG (formerly §5 TMG) requires a named natural person at a real
    address. Pin a presence-check so a future template refactor can't
    accidentally remove the Verantwortlicher block."""
    res = client.get("/impressum")
    assert res.status_code == 200
    text = res.text
    # Don't pin a specific name (the operator may change), but pin the
    # legal-anchor sections that must always be present.
    assert "Verantwortlich" in text, "Impressum missing Verantwortlich section (§ 5 DDG)"
    assert "Kontakt" in text, "Impressum missing Kontakt section (§ 5 DDG)"
    assert "§ 19 UStG" in text, "Impressum missing Kleinunternehmer status (§ 19 UStG)"
    assert "Steuernummer" not in text, (
        "Impressum should not display the raw Steuernummer (privacy / "
        "abuse risk per IT-Recht-Kanzlei / PRO-DSGVO recommendation)"
    )


def test_privacy_policy_mentions_gdpr_erasure_right(client) -> None:
    """The privacy page is the user's anchor for Art. 17 GDPR (right to
    erasure). If a copy edit removes the term, account-deletion users
    lose their legal anchor."""
    res = client.get("/privacy")
    assert res.status_code == 200
    text_lower = res.text.lower()
    # German or English variant — both are valid
    assert "art. 17" in text_lower or "erasure" in text_lower or "löschung" in text_lower, (
        "Privacy policy should reference Art. 17 GDPR / right to erasure"
    )


def test_enterprise_de_renders_authoritative_german(client, monkeypatch) -> None:
    """PR-i18n-2c: /de/enterprise carries the legal-authoritative DE text
    and must NOT show the EN-only disclaimer header (which calls itself
    out as a non-binding translation).

    M6 hardening: pin both ``<html lang="de"`` (locale resolution) AND a
    DSGVO-anchored legal citation (so a copy edit "Behörden"→"Verwaltung"
    can't silently slip the test). Either drift is independently a
    regression — the html-lang attribute proves the localisation pipeline
    routed the request, the DSGVO citation proves the DE template body
    actually rendered.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "pricing_page_enabled", True)
    res = client.get("/de/enterprise")
    assert res.status_code == 200
    text = res.text
    # Locale resolution: i18n pipeline routed the request to DE.
    assert '<html lang="de"' in text, (
        "/de/enterprise served without lang=de — locale resolution drift"
    )
    # Legal anchor: DSGVO is the German label for GDPR, untranslatable in
    # an EN render. Pinned alongside "Behörden" so either one carrying
    # the assertion catches a copy-edit regression.
    assert "DSGVO" in text or "Behörden" in text, (
        "/de/enterprise missing DSGVO citation / 'Behörden' — DE template body not rendered"
    )
    # Disclaimer is gated to locale=='en' — DE must not see it
    assert "authoritative legal text" not in text, (
        "/de/enterprise should not render the EN disclaimer (DE is authoritative)"
    )


def test_enterprise_en_renders_english_with_disclaimer(client, monkeypatch) -> None:
    """PR-i18n-2c: /en/enterprise carries the EN translation plus the
    disclaimer that points to the DE original as legally binding."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "pricing_page_enabled", True)
    res = client.get("/en/enterprise")
    assert res.status_code == 200
    text = res.text
    assert "authoritative legal text" in text, (
        "/en/enterprise must render the EN-only disclaimer pointing to DE original"
    )
    # 'Behörden' would only appear if a string slipped through the EN-twin
    assert "Behörden" not in text, (
        "/en/enterprise still has raw German term 'Behörden' — translation gap"
    )


def test_impressum_en_has_preamble_then_german(client) -> None:
    """PR-i18n-2c: /en/impressum prepends an EN preamble explaining why
    the legal body below stays in German (TMG § 5 Pflichtangaben).

    M7 hardening: pin the *order* — preamble before the German body.
    A template inversion (DE block above the EN explanation) would still
    pass a presence-only check but break the document's purpose
    (English speakers must see the preamble first to understand why the
    rest is in German).
    """
    res = client.get("/en/impressum")
    assert res.status_code == 200
    text = res.text
    preamble_marker = "as required by German law"
    body_marker = "Verantwortlich"
    assert preamble_marker in text, "/en/impressum missing EN preamble explaining DE legal text"
    assert body_marker in text, "/en/impressum missing the raw DE TMG section"
    # Order pin: EN preamble must precede the DE body.
    assert text.index(preamble_marker) < text.index(body_marker), (
        "/en/impressum has DE legal body before the EN preamble — template inverted?"
    )
