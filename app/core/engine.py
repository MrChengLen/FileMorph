# SPDX-License-Identifier: AGPL-3.0-or-later
"""Delivery of the local engine — the code that will process files in the
browser.

The engine is plain ES modules in ``app/static/engine/``: no bundler and no
build step, so the repository holds exactly what the browser runs. Its own
mount serves the files only under ``/static/engine/<tree-hash>/…``:

- ``<tree-hash>`` is the git tree id of ``app/static/engine``, so any release
  can be checked against what it serves: ``git rev-parse <tag>:app/static/engine``
  prints the hash (recipe in docs/self-hosting.md, "Local tools"). It is
  computed once per process: restart the server after editing an engine file.
- Any change to an engine file changes the URL, so a response can be cached
  for good (``immutable``). A browser then never asks again, not even for new
  headers. ``delivery.js`` holds a fingerprint of the delivery headers;
  tests/test_engine_delivery.py fails after a header change until it is
  updated, which changes the tree hash and with it every URL.
- A wrong or outdated hash is a plain 404 that no cache keeps: the next
  release's hash is public before its deploy.
- The MIME type is set here, not guessed: on Windows ``mimetypes`` reads the
  registry, which can map ``.js`` to ``text/plain``, and browsers refuse to
  run a module script of any type but JavaScript. Files of any other type are
  not served.
- Every response of the mount, its 404s included, carries the ``local`` CSP
  (``app/core/csp.py``). It governs a file that runs as a worker; a module
  that a page imports runs under that page's profile.
- Inert unless ``LOCAL_TOOLS_ENABLED`` is set: until then every engine URL is a
  404.
"""

from __future__ import annotations

import hashlib
import os
from functools import cache
from pathlib import Path

from starlette.exceptions import HTTPException
from starlette.responses import PlainTextResponse, Response
from starlette.staticfiles import StaticFiles
from starlette.types import Receive, Scope, Send

from app.compat import base_dir
from app.core.config import settings
from app.core.csp import use_csp_profile

ENGINE_DIR = base_dir() / "app" / "static" / "engine"
ENGINE_URL_PREFIX = "/static/engine"

# The only file types the engine ships. A new one (JSON, WASM) needs its MIME
# type here, where tests/test_engine_delivery.py looks for it, and a
# line-ending rule in .gitattributes (eol=lf or binary): otherwise a Windows
# checkout serves other bytes than git hashes.
ENGINE_MEDIA_TYPES = {".js": "text/javascript; charset=utf-8"}


def _git_object_id(kind: bytes, body: bytes) -> bytes:
    # SHA-1 is git's object id, used here to name a tree, not to protect it.
    header = kind + b" " + str(len(body)).encode() + b"\0"
    return hashlib.sha1(header + body, usedforsecurity=False).digest()


def _git_tree(directory: Path) -> bytes | None:
    """The git tree object id of ``directory``, or ``None`` if it holds no file.

    Every file counts as a regular, non-executable blob (mode 100644): the
    engine tree holds nothing else (tests/test_engine_delivery.py checks the
    git index). Empty directories are left out, as git leaves them out.
    """
    entries = []
    for child in directory.iterdir():
        name = os.fsencode(child.name)
        if child.is_dir():
            tree = _git_tree(child)
            if tree is not None:
                # git sorts a directory as if its name ended in "/".
                entries.append((name + b"/", b"40000 " + name + b"\0" + tree))
        else:
            blob = _git_object_id(b"blob", child.read_bytes())
            entries.append((name, b"100644 " + name + b"\0" + blob))
    if not entries:
        return None
    return _git_object_id(b"tree", b"".join(entry for _, entry in sorted(entries)))


def git_tree_id(directory: Path) -> str:
    """What ``git rev-parse <rev>:<directory>`` prints when ``directory``
    matches that revision."""
    return (_git_tree(directory) or _git_object_id(b"tree", b"")).hex()


@cache
def engine_tree_hash() -> str:
    """The tree hash in every engine URL, computed once per process."""
    return git_tree_id(ENGINE_DIR)


class EngineFiles(StaticFiles):
    """Serves ``ENGINE_DIR`` under ``/static/engine/<tree-hash>/…`` (module
    docstring)."""

    def __init__(self, *, directory: Path, tree_hash: str) -> None:
        super().__init__(directory=directory)
        self.tree_hash = tree_hash

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        # Before anything can fail, so that the 404s get it too.
        use_csp_profile(scope, "local")
        try:
            await super().__call__(scope, receive, send)
        except HTTPException as exc:
            # Not the site's 404 page, and never cached (module docstring).
            response = PlainTextResponse(
                exc.detail, status_code=exc.status_code, headers={"Cache-Control": "no-store"}
            )
            await response(scope, receive, send)

    def get_path(self, scope: Scope) -> str:
        # super() normalises the path below the mount: "<tree-hash>/core/x.js".
        parts = Path(super().get_path(scope)).parts
        if (
            not settings.local_tools_enabled
            or len(parts) < 2
            or parts[0] != self.tree_hash
            or Path(parts[-1]).suffix.lower() not in ENGINE_MEDIA_TYPES
        ):
            raise HTTPException(status_code=404)
        return os.path.join(*parts[1:])

    async def get_response(self, path: str, scope: Scope) -> Response:
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Content-Type"] = ENGINE_MEDIA_TYPES[Path(path).suffix.lower()]
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response
