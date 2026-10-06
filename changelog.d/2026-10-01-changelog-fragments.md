### Changed — changelog entries are one file each in `changelog.d/`

Every pull request used to add its entry directly under `## [Unreleased]` in
this file, the same line every time, so each merge left every other open pull
request in conflict, and a conflicting pull request gets no CI run at all.
Since 2026-09-01, 47 of 72 merged pull requests touched this file, and 22 of
them needed an extra three-commit round just to resolve that line. A
`merge=union` attribute is no way out: GitHub's server-side merges ignore it.

New entries now go in `changelog.d/<YYYY-MM-DD>-<topic>.md`, one file per
change, in the same house style; new files never conflict.
`scripts/changelog.py` folds them in here, newest first, and with
`--release X.Y.Z` it also cuts the version heading in the release-prep pull
request. `tests/test_changelog_fragments.py` checks each file's name and first
line, and fails when an entry is added at the top of this file instead. The
entries already below stay as they are and move under the next version at
release.
