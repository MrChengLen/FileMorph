# SPDX-License-Identifier: AGPL-3.0-or-later
"""Which scripts each page template loads.

base.html loads i18n-bootstrap.js, nav.js and cookie-notice.js on every page,
then auth.js and app.js in its ``core_scripts`` block. Both of those call the
API (app.js fetches /api/v1/formats on every page), so a strict page — CSP
profile ``local``, where the browser refuses fetch and XHR — empties that
block. ``_PAGES`` pins each template's own scripts, so a new script or a new
template is added on purpose.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from starlette.requests import Request

from app.core.i18n import localized_context
from app.core.templates import templates

_TEMPLATES = Path(__file__).resolve().parents[1] / "app" / "templates"
_SRC = re.compile(r'<script\b[^>]*\bsrc="([^"]+)"', re.IGNORECASE)

_SHARED = ["/static/js/i18n-bootstrap.js", "/static/js/nav.js", "/static/js/cookie-notice.js"]
_CORE = ["/static/js/auth.js", "/static/js/app.js"]

# Template → (a path that renders it, or None to render it directly; its own scripts).
_PAGES: dict[str, tuple[str | None, list[str]]] = {
    "index.html": ("/", []),
    "formats.html": ("/formats", []),
    "tools.html": ("/tools", []),
    "compress.html": ("/compress", []),
    "convert_pair.html": ("/convert/jpg-to-pdf", []),
    "video_to_gif.html": ("/convert/video-to-gif", []),
    "impressum.html": ("/impressum", []),
    "privacy.html": ("/privacy", []),
    "terms.html": ("/terms", []),
    "security.html": ("/security", []),
    "contact.html": ("/contact", ["/static/js/contact.js"]),
    "login.html": ("/login", ["/static/js/login.js"]),
    "register.html": ("/register", ["/static/js/register.js"]),
    "forgot-password.html": ("/forgot-password", ["/static/js/forgot-password.js"]),
    "reset-password.html": ("/reset-password", ["/static/js/reset-password.js"]),
    "verify-email.html": ("/verify-email", ["/static/js/verify-email.js"]),
    "dashboard.html": ("/dashboard", ["/static/js/dashboard.js"]),
    "account_deleted.html": ("/account-deleted", []),
    "cancel.html": ("/cancel", ["/static/js/cancel.js"]),
    "pricing.html": ("/pricing", ["/static/js/pricing.js", "/static/js/pricing-segment.js"]),
    "enterprise.html": ("/enterprise", []),
    "redact.html": ("/redact", ["/static/js/redact.js"]),
    "pdf_tool.html": ("/pdf/split", ["/static/js/pdf-tools.js"]),
    "cockpit.html": (
        "/cockpit",
        [
            "/static/vendor/chart.umd.min.js",
            "/static/js/cockpit.js",
            "/static/js/cockpit-metrics.js",
        ],
    ),
    "404.html": ("/no-such-page", []),
    "500.html": (None, []),
    # Stand-alone (does not extend base.html).
    "api_docs.html": ("/docs", ["/static/vendor/swagger-ui-bundle.js", "/static/js/api-docs.js"]),
}
_STANDALONE = {"api_docs.html"}


def _render(source: str = "", name: str = "") -> str:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "scheme": "http",
            "server": ("testserver", 80),
            "path": "/",
            "root_path": "",
            "query_string": b"",
            "headers": [],
            "state": {"locale": "en"},
        }
    )
    template = templates.env.from_string(source) if source else templates.env.get_template(name)
    return template.render({"request": request, **localized_context(request)})


def test_every_page_template_is_listed():
    found = {path.name for path in _TEMPLATES.glob("*.html")} - {"base.html"}
    assert found == set(_PAGES)


@pytest.mark.parametrize("name", sorted(_PAGES))
def test_each_page_loads_its_scripts(client, every_page_on, name):
    path, own = _PAGES[name]
    if path is None:
        html = _render(name=name)
    else:
        r = client.get(path)
        assert r.status_code == (404 if name == "404.html" else 200)
        html = r.text
    expected = own if name in _STANDALONE else _SHARED + _CORE + own
    assert sorted(_SRC.findall(html)) == sorted(expected)


def test_base_loads_the_core_scripts_by_default():
    assert _SRC.findall(_render('{% extends "base.html" %}')) == _SHARED + _CORE


def test_a_strict_page_can_leave_out_the_core_scripts():
    html = _render('{% extends "base.html" %}{% block core_scripts %}{% endblock %}')
    assert _SRC.findall(html) == _SHARED
    # i18n-bootstrap.js still finds its catalogue.
    assert '<script id="fm-i18n-strings" type="application/json">' in html
