# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regression guard: no executable inline <script> may ship unpinned.

The strict CSP (``script-src 'self' 'sha256-…'``) blocks any inline
executable script whose SHA-256 source-hash isn't listed. A regression
here is invisible server-side (tests pass, the page renders) but breaks
in the browser: the blocked script never runs, and its ``catch`` can't
fire because execution never starts. The original symptom was the i18n
bootstrap on ``/de/dashboard`` silently zeroing ``window.FM_I18N`` so
German strings fell back to English. Pin the invariant — every inline
executable script's hash must appear in the page's own CSP header.

Data blocks (``type="application/json"`` / ``application/ld+json``) are
not executed by the browser and are not governed by ``script-src``, so
they're exempt. External ``<script src>`` is governed by the ``'self'``
source, also exempt.
"""

from __future__ import annotations

import base64
import hashlib
import re

import pytest

# Routes that extend base.html and therefore carry the inline-script
# surface we care about. Both locale prefixes are included because the
# original bug was locale-visible (DE fell back to EN copy).
_ROUTES = [
    "/",
    "/dashboard",
    "/de/dashboard",
    "/en/dashboard",
    "/cockpit",
    "/de/cockpit",
]

_SCRIPT_RE = re.compile(r"<script\b([^>]*)>(.*?)</script>", re.IGNORECASE | re.DOTALL)
_TYPE_RE = re.compile(r"""type\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
_SRC_RE = re.compile(r"""\bsrc\s*=\s*["']""", re.IGNORECASE)

# Script types the browser treats as data, not executable JavaScript.
_DATA_TYPES = {"application/json", "application/ld+json"}


def _csp_source_for(body: str) -> str:
    digest = hashlib.sha256(body.encode("utf-8")).digest()
    return "'sha256-" + base64.b64encode(digest).decode("ascii") + "'"


def _executable_inline_scripts(html: str) -> list[str]:
    """Return the bodies of inline <script> blocks the browser executes."""
    out: list[str] = []
    for attrs, body in _SCRIPT_RE.findall(html):
        if _SRC_RE.search(attrs):
            continue  # external — governed by script-src 'self'
        type_match = _TYPE_RE.search(attrs)
        if type_match and type_match.group(1).strip().lower() in _DATA_TYPES:
            continue  # data block — never executed
        out.append(body)
    return out


@pytest.mark.parametrize("route", _ROUTES)
def test_no_unpinned_inline_scripts(client, route):
    r = client.get(route)
    assert r.status_code == 200, f"{route} did not render"
    csp = r.headers.get("content-security-policy", "")
    assert "script-src" in csp, f"{route} has no script-src directive"

    for body in _executable_inline_scripts(r.text):
        source = _csp_source_for(body)
        assert source in csp, (
            f"{route} ships an inline executable <script> whose hash {source} "
            f"is not in its CSP script-src. Move it to an external .js file "
            f"(loaded via <script src>) or pin the hash. "
            f"Script body starts: {body.strip()[:80]!r}"
        )


def test_csp_hardening_directives_present(client):
    """base-uri and frame-ancestors lock down base-tag injection and
    clickjacking; both were added alongside the inline-script fix."""
    csp = client.get("/").headers.get("content-security-policy", "")
    assert "base-uri 'self'" in csp
    assert "frame-ancestors 'none'" in csp


def test_i18n_bootstrap_loads_before_consumers(client):
    """The extracted bootstrap must load before nav/auth/app.js, which read
    window.FM_I18N at parse time. Order regression = empty catalogue."""
    html = client.get("/de/dashboard").text
    boot = html.find("/static/js/i18n-bootstrap.js")
    assert boot != -1, "i18n-bootstrap.js is not referenced on the page"
    for consumer in ("/static/js/nav.js", "/static/js/auth.js", "/static/js/app.js"):
        idx = html.find(consumer)
        if idx != -1:
            assert boot < idx, f"i18n-bootstrap.js must load before {consumer}"
