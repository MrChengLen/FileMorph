# SPDX-License-Identifier: AGPL-3.0-or-later
"""/docs serves the API explorer from FileMorph's own origin.

FastAPI's built-in /docs loaded Swagger UI from cdn.jsdelivr.net and started it
with an inline <script>. The site CSP (script-src 'self' plus one JSON-LD hash)
blocks both, so the live page rendered empty. The replacement serves the
vendored copy from /static/vendor/ and starts it from /static/js/api-docs.js;
these tests pin that contract. /redoc, broken the same way and linked nowhere,
is switched off.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core.assets import static_url

_ROOT = Path(__file__).resolve().parents[1]


def test_docs_page_loads_only_same_origin_assets(client):
    resp = client.get("/docs")
    assert resp.status_code == 200
    html = resp.text
    assert f'<script src="{static_url("vendor/swagger-ui-bundle.js")}"></script>' in html
    assert f'<script src="{static_url("js/api-docs.js")}"></script>' in html
    assert f'href="{static_url("vendor/swagger-ui.css")}"' in html
    refs = re.findall(r'\b(?:src|href)="([^"]*)"', html)
    assert refs
    assert all(ref.startswith("/") and not ref.startswith("//") for ref in refs), refs


def test_docs_page_has_no_inline_script(client):
    html = client.get("/docs").text
    for tag in re.findall(r"<script\b[^>]*>", html):
        assert "src=" in tag, tag
    assert not re.search(r"\son[a-z]+\s*=", html), "no inline event handlers"


def test_docs_page_points_swagger_at_the_openapi_schema(client):
    html = client.get("/docs").text
    assert 'data-openapi-url="/openapi.json"' in html
    schema = client.get("/openapi.json")
    assert schema.status_code == 200
    assert schema.json()["info"]["title"] == "FileMorph"


def test_docs_csp_allows_no_third_party_or_eval_script(client):
    csp = client.get("/docs").headers["content-security-policy"]
    script_src = next(d.strip() for d in csp.split(";") if d.strip().startswith("script-src"))
    assert "http" not in script_src
    assert "'unsafe-eval'" not in script_src
    assert "'unsafe-inline'" not in script_src


def test_start_script_keeps_the_schema_on_this_server():
    # Swagger UI's validator badge would send the schema URL to validator.swagger.io.
    js = (_ROOT / "app" / "static" / "js" / "api-docs.js").read_text(encoding="utf-8")
    assert "validatorUrl: null" in js


def test_vendored_swagger_assets_are_served(client):
    for path in ("/static/vendor/swagger-ui-bundle.js", "/static/vendor/swagger-ui.css"):
        assert client.get(path).status_code == 200, path


def test_redoc_is_switched_off(client):
    assert client.get("/redoc").status_code == 404


@pytest.mark.parametrize("path", ["/de/docs", "/en/docs"])
def test_docs_page_exists_only_at_the_root(client, path):
    # The explorer is English-only; no locale copies to index or count.
    assert client.get(path).status_code == 404


def test_docs_page_links_the_schema_if_the_explorer_cannot_load(client):
    # product-ux: no dead end — the text Swagger UI replaces on render stays
    # visible when the bundle fails to load or JavaScript is off.
    html = client.get("/docs").text
    assert '<a href="/openapi.json">' in html


def test_docs_page_respects_the_root_path():
    from fastapi.testclient import TestClient

    from app.main import app

    html = TestClient(app, root_path="/fm").get("/docs").text
    assert 'data-openapi-url="/fm/openapi.json"' in html
