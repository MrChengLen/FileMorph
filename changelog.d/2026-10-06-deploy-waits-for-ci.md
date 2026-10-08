### Changed — the deploy starts only for main's newest commit, once Docker and CI both passed for it

`notify-ops.yml`, which starts the deploy of filemorph.io after a merge to
`main`, used to wait for the `Docker` workflow alone, whichever commit that run
had built. The required checks are not strict and pull requests often merge
within minutes of each other, so a merge result that failed the tests could
reach production as soon as its images were built, and a deploy could pull the
image of a newer commit than the one it had checked. The deploy is now started
only when `Docker` and `CI` (lint, tests, PDF/A validation, dependency audit,
lockfile and secret scans) have both passed for the commit, and only if that
commit is still the tip of `main`, read from git when the check runs; for an
older one, the newer commit's own runs deploy. Either workflow finishing starts
the check and the run of whichever finished last goes on, so one build deploys
once. A manual `Docker` rebuild or a re-run of either workflow deploys again,
for the newest commit on `main`. The deploy pulls a moving image tag: the
dispatch now carries the commit's SHA, and pinning the deploy to it is a
follow-up on the deploy side.

The whole `CI` workflow counts, not only the required checks: while
`lockfile-drift`, which does not block a merge, or a newly published `pip-audit`
advisory keeps it red on `main`, nothing deploys, and the check says so in a
warning. Likewise, while the newest commit on `main` has not passed, an older
green one is not deployed, and neither is a commit whose `CI` run a newer merge
cancelled: the newer commit's own runs deploy instead. `docker.yml` now builds
one commit at a time per branch, so the image tags move in merge order (two
merges seconds apart used to finish out of order, as on 2026-09-26 and
2026-09-28): of several merges in a row the running build finishes, the newest
commit builds next and the ones in between are not built. Tests pin the
trigger, the job and the dispatch's body, and run the check in bash against
stand-ins for the API and `git`: a run for a pull request, a fork or another
branch never counts, a failed or empty answer is asked for again, and a tip
that cannot be read fails the step.
