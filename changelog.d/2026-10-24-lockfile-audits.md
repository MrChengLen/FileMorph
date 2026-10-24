### Security — the dependency audit asks OSV too and also checks the uv and SBOM-generator lockfiles

CI's blocking `pip-audit` gate checked one file, `requirements.lock`, against
one source, PyPI's advisory feed. Both limits let an advisory through:

- **The two lockfiles CI installs its own tools from were not audited.**
  `requirements-uv.lock` pins the uv that compiles the lockfiles, and
  `requirements-sbom.lock` the SBOM generator of every release. uv 0.12.23
  stayed on `main` although its bundled CA store trusted a root whose
  intermediate keys were compromised (GHSA-hq85-5cpj-mr62). Both files are now
  audited like `requirements.lock`.
- **PyPI's feed can lack an advisory that OSV lists.** It had no entry for
  PYSEC-2026-4243 (CVE-2026-102991) against Mako 1.4.1, which alembic pulls
  in: a path traversal through a drive-letter URI on Windows. Every lockfile is
  now audited against both sources.

Every audit now reads the pinned versions as written (`--disable-pip`): having
pip resolve the lockfile first left out packages that pip-audit's own scratch
environment already held. `--strict` fails an audit on a package a source
cannot look up instead of skipping it. The weekly `deps-latest` workflow
repeats the audits, so an advisory published in a week without pushes is
noticed too. `tests/test_supply_chain_hygiene.py` fails if a lockfile is no
longer audited against either source, or if the audit step may be skipped, may
fail without failing the job, or runs anything besides the audits.
