# SPDX-License-Identifier: AGPL-3.0-or-later
"""/redact page + discovery-surface gating (CP6).

The page route 404-gates on ``settings.ai_operations_enabled`` (runtime); the
template links/sections gate on the Jinja global of the same name (set once at
import). Tests patch BOTH so the enabled and inert states are exercised. Inert is
the default (no env var), so the disabled-state tests need no fixture.
"""

import pytest

from app.core.config import settings
from app.core.templates import templates


@pytest.fixture
def redact_enabled():
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


# ── page route gating ──────────────────────────────────────────────────────


def test_redact_404_when_disabled(client):
    # Default build (AI off): the page 404s on all three locale mounts.
    for path in ("/redact", "/de/redact", "/en/redact"):
        assert client.get(path).status_code == 404, path


def test_redact_renders_when_enabled(client, redact_enabled):
    for path in ("/redact", "/de/redact", "/en/redact"):
        r = client.get(path)
        assert r.status_code == 200, path
        assert 'id="redact-tool"' in r.text


# ── honesty + no margin leak ───────────────────────────────────────────────


def test_redact_states_its_limits(client, redact_enabled):
    blob = client.get("/en/redact").text.lower()
    assert "anonymization" in blob  # the persistent "no guarantee" notice
    assert "names" in blob  # honest "does not detect names/addresses"


def test_redact_no_cost_structure_leak(client, redact_enabled):
    blob = client.get("/en/redact").text.lower()
    for tok in ("haiku", "sonnet", "gpt-", "bedrock", "vertex", "presidio", "€"):
        assert tok not in blob, f"margin/model leak on /redact: {tok!r}"


def test_redact_nav_slot_present_when_enabled(client, redact_enabled):
    # The eligible-only nav link is hydrated client-side into this slot.
    assert 'id="nav-ai-slot"' in client.get("/en/redact").text


# ── discovery surfaces gated together ──────────────────────────────────────


def test_footer_and_seo_surfaces_present_when_enabled(client, redact_enabled):
    assert "/redact" in client.get("/en/").text  # footer link + homepage teaser
    assert "/redact" in client.get("/sitemap.xml").text
    assert "/redact" in client.get("/llms.txt").text


def test_no_redact_surfaces_when_disabled(client):
    assert "/redact" not in client.get("/en/").text
    assert "/redact" not in client.get("/sitemap.xml").text
    assert "/redact" not in client.get("/llms.txt").text
