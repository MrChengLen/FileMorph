# SPDX-License-Identifier: AGPL-3.0-or-later
"""Resolve content-hashed static asset filenames and versioned URLs.

`scripts/build-tailwind.sh` emits `tailwind.<sha256-prefix>.css`; the
template renders it via `{{ tailwind_css }}`. Scanning the directory
once at import time keeps the template dumb and avoids a build-time
manifest file the user would have to commit alongside the bundle.

Every other script and stylesheet keeps its plain name; templates link
it through `{{ static_url('js/app.js') }}`, which appends the file's
content version instead."""

import hashlib
import os
import re
from functools import lru_cache
from pathlib import Path

from app.compat import base_dir

_HASHED = re.compile(r"^tailwind\.[a-f0-9]{6,}\.css$")
_STATIC_DIR = base_dir() / "app" / "static"


def tailwind_css_filename() -> str:
    """Return the hashed tailwind bundle filename.

    Falls back to `tailwind.css` if no hashed build is present — lets the
    dev server render without a crash right after a fresh checkout, before
    `bash scripts/build-tailwind.sh` has been run. The test suite guards
    that a real hashed file exists in committed state."""
    css_dir = base_dir() / "app" / "static" / "css"
    for candidate in css_dir.glob("tailwind.*.css"):
        if _HASHED.match(candidate.name):
            return candidate.name
    return "tailwind.css"


def static_url(path: str) -> str:
    """Return `/static/<path>?v=<version>` for a file under `app/static/`.

    A page is fetched fresh on every visit, so it always names the current
    version: after an update, the first page a browser opens loads the new
    file, even if the old one was cached for longer than the app asked (a
    CDN may stretch a short cache time; Cloudflare's default stretches 5
    minutes to 4 hours). `CachingStaticFiles` (app/main.py) caches a request
    whose version matches the file for a year.

    A missing file keeps its plain URL: the page still renders and only that
    file fails to load, as before. The tests check that every linked file
    exists."""
    try:
        return f"/static/{path}?v={file_version(_STATIC_DIR / path)}"
    except FileNotFoundError:
        return f"/static/{path}"


def file_version(file: Path | str, stat: os.stat_result | None = None) -> str:
    """Return the content version of `file`: the first 12 hex digits of its SHA-256.

    The hash is cached per path, modification and change time, and size,
    so an edited file gets a new version without a restart (the dev server
    reloads on Python changes only)."""
    stat = stat or os.stat(file)
    return _file_version(str(file), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)


@lru_cache(maxsize=256)
def _file_version(file: str, mtime_ns: int, ctime_ns: int, size: int) -> str:
    return hashlib.sha256(Path(file).read_bytes()).hexdigest()[:12]
