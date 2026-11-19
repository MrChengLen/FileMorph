### Changed — dependency batch: FastAPI 0.162.7, pydantic-settings 2.16.3 and the development tools

Dependabot's weekly `python-all` group (#333) lands in one pull request, with
`requirements.lock` recompiled once. pypdf 7.1.0 and pikepdf 10.18.1 come in
the same batch; their entry is under Security. Every version is the one
Dependabot proposed after the three-day cooldown in `.github/dependabot.yml`.
Newer releases that were still inside it (FastAPI 0.163, pikepdf 10.18.2,
uv 0.13.9) wait for the next batch.

- **FastAPI 0.162.7** (from 0.162.0) declares support for Python 3.15, drops
  Python 3.10 (FileMorph needs 3.11 or newer), and requires AnyIO 4.1.0 or
  newer (the image ships 4.15.0). The cleanup after the `yield` of a
  dependency is no longer cut short when a request is cancelled: 0.162.5
  fixes this for synchronous dependencies, 0.162.7 for async ones.
  FileMorph's database session (`get_db`) is such an async dependency and
  closes its session in that cleanup.
- **pydantic-settings 2.16.3** (from 2.16.2) no longer reads a secret file
  that is a symbolic link to a file outside `secrets_dir`. FileMorph reads its
  settings from the environment and `.env` and sets no `secrets_dir`.

Development tools: ruff 0.17.5, which reformats nothing, and uv 0.13.8
(`requirements-uv.lock` regenerated), which writes the lockfiles in the same
format. pytest-asyncio 1.5.0 only raises the floor: the lockfile does not pin
development tools, so CI already ran this release.
