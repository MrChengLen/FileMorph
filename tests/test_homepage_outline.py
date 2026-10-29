# SPDX-License-Identifier: AGPL-3.0-or-later
"""Homepage heading outline (WCAG 1.3.1).

Moved out of the old tests/test_homepage_more_tools.py (IA rework PR 3) when
the "More tools" box was replaced by the quick-action chips — these guards
are about the page's heading hierarchy, not about any one section:
  - The Plans teaser (with Stripe) or the Free teaser (without), and the
    For-Developers block, use a real <h2> instead of a decorative eyebrow <p>.
  - The number of <h2>s is pinned, so a future edit that silently drops or
    duplicates a heading trips a test and gets updated deliberately.
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


@pytest.fixture
def stripe_enabled(monkeypatch):
    """Plans can be booked: the homepage shows the Plans teaser instead of
    the free one."""
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")  # gitleaks:allow
    monkeypatch.setitem(templates.env.globals, "stripe_enabled", True)


def test_plans_block_uses_h2(client, pricing_enabled, stripe_enabled):
    html = client.get("/en/").text
    assert (
        '<h2 class="text-xs font-semibold uppercase tracking-wider text-ink-faint">'
        "Plans</h2>" in html
    )


@pytest.fixture
def stripe_disabled(monkeypatch):
    """No plan can be booked, whatever the suite's env says."""
    monkeypatch.setattr(settings, "stripe_secret_key", "")
    monkeypatch.setitem(templates.env.globals, "stripe_enabled", False)


def test_free_block_uses_h2(client, pricing_enabled, stripe_disabled):
    """Without Stripe no plan can be booked, so the free teaser takes the
    Plans block's place — with the same kind of heading."""
    html = client.get("/en/").text
    assert (
        '<h2 class="text-xs font-semibold uppercase tracking-wider text-ink-muted">'
        "Free</h2>" in html
    )
    assert ">Plans</h2>" not in html


def test_for_developers_block_uses_h2(client):
    html = client.get("/en/").text
    assert (
        '<h2 class="text-xs font-semibold uppercase tracking-wider text-ink-faint">'
        "For Developers</h2>" in html
    )


def test_homepage_h2_count_default(client):
    """Self-hosted, For Developers, Comparison, FAQ = 4 h2s with pricing/AI
    both off (the "More tools" section is gone; Plans is conditional)."""
    html = client.get("/en/").text
    assert len(re.findall(r"<h2[ >]", html)) == 4, (
        "homepage h2 outline changed — update this guard deliberately"
    )


def test_homepage_h2_count_with_pricing_enabled(client, pricing_enabled, stripe_disabled):
    """Same 4, plus the Free teaser's h2 = 5."""
    html = client.get("/en/").text
    assert len(re.findall(r"<h2[ >]", html)) == 5, (
        "homepage h2 outline changed — update this guard deliberately"
    )


def test_homepage_h2_count_with_pricing_and_stripe(client, pricing_enabled, stripe_enabled):
    """Same 4, plus the Plans teaser's h2 = 5."""
    html = client.get("/en/").text
    assert len(re.findall(r"<h2[ >]", html)) == 5, (
        "homepage h2 outline changed — update this guard deliberately"
    )


def test_homepage_h2_count_unaffected_by_redact_flag(client, redact_enabled):
    """Redact is never surfaced on the homepage (no gated idle chip) —
    enabling the flag must not add or remove an h2."""
    html = client.get("/en/").text
    assert len(re.findall(r"<h2[ >]", html)) == 4, (
        "homepage h2 outline changed — update this guard deliberately"
    )
