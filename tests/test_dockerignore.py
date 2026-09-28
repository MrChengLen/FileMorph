# SPDX-License-Identifier: AGPL-3.0-or-later
"""``.dockerignore`` regression guard (CWE-538).

The runtime stage of the ``Dockerfile`` copies the whole build context
(``COPY . .``). Without a ``.dockerignore``, an image built from a working
folder carries what lies there in its layers: a real ``.env`` (which the
settings then read from ``/app/.env``), ``data/api_keys.json``, ``.git``,
``.venv``, ``.claude/``. CI builds from a clean checkout; self-hosters and
local builds don't.

The patterns are evaluated the way Docker evaluates them rather than checked
as strings, because the mistakes that matter are semantic: a bare pattern
matches only at the context root (``__pycache__`` misses ``app/__pycache__``),
and the last matching line wins, so a ``!`` exception placed before its
exclusion does nothing. The other direction matters as much: an over-broad
pattern ships an image without files the app reads at run time, and the
Docker workflow only builds after merge.
"""

from __future__ import annotations

import functools
import posixpath
import re
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DOCKERIGNORE = _REPO_ROOT / ".dockerignore"

# What a working folder may hold that must never reach an image layer.
_MUST_STAY_OUT = [
    ".env",  # the settings read /app/.env at start-up
    ".env.production",
    ".envrc",
    "data/api_keys.json",  # key hashes: a container without a data volume accepts them
    "docker-compose.override.yml",
    ".git",  # a file in a worktree, a directory in a clone
    ".git/config",
    ".venv/pyvenv.cfg",
    ".claude/settings.local.json",
    ".clone",
    ".mcp.json",
    ".vscode/settings.json",
    ".idea/dataSources.xml",
    "docs-internal/notes.md",
    "docs/screenshot.png",
    "CLAUDE.md",
    "2027-01-02-120000-this-session-is-being-continued-from-a-previous-c.txt",
    "app/__pycache__/main.cpython-314.pyc",  # needs the **/ prefix
    ".pytest_cache/v/cache/lastfailed",
    "tests/conftest.py",
]

# Tracked files the image deliberately leaves out: nothing reads them at run time.
_DEV_ONLY = (".github/", ".githooks/", "tests/", ".env.example")


@functools.cache
def _rules() -> list[tuple[bool, re.Pattern[str]]]:
    """``.dockerignore`` as ``(is_exception, regex)`` pairs, in file order.

    Follows moby/patternmatcher (``ignorefile.ReadAll`` + ``Pattern.compile``):
    only a ``#`` in column 1 starts a comment, ``*`` and ``?`` stop at ``/``,
    ``**`` spans directories and ``**/`` may match nothing at all. Character
    classes and backslash escapes are not ported, so they are rejected.
    """
    rules = []
    for line in _DOCKERIGNORE.read_text(encoding="utf-8-sig").splitlines():
        if line.startswith("#"):
            continue
        line = line.strip()
        if not line:
            continue
        exception = line.startswith("!")
        pattern = posixpath.normpath(line.removeprefix("!").strip()).lstrip("/")
        assert not set(pattern) & set("[]\\"), (
            f"{line!r}: `[...]` and `\\` are not ported to this matcher; extend _rules() first"
        )
        regex, i = "", 0
        while i < len(pattern):
            if pattern.startswith("**", i):
                i += 2
                if pattern.startswith("/", i):
                    i += 1
                regex += ".*" if i == len(pattern) else "(.*/)?"
            else:
                char = pattern[i]
                regex += {"*": "[^/]*", "?": "[^/]"}.get(char, re.escape(char))
                i += 1
        rules.append((exception, re.compile(regex)))
    return rules


def _is_excluded(path: str) -> bool:
    """Whether Docker leaves ``path`` (relative, ``/``-separated) out of the context.

    Same decision as patternmatcher's ``MatchesOrParentMatches``.
    """
    parts = path.split("/")
    # A pattern that matches a parent directory excludes everything below it.
    candidates = ["/".join(parts[: n + 1]) for n in range(len(parts))]
    excluded = False
    for exception, regex in _rules():
        if any(regex.fullmatch(candidate) for candidate in candidates):
            excluded = not exception
    return excluded


def _tracked_files() -> list[str]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=_REPO_ROOT,
            capture_output=True,
            check=True,
            text=True,
            encoding="utf-8",
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("needs a git checkout to list the tracked files")
    return [path for path in out.split("\0") if path]


@pytest.mark.parametrize("path", _MUST_STAY_OUT)
def test_secrets_and_local_state_stay_out_of_the_image(path: str) -> None:
    assert _is_excluded(path), (
        f"`COPY . .` would bake {path} into the image. Exclude it in .dockerignore; "
        f"a bare pattern there only matches at the context root, use **/ for any depth."
    )


def test_image_keeps_every_tracked_file_but_the_dev_only_ones() -> None:
    dropped = [p for p in _tracked_files() if _is_excluded(p) and not p.startswith(_DEV_ONLY)]
    assert not dropped, (
        f".dockerignore drops tracked files the image may need: {dropped[:10]}. "
        f"The Docker workflow only builds after merge, so this would first show up "
        f"as a broken image. Narrow the pattern, or add the path to _DEV_ONLY if "
        f"nothing reads it at run time."
    )
