#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fold the entries in changelog.d/ into CHANGELOG.md, newest first.

    python scripts/changelog.py                  # fold into [Unreleased]
    python scripts/changelog.py --release 1.2.0  # fold, then cut [1.2.0] — <today>

Only the release-prep pull request (or a dedicated fold pull request) runs
this; a feature pull request just adds its file to changelog.d/. Every pull
request used to insert its entry at the same line of CHANGELOG.md, so each
merge left every other open pull request in conflict. New files never
conflict. Fragment names start with the date, so name order is date order.
"""

from __future__ import annotations

import argparse
import datetime
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UNRELEASED = "## [Unreleased]\n\n"
POINTER = (
    "> New entries go in [`changelog.d/`](changelog.d/), one file per change;\n"
    "> `scripts/changelog.py` folds them in here, newest first.\n\n"
)
NAME = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}-[a-z0-9]+(?:-[a-z0-9]+)*\.md")
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")


def fragments_in(fragment_dir: Path) -> list[Path]:
    """Every fragment, oldest first. Anything else in the directory is refused."""
    if fragment_dir.is_symlink():
        raise SystemExit(f"{fragment_dir}: must be a directory, not a link")
    found = sorted(p for p in fragment_dir.iterdir() if p.name != "README.md")
    for path in found:
        if path.is_symlink() or not path.is_file() or not NAME.fullmatch(path.name):
            raise SystemExit(f"{path}: fragments are regular files named YYYY-MM-DD-<topic>.md")
    return found


def fold(changelog: Path, fragment_dir: Path, release: str | None, today: datetime.date) -> int:
    """Move every fragment into ``changelog`` right below the pointer.

    With ``release``, the folded entries and everything already in
    [Unreleased] go under ``## [X.Y.Z] — <today>``. Running the same release
    again (after a pull request merged late) adds the new entries under the
    heading already cut. Returns the number of fragments folded.
    """
    text = changelog.read_text(encoding="utf-8-sig")
    anchor = UNRELEASED + POINTER
    if text.count(anchor) != 1:
        raise SystemExit(
            f"{changelog}: the changelog.d pointer must sit directly under ## [Unreleased]"
        )
    fragments = fragments_in(fragment_dir)
    entries = "".join(
        p.read_text(encoding="utf-8-sig").strip() + "\n\n" for p in reversed(fragments)
    )
    head, rest = text.split(anchor, 1)
    if release is not None:
        cut = f"---\n\n## [{release}] — "
        if rest.startswith(cut):  # a late merge: join the heading already cut
            end = rest.index("\n", len(cut)) + 2
            entries, rest = rest[:end] + entries, rest[end:]
        elif f"## [{release}]" in rest:
            raise SystemExit(f"{changelog}: [{release}] is already released further down")
        elif not entries and rest.startswith("---\n\n## ["):
            raise SystemExit(f"{changelog}: nothing to release")
        else:
            entries = f"{cut}{today.isoformat()}\n\n{entries}"
    changelog.write_text(head + anchor + entries + rest, encoding="utf-8", newline="\n")
    for path in fragments:
        path.unlink()
    return len(fragments)


def main() -> None:
    parser = argparse.ArgumentParser(description="Fold changelog.d/ into CHANGELOG.md.")
    parser.add_argument("--release", metavar="X.Y.Z", help="also cut a version heading")
    args = parser.parse_args()
    if args.release is not None and not VERSION.fullmatch(args.release):
        parser.error("--release takes X.Y.Z, without a leading 'v'")
    count = fold(ROOT / "CHANGELOG.md", ROOT / "changelog.d", args.release, datetime.date.today())
    print(f"folded {count} fragment(s) into CHANGELOG.md")


if __name__ == "__main__":
    main()
