### Changed — every CI job stops after a time limit

Each job in `.github/workflows/` now has `timeout-minutes` — 10 to 30 minutes,
a few times its usual run — so a hanging step fails within minutes instead of
holding a runner for GitHub's default six hours. A test fails when a job has
no limit or one over 90 minutes.
