# SPDX-License-Identifier: AGPL-3.0-or-later
"""``.gitignore`` keeps local env files out of commits.

``.env`` on its own matches only that exact name, so a ``.env.local`` or
``.env.production`` in the working folder was not ignored: ``git add -A``
staged it, and a commit sent through the GitHub API (``createCommitOnBranch``)
never runs the pre-commit hook, which blocks only ``.env.production*`` by name.
``.env.*`` covers every variant; ``!.env.example`` exempts the template, which
only works below ``.env.*``, because the last matching line wins.

``--no-index`` judges the patterns alone. Without it git reports a tracked file
such as ``.env.example`` as not ignored, whatever the patterns say.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _deciding_rule(path: str) -> tuple[str, str]:
    """``(source, pattern)`` of the ignore rule that decides ``path``; empty if none matches."""
    if not (_REPO_ROOT / ".git").exists():
        pytest.skip("not a git checkout (e.g. an unpacked release tarball)")
    result = subprocess.run(
        # -v -n -z: one "<source>\0<line>\0<pattern>\0<path>\0" record per path,
        # with empty fields when no rule matches. A negation keeps its "!".
        # git accepts -z only together with --stdin.
        ["git", "check-ignore", "--no-index", "-v", "-n", "-z", "--stdin"],
        input=f"{path}\0",
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    # Exit 1 only means that no rule matched; 128 is a fatal error.
    assert result.returncode in (0, 1), result.stderr
    source, _line, pattern, _path, _ = result.stdout.split("\0")
    return source, pattern


@pytest.mark.parametrize(
    "path",
    # .env.staging: a name no rule spells out; app/: both patterns apply at any depth.
    [".env", ".env.local", ".env.production", ".env.staging", "app/.env", "app/.env.local"],
)
def test_local_env_files_are_ignored(path: str) -> None:
    source, pattern = _deciding_rule(path)
    rule = f"{source}: {pattern}" if source else "none"
    # Only the repository's own .gitignore counts: a global excludes file on one
    # machine protects nobody else's clone.
    assert source == ".gitignore" and not pattern.startswith("!"), (
        f"`git add -A` would stage {path}: no rule in the root .gitignore ignores it "
        f"(deciding rule: {rule}). Keep `.env` and `.env.*` there."
    )


def test_env_example_is_not_ignored() -> None:
    _source, pattern = _deciding_rule(".env.example")
    assert not pattern or pattern.startswith("!"), (
        f".gitignore ignores .env.example (rule {pattern!r}), the template "
        f"self-hosters copy. `!.env.example` has to stay below `.env.*`: the "
        f"last matching line wins."
    )
