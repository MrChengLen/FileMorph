# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stripe webhook — signature validation & misconfiguration guards.

These tests cover the security-critical path: we must never trust an
unverified payload, and we must refuse to run if the secret is missing.
Actual tier-sync logic (`_sync_subscription`) is exercised via live
Stripe test events in staging — covering it here would require a full
DB fixture that the Community Edition test suite deliberately avoids.
"""

from app.core.config import settings


def test_webhook_rejects_when_secret_not_configured(client, monkeypatch):
    """If STRIPE_WEBHOOK_SECRET is empty, the endpoint must return 503."""
    monkeypatch.setattr(settings, "stripe_webhook_secret", "")
    res = client.post(
        "/api/v1/billing/webhook",
        content=b'{"type":"customer.subscription.created"}',
        headers={"stripe-signature": "t=0,v1=deadbeef"},
    )
    assert res.status_code == 503
    assert "not configured" in res.json()["detail"].lower()


def test_webhook_rejects_missing_signature(client, monkeypatch):
    """A request without stripe-signature header must be rejected as invalid."""
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test_dummy")
    res = client.post(
        "/api/v1/billing/webhook",
        content=b'{"type":"customer.subscription.created"}',
    )
    assert res.status_code == 400
    assert "signature" in res.json()["detail"].lower()


def test_webhook_rejects_invalid_signature(client, monkeypatch):
    """A forged signature must be rejected — no tier change can leak through."""
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test_dummy")
    res = client.post(
        "/api/v1/billing/webhook",
        content=b'{"type":"customer.subscription.created"}',
        headers={
            "stripe-signature": "t=0,v1=0000000000000000000000000000000000000000000000000000000000000000"
        },
    )
    assert res.status_code == 400
    assert "signature" in res.json()["detail"].lower()
