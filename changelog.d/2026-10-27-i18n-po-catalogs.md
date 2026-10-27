### Changed — translations load straight from the `.po` files; no `.mo` in the repository

The app now compiles `locale/<code>/LC_MESSAGES/messages.po` in memory once,
at startup, with the same messages `pybabel compile` produced: fuzzy entries
stay out. The compiled `.mo` files are no longer committed. Each catalogue
change used to add a binary file that conflicted between pull requests, and
`scripts/i18n.py extract` and `update` now also drop the `POT-Creation-Date`
header, which Babel rewrote on every run. A missing or broken catalogue is
logged at startup, and the app serves the English source strings instead of
failing.

- Self-hosters: a source checkout, the release tarball and the Docker image
  work without a compile step, as before. If you customised translations by
  placing your own `.mo` in `locale/`, it is now ignored: edit the `.po`
  instead.
- Contributors: after `extract` and `update`, commit `locale/` as before,
  without running `compile`. A test now runs the placeholder checks that
  `compile` used to run.
