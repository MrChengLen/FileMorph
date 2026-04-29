# SPDX-License-Identifier: AGPL-3.0-or-later
"""Resolve content-hashed static asset filenames.

`scripts/build-tailwind.sh` emits `tailwind.<sha256-prefix>.css`; the
template renders it via `{{ tailwind_css }}`. Scanning the directory
once at import time keeps the template dumb and avoids a build-time
manifest file the user would have to commit alongside the bundle."""

import re

from app.compat import base_dir

_HASHED = re.compile(r"^tailwind\.[a-f0-9]{6,}\.css$")


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
