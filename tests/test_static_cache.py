# SPDX-License-Identifier: AGPL-3.0-or-later
"""S1-B: Cache-Control headers on /static mount."""

from app.main import _HASHED_ASSET


def test_unhashed_static_has_short_revalidate(client):
    r = client.get("/static/js/app.js")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "public, max-age=300, must-revalidate"


def test_unhashed_css_has_short_revalidate(client):
    r = client.get("/static/css/style.css")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "public, max-age=300, must-revalidate"


def test_vendored_dotted_name_not_misread_as_hash(client):
    """vendor/chart.umd.min.js has dots but no hex-hash → short cache, not immutable."""
    r = client.get("/static/vendor/chart.umd.min.js")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "public, max-age=300, must-revalidate"


def test_hash_regex_matches_bundler_output():
    """Guard the regex against regressions so a future esbuild/vite build gets immutable."""
    # Positive — hash-suffix patterns the build tools emit:
    assert _HASHED_ASSET.search("app.abc12345.js")
    assert _HASHED_ASSET.search("app-abc12345.js")
    assert _HASHED_ASSET.search("js/main.0a1b2c3d4e.css")
    assert _HASHED_ASSET.search("chart.umd.min.deadbeef.js")


def test_hash_regex_ignores_plain_names():
    """Plain filenames must not be misread as hashed."""
    assert not _HASHED_ASSET.search("app.js")
    assert not _HASHED_ASSET.search("style.css")
    assert not _HASHED_ASSET.search("chart.umd.min.js")
    assert not _HASHED_ASSET.search("favicon.svg")
    # 7 hex chars is below our 8-char threshold — treat as plain.
    assert not _HASHED_ASSET.search("app.abc1234.js")
