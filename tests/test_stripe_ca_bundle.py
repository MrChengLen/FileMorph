# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Stripe SDK verifies TLS against certifi's CA bundle, and that bundle
does not trust the emSign ECC Root CA - G3 (GHSA-6q48-6c7w-9gw2).

The SDK ships a CA file of its own (``stripe/data/ca-certificates.crt``) that
no dependency audit covers and that still holds this root.
``app/core/billing.py`` points the SDK at certifi's bundle instead, which
pip-audit watches and requirements.txt keeps past the advisory. These tests pin
what the SDK hands to ``requests`` on a real call, not just the setting, so an
SDK update that stops reading it turns them red.
"""

from __future__ import annotations

import ssl

import certifi
import requests
import stripe

import app.core.billing  # noqa: F401 — the import points the SDK at certifi

EMSIGN_G3 = "emSign ECC Root CA - G3"


class _Response:
    """Just enough of a ``requests.Response`` for the SDK to parse."""

    status_code = 200
    headers: dict[str, str] = {}
    content = b'{"id": "cus_test", "object": "customer"}'


def _trusted_common_names(cafile: str) -> set[str]:
    """Common names of the CA certificates a TLS client loads from ``cafile``."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.load_verify_locations(cafile=cafile)
    return {
        value
        for cert in ctx.get_ca_certs()
        for rdn in cert["subject"]
        for key, value in rdn
        if key == "commonName"
    }


def test_stripe_calls_verify_against_certifi(monkeypatch):
    seen = {}

    def fake_request(self, method, url, **kwargs):
        seen["url"] = url
        seen["verify"] = kwargs.get("verify")
        return _Response()

    monkeypatch.setattr(requests.Session, "request", fake_request)

    customer = stripe.Customer.retrieve("cus_test", api_key="sk_test_dummy")

    assert customer.id == "cus_test"
    assert seen["url"].startswith("https://api.stripe.com/")
    assert seen["verify"] == certifi.where()


def test_stripe_bundle_does_not_trust_emsign_g3():
    names = _trusted_common_names(stripe.ca_bundle_path)
    # A root every bundle has, so an empty or unreadable file cannot pass.
    assert "ISRG Root X1" in names
    assert EMSIGN_G3 not in names
