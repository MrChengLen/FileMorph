"""Site-wide JSON-LD structured data + their CSP source-hashes.

The server emits JSON-LD inline in ``base.html``. Strict CSP (`script-src 'self'`)
forbids inline scripts, so each block's SHA-256 hash is computed at import
time and injected into the Content-Security-Policy header. The same canonical
JSON string is rendered inline; both sides are guaranteed in sync because they
derive from the same Python literal.

If you change ``SITE_JSONLD_DATA``, the hash recomputes automatically — no
manual CSP edit needed.
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


SITE_JSONLD_DATA: list[dict] = [
    {
        "@context": "https://schema.org",
        "@type": "WebApplication",
        "name": "FileMorph",
        "url": "https://filemorph.io",
        "applicationCategory": "Multimedia",
        "operatingSystem": "Any",
        "offers": {"@type": "Offer", "price": "0", "priceCurrency": "EUR"},
        "description": (
            "Privacy-first file converter & compressor — EU-hosted, AGPLv3, self-hostable."
        ),
    },
    {
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        "name": "FileMorph",
        "url": "https://filemorph.io",
        "applicationCategory": "Multimedia",
        "operatingSystem": "Linux, Windows, macOS, Docker",
        "offers": {"@type": "Offer", "price": "0", "priceCurrency": "EUR"},
        "license": "https://www.gnu.org/licenses/agpl-3.0.html",
    },
]

SITE_JSONLD, SITE_JSONLD_CSP_SOURCE = _compile(SITE_JSONLD_DATA)
