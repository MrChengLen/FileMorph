### Changed — CI reports every check on the run page, and a merge's checks no longer wait in line

- Every check of the required `lint-and-test` job now runs even after an
  earlier one failed, so one red run shows them all. A newly published
  advisory used to stop the job at the dependency scan and leave the test
  suite unrun (13 times in two weeks). The dependency-scan and PDF/A steps
  keep their strict conditions.
- The job ends with a summary on the run page: every check with its result,
  the test counts and the 15 slowest tests. The test log lists skipped and
  failed tests with their reasons instead of one line per passing test, and
  each lockfile and advisory source of the dependency scan is a named step of
  its own.
- On `main` every commit gets a CI run of its own instead of queueing behind
  the previous merge's; on 2026-11-04 the commit about to be deployed waited
  three minutes.
- Every job runs on Ubuntu 26.04 instead of `ubuntu-latest`, which changed
  under CI in November 2026. The weekly `deps-latest` run keeps
  `ubuntu-latest`, as an early warning for the next image.
- The deploy trigger says on each run whether it dispatched a deploy, and why
  not otherwise. It retries the dispatch after a transient error and warns two
  weeks before its token expires.
- The vendored-code advisory check warns two weeks before an accepted
  advisory's review date.
- The checkouts of the CI, weekly-dependency and scope-guard workflows no
  longer keep the workflow token in the working copy, and an obsolete Node 24
  switch is gone.
