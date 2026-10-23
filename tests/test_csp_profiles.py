# SPDX-License-Identifier: AGPL-3.0-or-later
"""CSP profiles: the policy each route and each file gets.

app/main.py builds one policy per profile (app/core/csp.py). Every response
keeps ``default`` unless its route picks another profile; the engine files
under /static/engine/ always get ``local``, 404s included. These tests pin the
three policies, the choice per route and per file, and that no public page has
switched yet: a page that does adds its row to ``_ROUTE_PROFILES``.
"""

from __future__ import annotations

import pytest
from fastapi import Request
from fastapi.responses import HTMLResponse

from app.api.routes import pages
from app.core.config import settings
from app.core.csp import CSP_PROFILES, use_csp_profile
from app.core.engine import engine_tree_hash
from app.core.jsonld import build_site_jsonld
from app.main import _CSP_HEADERS, _build_csp_header, app

# Route path → profile, for every page route that does not use "default".
_ROUTE_PROFILES: dict[str, str] = {}

_PATH_PARAMS = {"{pair_slug}": "jpg-to-pdf", "{tool}": "split"}


def _directives(policy: str) -> dict[str, str]:
    out = {}
    for part in policy.split(";"):
        name, _, value = part.strip().partition(" ")
        if name:
            out[name] = value
    return out


def _page_paths() -> list[str]:
    paths = []
    for route in pages.router.routes:
        path = route.path
        for param, value in _PATH_PARAMS.items():
            path = path.replace(param, value)
        paths += [path, "/de" + path, "/en" + path]
    return paths + [route.path for route in pages.docs_router.routes]


def test_default_profile_is_the_policy_from_before_the_profiles():
    jsonld_hash = build_site_jsonld(settings.app_base_url)[1]
    assert _build_csp_header("") == (
        "default-src 'self'; "
        f"script-src 'self' {jsonld_hash}; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "base-uri 'self'; "
        "frame-ancestors 'none';"
    )
    assert _build_csp_header("", "default") == _build_csp_header("")


@pytest.mark.parametrize("api_base", ["", "https://api.example.com"])
def test_hybrid_only_adds_blob_images(api_base):
    default = _directives(_build_csp_header(api_base))
    hybrid = _directives(_build_csp_header(api_base, "hybrid"))
    assert hybrid.pop("img-src") == "'self' data: blob:"
    default.pop("img-src")
    assert hybrid == default


@pytest.mark.parametrize("api_base", ["", "https://api.example.com"])
def test_local_refuses_data_connections_and_form_posts(api_base):
    policy = _build_csp_header(api_base, "local")
    local = _directives(policy)
    # No fetch / XHR / WebSocket / EventSource / beacon, and no form posts.
    assert local["connect-src"] == "'none'"
    assert local["form-action"] == "'none'"
    # No plugins and no frames: a same-origin frame would bring its own policy.
    assert local["object-src"] == "'none'"
    assert local["frame-src"] == "'none'"
    assert local["worker-src"] == "'self'"
    assert local["manifest-src"] == "'self'"
    assert "api.example.com" not in policy
    # Everything else as in "hybrid" (previews included).
    hybrid = _directives(_build_csp_header(api_base, "hybrid"))
    for name in (
        "default-src",
        "script-src",
        "style-src",
        "img-src",
        "base-uri",
        "frame-ancestors",
    ):
        assert local[name] == hybrid[name], name


def test_unknown_profile_is_an_error():
    with pytest.raises(ValueError):
        use_csp_profile({}, "lokal")


def test_the_app_builds_one_policy_per_profile():
    assert set(_CSP_HEADERS) == set(CSP_PROFILES)
    for profile, policy in _CSP_HEADERS.items():
        assert policy == _build_csp_header(settings.api_base_url, profile)


@pytest.mark.parametrize("path", _page_paths())
def test_each_page_route_answers_with_its_profile(client, every_page_on, path):
    r = client.get(path)
    assert r.status_code == 200, path  # the page itself, not the 404 page
    profile = _ROUTE_PROFILES.get(path, "default")
    assert r.headers["content-security-policy"] == _CSP_HEADERS[profile]


@pytest.mark.parametrize(
    "path",
    ["/api/v1/health", "/robots.txt", "/no-such-page", "/static/js/app.js", "/static/nope.js"],
)
def test_other_routes_and_static_files_keep_default(client, path):
    assert client.get(path).headers["content-security-policy"] == _CSP_HEADERS["default"]


@pytest.fixture
def profile_route():
    """A throwaway route that picks the profile named in its path."""

    async def endpoint(request: Request, profile: str):
        use_csp_profile(request.scope, profile)
        return HTMLResponse("<p>ok</p>")

    app.add_api_route("/csp-profile-test/{profile}", endpoint, include_in_schema=False)
    route = app.router.routes[-1]
    try:
        yield
    finally:
        app.router.routes.remove(route)


@pytest.mark.parametrize("profile", CSP_PROFILES)
def test_a_route_picks_its_profile(client, profile_route, profile):
    r = client.get(f"/csp-profile-test/{profile}")
    assert r.status_code == 200
    assert r.headers["content-security-policy"] == _CSP_HEADERS[profile]


def test_the_choice_ends_with_its_request(client, profile_route):
    client.get("/csp-profile-test/local")
    assert client.get("/").headers["content-security-policy"] == _CSP_HEADERS["default"]


@pytest.mark.parametrize("enabled", [False, True])
def test_engine_files_always_get_local(client, monkeypatch, enabled):
    monkeypatch.setattr(settings, "local_tools_enabled", enabled)
    tree = engine_tree_hash()
    for path in (
        f"/static/engine/{tree}/placeholder.js",  # 200 when enabled
        f"/static/engine/{'0' * 40}/placeholder.js",
        "/static/engine/placeholder.js",
    ):
        r = client.get(path)
        assert r.headers["content-security-policy"] == _CSP_HEADERS["local"], path
