# SPDX-License-Identifier: AGPL-3.0-or-later
"""Delivery of the local engine: tree hash, 404s, MIME type, cache headers.

app/core/engine.py serves app/static/engine/ only under
/static/engine/<tree-hash>/, where <tree-hash> is the git tree id of that
directory: ``git rev-parse <tag>:app/static/engine`` names what a release
serves. So the hash must equal git's, a wrong hash must be a 404, the
JavaScript type must not come from the OS (Windows reads it from the
registry), and LOCAL_TOOLS_ENABLED must keep the whole path inert by default.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import starlette.responses
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from app.core.config import Settings, settings
from app.core.engine import (
    ENGINE_DIR,
    ENGINE_MEDIA_TYPES,
    EngineFiles,
    engine_tree_hash,
    git_tree_id,
)
from app.core.jsonld import build_site_jsonld

_ROOT = Path(__file__).resolve().parents[1]
_IMMUTABLE = "public, max-age=31536000, immutable"
_JS = "text/javascript; charset=utf-8"
needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def _git(*args: str, cwd: Path = _ROOT) -> str:
    # GIT_DIR & co. would point git at another repository (git sets them for
    # hooks); core.longpaths lets git on Windows work under a deep temp dir.
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    return subprocess.run(
        ["git", "-c", "core.longpaths=true", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        check=True,
        encoding="utf-8",
    ).stdout.strip()


def _url(name: str = "placeholder.js") -> str:
    return f"/static/engine/{engine_tree_hash()}/{name}"


@pytest.fixture
def engine_on(monkeypatch):
    monkeypatch.setattr(settings, "local_tools_enabled", True)


# ── Tree hash ────────────────────────────────────────────────────────────────


@needs_git
def test_tree_hash_is_the_git_tree_id(tmp_path):
    engine = tmp_path / "engine"
    files = {
        # git sorts the directory "a" as "a/", i.e. after the file "a.js".
        "a.js": b"export const a = 1;\n",
        "a/b.js": b"export const b = 2;\n",
        "a-b.js": b"",
        "core/deep/x.js": b"// x\n",
        "Z.js": b"export {};\n",
    }
    for name, body in files.items():
        path = engine / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    (engine / "empty").mkdir()  # git keeps no empty directory
    _git("init", "-q", cwd=tmp_path)
    _git("-c", "core.autocrlf=false", "add", "-A", cwd=tmp_path)
    tree = _git("write-tree", cwd=tmp_path)
    assert git_tree_id(engine) == _git("rev-parse", f"{tree}:engine", cwd=tmp_path)


@needs_git
def test_served_hash_is_the_committed_tree():
    """The recipe in docs/self-hosting.md: ``git rev-parse <rev>:app/static/engine``."""
    try:
        changes = _git(
            "status", "--porcelain", "--ignored", "--untracked-files=all", "--", "app/static/engine"
        )
        committed = _git("rev-parse", "HEAD:app/static/engine")
    except subprocess.CalledProcessError:
        pytest.skip("no git checkout, or app/static/engine is not committed yet")
    if changes:
        pytest.skip("app/static/engine differs from HEAD")
    assert engine_tree_hash() == committed


@needs_git
def test_engine_files_are_plain_blobs():
    # The tree hash counts every file as mode 100644: no executable bit, no symlink.
    try:
        entries = _git("ls-files", "--stage", "--", "app/static/engine").splitlines()
    except subprocess.CalledProcessError:
        pytest.skip("no git checkout")
    assert entries, "app/static/engine has no tracked file"
    for entry in entries:
        assert entry.startswith("100644 "), entry


def test_engine_files_have_a_media_type():
    files = [p for p in ENGINE_DIR.rglob("*") if p.is_file()]
    assert files
    for path in files:
        assert path.suffix.lower() in ENGINE_MEDIA_TYPES, f"{path}: add its MIME type"


# ── Serving ──────────────────────────────────────────────────────────────────


def test_engine_file_is_served_under_its_tree_hash(client, engine_on):
    r = client.get(_url())
    assert r.status_code == 200
    assert r.content == (ENGINE_DIR / "placeholder.js").read_bytes()
    assert r.headers["content-type"] == _JS
    assert r.headers["cache-control"] == _IMMUTABLE
    again = client.get(_url(), headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304
    assert again.headers["cache-control"] == _IMMUTABLE


def test_javascript_type_does_not_come_from_the_os(client, engine_on, monkeypatch):
    # As on a Windows machine whose registry maps .js to text/plain: browsers
    # refuse to run a module script of that type.
    monkeypatch.setattr(starlette.responses, "guess_type", lambda *a, **k: ("text/plain", None))
    assert client.get("/static/js/nav.js").headers["content-type"].startswith("text/plain")
    assert client.get(_url()).headers["content-type"] == _JS


def test_header_changes_change_every_engine_url(client, engine_on):
    """Engine files are cached as immutable, so a browser that has one never
    sees later headers (CSP, type, a future COEP). app/static/engine/delivery.js
    carries a fingerprint of them, and with it the tree hash: a header change
    needs a new fingerprint, which gives every engine file a new URL."""
    r = client.get(_url("delivery.js"))
    assert r.status_code == 200
    volatile = {"content-length", "date", "etag", "last-modified"}
    headers = {k.lower(): v for k, v in r.headers.items() if k.lower() not in volatile}
    # The JSON-LD hash in script-src differs per deployment (APP_BASE_URL).
    jsonld = build_site_jsonld(settings.app_base_url)[1]
    headers["content-security-policy"] = headers["content-security-policy"].replace(
        jsonld, "'sha256-json-ld'"
    )
    fingerprint = hashlib.sha256(json.dumps(headers, sort_keys=True).encode()).hexdigest()[:12]
    source = (ENGINE_DIR / "delivery.js").read_text(encoding="utf-8")
    assert f'export const DELIVERY = "{fingerprint}";' in source, (
        f'The engine delivery headers changed: set DELIVERY in app/static/engine/delivery.js to "{fingerprint}".'
    )


@pytest.mark.parametrize(
    "path",
    [
        "/static/engine/{zero}/placeholder.js",  # wrong hash
        "/static/engine/{short}/placeholder.js",  # abbreviated hash
        "/static/engine/{upper}/placeholder.js",
        "/static/engine/placeholder.js",  # no hash
        "/static/engine/{tree}/",
        "/static/engine/{tree}/missing.js",
        "/static/engine/%2e%2e/js/app.js",  # out of the engine mount
        "/static/js/%2e%2e/engine/placeholder.js",  # into it through /static
        "/static/js%2f..%2fengine/placeholder.js",  # the same as a browser can send it
    ],
)
def test_anything_but_the_tree_hash_is_404(client, engine_on, path):
    tree = engine_tree_hash()
    url = path.format(tree=tree, zero="0" * 40, short=tree[:12], upper=tree.upper())
    assert client.get(url).status_code == 404


@pytest.mark.parametrize("enabled", [False, True])
def test_engine_404s_are_plain_and_never_cached(client, monkeypatch, enabled):
    # The next release's tree hash is public before its deploy: no cache may
    # keep a 404 for it.
    monkeypatch.setattr(settings, "local_tools_enabled", enabled)
    r = client.get(f"/static/engine/{'0' * 40}/placeholder.js")
    assert r.status_code == 404
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["content-type"].startswith("text/plain")


def test_engine_is_inert_unless_enabled(client, monkeypatch):
    assert Settings.model_fields["local_tools_enabled"].default is False
    monkeypatch.setattr(settings, "local_tools_enabled", False)
    assert client.get(_url()).status_code == 404


def test_only_files_with_a_media_type_are_served(tmp_path, engine_on):
    (tmp_path / "x.js").write_bytes(b"export {};\n")
    (tmp_path / "notes.txt").write_bytes(b"not part of the engine\n")
    files = EngineFiles(directory=tmp_path, tree_hash=git_tree_id(tmp_path))
    with TestClient(Starlette(routes=[Mount("/engine", files)])) as c:
        assert c.get(f"/engine/{files.tree_hash}/x.js").status_code == 200
        assert c.get(f"/engine/{files.tree_hash}/notes.txt").status_code == 404
