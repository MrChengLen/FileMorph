# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pricing-overhaul 2026-05-25: centralisation + deployment-agnostic guards.

Pins the properties that make the pricing surface safe for self-hosters and
free of drift:

1. When display prices are configured (filemorph.io env), /pricing renders them.
2. Self-host default (no price env) shows NO SaaS price — a self-hoster never
   inherits filemorph.io's amounts; the paid tiers fall back to "Contact us".
3. The quota numbers on the page come from ``app/core/quotas.py`` (no drift
   between the advertised limit and the enforced one).
4. Stripe redirect URLs are built from ``app_base_url``, never hardcoded
   ``filemorph.io``.
5. Honesty: the commercial surface makes no false certification claims.
"""

from __future__ import annotations

from app.core.config import settings


def _enable_pricing(monkeypatch):
    monkeypatch.setattr(settings, "pricing_page_enabled", True)


def test_configured_prices_render(client, monkeypatch):
    _enable_pricing(monkeypatch)
    monkeypatch.setattr(settings, "price_pro_display", "3")
    monkeypatch.setattr(settings, "price_business_display", "9")
    body = client.get("/en/pricing").text
    assert "€3" in body
    assert "€9" in body


def test_self_host_default_hides_saas_prices(client, monkeypatch):
    """Empty price env (Community default) → paid tiers render without an
    amount; no filemorph.io price leaks into a self-hoster's page."""
    _enable_pricing(monkeypatch)
    monkeypatch.setattr(settings, "price_pro_display", "")
    monkeypatch.setattr(settings, "price_business_display", "")
    body = client.get("/en/pricing").text
    assert "€3" not in body
    assert "€9" not in body
    assert "Contact us" in body  # placeholder for the unconfigured paid tiers


def test_quota_numbers_come_from_quotas(client, monkeypatch):
    """No drift: the API-call number shown for Pro is the QUOTAS value,
    locale-formatted (EN thousands grouping)."""
    from app.core.quotas import get_quota

    _enable_pricing(monkeypatch)
    body = client.get("/en/pricing").text
    expected = f"{get_quota('pro').api_calls_per_month:,}"
    assert expected in body


def test_pricing_shows_kleinunternehmer_vat_note(client, monkeypatch):
    _enable_pricing(monkeypatch)
    assert "§19 UStG" in client.get("/en/pricing").text


def test_billing_redirects_use_app_base_url(monkeypatch):
    """Stripe redirect URLs are built on the deployment's own origin, never on
    a hardcoded filemorph.io. Uses ``_app_url`` from billing.py (the helper
    landed in PR #41 covers the same case my own ``_redirect_base`` did)."""
    from app.api.routes.billing import _app_url

    monkeypatch.setattr(settings, "app_base_url", "https://files.example.com")
    url = _app_url("/dashboard")
    assert url == "https://files.example.com/dashboard"
    assert "filemorph.io" not in url


def test_commercial_pages_make_no_false_certification_claims(client, monkeypatch):
    """We have no external audit/certification yet — the page must not claim one."""
    _enable_pricing(monkeypatch)
    for url in ("/en/pricing", "/en/enterprise"):
        body = client.get(url).text
        assert "ISO 27001 certified" not in body
        assert "SOC 2" not in body
