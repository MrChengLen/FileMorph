"""Site-wide JSON-LD structured data + their CSP source-hashes.

The server emits JSON-LD inline in ``base.html``. Strict CSP (`script-src 'self'`)
forbids inline scripts, so each block's SHA-256 hash is computed at startup
time and injected into the Content-Security-Policy header. The same canonical
JSON string is rendered inline; both sides are guaranteed in sync because they
derive from the same Python literal.

The ``url`` field is filled from ``settings.app_base_url`` at app startup, not
hardcoded — that keeps a self-hoster's deployment from shipping the upstream
SaaS URL in their structured data.
"""

from __future__ import annotations

import base64
import hashlib
import json


def _compile(data: list[dict] | dict) -> tuple[str, str]:
    """Return ``(canonical_json, csp_source)``.

    ``canonical_json`` is what gets rendered inline in the template;
    ``csp_source`` (e.g. ``'sha256-abc=='``) is what lands in the CSP
    header's ``script-src`` directive. The hash is computed over the
    same bytes that get rendered.
    """
    canonical = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).digest()
    return canonical, "'sha256-" + base64.b64encode(digest).decode("ascii") + "'"


def build_site_jsonld(app_base_url: str) -> tuple[str, str]:
    """Build the homepage JSON-LD + its CSP source-hash for a given base URL.

    Called once at app startup with ``settings.app_base_url`` so the structured
    data points at the deployment's own canonical origin (e.g. a self-hoster's
    `https://files.example.com`), not the upstream SaaS URL.
    """
    base = app_base_url.rstrip("/") or "http://localhost:8000"
    data: list[dict] = [
        {
            "@context": "https://schema.org",
            "@type": "WebApplication",
            "name": "FileMorph",
            "url": base,
            "applicationCategory": "Multimedia",
            "operatingSystem": "Any",
            "offers": {"@type": "Offer", "price": "0", "priceCurrency": "EUR"},
            "description": (
                "Privacy-respecting file converter & compressor — open-source and self-hostable."
            ),
        },
        {
            "@context": "https://schema.org",
            "@type": "SoftwareApplication",
            "name": "FileMorph",
            "url": base,
            "applicationCategory": "Multimedia",
            "operatingSystem": "Linux, Windows, macOS, Docker",
            "offers": {"@type": "Offer", "price": "0", "priceCurrency": "EUR"},
            "license": "https://www.gnu.org/licenses/agpl-3.0.html",
        },
    ]
    return _compile(data)
