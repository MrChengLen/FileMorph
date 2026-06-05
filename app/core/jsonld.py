# SPDX-License-Identifier: AGPL-3.0-or-later
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

from app.core.config import settings


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


# Canonical GitHub repo — the entity's `sameAs` anchor. Hardcoding the
# upstream repo here is intentional and *not* a deployment-agnosticism
# breach: a self-hoster's fork is still the same software project, and the
# Organization/SoftwareApplication this describes (FileMorph the OSS product)
# lives at this one URL regardless of where a copy is deployed. Only the
# `url` field (the running deployment's origin) is parameterised.
GITHUB_URL = "https://github.com/MrChengLen/FileMorph"


def build_site_jsonld(app_base_url: str) -> tuple[str, str]:
    """Build the homepage JSON-LD + its CSP source-hash for a given base URL.

    Called once at app startup with ``settings.app_base_url`` so the structured
    data points at the deployment's own canonical origin (e.g. a self-hoster's
    `https://files.example.com`), not the upstream SaaS URL.

    The block is intentionally **locale-independent**: it is compiled once at
    startup into a single CSP-hashed ``<script>`` (one block → one byte-exact
    SHA-256 → one ``script-src`` source). Per-page, per-locale structured data
    (e.g. ``FAQPage`` mirroring the German vs. English homepage FAQ) cannot
    live here without either breaking the single-hash invariant or shipping a
    language mismatch between the markup and the visible copy. The homepage's
    visible FAQ section (translated question-headings + answers) is what
    carries the AI-extractability / GEO weight instead — so we deliberately do
    **not** emit ``FAQPage``/``HowTo`` here. ``Organization`` and the two
    application types below *are* language-neutral entity descriptors and are
    safe to compile once.
    """
    base = app_base_url.rstrip("/") or "http://localhost:8000"
    # Honest feature list — only capabilities that actually ship (see
    # docs/claims-audit.md). No AVIF auto-routing / pre-upload size-preview.
    feature_list = [
        "Convert images (HEIC, JPG, PNG, WebP, BMP, TIFF, GIF)",
        "Convert documents (DOCX, PDF, TXT, Markdown)",
        "Convert spreadsheets (XLSX, CSV, JSON)",
        "Convert audio (MP3, WAV, FLAC, OGG, M4A)",
        "Convert video (MP4, MOV, AVI, MKV, WebM)",
        "Compress images to an exact target size",
        "No account required",
        "Self-hostable via Docker",
        "REST API for programmatic conversion",
        "EU-hosted, GDPR-friendly",
    ]
    data: list[dict] = [
        {
            "@context": "https://schema.org",
            "@type": "WebApplication",
            "name": "FileMorph",
            "url": base,
            "applicationCategory": "Multimedia",
            "operatingSystem": "Any",
            "offers": {"@type": "Offer", "price": "0", "priceCurrency": settings.price_currency},
            "featureList": feature_list,
            "isAccessibleForFree": True,
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
            "offers": {"@type": "Offer", "price": "0", "priceCurrency": settings.price_currency},
            "license": "https://www.gnu.org/licenses/agpl-3.0.html",
        },
        {
            "@context": "https://schema.org",
            "@type": "Organization",
            "name": "FileMorph",
            "url": base,
            "logo": f"{base}/static/og-image.png",
            "description": (
                "Open-source, privacy-respecting file conversion and compression — "
                "AGPLv3, self-hostable, EU-hosted."
            ),
            "sameAs": [GITHUB_URL],
        },
    ]
    return _compile(data)
