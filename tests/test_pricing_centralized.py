# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pricing-overhaul 2026-05-25: centralisation + deployment-agnostic guards.

Pins the properties that make the pricing surface safe for self-hosters and
free of drift:

1. When display prices are configured and plans can be booked (Stripe), /pricing
   renders them.
2. Self-host default (no price env) shows NO SaaS price — a self-hoster never
   inherits filemorph.io's amounts; the paid tiers fall back to "Contact us".
3. The quota numbers on the page come from ``app/core/quotas.py`` (no drift
   between the advertised limit and the enforced one), in both variants.
3a. Without Stripe the page is the free variant: no plan prices at all, even
    where display prices are configured (filemorph.io, where paid plans are shelved).
4. Stripe redirect URLs are built from ``app_base_url``, never hardcoded
   ``filemorph.io``.
5. Honesty: the commercial surface makes no false certification claims.
"""

from __future__ import annotations

import re

import pytest

from app.core.config import settings
from app.core.templates import templates


def _enable_pricing(monkeypatch, *, stripe=True):
    """/pricing on; with ``stripe`` plans can be booked, so the plan cards render
    (the route reads ``settings``, the template the Jinja global)."""
    monkeypatch.setattr(settings, "pricing_page_enabled", True)
    stripe_key = "sk_test_dummy" if stripe else ""  # gitleaks:allow
    monkeypatch.setattr(settings, "stripe_secret_key", stripe_key)
    monkeypatch.setitem(templates.env.globals, "stripe_enabled", stripe)


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


def test_free_pricing_shows_no_plan_prices_even_when_configured(client, monkeypatch):
    """No Stripe → nothing can be booked → no amount and no VAT note, even with
    the display prices still set in the deployment env."""
    _enable_pricing(monkeypatch, stripe=False)
    monkeypatch.setattr(settings, "price_pro_display", "3")
    monkeypatch.setattr(settings, "price_business_display", "9")
    body = client.get("/en/pricing").text
    for absent in ("€3", "€9", "Contact us", "§19 UStG", 'id="pro-btn"'):
        assert absent not in body, absent
    assert "€0" in body


def test_free_pricing_quota_numbers_come_from_quotas(client, monkeypatch):
    """The free variant's numbers are the same display values the plan cards
    use (app/core/pricing.py, read from quotas.py)."""
    from app.core.pricing import anonymous_plan, saas_plans

    _enable_pricing(monkeypatch, stripe=False)
    body = " ".join(re.sub(r"<[^>]+>", " ", client.get("/en/pricing").text).split())
    anon, free = anonymous_plan("en"), saas_plans("en")[0]
    assert f"Without an account: up to {anon.max_file_size_mb} MB per file" in body
    assert f"With a free account: up to {free.max_file_size_mb} MB per file" in body
    assert f"Batch upload: {free.max_files_per_batch} files per request" in body
    assert f"{free.api_calls_display} calls / month , {free.concurrency} concurrent" in body
    assert f"takes files up to {free.max_file_size_mb} MB." in body


def test_enterprise_vat_note_only_with_a_price(client, monkeypatch):
    """/enterprise: with no Compliance display price every tier reads "on
    request" and the per-year VAT note stays away; one configured price brings
    the note back."""
    monkeypatch.setattr(settings, "pricing_page_enabled", True)
    for tier in ("starter", "standard", "enterprise"):
        monkeypatch.setattr(settings, f"price_compliance_{tier}_display", "")
    body = client.get("/en/enterprise").text
    assert body.count(">on request</td>") == 3
    assert "Prices per year" not in body
    monkeypatch.setattr(settings, "price_compliance_starter_display", "990")
    body = client.get("/en/enterprise").text
    assert "€ 990" in body and "Prices per year" in body


def test_billing_redirects_use_app_base_url(monkeypatch):
    """Stripe redirect URLs are built on the deployment's own origin, never on
    a hardcoded filemorph.io. Uses ``_app_url`` from billing.py (the helper
    landed in PR #41 covers the same case my own ``_redirect_base`` did)."""
    from app.api.routes.billing import _app_url

    monkeypatch.setattr(settings, "app_base_url", "https://files.example.com")
    url = _app_url("/dashboard")
    assert url == "https://files.example.com/dashboard"
    assert "filemorph.io" not in url


@pytest.mark.parametrize("stripe", [False, True], ids=["free", "plans"])
def test_commercial_pages_make_no_false_certification_claims(client, monkeypatch, stripe):
    """We have no external audit/certification yet — the page must not claim one."""
    _enable_pricing(monkeypatch, stripe=stripe)
    for url in ("/en/pricing", "/en/enterprise"):
        body = client.get(url).text
        assert "ISO 27001 certified" not in body
        assert "SOC 2" not in body


def test_terms_page_has_no_hardcoded_euro_price(client):
    """Terms §8 must point to /pricing for the current amount, never hardcode
    a euro price that can drift from app/core/pricing.py / settings (it used
    to quote "Pro €7/month, Business €19/month" — already stale)."""
    for url in ("/de/terms", "/en/terms"):
        body = client.get(url).text
        # "€7" (en) as well as "7 €" (de)
        assert not re.search(r"€\s?\d|\d\s?€", body), f"{url} hardcodes a euro price in Terms"
