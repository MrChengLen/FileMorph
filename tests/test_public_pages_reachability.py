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
        ("/privacy", "Privacy Policy"),
        ("/terms", "Terms of Use"),
        ("/impressum", "Impressum"),
        ("/security", "Reporting a vulnerability"),
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
    """§ 5 TMG requires a named natural person at a real address. Pin
    a presence-check so a future template refactor can't accidentally
    remove the Verantwortlicher block."""
    res = client.get("/impressum")
    assert res.status_code == 200
    text = res.text
    # Don't pin a specific name (the operator may change), but pin the
    # legal-anchor sections that must always be present.
    assert "Verantwortlich" in text, "Impressum missing Verantwortlich section (§ 5 TMG)"
    assert "Kontakt" in text, "Impressum missing Kontakt section (§ 5 TMG)"


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
