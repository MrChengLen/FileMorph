# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tracked text files are stored with LF line endings.

``.gitattributes`` normalises text files to LF, but only when git itself stages
them. A commit made through the GitHub API (``createCommitOnBranch``) stores
exactly the bytes it is sent, CRLF included: ``requirements.lock`` landed that
way in 7caa75e (PR #81, repaired in PR #85), ``.github/workflows/docker.yml`` in
f72dedc. Nothing breaks, but that commit is already a whole-file diff, and for a
file pinned to ``eol=lf`` the next ordinary edit renormalises it into another.

This reads the index (the ``i/`` column of ``git ls-files --eol``), not the
working tree: a Windows checkout may hold CRLF on disk, and what matters is the
blob that gets committed.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent


def test_no_tracked_text_file_is_stored_with_crlf() -> None:
    if not (_REPO_ROOT / ".git").exists():
        pytest.skip("not a git checkout (e.g. an unpacked release tarball)")
    listing = subprocess.run(
        ["git", "ls-files", "--eol", "-z"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout
    offenders = []
    for entry in filter(None, listing.split("\0")):
        # "i/<eol> w/<eol> attr/<attributes>\t<path>"; -z leaves the path unquoted.
        info, path = entry.split("\t", 1)
        index_eol, _worktree_eol, attr = info.split(maxsplit=2)
        # `-text` (or `binary`) in .gitattributes opts a file out of
        # normalisation, e.g. an .eml fixture that has to keep CRLF.
        if index_eol in ("i/crlf", "i/mixed") and "-text" not in attr:
            offenders.append(f"{index_eol:8} {path}")
    assert not offenders, (
        "stored with CRLF line endings, although .gitattributes normalises them to LF:\n  "
        + "\n  ".join(offenders)
        + "\nFix: `git add --renormalize <path>`. For a commit through the API, convert "
        "\\r\\n to \\n before base64-encoding. A file that has to keep CRLF needs "
        "`-text` in .gitattributes."
    )
