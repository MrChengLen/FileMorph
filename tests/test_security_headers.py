# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regression guards for the security-headers middleware in app/main.py.

These headers are first-pass-fail items in any procurement-side scanner
(Mozilla Observatory, NIST, securityheaders.com). A doc-claim drift
between security-overview.md and the middleware would be a credibility
problem on the first Behörden-IT review — pin the truth here.
"""

from __future__ import annotations


def test_response_carries_baseline_security_headers(client):
    r = client.get("/")
    assert r.status_code == 200
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"
    assert r.headers.get("referrer-policy") == "strict-origin-when-cross-origin"


def test_csp_default_src_self(client):
    r = client.get("/")
    csp = r.headers.get("content-security-policy", "")
    assert "default-src 'self'" in csp
    assert "frame-ancestors" in csp or "X-Frame-Options" in r.headers, (
        "framing must be denied via CSP frame-ancestors or X-Frame-Options"
    )


def test_permissions_policy_disables_camera_mic_geolocation(client):
    """A converter site should never need camera, mic, or geolocation;
    locking them down at the policy layer protects against a future XSS
    or 3rd-party inclusion popping a permission prompt."""
    r = client.get("/")
    pp = r.headers.get("permissions-policy", "")
    assert "camera=()" in pp
    assert "microphone=()" in pp
    assert "geolocation=()" in pp


def test_hsts_present_only_on_https(client):
    """HSTS is meaningful over HTTPS only — TestClient defaults to http,
    so HSTS must be absent. A self-hoster behind Caddy/nginx with
    ``X-Forwarded-Proto: https`` gets the header on real traffic."""
    r = client.get("/")
    assert r.url.scheme == "http"
    assert "strict-transport-security" not in {k.lower() for k in r.headers.keys()}


def test_hsts_present_when_request_scheme_is_https(client):
    """When the request reports https, HSTS must be set with ≥1 year
    max-age and includeSubDomains. TestClient routes a direct
    https-prefixed URL verbatim — uvicorn's ProxyHeadersMiddleware
    handles the X-Forwarded-Proto promotion in real deployments."""
    r = client.get("https://testserver/")
    hsts = r.headers.get("strict-transport-security", "")
    assert "max-age=31536000" in hsts
    assert "includeSubDomains" in hsts
