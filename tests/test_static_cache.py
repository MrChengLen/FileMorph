# SPDX-License-Identifier: AGPL-3.0-or-later
"""S1-B: Cache-Control headers on /static mount."""

import hashlib
import re
from pathlib import Path

from app.core import assets
from app.core.assets import _file_version, file_version, static_url
from app.main import _HASHED_ASSET

_TEMPLATES = Path(__file__).resolve().parents[1] / "app" / "templates"
_IMMUTABLE = "public, max-age=31536000, immutable"


def _detour(levels: int, path: str = "js/app.js") -> str:
    """/static/<path> spelled as `levels` × `..` past the filesystem root and the
    static directory's absolute path again — a spelling Starlette resolves and
    serves. Slashes are %2F-encoded so the client doesn't collapse the `..`."""
    static = assets._STATIC_DIR.resolve()
    depth = len(static.parts) - 1
    inner = [".."] * (depth + levels) + list(static.parts[1:]) + path.split("/")
    return "/static/" + "%2F".join(inner)


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


def test_versioned_static_is_immutable(client):
    """A file requested with its current version is cached for a year."""
    for path in ("js/app.js", "css/style.css", "vendor/chart.umd.min.js"):
        url = static_url(path)
        assert re.fullmatch(rf"/static/{re.escape(path)}\?v=[0-9a-f]{{12}}", url)
        r = client.get(url)
        assert r.status_code == 200
        assert r.headers.get("cache-control") == _IMMUTABLE, url


def test_another_version_is_not_cached(client):
    """A version that isn't the file's — asked for before a deploy finished, or
    answered by an old replica — must not pin this body under that URL."""
    r = client.get("/static/js/app.js?v=000000000000")
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-store"


def test_version_follows_the_file_content(tmp_path):
    script = tmp_path / "a.js"
    script.write_bytes(b"one")
    first = file_version(script)
    assert file_version(script) == first
    script.write_bytes(b"two!")
    assert file_version(script) != first
    # The content hash, so every worker and replica names the same URL.
    assert file_version(script) == hashlib.sha256(b"two!").hexdigest()[:12]


def test_path_detours_share_one_version(client):
    """The version comes from the file Starlette resolved, not from the request's
    spelling: each spelling would otherwise be hashed and cached on its own."""
    version = static_url("js/app.js").split("?v=")[1]
    client.get(f"/static/js/app.js?v={version}")
    before = _file_version.cache_info().currsize
    for levels in range(20):
        r = client.get(f"{_detour(levels)}?v={version}")
        assert r.status_code == 200
        assert r.headers.get("cache-control") == _IMMUTABLE
    assert _file_version.cache_info().currsize == before


def test_an_overlong_path_spelling_is_no_server_error(client):
    r = client.get(f"{_detour(1500)}?v=000000000000")
    assert r.status_code in (200, 404)


def test_a_missing_file_keeps_its_plain_url():
    assert static_url("js/no-such-file.js") == "/static/js/no-such-file.js"


def test_every_versioned_link_names_an_existing_file():
    """static_url() falls back to the plain URL for a missing file, so the page
    still renders; a typo would then only show as a 404 in the browser."""
    linked = {
        name
        for template in _TEMPLATES.rglob("*.html")
        for name in re.findall(r"static_url\('([^']+)'\)", template.read_text(encoding="utf-8"))
    }
    assert linked
    missing = sorted(name for name in linked if not (assets._STATIC_DIR / name).is_file())
    assert not missing, missing


def test_templates_link_scripts_and_stylesheets_with_their_version():
    """A plain /static/….js or ….css link would keep serving the old file from
    the browser cache after an update; static_url() adds the content version."""
    plain = re.compile(r"""(?:src|href)=["']/static/[^"'{]+\.(?:js|css)["']""")
    found = [
        f"{template.relative_to(_TEMPLATES)}: {link}"
        for template in sorted(_TEMPLATES.rglob("*.html"))
        for link in plain.findall(template.read_text(encoding="utf-8"))
    ]
    assert not found, found
