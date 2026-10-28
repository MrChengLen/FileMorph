### Changed — dependency batch: FastAPI 0.162, Starlette 1.10, SQLAlchemy 2.1.6 and five smaller updates

Dependabot's weekly `python-all` group (#273) lands in one pull request, with
`requirements.lock` recompiled once. Every version has passed the three-day
cooldown in `.github/dependabot.yml`. What the image ships now:

- **FastAPI 0.162.0** (from 0.154.0). Three releases in between are marked as
  breaking: unknown keyword arguments to `Form()`, `Query()` and the like now
  raise an error (0.155), a parameter model's `extra` setting also covers the
  fields declared next to it (0.160), and an omitted `bool` form field takes
  its declared default or counts as missing instead of reading as `False`
  (0.162). FileMorph's routes use none of these: no extra keyword arguments, no
  parameter models, no boolean form fields.
- **Starlette 1.10.0** (from 1.6.0). FileMorph imports it directly, so
  `requirements.txt` now lists it: a lockfile recompile keeps a package that
  only FastAPI requires at its old pin, and Dependabot proposes updates only
  for what the file lists. From 1.7 on, its CORS middleware adds `Vary: Origin`
  to every response, so that a shared cache keeps the answers for different
  origins apart. That header is part of how the local engine's files are
  delivered, so `app/static/engine/delivery.js` gets a new fingerprint, and
  every engine URL a new tree hash: a browser that cached an engine file with
  the old headers loads it again. The engine stays off unless
  `LOCAL_TOOLS_ENABLED` is set. The weekly `deps-latest` run, which installs
  the newest releases, had failed on exactly this since 2026-10-24.
- **SQLAlchemy 2.1.6** (from 2.1.5), with ORM fixes, two of them for
  regressions, and alembic 1.20.1 (from 1.20.0), whose fixes are mostly in
  autogenerate.
- **certifi 2026.10.23** (from 2026.10.19). The CA bundle that Stripe calls
  verify against drops two more eMudhra roots, emSign Root CA - C1 and emSign
  ECC Root CA - C3. 2026.10.19 had removed the emSign ECC Root CA - G3
  (GHSA-6q48-6c7w-9gw2).
- **ReportLab 5.1.0** (from 5.0.1) hardens `rl_safe_eval`, the restricted
  evaluator that ReportLab runs document-template expressions through (and
  colour strings, if configured to), against sandbox escapes that allowed code
  execution. None was reachable in FileMorph: TXT → PDF draws the file's lines
  as plain text on a canvas and evaluates nothing.
- The floors for pypdf (6.21.2) and Mako (1.4.3) move up to the versions the
  lockfile already pins.

Development tools: ruff 0.17.2, which reformats nothing, and uv 0.13.5
(`requirements-uv.lock` regenerated), which, after 0.13.4 removed the emSign
root, also rejects certificate chains that contain the compromised eMudhra
intermediate keys. The lockfiles come out in the same format.
