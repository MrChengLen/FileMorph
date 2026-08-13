# SPDX-License-Identifier: AGPL-3.0-or-later
"""/redact page + discovery-surface gating (CP6).

The page route 404-gates on ``settings.ai_operations_enabled`` (runtime); the
template links/sections gate on the Jinja global of the same name (set once at
import). Tests patch BOTH so the enabled and inert states are exercised. Inert is
the default (no env var), so the disabled-state tests need no fixture.
"""


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


def test_redact_footer_link_present_when_enabled_no_nav_slot(client, redact_enabled):
    """IA-rework PR 1: the client-side-hydrated nav slot (auth.js's
    _renderAiNavLink, eligible-user-only) is gone — every nav/footer link
    must be server-rendered in the raw HTML (G6 CSP). Redact discoverability
    now lives in the footer's Tools group, gated only by the flag, so it
    renders regardless of auth state (there is no auth-conditional branch
    left in the server-rendered markup at all)."""
    r = client.get("/en/redact")
    assert 'id="nav-ai-slot"' not in r.text
    assert 'id="nav-ai-slot-mobile"' not in r.text
    footer = r.text[r.text.index("<footer") :]
    assert 'href="/en/redact"' in footer  # footer Tools-group link


# ── discovery surfaces gated together ──────────────────────────────────────


def test_footer_and_seo_surfaces_present_when_enabled(client, redact_enabled):
    assert "/redact" in client.get("/en/").text  # footer link + homepage teaser
    assert "/redact" in client.get("/sitemap.xml").text
    assert "/redact" in client.get("/llms.txt").text


def test_no_redact_surfaces_when_disabled(client):
    assert "/redact" not in client.get("/en/").text
    assert "/redact" not in client.get("/sitemap.xml").text
    assert "/redact" not in client.get("/llms.txt").text
