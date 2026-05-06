# SPDX-License-Identifier: AGPL-3.0-or-later
"""NEU-D.2: pricing page surfaces concurrency + rate-limits per tier.

A hard regression-guard so the contract on `/pricing` cannot drift
out of sync with the limiter values in
``app/core/concurrency.py::_PER_TIER_CONCURRENCY``. The Pricing
page is the public claim ("10,000 calls / month, 2 concurrent");
the limiter is the enforcement; if they disagree, paying users
hit unexpected 429s.

The test renders the pricing template via ``stripe_enabled=True``
so the full feature list is shown (the Coming-Soon banner replaces
the buttons in the OFF case but the bullet lists stay either way).
"""

from __future__ import annotations

import pytest

from app.core.concurrency import _PER_TIER_CONCURRENCY
from app.core.config import settings
from app.main import app


@pytest.fixture
def pricing_html(client, monkeypatch):
    monkeypatch.setattr(settings, "pricing_page_enabled", True)
    # Force the page-builder branch that renders feature bullet lists
    # exactly as the public site shows them, regardless of whether
    # Stripe is configured in the dev env that runs the test suite.
    app.state  # access only — no mutation needed
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_placeholder")
    res = client.get("/pricing")
    assert res.status_code == 200, res.text
    return res.text


def test_pricing_explains_quota_vs_concurrency(pricing_html):
    """The page must explain that the monthly call number is a
    bucket size, not a parallelism guarantee. The exact wording
    can change; the concept must stay visible."""
    assert "concurrency" in pricing_html.lower()
    assert "429" in pricing_html or "Retry-After" in pricing_html


@pytest.mark.parametrize(
    "tier,quota_label,concurrent",
    [
        ("free", "500", _PER_TIER_CONCURRENCY["free"]),
        ("pro", "10,000", _PER_TIER_CONCURRENCY["pro"]),
        ("business", "100,000", _PER_TIER_CONCURRENCY["business"]),
    ],
)
def test_each_tier_lists_quota_concurrent_and_rate(pricing_html, tier, quota_label, concurrent):
    """Every paid (and free-API) tier prints the monthly quota
    *and* the concurrent slot count. If the limiter changes the
    per-tier number, this test fails until the page is updated."""
    assert quota_label in pricing_html, f"{tier}: missing {quota_label} in pricing HTML"
    # Concurrent slot count appears on the same line as the quota.
    needle = f"{concurrent} concurrent"
    assert needle in pricing_html, f"{tier}: missing '{needle}' in pricing HTML"
