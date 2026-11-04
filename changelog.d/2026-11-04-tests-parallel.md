### Changed — CI runs the test suite on every CPU of the runner

- `lint-and-test` and the weekly `deps-latest` run start pytest with
  `-n logical` (pytest-xdist, a new development dependency): one worker per
  vCPU
  instead of one process for all 3,400 tests, which took about 2.7 of the
  job's 5 minutes.
- Each test file stays on one worker (`--dist loadfile`), so the Postgres
  tests, which share one database and empty its tables before each test, run
  one after another.
- Under xdist every worker gets a temp directory of its own, so the tests
  that compare the `fm_*` directories before and after a request never see
  another worker's.
- `pytest tests/` without `-n` still runs the suite in one process, as
  before.
