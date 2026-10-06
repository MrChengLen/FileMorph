# changelog.d — one file per change

A pull request with a user-visible change adds one file here instead of
editing `CHANGELOG.md`. Every pull request used to insert its entry at the same
line of `CHANGELOG.md`, so each merge left every other open pull request in
conflict. New files never conflict.

- **Name:** `YYYY-MM-DD-<topic>.md`. Use the day you write it and a short
  topic, e.g. your branch name without its prefix. Lower case, digits and `-`
  only. Save as UTF-8 with LF line endings. (In Windows PowerShell 5.1, `>`
  and `Out-File` write UTF-16; use your editor instead.)
- **Content:** one entry in the changelog's house style. The first line is
  `### Added|Changed|Deprecated|Removed|Fixed|Security — <headline>`, with an
  em dash, followed by the paragraphs and bullets. No `#` or `##` headings.
- **Scans:** `CHANGELOG.md` is exempt from the commit hooks' content checks
  and the scope guard's ops-name check; these files are not. Describe
  ops-only names (secrets, hosts, server paths) instead of spelling them out,
  and never write `NAME=value` lines for secret variables.
- **Status:** an entry here is on `main` but not yet in a tagged release.
- **Order:** entries come out newest first by the date in the name; files
  from the same day are in reverse alphabetical order.

Feature pull requests never edit `CHANGELOG.md` and never run the script.
Only the release-prep pull request (or a dedicated fold pull request) runs
`python scripts/changelog.py --release X.Y.Z`. It folds the files into
`CHANGELOG.md` under `## [X.Y.Z] — <date>`, newest first, and deletes them.
If a pull request merges after that, run the same command again: the late
entry joins the heading already cut. Without `--release`, the script folds
the files into `[Unreleased]`.

`tests/test_changelog_fragments.py` checks names and first lines. It also
fails if an entry is added at the top of `CHANGELOG.md` instead.
