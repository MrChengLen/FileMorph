# Changelog

All notable changes to FileMorph are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versions follow [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Security — the Docker image is built without a restored build cache

`docker.yml` restored BuildKit's GitHub Actions cache (`cache-from: type=gha`)
in the job that holds `packages: write` and the cosign signing identity, on
tag builds and on main. Every job that runs on main can write that cache,
whatever its `permissions:` say — the cache token can be read from the runner
process — and jobs there install PyPI releases that no lockfile pins, such as
`ci.yml`'s lint-and-test (the dev tools) and the weekly `deps-latest.yml`.
BuildKit reuses a cached layer without re-running its step, so a malicious
release could have planted the layer for `pip install --require-hashes -r
requirements.lock`. The image would then have carried packages no hash was
checked against and been signed all the same — and deployed from main, or
named in a release's `IMAGE_DIGEST.txt` from a tag. Found by the security
review of PR #163; it took a compromised upstream release, not an outside
push.

- **No cache on any build.** The build step sets `no-cache: true` and neither
  restores nor exports a cache, and `setup-buildx-action` gets
  `cache-binary: false`, so a buildx binary it downloads would not go through
  the cache either. Main gets no exception: its builds read main's entries
  directly and deploy.
- **What it costs.** A warm cached build took 29 s for the slim image and 75 s
  for the office image; built cold, they take about 60 s and 110 s. Every
  build now installs the current Debian packages (ffmpeg, Ghostscript, …)
  instead of reusing a cached layer, and those layers get new digests each
  time: pulling an update downloads everything above the Python base image —
  about 300 MB compressed for the slim image, 440 MB for the office image —
  not only the layers after `COPY . .`.
- **Guards.** `tests/test_supply_chain_hygiene.py` now fails if any job that
  holds a write token or a secret restores or saves an Actions cache — an
  `actions/cache` step, or a cache input that does not switch caching off —
  or if `docker.yml` drops `no-cache: true` or `cache-binary: false`. Each of
  14 simulated regressions, a tag-only `no-cache` among them, fails at least
  one guard.

### Added — `API_KEYS_FILE_TIER`: API keys on a self-hosted instance can run on a bigger tier

Without `DATABASE_URL` there are no accounts, so every caller of a Community
Edition instance ran on the anonymous tier — 30 MB per file, 1 file per
batch, a 90 MB output cap, 1 concurrent request per client IP — including
callers with a valid key from `data/api_keys.json`: without a database
`get_optional_user` returns `None`, and `tier_for(None)` is `anonymous`. Short
of editing `app/core/quotas.py` an operator could not change that, and the
docs did not say it: `docs/installation.md` described the Community Edition
as "anonymous + API-key auth" without the caps, `docs/self-hosting.md` did
not mention them, and `docs/api-usage-guide.md` told self-hosters to raise
`MAX_UPLOAD_SIZE_MB` "if the larger tier limits should apply", which it
could not do on its own. The caps are sized for the hosted service's server;
on a self-hosted instance the operator's hardware sets the limit.

The new setting `API_KEYS_FILE_TIER` (default `anonymous`, so nothing changes
unless an operator sets it; empty means `anonymous` too) names the tier keys
from the key file run on: `free`, `pro`, `business` or `enterprise` gives them
that tier's file size, batch size, output cap and concurrency on convert,
compress and the PDF page routes (`app/api/deps.py::caller_tier`). Accounts
keep their own tier; callers without a key — the web UI included — stay
anonymous; the AI routes keep reading the account's tier, because their
credit ledger needs an account. An unknown value stops the start-up instead
of falling back to anonymous. Keyed requests on a lifted tier get their own
per-IP concurrency slot: `actor_id(request, user, tier)` now requires the
tier, because the per-actor semaphore is rebuilt whenever its tier's cap
changes, so keyed and keyless requests alternating on one IP would otherwise
lift the cap. The file-size and output-cap messages pick their "register"
wording by tier instead of by "no account", so a lifted key is not told it
is anonymous. The first-run banners (`entrypoint.sh`, `run.py`) no longer
point to an "API Key" field in the web UI, which has none; they name the
`X-API-Key` header. Documented in `.env.example`, a new "Limits on a
Community Edition instance" section in `docs/self-hosting.md` (including how
much memory and how many parallel slots one key can take),
`docs/installation.md`, `docs/api-usage-guide.md` and
`docs/api-reference.md`; pinned by `tests/test_api_keys_file_tier.py` (the
Community Edition chain, the setting on all seven engine routes, the web-UI
and AI boundaries) and three new checks in `tests/test_docs_match_code.py`.
`scripts/make_testdata_api_keys_file_tier.py` writes byte-stable fixtures for
checking this by hand (two small pictures and a 35 MB BMP) to a gitignored
local folder; only the script ships.


### Security — the Cloud Edition refuses to start with a public or short `JWT_SECRET`

With `DATABASE_URL` set, every login is a JWT signed with `JWT_SECRET`, and
nothing checked that value. Without it the app fell back to the default in
`app/core/config.py`, which `.env.example` also set outright, and
`docker-compose.cloud.yml` filled in a placeholder of its own. Both strings are
published in this repository, so on a deployment running with either one,
anyone who knew an account's id (random, but not secret: it is readable in the
tokens and email links the app issues) could sign a valid login token for that
account. Admin routes re-read the role from the database, so a forged token
could not turn an ordinary account into an admin, but a token for an admin's
id was an admin session. Since PR #144 a self-built image no longer carries a
`.env`, which made a `docker run` without `JWT_SECRET` more likely.

- **The app stops at start-up** when `DATABASE_URL` is set and `JWT_SECRET` is
  unset, one of the two placeholders (also in quotes or with trailing spaces),
  or shorter than 32 characters. The log reads `Refusing to start`, names the
  reason and says what to set where; it never prints the secret. The process
  exits with status 3, which uvicorn and gunicorn treat as a failed start, so a
  server with several workers stops too instead of restarting them forever.
  The check runs when `app.main` is imported, so no server option can skip it,
  and `alembic`, which the entrypoint runs first, does not import it. The
  Community Edition (no `DATABASE_URL`) issues no logins and still starts
  without `JWT_SECRET`.
- **`docker-compose.cloud.yml` has no fallback any more.** Without
  `JWT_SECRET`, every `docker compose` command that includes the overlay stops
  with a message.
- **`.env.example`** leaves `JWT_SECRET` commented out, next to a command that
  generates one.
- Generating a random secret at start-up instead was rejected: each worker
  process would sign with its own, and every restart would sign everyone out.

`docs/self-hosting.md` has a new "JWT secret (Cloud Edition)" section and a
checklist item; it recommends handing the secret over in a file (`--env-file`,
systemd `EnvironmentFile=`) rather than `docker run -e` or a systemd
`Environment=` line, which every local user can read. The installation guide
and the security overview say what the check does; the API reference listed a
missing `JWT_SECRET` among the causes of a `503`, which it never was.
`tests/test_jwt_secret_guard.py` imports the app in a fresh interpreter with
and without a usable secret, and fails if the compose overlay or
`.env.example` gets a value again.

**Upgrading:** a Cloud Edition deployment that ran without its own
`JWT_SECRET`, or with a placeholder or a shorter one, will not start after this
update. Generate a secret with
`python -c "import secrets; print(secrets.token_urlsafe(32))"`, set it as
`JWT_SECRET` in `.env` or the container's environment, and start again. With
Docker Compose, set it before any command that includes
`docker-compose.cloud.yml`, `down` and `logs` too; the running container keeps
the old secret, and stays exposed if that was a placeholder, until `up -d`
succeeds. Tokens signed with the old secret stop working, so everyone has to
log in again.

If such a deployment was reachable from the internet, anyone who knew an
account's id could have acted as that account. The new secret ends those
sessions but not what they created: revoke API keys you don't recognise
(`api_keys`, by `created_at` and `last_used_at`), and check `users.role`,
`users.tier` and `users.is_active` for changes you didn't make; the app log
records admin changes as `cockpit.patch_user` and `cockpit.soft_delete`.

### Fixed — Impressum names the Wirtschafts-Identifikationsnummer; dead EU ODR link removed

The Impressum still said a Wirtschafts-Identifikationsnummer "will be added
once issued". It has been issued, and § 5 (1) Nr. 6 DDG requires stating it,
so the page now shows it (DE463352637) in both languages. The number sits
next to the translated label, not inside it. The link to the EU Online
Dispute Resolution platform is gone: the platform was shut down on
2025-07-20, so the link pointed nowhere. The § 36 VSBG statement stays. A
new test in `tests/test_public_pages_reachability.py` pins all three in both
locales, next to the existing guard that the Steuernummer is never shown.

### Fixed — the lockfile jobs no longer fall behind a uv bump

`lockfile-drift` in `ci.yml` and the `deps-lock` workflow recompile the
lockfiles with uv, and a different uv release can write the same lockfile
differently, so both are meant to run the uv that `requirements-dev.txt` pins.
They had the version typed in, though, and Dependabot only bumps
`requirements-dev.txt`, so the workflows fell behind it twice: on 0.12.13
while it moved to 0.12.16, then on 0.12.16 while it moved to 0.12.19, where
main stood until now. Both workflows now read the version from
`requirements-dev.txt` and install it as a wheel, so a bump there moves them
too, and they stop if the file has no `uv==` line (pip would take the empty
result as nothing to install and succeed). A new test in
`tests/test_supply_chain_hygiene.py` requires that line to be a bare
`uv==X.Y.Z`, and fails if any workflow pins its own uv or a job that compiles
a lockfile installs uv any other way. uv 0.12.19 writes both lockfiles byte
for byte as 0.12.16 did, so neither is recompiled.

### Security — git ignores `.env.local`, `.env.production` and the other local `.env.*` files

`.gitignore` listed `.env`, which matches only that exact name. A
`.env.local`, `.env.production` or `.env.staging` in a working folder therefore
showed up as an untracked file, and `git add -A` staged it. The pre-commit hook
blocks `.env.production*` by name, and other files only when they assign one of
the secret variables it lists. A commit created through the GitHub API
(`createCommitOnBranch`) skips local hooks altogether, and the secret scan in
CI recognises secrets by their format, not by the file they sit in. No such
file was ever committed: `.env.example` is the only `.env` file in the history.

`.env.*` now covers the variants. `!.env.example` below it exempts the
template, since the last matching line wins, so `git add` and tools that
honour `.gitignore` still see it. `tests/test_gitignore.py` asks
`git check-ignore --no-index` about `.env`, `.env.local`, `.env.production`,
`.env.staging` and the nested `app/.env` and `app/.env.local` (all ignored),
and about `.env.example` (not ignored). It accepts only a rule from the
repository's own `.gitignore`, so a global excludes file on one machine
cannot hide a regression.

### Changed — the web UI offers target-size compression for AVIF too

The server has compressed AVIF to an exact target size since AVIF support
landed, but the web UI offered "By target size" only for JPEG and WebP: with
an AVIF file selected, the option silently disappeared. The UI now offers it
for AVIF as well — `TARGET_SIZE_FORMATS` in `app/static/js/app.js` matches
the server set in `app/compressors/image.py` again, pinned by the new
`tests/test_target_size_formats_parity.py`. AVIF encoding is CPU-heavy and
the binary search re-encodes several times (measured locally on two cores:
about 7–11 s for a 4-megapixel image, about 30 s for a 12-megapixel photo),
so the target-size section shows a note when an AVIF file is selected: a
large photo can take a minute or more, so AVIF batches should stay small.
Every text that said "JPEG/WebP" now names AVIF too — the mode hint in the
tool, the homepage FAQ, `/formats`, `/compress` (title, meta description,
heading, intro, limits incl. the duration caveat, how-it-works, FAQ), the
`/tools` card, `/llms.txt` and `docs/formats.md`. Two API texts were wrong
and are fixed: the OpenAPI description of `target_size_kb` (single and
batch) and `docs/api-usage-guide.md` claimed JPEG/WebP only, although the API
already accepted AVIF; the guide's timing list and target-size example now
allow for slow AVIF encodes. Rate limit, concurrency caps and output caps are
unchanged; the API already offered AVIF target-size without a key. Also
fixed on the way: clearing the file selection hid only the quality slider,
so the compression-mode toggle and target-size section (now including the
AVIF note) stayed on screen with no file selected.
`scripts/make_testdata_avif_target_size.py` writes byte-stable fixtures for
checking this by hand (a 4- and a 12-megapixel AVIF, plus a JPEG twin) to a
gitignored local folder; only the script ships.


### Security — account, API-key and billing routes are rate-limited; failed API keys are throttled

`app/core/rate_limit.py` set `default_limits=["60/minute"]`, but slowapi only
applies those through `SlowAPIMiddleware`, which the app never installed — so
only routes with their own `@limiter.limit(...)` were limited. Stripe checkout
and portal, creating, listing and revoking API keys, `/auth/refresh`,
`/auth/me` and `/auth/account/language` had no limit at all (70 ×
`GET /api/v1/keys` → no 429). A free account could create API keys without
bound, each with a label of any length, and every checkout request writes an
audit row and calls Stripe.

The account routes now have explicit limits, counted per signed-in account
rather than per IP: checkout and portal 5/min, key creation 10/min, key
revocation 30/min, key list 120/min, email language 10/min. Per account,
because a per-IP limit would let one free account use up checkout or key
revocation for everyone behind the same IP — an office, or every visitor when
the proxy doesn't forward client IPs. Limits are checked after the
dependencies, so the token is already verified when the key is derived from
it.

Three routes are exempt on purpose, each with its reason next to the
decorator:
- The Stripe webhook: Stripe signs every delivery and retries failed ones.
- `/auth/me`: its limit would be checked only after the token check and the
  DB lookup have run, so it would protect nothing, while the web UI calls it
  on every page view and a 429 sends the dashboard to `/login`.
- `/auth/refresh`: a request costs one signature check, and the web UI signs
  the user out when a refresh fails, so junk requests exhausting a per-IP
  limit would sign out everyone behind that IP.

The dead default is gone, and the limiter now counts per route instead of per
URL, so `DELETE /api/v1/keys/<id>` has one budget whatever the id. That also
applies to the cockpit's per-user `PATCH`/`DELETE` (10/min per admin IP across
all users; it used to be per target user). slowapi no longer writes its
"ratelimit exceeded" warnings, which carry the client IP or account id, to the
log: the privacy policy promises that rate-limiter IPs stay out of the logs.

An account holds at most 25 active API keys. Beyond that, `POST /api/v1/keys`
returns `409`, and the dashboard says to revoke an unused key first — it used
to reset the button silently on any failure. Key labels are capped at 100
characters.

Failed `X-API-Key` attempts were never limited either. The key check is a
FastAPI dependency and rejects a wrong key before any route limit runs (25
random keys → 25 × 401, 0 × 429). `require_api_key` now counts rejected keys
per IP across all upload routes: the first 30 per minute get `401`, later ones
`429` with `Retry-After`. The count starts only after both the key file and
the database have said no. A valid key is therefore never refused, so a
script stuck on a revoked key can't lock out its colleagues behind the same
IP — or, where the proxy doesn't pass client IPs through, every API user at
once. Requests without a key behave as before. Keys are 256-bit random values,
so this is about telling broken clients to back off, not about guessing.

`docs/api-reference.md` now lists every API endpoint with its limit and
whether it counts per IP or per account, or with the reason it has none. It
used to claim "3–5/min" for all of `/auth/*`, although refresh, `/me` and the
email language had no limit. It also claimed 5/min for billing, which had
none, and a 60/min default that never applied. And it left out the PDF, AI
and cockpit routes. It now also says that "per IP" behind a proxy needs
`FORWARDED_ALLOW_IPS`, and, behind a CDN, the visitor's address from the CDN's
header. The API usage guide and the error table say what to do about the new
`429`: fix the key, because waiting doesn't help. Two new tests fail CI when an
API route has neither a limit nor an explicit exemption, or when the table and
the code disagree. The security
overview no longer describes a 60/min bucket. The pentest report's PT-006
gets a correction note: its "60 requests/minute" and "60 guesses/minute" never
applied.

### Security — the release job no longer runs unpinned code next to its write token

A security review of PR #146 found that `release.yml`'s single job held
`contents: write`, kept the checkout's credentials, restored the pip cache
shared with the workflows on main, and then installed the CycloneDX generator
— about thirty packages, unpinned and unhashed — between building the source
tarball and publishing it. A malicious generator release, or a cache entry
planted by code merged to main, could have replaced the tarball, forged the
SBOM or `IMAGE_DIGEST.txt`, or used the token. Release tags must be
GPG-signed, so this took a compromised upstream package or main-branch code,
not an outside push.

- **Two jobs.** `sbom` installs the image's dependency set and the generator
  and runs it with `contents: read`. `verify-and-publish` holds
  `contents: write`, installs nothing and receives the SBOM as an artifact,
  downloaded into a directory of its own so it cannot replace the tarball or
  anything else the job reads. Neither job restores a cache or keeps the
  checkout's credentials, and `sbom.yml` now runs the same way. Hashes alone
  would not make a cache safe: pip installs a wheel it once built from an
  sdist on the strength of the sdist's recorded hash. The publish step now
  fails, rather than releasing without the file, if an attachment pattern
  matches nothing.
- **Hash-pinned generator.** `sbom.yml` and `release.yml` install it from the
  new `requirements-sbom.lock` with `--require-hashes --only-binary :all:`:
  32 packages around `cyclonedx-bom` 5.5.0, wheels only, so no unhashed build
  dependency can slip in. The lockfile is compiled from
  `requirements-sbom.txt`, which Dependabot updates like `requirements.txt`.
  A lockfile that no longer satisfies it fails the required test job,
  `lockfile-drift` flags any other difference, and `deps-lock` recompiles
  both lockfiles — and, since it can push, no longer restores the pip cache.
  Dependabot leaves the major version alone: 5.5.0 is the last 5.x release,
  and 7.x no longer accepts `--PEP-639`, so that move stays deliberate.
- **Shell injection (CWE-78, low).** `release.yml` pasted the tag-derived
  image name into a shell script as `${{ }}`, and `deps-lock.yml` did the same
  with the branch name before `git push` — git allows `$(` and backticks in
  both. Both values now arrive through `env:`.
- **veraPDF** runs `verapdf/cli` pinned by digest — v1.30.2, which is what
  `latest` pointed at — instead of the moving `latest` tag. Dependabot does not
  track images in workflow scripts; the comment next to the pin says how to
  move it.
- **SBOM licences.** `cyclonedx-py` now runs with `--PEP-639`. Without it
  cyclonedx-bom 5.x ignores the `License-Expression` field, so packages that
  declare their licence only there were listed without one: 30 of the 78
  components in the SBOM built from main at `c13ed52`, FastAPI, Starlette,
  Pydantic, cryptography, Pillow, pikepdf, pypdf and uvicorn among them. With
  the flag, all 78 have one; the components and their versions are unchanged.

`release.yml` only runs on a signed tag and cannot be tried on a PR, so its
three SBOM steps are `sbom.yml`'s verbatim — and `sbom.yml` can be dispatched
on a branch. `tests/test_supply_chain_hygiene.py` fails if the two differ, and
guards the job split, the hashed wheel-only installs, the lockfile and the
commands that compile it, the absent caches and credentials,
`fail_on_unmatched_files`, the `env:` handling, the digest pin and
`--PEP-639`. Each of 28 simulated regressions fails at least one guard.

### Fixed — CI tests, and the SBOM lists, the versions the image ships

The image installs `requirements.lock`. Four workflows still installed
`requirements.txt`, whose `>=` ranges resolve to the newest releases, so what
they tested or described was not what ships.

- **Tests.** `lint-and-test` ran against whatever was newest on PyPI — that is
  how SQLAlchemy 2.1.0 failed a test on every branch while production stayed
  on 2.0.52. It now installs with the lockfile as a constraints file, so every
  runtime package is at its shipped version. The dev-only tools (pytest, ruff,
  uv, aiosqlite, …) are not in the lockfile and resolve as before; a dependency
  they share with the app stays at the locked version. The constraints are the
  lockfile's pins without their hashes, because pip turns on `--require-hashes`
  for the whole install as soon as one constraint carries a hash. A
  `requirements.txt` floor raised past the locked version (the usual
  Dependabot pip PR) now fails this job's install as well as `lockfile-drift`;
  recompiling the lockfile fixes both.
- **The early warning stays.** The unpinned run caught SQLAlchemy 2.1 before
  any lockfile bump would have pulled it in. It now runs in the new
  `deps-latest` workflow — weekly on Mondays and on demand — and gates nothing.
- **SBOM.** `sbom.yml`, and `release.yml` for the copy attached to releases,
  built the SBOM from the runner's Python after `pip install -r
  requirements.txt` plus the CycloneDX generator. The one produced for main
  at `1d7bad6` listed 106 packages against 77 in the lockfile: 19 locked
  packages at a version the image does not contain (SQLAlchemy 2.1.1 instead
  of 2.0.52), plus 28 that belong to the generator (`cyclonedx-bom` and its
  dependencies) — whose install had also downgraded `packaging` to 25.0,
  while the image ships 26.3. Both workflows now install the lockfile into a
  fresh venv exactly as the Dockerfile does, install the generator outside it,
  and point `cyclonedx-py environment` at that venv. (`cyclonedx-py requirements
  requirements.lock` reads the hashed lockfile fine, but its SBOM has no
  licence data and no dependency graph.) An SBOM from before this change can
  list extra packages and versions ahead of the image.
- **veraPDF.** The PDF/A-2b gate built its fixture with the newest pikepdf; it
  now installs the lockfile the way the image does.

`tests/test_supply_chain_hygiene.py` pins all four, so none of them can
quietly go back to the manifest.

### Fixed — `requirements.lock` caught up with three Dependabot floors; `uv` pinned alike

Dependabot raised the floors for `pikepdf` (`>=10.13.0.post1`), `aiosmtplib`
(`>=5.1.3`) and `alembic` (`>=1.20.0`) in `requirements.txt`, and the three
PRs were merged one at a time without recompiling the lockfile, so
`lockfile-drift` had been red on `main` since. Production was unaffected: the
image installs only `requirements.lock`, so it kept shipping the previous,
tested versions. The lockfile is recompiled with the command in its header;
exactly those three packages move (pikepdf 10.12.0 -> 10.13.0.post1,
aiosmtplib 5.1.2 -> 5.1.3, alembic 1.19.2 -> 1.20.0), every other pin stays.
With this recompile, the next image ships them.

Dependabot's `python-minor-patch` group (#132) moved `uv` to 0.12.16 in
`requirements-dev.txt` only, while `ci.yml`'s `lockfile-drift` job and the
`deps-lock` workflow still installed 0.12.13. Both now pin 0.12.16 as well, so
a lockfile compiled locally with the dev pin and the one the gate recompiles
come from the same resolver — the same three-place move as in the two
dependency batches below.

### Security — self-built images no longer bake in `.env`, API keys or `.git`

The runtime stage of the `Dockerfile` copies the whole build context
(`COPY . .`), and the repository had no `.dockerignore`. An image built from a
working folder therefore carried whatever lay in it: a real `.env`, which the
app then reads from `/app/.env` at start-up, plus `data/api_keys.json`, `.git`,
`.venv` and `.claude/` (CWE-538). Anyone with the image could read those files
back out of its layers, and a container started from it without a `./data`
volume accepted the builder's API keys instead of generating its own.

A new `.dockerignore` keeps secrets and local state (`.env*`, everything in
`data/` except `.gitkeep`, Compose override files), version-control, editor and
assistant state, Python environments and caches, local-only notes and the test
suite out of the build context.
`tests/test_dockerignore.py` evaluates the patterns the way Docker does and
checks both directions: those paths stay out, and every tracked file except the
dev-only ones (`tests/`, `.github/`, `.githooks/`, `.env.example`) stays in. The
Docker workflow only builds after merge, so a pattern that dropped a runtime
file would otherwise first show up as a broken image.

Images published by CI are built from a clean checkout, so they never contained
a `.env` or API keys; they did include that checkout's `.git` directory, the
test suite and the CI configuration, which are now left out as well. Images
built up to 2026-05-26 (with `actions/checkout` v4) also held the build job's
`GITHUB_TOKEN` in `.git/config`; GitHub revokes that token when the job ends,
so there is nothing to rotate.

**If you build the image yourself:** a `.env` in the build folder no longer
reaches the container through the image. Docker Compose is unaffected: it
passes `.env` at run time (`env_file`) and mounts `./data` as a volume. With
plain `docker run`, pass `--env-file .env -v "$PWD/data:/app/data"`; in Cloud
mode, make sure `JWT_SECRET` arrives, because without it the app now refuses to
start (see the `JWT_SECRET` entry above). If you pushed or shared an image
built before this change, treat the secrets in that `.env` (JWT secret,
database and SMTP passwords, Stripe keys) and any credential in its
`.git/config` as exposed, and rotate them. A container that ran such an image
with a named volume for `/app/data` copied the baked `api_keys.json` into that
volume; delete it there and restart to get a fresh key.

### Fixed — security docs named `requirements.txt` as the CVE-scan target

Since 2026-09-09 (PR #112) CI has run `pip-audit -r requirements.lock`: the
lockfile pins every direct and transitive Python dependency to an exact version
and hash, and it is what the image installs, while `requirements.txt` states
only version ranges. Four public docs kept quoting
`pip-audit -r requirements.txt` — among them the DPA's TOM annex, which a
procurement reviewer reads as a statement of fact — and several, §11.4 of the
vendor questionnaire included, said dependencies were pinned in
`requirements.txt`.

Corrected: `dpa-tom-annex.md` (supply-chain controls), `security-overview.md`
(self-hoster checklist item 5, CVE history, update cadence),
`security-pentest-report.md` (resolution status), `tech-stack-rationale.md`
and §11.4 of `vendor-security-questionnaire.md`. Self-hosters who fork are now
told to recompile `requirements.lock` and audit that, and `development.md`
says to recompile it after adding a package. Two more stale claims in the same
lists are gone: `security-overview.md` still called `pip-audit` a non-blocking
check, and it and the questionnaire listed Dependabot as "on the backlog",
although Dependabot (configured in `.github/dependabot.yml`) has opened weekly
update PRs since May. Both now also say that Dependabot does not touch the
lockfile, so a Python update reaches the image once the lockfile is
recompiled.

The two docs corrected in PR #112 each kept one inaccurate sentence.
`patch-policy.md` said the audit blocks the merge on High and Critical
findings, implying lower severities pass; `pip-audit` has no severity
threshold, so any finding fails the build until it is fixed or waived with
`--ignore-vuln`, as the Moderate CVE-2026-55073 was. §8.2 of the questionnaire
said CI blocks any drift between `requirements.txt` and the lockfile; the
`lockfile-drift` job flags drift without blocking a merge, and the sentence now
says so.

`tests/test_supply_chain_hygiene.py` now fails if `ci.yml` stops auditing the
lockfile, or if a tracked doc under `docs/` or a top-level `.md` file quotes a
`pip-audit -r` target other than `requirements.lock`.

### Removed — the Windows desktop build, which had never run

`build-desktop.yml` was meant to attach a `FileMorph-Windows.zip` (the app
bundled with PyInstaller, plus ffmpeg) to every GitHub release. It triggered on
`release: published`, but `release.yml` publishes releases with the built-in
`GITHUB_TOKEN`, and GitHub starts no workflow runs for events caused by that
token — the trap that once left v1.1.0 without its SBOM. The workflow never
ran, not even by hand, so no release ever carried the ZIP; the README's
download link for it had already been removed as dead in May 2026.

It is retired rather than repaired: the spec bundled no translations
(`locale/`), so the German interface would have shown English without a
warning, the build provided none of the GTK libraries WeasyPrint needs on
Windows to render Word, HTML, Markdown and email to PDF, and an unsigned
executable without an SBOM would have been the one unverifiable release
artifact. On Windows, FileMorph runs with Docker Desktop (`start.bat`) or from
source (`dev.ps1`). The workflow, `filemorph.spec`, `pyinstaller` and the
PyInstaller-only `.gitignore` entries are gone; the frozen-mode code in
`run.py` and `app/compat.py` stays (inert from source).

`tests/test_workflow_triggers.py` now fails CI if any workflow triggers on
`release`, so work that follows a release goes into `release.yml` itself.

### Fixed — API docs: status codes, error texts and Retry-After match the code

A second pass over the public docs, after the tier-limit fix below, found more
statements the code contradicts. Each one was checked against the route that
answers before it was changed.

- **`/formats` is rate-limited.** The API guide called it "unlimited"; it
  allows 120 requests/min per client IP, and it does not count toward the
  monthly API calls. The guide's `can_convert()` example read
  `formats["convert"]`, a key the response does not have — it now reads
  `formats["conversions"]`.
- **Batch `target_formats` needs one entry per file.** A count mismatch
  returns `422`, not `400`. The API reference said a single value applies to
  every file, and its example (three files, one target) got that `422`.
- **Error texts:** the guide quoted `"Output too large; try WebP/AVIF or
  upgrade."`; the output-cap errors read `"Output too large (N MB > M MB
  cap)."` plus a hint that differs between `/convert` and `/compress`. The
  file-size `413` is quoted as sent, too.
- **Batch manifest example:** entries carry the output file's name
  (`one.png`, not `one.jpg`) and the operation reads `convert`, not
  `convert_batch`.
- **`Retry-After`:** a `429` from the rate limiter carries none, but the
  per-tier concurrency `429`, the monthly-quota `429` and the `503` of a server
  at capacity do. The guide said no response had one, the API reference only
  the `503`. The guide's backoff example now honours the header and gives up
  on waits longer than two minutes, such as a used-up monthly quota.
- **Error bodies:** not every error is `{"detail": …}` — the rate limiter's
  `429` is `{"error": "Rate limit exceeded: 10 per 1 minute"}`, and a batch
  where every file failed returns `{"summary": …, "files": […]}`.
- **Status and header tables:** `413` also covers the tier's file and output
  caps, and the guide's status table gained `415`. `X-Output-SHA256` is only
  sent on single-file `/convert` and `/compress`, not on batch ZIPs, and
  `X-FileMorph-Achieved-Bytes` is sent by `/pdf/compress` as well.
- **Magic-byte rejections** are `400 "File type not permitted."`, not `415`
  (architecture doc and threat model). The API guide also said the check
  applies "regardless of whether a converter for that pair exists"; an
  unsupported pair fails first, with `422`.
- **Self-hosting guide:** "No rate limits" was wrong — the per-IP limits are
  route decorators that run on every instance. It now says where to change
  them.
- Code comments with old numbers (monthly quotas, the pro tier's output-cap
  headroom, the concurrency limiter's actor key, two test docstrings) now match
  `app/core/quotas.py` and `actor_id`.

`tests/test_docs_match_code.py` now also calls the routes and compares their
status codes, error messages and the manifest shape with what the docs quote,
and `tests/test_rate_limit.py` pins the rate-limit `429` itself: its body, and
no `Retry-After`.

### Fixed — `docs/formats.md` left out ICO and PDF → PDF/A

The conversion tables in `docs/formats.md` (linked from the README and from
the app's DOCX engine notice) had fallen behind the converter registry. The
Images table had no ICO row, although ICO converts to every other image format
FileMorph writes and to PDF; the HEIC / HEIF, WebP, BMP, TIFF / TIF and GIF
rows didn't list ICO as a target, although all of them convert to it; and the
Documents table had no PDF → PDF/A-2b row. The Video section also still said
every conversion uses libx264 + AAC — codecs are chosen per target container
(VP9 + Opus for WebM, MPEG-4 Part 2 + MP3 for AVI, WMV2 + WMA for WMV, H.264 +
AAC for the rest).

New tests in `tests/test_format_lists_match_registry.py` compare the tables
with the registry: for each From cell (e.g. "TIFF / TIF"), the To cells must
list exactly what the registry converts each format named there to, minus the
format itself. Rows sharing a From cell are merged, since the Documents and
Spreadsheets tables give each pair its own row and note. Every source in the
registry must appear in a table or in the Audio/Video lists, and the "any of
the above can be converted to any other format" sentence under those lists is
checked too.

### Added — QA fixture generator for the batch ZIP names

`scripts/make_testdata_batch_zip_names.py` writes byte-stable fixtures for
checking the batch-ZIP fix below by hand: three small images whose PNG names
collide, a CSV that converts to `manifest.json`, and a file with a `.jpg` name
that fails to convert. Output goes to a gitignored local folder; only the
script ships.

### Fixed — batch ZIPs could contain two files with the same name

When two files in a batch produce the same output name, the later one gets a
numeric suffix (`a.png`, `a_1.png`, `a_2.png`). The counter only knew the
original names, so a suffixed name that was already taken went into the ZIP a
second time: files that became `a.png`, `a.png` and `a_1.png` came out as
`a.png`, `a_1.png`, `a_1.png`, and unzipping could keep only one of the two
`a_1.png`. An output named `manifest.json` in a batch with a failed file
clashed the same way with the report of that name. `build_batch_zip` now
tracks every name it has written and never reuses one — the third file above
becomes `a_1_1.png`, the output named `manifest.json` becomes
`manifest_1.json` (it keeps its name when no file failed, since there is no
report then). Plain duplicates are named as before, and a failed file still
takes no name. The API guide's "Duplicate filenames" section describes the
rule and points API clients to the `X-FileMorph-Batch-Failed` header, rather
than the file name, to tell whether a report is present. New unit tests in
`tests/test_batch_zip.py`.

### Fixed — a plan change did not change the concurrency limit until a restart

How many requests a user (or, when anonymous, an IP) may run at once depends
on the plan: Free 1, Pro 3, Business 6. That limit was fixed when the server
first saw the user and kept until the next restart, so a user who upgraded
from Free to Pro still got `429` on their second parallel request, and a
downgraded user kept the higher limit. The workaround the code comment
suggested — minting a new API key — did not help, because the limit is tracked
per user, not per key. The limit is now checked on every request and follows a
plan change on the next one. Requests still running at that moment give their
slot back to the old limit, so they cannot raise the new one. Two new tests in
`tests/test_concurrency.py`.

### Fixed — docs quoted tier limits from before the pricing overhaul

The API usage guide's tier table and the API reference's monthly-quota table
still showed the limits from before the 2026-05-25 pricing overhaul (for
example free 50 MB / 5 files / 500 calls a month, pro 10,000 calls). Both now
match `app/core/quotas.py`, the source the server enforces and `/pricing`
renders.

- **Rate limits are not per tier.** The guide's "API/min" column promised paid
  tiers 60 requests/min, and its quickstart offered "higher rate limits" with an
  account. The limiter counts per client IP and per endpoint, the same for
  everyone: 10/min on `/convert` and `/compress`, 3/min on the batch endpoints.
  The guide now says so. In place of that column the table shows the per-tier
  concurrent-request cap (1 / 1 / 3 / 6 / 10), which is enforced per tier.
- **Anonymous uploads cap at 30 MB, not 20 MB.** Fixed in the API guide, the
  security overview and the vendor security questionnaire. Anonymous callers
  can also send a one-file batch; the guide said batch endpoints reject them.
- **Self-hosting guide:** Pro gets 3 concurrent requests and Business 6, not 2
  and 5.
- **Duplicate names in a batch ZIP** come out as `a.png`, `a_1.png`, `a_2.png`;
  the guide said the second file gets `_2`.
- **Monthly API calls:** a request rejected by the output cap does not count
  toward them (the guide said it did), and the PDF tools do (the API reference
  left them out). Its example `429` body now quotes Pro's 25000 calls.
- **Caps above the tier:** the guide now says that `MAX_UPLOAD_SIZE_MB`
  (default 100 MB) caps every whole request, so a self-hosted instance has to
  raise it for the larger tier limits to apply, and that past the server-wide
  concurrency cap (`MAX_GLOBAL_CONCURRENCY`) requests get `503`. The
  architecture doc gave that default as 2000 MB.

`tests/test_docs_match_code.py` reads the tier numbers back out of the markdown
and compares them with `QUOTAS`, and the duplicate-name example with
`build_batch_zip`, so the next quota change fails CI until the docs follow.

### Added — QA fixture generator for the batch error messages

`scripts/make_testdata_batch_errors.py` writes byte-stable fixtures for
checking the fix below by hand: a windows-1252 Markdown file and CSV, a JSON
object that isn't an array, and a small JPEG for a mixed batch. Output goes to
a gitignored local folder; only the script ships.

### Security — batch error messages no longer echo library internals

`/api/v1/convert/batch` and `/api/v1/compress/batch` returned the text of any
`ValueError` as the file's error message. Library exceptions are ValueErrors
too, so a Markdown file that isn't UTF-8 put the decoder's text (codec, byte,
offset) into the per-file message, the `X-FileMorph-Batch-Failures` header and
`manifest.json`; invalid JSON did the same with the parser's position
(CWE-209, low). Only the routes' own messages (e.g. "File too large …", "File
type not permitted.", "Output too large …") and hints a converter writes for
the user reach the client now. Everything else reads "Conversion failed. Verify
the file is valid." (compress: "Compression failed. …"), with the details in
the server log. The `/api/v1/pdf/*` routes already worked this way.

A Markdown, CSV or JSON file that isn't UTF-8 (Excel's default CSV export on
Windows, for one) gets a message naming the fix ("Re-save it as UTF-8 …"): per
file in a batch, and from single-file `/convert` as a `400` with
`X-FileMorph-Error-Code: invalid_input` instead of a generic `500` that API
clients would retry. The JSON → CSV hint "JSON must be a non-empty array of
objects", until now only visible in a batch, is returned the same way. A
leading byte-order mark, which Excel's "CSV UTF-8" always writes, is dropped
now instead of ending up in the first column name (CSV → JSON / XLSX) or
failing a JSON file.

### Fixed — `docker.yml` stored with CRLF line endings; CI now rejects CRLF files

`.github/workflows/docker.yml` had been stored with Windows line endings (CRLF)
since the manual-rebuild change (`f72dedc`), although `.gitattributes` pins YAML
to LF. GitHub runs the workflow either way, so nothing broke, but the next
ordinary edit would have converted all 117 lines and shown up as a whole-file
diff that hides the lines actually changed. The file is back to LF; its content
is unchanged (`git diff -w` is empty).

`.gitattributes` only normalises line endings when git itself stages a file. A
commit made through the GitHub API stores exactly the bytes it is sent, and a
file read from a Windows checkout can carry CRLF, which is how
`requirements.lock` once turned into a 3725-line diff. `tests/test_line_endings.py`
now fails CI when any tracked text file is stored with CRLF, so the next one is
caught in its own pull request rather than by whoever edits the file after it.

### Fixed — long upload names lost their file extension on download

`safe_download_name()` cut the finished download name to 200 characters, so an
upload whose name without extension ran past about 185–196 characters came
back as `….pn`, `…_pdfa.pd`, without any extension, or ending in one taken
from inside the name (`….exe`) — a file the OS could not open, or would treat
as the wrong type. Names that NFKD normalisation lengthens hit this much
sooner: a Hangul syllable becomes two or three characters (한 → 3), so Korean
file names of about 70 characters were already affected. The helper now
receives the stem and the suffix the route appends (`.png`, `_pdfa.pdf`,
`_compressed.jpg`, `_pages.zip`, `.redacted.<ext>`) separately and shortens
only the stem, after sanitising; the shortened stem no longer ends in a stray
dot or space. Convert and compress (single and batch), the PDF
extract/split/compress tools and AI redaction all pass their suffix this way.
Any name that already fit in 200 characters comes out exactly as before. New
tests send a 250-character name through each of those routes and cover the
Hangul case in `tests/test_core.py`.

### Changed — homepage shows seven quick actions; "More tools" box removed

Before a file was chosen, the homepage's tool card offered no concrete
operation — just the Convert/Compress toggle and an empty target-format
dropdown — and on the homepage the PDF tools (split, extract, compress)
appeared only as small text links in a "More tools" box below the fold (plus
the footer). This is the first visible step of surfacing operations earlier.

The tool card now shows, under the drop zone, seven secondary "chip" links
under an "Or choose directly" label — Compress PDF, JPG to PDF, Word to PDF,
Split PDF, Extract PDF pages, HEIC to JPG and Compress image (KB/MB) —
followed by an "All tools →" link. All seven point at pages that already
exist; "(KB/MB)" signals file size, not pixel dimensions. They render only on
the homepage — the same tool card is shared by `/compress` and the 12
`/convert/<pair>` pages, which would otherwise show self-links — and step
aside while files are selected, returning when the selection is cleared. The
"More tools" box is gone; its links now live in the chips and the "All tools"
link. The subline above the tool gains "PDF". Redact is no longer teased on
the homepage — it still appears in the footer and on /tools when AI
operations are enabled.

`scripts/i18n.py update` now passes `--ignore-obsolete`, so removed strings
are dropped from the catalogs instead of piling up as `#~` blocks.

### Fixed — FAQ, `/llms.txt`, JSON-LD and README listed an outdated set of formats

The homepage FAQ answer "Which file formats can I convert?" (DE and EN), the
format sentence in `/llms.txt`, the JSON-LD `featureList` and the README's
drop-zone mockup still named the formats from before HEIF, AVIF, ICO, HTML,
EML, FLV, WMV, AAC, WMA and Opus were added, so the homepage FAQ contradicted
the drop-zone caption above it. All of them now list every format
`/api/v1/formats` accepts. The README's "Supported Formats" table was missing
HTML and EML (now a row of their own, since they only convert to PDF) and PDF
as an image output. The lists stay hand-written (the FAQ answer is translated,
the README is static Markdown), and a new test compares each one with the
converter registry, so a new input format added without updating them fails CI
with the stale list named.

The JSON-LD honesty test used to reject the word "AVIF" anywhere in the feature
list — it was written before AVIF conversion existed. AVIF may now appear in a
format list in brackets; anywhere else the test still rejects it, because
automatic AVIF/WebP output routing still doesn't ship.

### Fixed — API keys created in the dashboard were rejected on every upload route

A key minted via `POST /api/v1/keys` (the dashboard) is stored only as a row in
the `api_keys` table. The gate in front of every upload route
(`require_api_key` on convert and compress plus their batch variants, the PDF
tools and AI redaction) checked only the self-host key file, so such a key got
`401 Invalid API key.` before `get_optional_user` — which did know how to
resolve it to its owner — ever ran. The documented CLI path (create a key in
the dashboard, send it as `X-API-Key`) therefore never worked. The regression
test for that path passed only because it reused the file-store test key.

The gate now accepts a key from the file store (unchanged,
`hmac.compare_digest`) or, when a database is configured, an active dashboard
key, looked up by its SHA-256 hash. The gate and `get_optional_user` share one
helper, `find_active_api_key` in `app/core/security.py`, so both apply one rule
to dashboard keys. A revoked key, or one whose owner is deactivated, is still
rejected with 401 rather than falling through to the anonymous tier; the
helper also checks `deleted_at`, the backstop the Bearer path already had.
Without `DATABASE_URL` (Community Edition) validation stays file-only. Six new
test cases in `tests/test_upload_auth_resolution.py`; the batch test now uses
a DB-only key and asserts 200, because a 401 also lacks the "tier limit" text
it used to check for. The architecture, security-overview, threat-model,
vendor-questionnaire and TOM-annex docs no longer say every key is compared in
constant time.

### Added — QA fixture generator for the format fixes

`scripts/make_testdata_format_fixes.py` writes byte-stable fixtures for
checking the fixes below by hand: a text PDF for the PDF/A download name, and
a windows-1252 `.htm` plus a UTF-8 `.html` with umlauts. Output goes to a
gitignored local folder; only the script ships.

### Fixed — `FILEMORPH_OFFICE_ENGINE` was silently ignored

The docs, the office compose overlay and the runtime error message all name
the DOCX → PDF engine variable `FILEMORPH_OFFICE_ENGINE`, but the settings class
only read `OFFICE_ENGINE`, so following the docs did nothing. Both names are
accepted now; `FILEMORPH_OFFICE_ENGINE` is the documented one and wins if both
are set in the same place, so set only one. `.env.example` lists it
(commented out, default `auto`).

The office overlay (`docker-compose.office.yml`) also pinned
`FILEMORPH_OFFICE_ENGINE=auto` under `environment:`, which Compose ranks above
the `.env` file. It no longer sets the variable, so the value in your `.env`
reaches the app under either name.

**Check your deployment:** if you set `FILEMORPH_OFFICE_ENGINE=libreoffice` or
`=mammoth` (in `.env` or the container environment), that value takes effect
with this change; until now you were running `auto`. `libreoffice` needs an
image with LibreOffice (`filemorph:office`) — on the slim image every DOCX → PDF
conversion would fail.

### Fixed — five places where the app said one thing and did another

- **PDF/A results download as `.pdf`.** `pdf → pdfa` used the target token as
  the file extension, so a converted `Vertrag.pdf` arrived as `Vertrag.pdfa`,
  which no operating system opens as a PDF. The download is now
  `Vertrag_pdfa.pdf`: PDF/A is a PDF profile, and the `_pdfa` suffix follows the
  `_compressed` / `_pages` convention for outputs that share their source's
  extension, so the archival copy doesn't collide with the original in the
  Downloads folder. Covers the single download, the batch ZIP entries and the
  browser's fallback name (used when a proxy strips `Content-Disposition`).
- **The 413 hint named a stale free-tier limit.** Anonymous uploads over the cap
  were told "Register free to upload up to 50 MB" on `/convert` and
  `/compress`, while the free tier allows 100 MB. The number is now read from
  `app/core/quotas.py`, so the hint follows the quota instead of drifting.
- **The drop zone's "Supported:" lists were incomplete.** The homepage caption
  left out AVIF, HEIF, ICO, HTML, EML, FLV, WMV, AAC, WMA and OPUS (compress
  mode: AVIF). Both lists now match `/api/v1/formats`; only the "Supported:"
  label is translated, the format names are plain text. A new test compares
  the rendered captions (DE and EN) with the live API, so a converter added
  without a caption update fails CI.
- **`/formats` filed AVIF and EML under "Other".** They now sit under Images and
  Documents; a test fails when a registered source format has no category.
- **`.htm` on `/convert/html-to-pdf` was a dead end.** The file picker offered
  `.htm`, but no converter accepted it, so the user got stuck at "Please select
  a target format". `.htm` is now an alias of HTML → PDF (same converter class,
  same SSRF-guarded `url_fetcher`) and `/api/v1/formats` lists it; a test
  checks that every extension a pair page's picker offers actually converts.
  Because `.htm` is what Word's "Save as Web Page" writes — in windows-1252 —
  HTML input that isn't UTF-8 now goes to WeasyPrint as bytes, so its
  `<meta charset>` is honoured. Until now every umlaut in such a file came out
  as `�` in a conversion reported as successful (this affected `.html` too).

### Fixed — stale Tailwind bundle rebuilt; CI now rejects a stale one

The committed bundle (`tailwind.625748cf.css`) had last been rebuilt in May,
so every utility class a template or script started using afterwards never
reached the browser — 46 of them. Visible effects on the live site: the
footer's "Popular conversions" grid stopped at three columns and had no
gaps; the homepage's self-hosting checklist (and grids on `/formats` and
`/pricing`) never went two-column; the "How it works" steps on `/compress`,
the PDF tools and `/redact` had no numbers; the converter's notice boxes
(DOCX engine notice, PDF-tools hint, conversion warnings) and the green
batch summary lost their tinted background, border and text colour; and
`bottom-0`/`inset-x-0` were missing, which is why the cookie notice needed a
positioning shim in `style.css`. The rebuild (`tailwind.8be3407b.css`) emits
all of them; the shim is removed. The only class dropped, `grid-cols-3`, is
no longer used anywhere.

Root cause: `docs/tailwind-build-setup.md` described a CI step that rebuilds
the bundle and fails on a difference, but it was never added to `ci.yml`. It
is now the `Tailwind bundle freshness gate`; a failing run attaches its own
bundle as the `tailwind-bundle-ci-built` artifact. Because CI now downloads
and runs the Tailwind CLI on every run, `scripts/build-tailwind.sh` verifies
each download against SHA-256 pins from the v3.4.17 release's
`sha256sums.txt` before it becomes executable (a mismatching binary in
`.tools/` is re-downloaded, a mismatching download is deleted), and `curl -f`
makes an HTTP error fail loudly instead of saving an error page as the binary.

Also fixed: the "Compare plans" heading on `/pricing` used `text-h-section`,
a class that does not exist (the token is `text-h-sect`), so it rendered as
plain body text.

### Fixed — metrics concurrency test runs each writer on its own connection

SQLAlchemy 2.1.0 (released 2026-09-24) turned
`test_daily_metrics.py::test_increment_is_safe_under_concurrent_callers` red on
every branch: 50 concurrent increments of one counter landed at 9 to 48. CI
installs `requirements.txt` unpinned, so it picked 2.1.0 up by itself; the
image installs `requirements.lock`, so production is still on 2.0.52.

The cause was the test harness, not `app/core/metrics.py`. The test ran its 50
sessions on the module's shared in-memory engine, whose `StaticPool` hands
every session the same connection — so all writers shared one transaction, and
since 2.1's aiosqlite adapter one session's pool-return rollback can land
between another's `UPDATE` and `COMMIT` and discard it. On 2.0.x the same
harness ran all 50 writes in one transaction with a single commit, so it never
exercised concurrent writers at all. Production never shares a connection
between sessions. The test now uses a file database with `NullPool`, so each
session has a real connection and the SQLite busy timeout serialises the
writers; it passes on 2.0.x and 2.1.0, still fails a non-atomic read-then-write
implementation, and checks the log first so a lock timeout fails as itself.
No version cap needed.

### Changed — dependency batch (supersedes five Dependabot PRs)

`mammoth>=1.12.1`, `pillow-heif>=1.7.0`, `stripe>=15.6.1`, `python-docx>=1.2.0`,
`ruff==0.16.7`, `uv==0.12.13`. Batched so the lockfile recompiles once and the
deploy happens once instead of five times.

Only `pillow-heif` moved in the lockfile (1.6.0 -> 1.7.0). Worth noting that
its constraint had read `>=0.15.0` while the resolved version was already on
the 1.x line — the bump to `>=1.7.0` corrects a floor that had drifted far
below what actually ships, rather than introducing a major upgrade. The 11 HEIC
tests pass.

As before, the `uv` pin is moved in all three places it appears
(`requirements-dev.txt` and the two workflows that recompile the lockfile);
Dependabot only edits the first, and a mismatch reddens the drift gate with no
dependency change behind it.

### Security — assessed CVE-2026-55073 (WeasyPrint SSRF bypass) as not reachable

`pip-audit` began flagging `weasyprint==69.0` for CVE-2026-55073
(GHSA-jf6q-chmf-3h3v, MODERATE, CVSS 6.2, `AV:L`), fixed in 70.0. The advisory
describes an SSRF-protection bypass in the very mechanism FileMorph relies on:
two `write_pdf()` channels build a fresh default `URLFetcher` instead of the
document's, so a restrictive `url_fetcher` is silently ignored.

Not reachable here. The bypass exists only for the `xmp_metadata=[url]` and
`stylesheets=[url]` parameters, and all four `write_pdf()` call sites pass the
output path alone (`app/converters/document.py` lines 228, 392, 426, 491). The
advisory's third precondition — forwarding an attacker-influenced URL into
either parameter — cannot occur.

Taking the fix is blocked by the same API change that the `<70` cap exists for:
70.0 turns `url_fetcher` from a callable into an object, which breaks
`_deny_url_fetcher`. The ignore is documented at the pip-audit step in `ci.yml`
and at the cap in `requirements.txt`, both pointing at the port that lifts it.

### Changed — dependency batch (supersedes five Dependabot PRs)

`fastapi>=0.141.1`, `uvicorn[standard]>=0.52.4`, `alembic>=1.19.2`,
`ruff==0.16.6`, `uv==0.12.10`, and the base-image digest. Batched into one
change so the lockfile is recompiled once and the deploy happens once rather
than five times. Only `alembic` actually moved in the lockfile (1.19.1 ->
1.19.2); the other constraints were already satisfied by the pinned versions.

The `uv` pin lives in three places — `requirements-dev.txt` and the two
workflows that recompile the lockfile — and Dependabot only updates the first.
All three are moved together here; a mismatch would turn the drift gate red
with no dependency change behind it.

### Added — informational cookie notice (no consent dialog) + TDDDG citation refresh

FileMorph needs no cookie banner: the app sets zero HTTP cookies (verified in
code and against production response headers), loads no third-party resources,
and until this change wrote `localStorage` only for signed-in sessions — all
consent-exempt under § 25 Abs. 2 Nr. 2 TDDDG / Art. 5(3) ePrivacy. Instead of a consent dialog
(nothing to consent to; an Accept/Reject pair would be misleading), first-time
visitors now get a dismissible informational bar
(`partials/cookie_notice.html` + `cookie-notice.js`, CSP-safe, no inline JS)
stating exactly that and deep-linking `/privacy#cookies`. The dismissal is
remembered per browser in `localStorage` (`fm_cookie_notice_dismissed` — a
cookie would contradict the claim), so the bar appears exactly once; its
fixed-bottom rule lives in `style.css` because the committed Tailwind build
lacks `bottom-0`/`inset-x-0`. The privacy policy documents the new key, and
all legal citations move from the renamed TTDSG to TDDDG (renamed May 2024,
§ 25 unchanged) across `privacy.html` and both compliance docs; the vendor
questionnaire's incorrect "session cookies (Cloud features)" line now
correctly says localStorage JWTs. New regression guards:
`test_no_set_cookie_on_public_pages` pins the zero-cookie promise,
`tests/test_cookie_notice.py` pins presence, dismiss wiring, per-locale
privacy deep link, and DE/EN texts.

### Added — deterministic QA fixture generator for manual test rounds

`scripts/make_testdata_ia_rework.py` generates seed-stable photo-like image
fixtures (large JPEG, small WebP, PNG) for hands-on testing of the target-size
compressor; output goes to a gitignored local folder, only the script ships.

### Changed — /compress review follow-ups (honest title, no-JS correctness)

The `/compress` page title no longer binds video to exact-target-size
compression (now "Compress a JPEG/WebP to a target size" / „JPEG/WebP auf
Zielgröße verkleinern" — video is quality-based, as the page copy already
said), and the embedded tool's Compress toggle is server-rendered active on
`/compress`, so the page is correct even before/without JavaScript. Plus a
README clause with the same video/target-size precision.

### Fixed — one Python version, and a lockfile that is actually installed

Two problems, one root cause: nothing compared the places where a version is
written down.

**Python.** Dependabot bumped the base image from `python:3.12-slim` to
`python:3.14-slim` on 2026-05-26 (`2b26b49`) — two minor versions in a single
"deps" commit. Nothing carried the change into the workflows, so for three
months CI tested 3.12 while production ran 3.14, and `requirements.lock` still
named the 3.11 it had been compiled with. All five workflows now use the
shipped version, and `scripts/check_python_version.py` fails CI if the
Dockerfile, the workflows and the lockfile ever disagree again. The Dockerfile
is the declared source of truth, since it is what ships.

**Lockfile.** `requirements.lock` was hash-pinned and carefully generated —
and installed by nobody: all six entry points (Dockerfile, `ci`, `sbom`,
`release`, `verapdf`, `build-desktop`) installed from `requirements.txt`.
Dependabot has no concept of it, so it drifted unnoticed: 32 commits to
`requirements.txt` in six months against 4 to the lockfile, one of those only
line endings. It ended up missing four packages outright — `mammoth`,
`pikepdf`, `Babel`, `prometheus-client` — and behind on five more, including
`uvicorn` (0.46.0 against a `>=0.49.0` constraint). A lockfile with no
consumer and no gate is decoration that reads as a guarantee.

It is now real: the Dockerfile installs with `pip install --require-hashes -r
requirements.lock`, `pip-audit` audits the lockfile instead of the manifest
(the lockfile being what reaches production), a `lockfile-drift` CI job
recompiles and diffs against the committed file — uploading the correct one as
an artifact when it fails — and a `deps-lock` workflow regenerates and commits
it on demand. Dependabot's own config now documents that its pip PRs turn that
gate red until the lockfile follows.

The lockfile is now compiled by **uv** rather than pip-compile, pinned to an
exact version like ruff. pip-compile can only resolve for the interpreter it
runs on, which is the mechanical reason this drifted in the first place: the
committed lockfile carried 3.11 because that was somebody's local Python, and
nobody could regenerate it for the image without installing 3.14 first. `uv pip
compile --python-version 3.14` resolves *for* the shipped interpreter from any
machine, so keeping the lockfile current no longer depends on matching the
image locally. The regenerated lockfile covers 76 packages with 2003 hashes,
and all 30 direct dependencies now satisfy their constraints — previously five
did not. `.gitattributes` pins the lockfile to LF so a CRLF checkout cannot
make the drift gate compare Windows-generated against Linux-generated output.

Documentation corrected alongside: `patch-policy.md` claimed direct
dependencies were "pinned to a specific minor version" (they carry `>=`
constraints) and treated the lockfile as optional;
`vendor-security-questionnaire.md` repeated that pinning claim and named the
wrong `pip-audit` target; the regeneration recipe in
`third-party-licenses.md` now matches what actually ships. `self-hosting.md`
gains a "Reproducible builds" section — the gap the internal promise audit
tracked as M1.

### Fixed — trusted-proxy guidance pointed at the wrong knob

`security-overview.md` § Operational Hardening told self-hosters that the rate
limiter "trusts the `X-Forwarded-For` header" and to close the gap with nginx's
`set_real_ip_from` or Caddy's `trusted_proxies`. Both halves are wrong for the
shipped default. `app/core/rate_limit.py` keys on `get_remote_address`, which
reads `request.client.host` only — never the header (that is slowapi's other
helper, `get_ipaddr`, which the app does not use). uvicorn rewrites
`request.client` from `X-Forwarded-For` solely when the peer is covered by
`FORWARDED_ALLOW_IPS`, default `127.0.0.1`; under Docker the proxy arrives from
the bridge network, so it never matches. Proxy-side directives cannot move
uvicorn's trust boundary.

The live consequence is the inverse of the documented one: instead of clients
rotating IPs to escape the limit, every anonymous request keys to the same
bridge-gateway address, so all visitors share a single 60/min bucket. Item 3 now
says that, names `FORWARDED_ALLOW_IPS` as the actual lever, warns against `*`,
and keeps the proxy-side directives as the complement they are. The PT-006 entry
that pointed at the old instruction is corrected alongside.

`security-pentest-report.md` gains a post-audit correction note on finding 4,
which attributes header-reading to the wrong slowapi helper; the original
finding text is left intact, and the PT-006 residual row now names the real
knob.

Docs only; no code change.

### Fixed — HSTS docs now describe what is actually served

The security docs stated that `security_headers` emits
`Strict-Transport-Security: max-age=31536000; includeSubDomains` on every HTTPS
response. It did not. The middleware gates on `request.url.scheme`, which uvicorn
derives from `X-Forwarded-Proto` — and uvicorn honours that header from
`127.0.0.1` only unless `--forwarded-allow-ips` widens it. Under Docker the proxy
reaches the container across the bridge network, so the header was discarded and
no HSTS ever shipped. The claim was externally falsifiable with a single `curl`,
which made it a liability in `vendor-security-questionnaire.md` in particular.

filemorph.io now serves `max-age=15552000` (6 months, no `includeSubDomains`, no
preload) from the Cloudflare edge; `security-overview.md`, `dpa-tom-annex.md` and
the vendor questionnaire say so, and separate the managed service from the
self-hosted case. `self-hosting.md` gains an "HSTS behind Docker" section
documenting both remedies — a proxy-set header (Caddy and nginx snippets), or
naming the proxy in `FORWARDED_ALLOW_IPS` via `.env` — with an external
verification command.

The second remedy is documented as a named address or CIDR, never `*`. With `*`
uvicorn takes the leftmost `X-Forwarded-For` entry, and both documented proxies
append to the client-supplied header, so any visitor could forge the address
uvicorn records — through the proxy, with port 8000 closed. That address is the
rate-limit key (`app/core/rate_limit.py`), the anonymous quota identity, and the
audit log's `actor_ip`. The section also flags that the shipped compose file
publishes port 8000 on every host interface. `.env.example` documents the knob,
commented out — an empty value would trust no peer at all and break the
bare-metal setup that works today.

No behaviour change: the only non-Markdown edit is a docstring in
`tests/test_security_headers.py` that carried the same corrected-away claim. The
middleware still emits nothing under Docker, so self-hosters must apply one of
the two documented remedies.

### Added — /compress landing page (IA rework PR 4)

Final slice of the navigation/IA rework (`docs-internal/ia-navigation-konzept.md`).
Compress-to-a-target-size — the product's flagship differentiator — gets its own
URL: `/compress` embeds the same Convert/Compress tool as the homepage, pre-set
to Compress mode via a `data-preset-mode` attribute (`app.js` calls the existing
`setMode('compress')` on init when it's present; CSP-safe, no inline JS), plus an
honest-limits section, a 3-step "how it works", a "when to use it" paragraph, an
FAQ (one entry states plainly that exact target-size compression only works for
JPEG/WebP — video and PNG/TIFF compress by quality instead), a "PDFs?" pointer to
`/pdf/compress`, and a related-tools row. Title/meta deliberately never say
"pdf" (cannibalization guard — the PDF slice of this query space stays on
`/pdf/compress`). `/tools` gets a second card, "Compress to a target size",
next to Convert & Compress; the Convert card's own description no longer
claims video hits an exact target (it never could — `compress_video()` only
takes a quality/CRF re-encode) and now only names batch conversion, its one
remaining URL-less mode. `/formats`' "Compress to a target size" CTA now
points at `/compress` instead of `/`, and its intro paragraph gets the same
video-target-size correction. Sitemap (`priority=0.7`, matching `/pdf/compress`)
and `llms.txt` list the new page in the same commit.

### Changed — homepage "More tools" section, heading hierarchy fix (IA rework PR 3)

Third slice of the navigation/IA rework (`docs-internal/ia-navigation-konzept.md`).
The homepage's two separate tool teasers — the gated Redact card and the ungated
PDF-tools card — are merged into one "More tools" / "Weitere Tools" section: PDF
Split/Extract/Compress, Redact PII (still gated on `ai_operations_enabled`), and a
closing "All tools →" link to `/tools` (reusing the same label the footer's Tools
group already uses). The Plans and For-Developers blocks now use a real `<h2>`
instead of a decorative eyebrow `<p>` (WCAG 1.3.1 heading hierarchy) — same
classes, no copy change.

### Added — /tools operations hub, /formats becomes format-first (IA rework PR 2)

Second slice of the navigation/IA rework (`docs-internal/ia-navigation-konzept.md`).
A new `/tools` page is the operations-first counterpart to the format-first
`/formats` matrix: cards for Convert & Compress (the only place the
compress-to-target-size and multi-file-batch modes are described, since
neither has its own URL), the three PDF structural tools, and — gated on
`ai_operations_enabled` — Redact PII, labelled "(Pro)" as plain text, no
badge styling. The navbar's "Convert" item is now "Tools" (desktop + mobile)
and links here; the footer's Tools group gets a new first link, "All tools
→". `/formats` drops its 3-sub-block "PDF tools" section in favour of one
cross-link to `/tools` (and vice versa); its conversion-matrix chips are now
clickable `<a>` links to `/convert/<src>-to-<tgt>` for the 12 curated pairs,
while uncurated chips stay plain `<span>`s (unchanged honest signal). Each
`/pdf/{split,extract,compress}` page gets a new "Related tools" block after
the FAQ, linking its two sibling PDF tools, `/formats`, and 1-2 topically
relevant curated convert pairs (e.g. compress links `docx-to-pdf` and
`jpg-to-pdf`) — fixing the previous dead end. `/tools` is listed in the
sitemap (priority 0.8) and `llms.txt`, which also gains a "Conversions"
section listing every curated pair URL — both generated from the existing
registries, not hardcoded.

### Changed — footer regrouped into Tools/Product/Legal, redact nav-slot removed

First slice of the navigation/IA rework (`docs-internal/ia-navigation-konzept.md`).
The footer's flat link row is now three named, server-rendered groups — Tools
(Split/Extract/Compress PDF, Redact PII*, Formats), Product (Self-Hosted,
Pricing*, Enterprise*, API Docs, GitHub), Legal (Privacy, Terms, Impressum,
Contact) — same label styling as the unchanged "Popular conversions" grid;
the copyright line moved onto its own line. The client-side-hydrated
`#nav-ai-slot` / `#nav-ai-slot-mobile` (`auth.js`'s `_renderAiNavLink`) is
gone: Redact PII is no longer a navbar item, discoverable via the footer
(flag-gated) and homepage teaser only, so every nav/footer link is now
server-rendered in the raw HTML (CSP hardening — visibility never depends on
a client-side fetch). Mobile nav order now matches desktop (language switcher
moved to just before the auth block). Quota-error states (`input_too_large` /
`output_cap_exceeded` / `target_size_exceeds_cap`) on the PDF tools and the
main Convert/Compress tool now show a "See plans and limits →" link next to
the existing honest error text, only when `pricing_enabled` (self-host builds
render no element). PDF-compress's "nothing to recompress" outcome now labels
the download button "Download unchanged file" instead of the default
"Download PDF", so it never implies a compression that didn't happen.

### Added — Web UI for the PDF structural-operation tools

Three focused, bilingual (DE/EN) landing pages for the PDF page-extract /
split / compress-to-target API added above — `/pdf/split`, `/pdf/extract`,
`/pdf/compress` — each with its own SEO content (distinct search intent per
tool), an embedded working tool, and an honest-limits / how-it-works / FAQ
section. Ungated (free, no account, like the main Convert/Compress tool).
**Honest compress UX:** the result reads `X-FileMorph-Converged` /
`X-FileMorph-Recompressible-Images` and shows a plain amber notice — with the
achieved size — when a PDF has nothing to recompress or the target wasn't
fully reached, rather than claiming a compression that didn't happen; the
download is offered regardless. Discoverable via the sitemap, `llms.txt`, the
footer, the homepage, and a new "PDF tools" section on `/formats`.

### Changed — identity conversion pairs hidden from user-facing listings

`GET /api/v1/formats` and the `/formats` page / convert-tool dropdown no
longer list a same-format pair (e.g. "PDF → PDF") as a *target* — offering it
was a silent no-op re-save. A new `get_public_conversions()` filters the live
registry for user-facing listings only; `/api/v1/convert` and the raw
registry are unaffected (`pdf → pdf` still works via the API and backs the
page-extract/split/compress routes above). The Convert card shows a hint
linking to the dedicated PDF tools when the selected file is a PDF.
`X-FileMorph-Converged` and `X-FileMorph-Recompressible-Images` were added to
CORS `expose_headers` (same-origin today, but future-proofs the S1.5
cross-origin upload split) alongside the Web UI change above.

### Added — PDF structural operations (page extract / split / compress-to-target)

Three pure-Python *morph* operations on existing PDFs, each a dedicated
same-origin route reusing the shared hardening pipeline (magic-byte guard, tier
caps, output cap, `asyncio.to_thread` offload, UUID temp dir, generic errors):

- **`POST /api/v1/pdf/extract`** (`pages=1-3,5`, 1-based) — write a new PDF with
  only the selected pages; text/fonts/vector copied intact. Malformed / reversed
  / out-of-range / non-numeric selections are a clean `400` (no pypdf internals
  leaked); a selection is capped at 10 000 pages.
- **`POST /api/v1/pdf/split`** — one single-page PDF per page, bundled as a ZIP
  (`page_001.pdf`, … zero-padded). Capped at **10 000 pages** (a larger document
  is a `400` before any work, so a crafted huge-page PDF can't exhaust memory).
- **`POST /api/v1/pdf/compress`** (`target_kb`) — shrink toward a byte budget by
  recompressing embedded raster images (binary search on a global JPEG quality);
  page count and every glyph preserved. **Honest limits:** only image-heavy PDFs
  shrink — a text/vector-only PDF (or one whose images are all masks / palette /
  alpha) comes back valid and unchanged, reported `X-FileMorph-Converged: false`
  / `X-FileMorph-Recompressible-Images: 0` rather than a fake compression claim.
  Response headers `X-FileMorph-Achieved-Bytes`, `X-FileMorph-Converged`,
  `X-FileMorph-Recompressible-Images`. A working-set ceiling caps the total
  decoded pixel area / image count and bails to the unchanged-PDF path instead
  of decoding a crafted image-bomb PDF (DoS guard mirroring the single-image
  decompression-bomb hardening).

### Added — AVIF image encode + decode

AVIF (AV1-based image format) is now a first-class image format for both
conversion and compression, via the new `pillow-avif-plugin` dependency
(libavif bundled in the wheel — no system package). Every `*→avif` and
`avif→*` pair is registered through the existing generic image converter, and
AVIF joins the quality- and **target-size**-compression sets (binary search on
quality, like JPEG/WebP). EXIF/GPS metadata is stripped on every AVIF write,
matching the existing privacy posture. **Honest note:** AVIF/AV1 encode is more
CPU-intensive than JPEG/WebP — a single encode is slower, and target-size
compression runs several encode passes; decoding from AVIF is cheap.

### Security — accepted advisory PYSEC-2026-1325 (`ecdsa`, no fix available)

`pip-audit` in CI now ignores PYSEC-2026-1325 (= CVE-2024-23342, the Minerva
timing side-channel in the `ecdsa` package, pulled in transitively by
`python-jose`). No fixed release exists and upstream considers side-channel
attacks out of scope. FileMorph is not affected in practice: all JWTs are
signed and verified with HS256 only (`app/core/tokens.py`), so the vulnerable
ECDSA signing/keygen/ECDH paths are never executed. The exception is documented
next to the ignore flag in `ci.yml` and is re-evaluated at each release;
migrating off `python-jose` would remove the dependency entirely.

### Added — PII redaction (Enterprise Edition, commercial add-on)

Deterministic, local-CPU PII redaction for UTF-8 text, DOCX and XLSX — detects
IBAN (mod-97), email, phone, IPv4 and payment-card (Luhn) by regex + checksum,
no external model call. A mandatory **fail-closed** pass re-scans the *serialized
output package* (all XML parts — body, metadata, comments, sheet names,
attributes), so a half-redacted file is never returned. Lives under `app/ee/`
(commercial-licensed); inert unless `AI_OPERATIONS_ENABLED` is set.
**Honest limits:** free-text names and postal addresses are not detected yet (no
NER), and PDF is unsupported (returns 415 — safe PDF redaction must delete the
text layer, a separate checkpoint; we don't ship a cover-only fake).

### Added — Redaction API + `/redact` tool page

`POST /api/v1/ai/redact/{detect,apply}`: two-phase — `detect` returns a free
findings preview (open to anonymous/free users); `apply` produces the redacted
file (paid-tier-gated, credit-metered, atomic charge). CPU work runs off the
event loop. New `/redact` page (gated on `AI_OPERATIONS_ENABLED`, 404 when off)
with a free scan → review → download flow, an honest scope notice, footer link,
homepage/pricing/enterprise surfaces, and an eligible-only nav link. Responses
are credit-denominated only — never a model id, token count, or euro cost.

### Changed — Footer "Popular conversions" uses explicit pair labels

Replaced the target-grouped footer layout (a "→ PDF" heading with bare source
names beneath — hard to parse and sparse) with explicit, directly-readable
`JPG → PDF` labels in a balanced responsive multi-column grid. Each conversion
is self-explanatory and one click away; the columns fill the width evenly.
`convert_pairs.FOOTER_LINKS` (flat) replaces `FOOTER_LINK_GROUPS`.

### Changed — Hide the Target Format dropdown on convert-pair pages

On `/convert/<src>-to-<tgt>` the target is fixed by the URL, so the "Target
Format" label + dropdown are no longer shown — the page itself is the choice.
The `<select id="target-format">` stays in the DOM (hidden) because `app.js`
reads it for submit, the download-name fallback, and the bandwidth-amplification
warning (which stays visible). Confirmed **frontend-only** by the
backend-architect: the conversion reuses the format-agnostic
`POST /api/v1/convert` (`target_format` from the form), so no backend or
API-contract change — a per-pair endpoint would just duplicate the
security/quota pipeline.

### Fixed — Convert-tool German strings (i18n partial-scan regression)

When the convert tool card was extracted into a Jinja partial under
`app/templates/_components/`, babel's extractor — which prunes underscore-
prefixed directories — stopped scanning it, so ~26 tool strings (drag-&-drop,
"Supported: …", Target Format, Quality, Download Result, …) silently fell back
to **English on `/de/`**. Moved the content partial to
`app/templates/partials/convert_tool.html` (scanned normally), documented the
underscore-dir limitation in `babel.cfg`, recovered the German translations,
and added a regression test asserting the partial renders translated on `/de/`.

### Changed — Dedicated convert-pair pages + structured footer

- **`/convert/<src>-to-<tgt>` pages are now a focused tool**, not the generic
  app: the upload shows only the pair's source format, `#file-input` gets an
  `accept` scoped to it, and the Convert/Compress toggle is hidden (a
  conversion pair is convert-only). The target stays pre-selected.
- **Footer "Popular conversions"** is grouped by target format ("→ PDF",
  "→ JPG", …) in a responsive grid (stacked columns) instead of a ragged inline
  row — more scannable, same internal-link coverage.

### Added — Footer links to the convert-pair pages

The global footer (`base.html`, every page) now has a "Popular conversions"
row linking all curated `/convert/<src>-to-<tgt>` pages — spreading internal
link equity to them on every page and aiding discovery (the standard SEO
footer pattern). Language-neutral arrow labels ("JPG → PDF"), locale-aware
hrefs; `footer_convert_links` is injected into every render context via
`app/core/i18n.py::localized_context` (lazy import to avoid the
i18n↔convert_pairs cycle). Guards in `tests/test_convert_pair_pages.py`.

### Added — Convert-pair landing pages (`/convert/<src>-to-<tgt>`)

Penalty-safe programmatic SEO pages for the highest-volume conversions
(`/convert/jpg-to-pdf`, `/convert/heic-to-jpg`, …). Each page **embeds the
real, working converter pre-set to that pair** — the tool card was extracted
into a shared `app/templates/_components/convert_tool.html` partial, and
`app.js` reads `data-preset-target` to pre-select the format (not disabled, so
the user can still change it). Alongside the tool, each page carries **unique,
localized (DE/EN) content**: when-to-use, technical/size-amplification notes, a
visible question-heading FAQ (GEO) and related-pair links. 12 curated pairs to
start. A page exists **only** when hand-written content lives in
`app/core/convert_pairs.py` *and* the conversion is registered — anything else
404s, so there are no thin auto-generated pages (Google 2026 "scaled content
abuse" safety; measure in Search Console, then scale). The sitemap
auto-populates the pairs (de/en/x-default + hreflang). New `convert_pair.html`
+ route in `pages.py`; +68 guards in `tests/test_convert_pair_pages.py`.

### Added — image / HTML / email → PDF converters

Three new "to-PDF" conversions, all **zero new dependencies** (Pillow + the
in-tree WeasyPrint engine). **`image→pdf`** (every supported image format →
single-page PDF; alpha flattened onto white, EXIF stripped) — useful for turning
scans/photos into uniform documents. **`html→pdf`** and **`eml→pdf`** (email:
common headers + body, HTML part preferred) render via WeasyPrint with the
mandatory `url_fetcher=_deny_url_fetcher` SSRF guard, so remote CSS/images and
`file://` are never fetched. New converters live in `app/converters/image.py`
and `document.py` (auto-registered, so they appear on `/formats` +
`/api/v1/formats`); guards in `tests/test_to_pdf_converters.py` (valid PDF
output, SSRF-blocked, magic-byte still enforced). `.msg` (Outlook) deferred —
it would need a new dependency.

### Fixed — Media conversion correctness: per-container codec matrix, direct ffmpeg audio, hard timeouts

The video converter forced `libx264`/`aac` into every container — but the
WebM muxer only accepts VP9/Opus and ffmpeg has no muxers named `mkv`/`wmv`
(the real names are `matroska`/`asf`), so **18 of the 42 advertised video
pairs failed at runtime** with a generic 500. Video output now uses a
per-container codec matrix (`app/converters/_ffmpeg.py`): WebM → VP9/Opus,
AVI → MPEG-4/MP3 (legacy-player compatibility), WMV → WMV2/WMA, everything
else H.264/AAC with `yuv420p` for player compatibility (odd-dimension
sources are rounded down one pixel instead of failing). The `quality`
parameter (previously accepted and ignored for media) now drives each
encoder's native rate control (CRF/qscale/VBR/bitrate).

Audio conversion drops pydub (unmaintained since 2021): it decoded the
whole file to PCM in RAM (a 100 MB MP3 is >1 GB decoded — an OOM vector
under the 500 MB Business input cap) and passed the bare extension as the
ffmpeg output format, **breaking m4a/aac/wma targets** (no such muxers;
correct: `ipod`/`adts`/`asf`). Audio now invokes ffmpeg directly with
constant memory and per-codec quality mapping; embedded cover-art streams
are dropped (consistent with the NEU-C.2 strip-metadata default).

`/compress` for video previously remuxed **everything into MP4 while
keeping the original extension** (a compressed `.webm` was an MP4 file
mislabelled as WebM); it now preserves the container and picks codecs from
the same matrix. Every ffmpeg invocation now runs under a hard timeout
(`MEDIA_SUBPROCESS_TIMEOUT_SECONDS`, default 600 s) like the LibreOffice
and ghostscript subprocesses already did — no more unbounded worker-thread
pinning. New functional smoke matrix (`tests/test_media_smoke.py`)
generates 1-second clips via ffmpeg `lavfi` in CI and verifies container +
codecs of every video/audio target with ffprobe (skips cleanly where
ffmpeg is absent, e.g. local Windows dev).

### Fixed — Social-preview (og-image) logo

The `app/static/og-image.png` social card showed a different, off-brand mark
(an empty box with two arrows) instead of the real FileMorph logo. Regenerated
it to use the **same document-tray + download-arrow mark as `favicon.svg`/the
navbar** (brand indigo `#6366f1`), wordmark and chips unchanged. Added a
Pillow-only, reproducible generator `scripts/generate_og_image.py` (the asset
previously had none, which is how it drifted) — re-run it after any logo or
wording change. Still 1200×630, no SaaS host string baked in.

### Added — SEO/GEO visibility foundation (Phase 1)

Sharpens organic-search and AI-answer-engine discoverability without touching
the conversion engine. **On-page:** keyword-front, SERP-length-safe titles
(≤60) and a per-page `meta_description` block in `base.html` (the homepage DE
title now carries the exact-match phrase "Dateien … konvertieren"); a homepage
FAQ section (question-style `<h3>` headings) and an honest "FileMorph vs.
typical cloud converter" comparison table — visible content built for AI
extractability (GEO). **Structured data:** an `Organization` entity
(`sameAs` → GitHub) and an honest `featureList` added to the homepage JSON-LD
(still one CSP-hashed, deployment-agnostic block). **GEO:** a new `/llms.txt`
entry point (llmstxt.org convention) and explicit AI-crawler allowances in
`robots.txt` (GPTBot, ClaudeBot, PerplexityBot, Google-Extended, …). **New
`/formats` hub** that renders the live `@register` converter registry grouped
by category — a unique-content, ungated, sitemap-listed discovery page (and the
anchor for future per-pair pages). Fully localised (DE 100 %, drift-check
green) and deployment-agnostic. Adds 14 regression guards to
`tests/test_seo_foundation.py`; also clears a stale `Compression`→`Imprint`
fuzzy entry in the EN catalogue.

### Added — Account-deletion paid-path (tax-retention, c.2)

Extends the free-path self-service deletion (`DELETE /api/v1/auth/account`)
with the **paid-account path** required by German commercial law. Accounts
ever linked to Stripe now get a **restricted delete** instead of a hard
delete: only `email`, `stripe_customer_id`, `tier`, `created_at` are
retained, everything else is nulled, `password_hash` becomes a `DELETED:`
sentinel, and `deleted_at` is set (HGB §257 / AO §147 10-year retention
under DSGVO Art. 17(3)(b)). New `app/core/account_deletion.py`
(`deletion_mode_for` + `perform_account_deletion`), migration
`010_account_deletion_paid_path` (`users.deleted_at` + partial unique index
`ix_users_email_active`), Stripe cancel-first ordering, a dashboard
"Danger Zone" + `/account-deleted` page. Lookup queries filter
`deleted_at IS NULL`. Also fixes `scripts/scope_review.py` to decode the
staged diff as UTF-8 (was crashing the advisory hook on non-ASCII diffs).

### Added — Localised transactional email (i18n-3)

All transactional emails (verification, password-reset, account-deletion,
dunning) now render in the recipient's `preferred_lang` (`de`/`en`) via
`email.render_email(stem, locale=…)` and `{% trans %}` templates. A new
`User.preferred_lang` column (migration `009_preferred_lang`, NULL →
`LANG_DEFAULT`) is seeded from the request locale at registration and is
changeable via `PUT /api/v1/auth/account/language` plus a dashboard
language picker. The dunning mail — fired from a Stripe webhook with no
request context — reads the column. Web-UI locale stays URL-prefix-driven;
a sticky logged-in web-UI preference is a follow-up (PR-i18n-4).

---

## [1.1.0] — 2026-05-29

The Compliance-First strategic pivot (2026-05): FileMorph adds the
auditability + traceability surface that DACH Behörden, Krankenhäuser,
and Anwaltskanzleien expect. None of this changes the existing public
API behaviour for casual callers — every change is additive, defaulted
off where applicable, and optional at deploy time.

### Added — Homepage Self-Hosted promotion + nav anchor

The canonical product truth (open-source AGPLv3 engine, runs on your own
infrastructure — see `docs-internal/pricing-overhaul-konzept.md` §1) was
barely visible on the homepage: a single grey `mailto:` line at the
bottom. This sprint adds a real promotion surface so a visitor scanning
for "can I self-host this?" sees the answer on the highest-authority page.

- `app/templates/index.html` — new `id="self-hosted"` section directly
  after the tool card. Lists only **real** features (AGPLv3, Docker
  deploy, signed releases + CycloneDX SBOM, audit-log hash chain,
  PDF/A-2b, EU hosting) per the §7 honesty guardrail. Primary CTA →
  upstream `docs/self-hosting.md` on GitHub (always available, including
  on self-host). Secondary CTA → `/enterprise` Compliance Edition,
  gated by `pricing_enabled` so a self-host deployment doesn't link to
  its own 404. The pre-existing weak `enterprise@filemorph.io`
  `mailto:` line is removed — the section supersedes it, and gating the
  Compliance CTA prevents self-host deployments from advertising the
  upstream procurement contact as if it were their own.
- `app/templates/base.html` — ungated "Self-Hosted" nav entry (desktop
  + mobile) that points at the homepage `#self-hosted` anchor. Anchor
  navigation needs no JS (CSP-safe). The link works on every
  deployment because the section is always rendered.
- Internal link graph: the homepage now has a direct, gated link to
  `/enterprise`, strengthening the commercial page's inbound equity.
  Sitemap already covers `/enterprise` when `pricing_page_enabled`.

### Fixed — Homepage tier teaser now reads from the central pricing source

The pricing-overhaul (`feat(pricing)` 153f72d on this branch) made
`/pricing` deployment-agnostic via `app/core/pricing.py`, but missed the
homepage tier teaser in `index.html`, which kept hardcoding `Pro €7/mo`,
`Business €19`, `Free 50 MB`, `anon 20 MB`. `/pricing` therefore said
`€3`/`€9` while the homepage still said `€7`/`€19` — a fresh drift the
overhaul was meant to prevent.

- `app/api/routes/pages.py` — `index()` now passes `anon_plan`, `plans`,
  `saas_prices_configured`, and `price_currency` to the template,
  mirroring `pricing_page()`'s contract. Cheap (`pricing` helpers read
  from settings + `quotas.py`, no DB).
- `app/templates/index.html` — teaser pulls limits from `quotas.py` via
  `plans.<tier>.max_file_size_mb`/`.api_calls_display` and prices from
  `PRICE_*_DISPLAY` env via `plans.<tier>.price_display`. When a price
  isn't configured the `· €N/mo` suffix collapses — a self-host
  operator who enabled the pricing page without setting display prices
  no longer inherits filemorph.io's amounts.
- `tests/test_seo_foundation.py` — eleven new tests guard: section
  always rendered (both modes), Self-hosting guide link points at the
  GitHub repo (not `filemorph.io`), nav anchor present on both modes,
  Compliance CTA gated, teaser reads from configured price, no legacy
  `€7/mo`/`€19` strings ever reappear.

### Added — Prometheus metrics endpoint (`/api/v1/metrics`)

Request-path observability for self-hosters and the Compliance Edition.
Gated by `METRICS_ENABLED` (default `true`; the same flag the cockpit's
analytics card already references). When disabled, no instrumentation is
attached and the endpoint 404s — a single-tenant deployment that doesn't
run Prometheus pays nothing.

- `app/core/observability.py` — new. A small request-timing middleware
  (built on the raw `prometheus-client`, not the FastAPI instrumentator
  wrapper) records `http_requests_total{method,handler,status}` and the
  `http_request_duration_seconds{method,handler}` histogram, plus a
  domain counter `filemorph_conversions_total{operation,src,tgt,status}`.
  The middleware is attached last in `app/main.py` so it sits outermost
  and measures full request time.
- **Raw client, not the wrapper — a security choice.** The
  `prometheus-fastapi-instrumentator` wrapper pins `starlette<1.0.0`,
  which would hold the dependency below the `1.0.1` fix for
  PYSEC-2026-161 (Host-header URL-reconstruction / auth-bypass class).
  The raw `prometheus-client` has no such constraint, so the CVE scan
  stays clean and starlette floats to the patched release.
- **Cardinality is capped.** `src`/`tgt` and the request `handler` come
  from request data, so unknown formats collapse to `other` and an
  unmatched path (404) reports `handler="other"`; the label space is
  bounded by registered routes and formats, not by what a caller sends.
- `app/api/routes/convert.py` + `compress.py` — increment the domain
  counter at the same success/failure sites that already feed the
  `daily_metrics` table (single + batch), so the cockpit's DB counters
  and the scrape-friendly counter never diverge.
- The endpoint is **unauthenticated by design** (standard Prometheus
  pattern) and must be IP-restricted at the reverse proxy — see
  `docs/self-hosting.md` (Monitoring & metrics) and
  `docs/security-overview.md`.
- Tests: `tests/test_observability_metrics.py` (exposition format,
  counter increment + visibility, cardinality cap, disabled-path no-op).
- Grafana dashboards / alert rules are a follow-up (private ops repo);
  the OSS app ships only the instrumentation + endpoint.

### Fixed — CSP: inline i18n bootstrap moved to an external file

The `window.FM_I18N = JSON.parse(...)` bootstrap in `base.html` was an
inline `<script>` with no `src` and no pinned hash, so the strict CSP
(`script-src 'self' 'sha256-<jsonld>'`) blocked it on every page. The
block was silent server-side (the page still renders) but visible in the
browser console, and because the blocked script never runs, its `catch`
never fired — `window.FM_I18N` stayed `undefined` and every JS string
fell back to its English literal. Most visible on `/de/dashboard`, where
German copy silently rendered in English.

- `app/static/js/i18n-bootstrap.js` — new. Parses the `#fm-i18n-strings`
  data block into `window.FM_I18N`, loaded via `<script src>` before the
  consumer scripts (nav/auth/app). No inline executable script remains.
- `app/main.py::_build_csp_header` — added `base-uri 'self'` and
  `frame-ancestors 'none'` while in the file.
- `tests/test_csp_no_unpinned_inline_scripts.py` — new regression guard:
  every inline executable `<script>` on `/`, `/dashboard`,
  `/{de,en}/dashboard`, `/cockpit`, `/de/cockpit` must have its SHA-256
  in that page's own CSP, or the build fails.
- `docs/security-overview.md` — CSP section corrected (it still described
  a Tailwind inline-config block that no longer exists).

### Polished — Mobile-UX touch-target sweep (P1-5)

Structural audit of every template at the 375 px viewport flagged a
handful of touch targets below the W3C/Apple-HIG 44 px minimum and
one grid that didn't stack on narrow screens. Concrete fixes:

- `app/templates/index.html` — Tier-teaser grid `grid-cols-3` →
  `grid-cols-1 sm:grid-cols-3`. On phones the three plan badges now
  stack instead of crushing into ~114 px wide cards.
- `app/templates/base.html` — Mobile drawer nav links bumped from
  `py-1` (~28 px) to `py-2.5` (~40 px). Seven links + auth-mobile
  pair touched.
- `app/templates/cockpit.html` — Six chart range-buttons + four
  filter controls (search input + 3 selects) + two pagination
  buttons lifted from `py-1` / `py-1.5 text-xs` to `py-2 text-sm`.
  Admin-only UI but the operator runs the cockpit from a phone
  during incident response.
- `app/templates/dashboard.html` — API-key Copy button consistency:
  `py-2 text-xs` → `py-2.5 text-sm`.

Total: 4 files, 14 line-level edits. No new components, no JS
changes, no layout rework. The audit's "verify on a real device"
list (native iOS picker behaviour, keyboard-pop coverage of submit
buttons, modal scroll-lock on iOS Safari bounce-scroll) remains
open as a `device-only` validation pass for a manual browser
session.

### Added — Per-file batch result summary (P2-1)

- `/api/v1/convert/batch` and `/api/v1/compress/batch` now emit four
  structured response headers alongside the ZIP body:
  `X-FileMorph-Batch-Total`, `X-FileMorph-Batch-Succeeded`,
  `X-FileMorph-Batch-Failed`, and (only when at least one file
  errored) `X-FileMorph-Batch-Failures` — a semicolon-joined list
  of URL-encoded `<name>|<reason>` pairs, capped at 4 KB to stay
  under typical proxy limits with a `...` sentinel signalling
  truncation. The `manifest.json` inside the ZIP remains the full
  source of truth for callers who want the complete detail.
- Web UI reads the headers after a successful batch response and
  renders a per-file summary block above the green download button —
  emerald tone when 0 failures, amber tone otherwise, with each
  failed filename rendered as `<code>` next to its server-reported
  reason. The user no longer has to unzip the ZIP just to see which
  file failed and why.
- CORS `expose_headers` extended in `app/main.py` so cross-origin
  clients can read the new headers.
- Tests: existing `test_batch_partial_failure_continues` extended
  to pin the headers on partial-failure; new
  `test_batch_all_success_omits_failures_header` pins the
  all-success contract (no `Failures` header when nothing failed).
- New i18n key `batchSummaryCounts` carries the
  `{succeeded} of {total} files succeeded ({failed} failed)`
  template; German translation applied. Locale catalogue compiled
  + drift-check passes.

### Hardened — Multi-stage Dockerfile builder / runtime split (P3-8)

- `Dockerfile` now has three stages: `builder` (compilers + dev
  headers), `base` (runtime libs only — published as
  `filemorph:latest`), and `office` (base + LibreOffice + OFL fonts
  — published as `filemorph:office`). The `builder` stage installs
  `build-essential`, `libheif-dev`, `libffi-dev`, `libssl-dev` —
  the four packages needed *only* at Python-wheel-install time for
  the rare cases where a manylinux prebuild isn't available — and
  pip-installs the requirements into a venv at `/opt/venv`. The
  `base` stage copies just `/opt/venv` from the builder and installs
  only runtime libs (`ffmpeg`, `ghostscript`, `libheif1`, Cairo /
  Pango, curl).
- Effect on the running container: no gcc / ld / make / dev-headers
  on disk; smaller attack surface for any post-exploit probe; image
  size drops by the weight of those four apt sets
  (build-essential alone is ~120 MB extracted on bookworm).
  Pre-built wheels behave identically — only the install path
  changes, not the runtime ABI.
- `docs/third-party-licenses.md` updated: the libheif row points at
  the runtime `libheif1` package rather than the build-time
  `libheif-dev` headers.
- Pre-flight disk check in `filemorph-ops/deploy.sh` (the
  `MIN_FREE_GB=2` gate, commit `a30615e` in the ops-repo) keeps the
  same threshold — the office image still adds ~280 MB on top of
  the slim base; the savings stack on the *base* side, not on the
  LibreOffice apt set.

### Hardened — Pillow decompression-bomb hard-reject (P3-4)

- `app/core/image_hardening.py` (new) promotes Pillow's
  `DecompressionBombWarning` to a synchronously raised
  `DecompressionBombError` at startup. The stock warn-but-continue
  behaviour between the configured `MAX_IMAGE_PIXELS` threshold and
  2× the threshold was a denial-of-service vector for a conversion
  service: a 200 kB PNG with an IHDR claiming 60 000 × 60 000 pixels
  (~3.6 GP) coasted past every input-size check and pinned the worker
  decoding ~14 GB of memory before the output-cap guard rejected the
  result.
- New env var `FILEMORPH_IMAGE_MAX_MEGAPIXELS` (default 89, range
  1–10 000) lets self-hosters with explicit large-image use cases
  (GIS, scans, microscopy) raise the threshold. Garbage / out-of-range
  values fall back to the default rather than refusing to boot.
- `/api/v1/convert` and `/api/v1/compress` catch the
  `DecompressionBombError` specifically and emit HTTP 400 with
  `X-FileMorph-Error-Code: decompression_bomb` so the UI can render
  a distinct "image too large to decode safely" message instead of
  the generic 500. CORS expose-headers already includes
  `X-FileMorph-Error-Code` since the Sprint B 413-disambiguation
  commit, so cross-origin callers see it too.
- 6 new regression tests in `tests/test_image_hardening.py` pin the
  hardening module (MAX_IMAGE_PIXELS resolution, warning-to-error
  filter, env-var override + garbage-value fallback) and the two
  route handlers (400 + structured header on bomb input, no
  false-positive on normal-sized images).
- `docs/security-overview.md` § "Decompression bombs" updated from
  "Pillow default is in effect" to the current hard-reject contract.

### Added — DOCX → PDF high-fidelity engine (Technology-First Sprint A)

- Two-engine routing for DOCX → PDF in `app/converters/document.py`. A
  per-document complexity detector opens the OPC ZIP and probes for the
  features `mammoth` silently drops — footnotes, endnotes, headers,
  footers, OLE embeddings, multi-section page layout, OMML equations,
  multi-level numbered lists. Complex docs route to LibreOffice
  (`soffice --headless --convert-to pdf`); simple docs stay on the
  fast pure-Python mammoth+WeasyPrint path.
- New env var `FILEMORPH_OFFICE_ENGINE` (`auto` default,
  `libreoffice`, `mammoth`). `auto` does the routing described above
  and falls back to mammoth when `soffice` is missing, with a
  structured `X-FileMorph-Warnings` response header so the client
  knows fidelity was reduced (`engine=mammoth_fallback,
  reason=soffice_unavailable, simplified=footnotes, …`).
  `libreoffice` forces the high-fidelity path and fails loud when
  `soffice` isn't on PATH — for deployments that explicitly never
  want the fallback. `mammoth` forces the pure-Python path even when
  LibreOffice is installed (A/B comparison, predictability).
- New `filemorph:office` image variant. `Dockerfile` is now
  multi-stage: the `base` stage is the slim image
  (`ghcr.io/mrchenglen/filemorph:latest`, unchanged footprint),
  the `office` stage adds LibreOffice + OFL Calibri/Arial/Times-metric
  fonts (`fonts-crosextra-carlito`, `fonts-liberation`,
  `fonts-dejavu-core`) on top. The office image is published as
  `:office`, `:{version}-office`, and `:{major}.{minor}-office`,
  cosign-signed identically to the slim variant.
- New `docker-compose.office.yml` overlay for self-hosters who want
  the office image without changing the default
  `docker compose up` behaviour:
  `docker compose -f docker-compose.yml -f docker-compose.office.yml up -d`.
- `docs/formats.md`, `docs/self-hosting.md`, and
  `docs/tech-stack-rationale.md` updated to document the routing,
  the two image variants, and the historical decision trail (the
  2026-05-08 `docx2pdf` failure plus the AGPL § 13 reasoning against
  Aspose.Words now both live in the Considered-and-Rejected section).
- 21 new regression tests in `tests/test_docx_complexity.py` pinning
  every detector branch + every engine-resolution outcome + the full
  fallback chain. The existing `tests/test_convert_document.py` suite
  is unchanged and still skips on Windows dev boxes that lack
  GTK/Pango (CI on Linux + the Dockerfile both run it).

### Added — Public contact form (German Impressum, DDG §5)

- `/contact` page with a contact form (de / en / x-default). Submissions
  are emailed to the operator with `Reply-To` set to the sender so a
  reply goes straight back; **the message is not persisted** — only a
  hashed-email audit event (`contact.message.received`) is recorded.
  Anti-spam: a hidden honeypot field + a `5/hour` per-IP rate limit; no
  external captcha (keeps the "no external resources" privacy promise).
  New `app/api/routes/contact.py`, `app/templates/contact.html`,
  `app/static/js/contact.js`, `app/templates/_components/textarea.html`.
- The Impressum now lists the contact form as a second, fast-direct
  contact channel alongside the email address (German DDG §5 + ECJ
  C-298/07) and cites the current statute (`§ 5 DDG`) instead of the
  repealed `§ 5 TMG`. The footer gained a "Contact" link.
- Privacy policy: new § 2f documents the contact-form data flow
  (Art. 6(1)(f) GDPR, not persisted); § 3 extended accordingly.
- New env var `CONTACT_FORM_RECIPIENT_EMAIL` (optional; falls back to
  `SMTP_REPLY_TO` → `SMTP_FROM_EMAIL`). `app.core.email.send_email()`
  gained an optional `reply_to` parameter. `/contact` is in the sitemap.

### Added — Trust foundation (NEU-A)

- `security.txt` (RFC 9116) under `/.well-known/security.txt` plus a
  human-readable `/security` page and `SECURITY.md`.
- Architecture overview, sub-processor list, STRIDE threat model,
  patch policy, incident-response playbook, AGPLv3 explainer for
  German Behörden — all under `docs/`.
- `docs/support-sla.md` — the security-fix timeline (applies to every
  deployment, free or paid) and the Compliance-Edition support
  framework (set per agreement; no standing SLA during the
  design-partner phase), kept explicitly distinct.
- `docs/dpa-tom-annex.md` — "Annex II — Technical and Organisational
  Measures" template for the Article 28 DPA: structured along the
  Article 32 GDPR categories, with the application-level measures filled
  in (each with a code anchor) and the deployment-level measures as
  `[operator: …]` placeholders. Referenced from `docs/dpa-template.md` §7
  and its finalisation checklist.
- `docs/records-of-processing-template.md` — an Article 30 GDPR
  "Verzeichnis von Verarbeitungstätigkeiten" (Records of Processing
  Activities) template: an identification block, six controller
  activities (A1–A6) and one processor activity (B1), each with the
  Art. 30 fields (purpose, data subjects, data categories, recipients,
  transfers, retention, TOM reference), `[operator: …]` placeholders,
  and a prune-down note for Community-Edition deployments.
  `docs/dpa-template.md` §5 now distinguishes the audit log (a record of
  processing *operations*) from this register.
- `docs/onboarding.md` — defines the Compliance-Edition onboarding scope
  ("dedicated onboarding" at the Enterprise tier, lighter at the others):
  per-tier inclusion table, the contract-signed-to-go-live sequence,
  timeframe, and what is out of scope. Referenced from
  `COMMERCIAL-LICENSE.md`.
- `docs/commercial-license-agreement-template.md` — a signature-ready
  Commercial License Agreement skeleton (licence grant, term / renewal,
  fees, warranties, liability cap, third-party-IP indemnity,
  confidentiality, German law / Hamburg jurisdiction) with Schedules
  A–D wiring in the tier and fees, the Support SLA, the DPA + TOM annex,
  and the onboarding scope. Published for procurement review; flagged
  "not legal advice — have counsel review and tailor it before signing."
- `docs/vendor-security-questionnaire.md` — standing answers to the
  recurring questions in vendor security questionnaires (VSA, SIG / SIG
  Lite, CAIQ, BSI Grundschutz-style reviews, KRITIS / B3S supplier
  checklists, ad-hoc DPO worksheets). 16 sections — vendor ID, product
  overview, hosting / data residency, GDPR Art. 28 readiness, encryption,
  authN/authZ, application security (OWASP Top 10 walk), audit logging,
  vulnerability management, incident response, BCP/DR, source / supply
  chain / SBOM, certifications, support tiers, exit / portability,
  personnel, public artefacts index — each section cites the canonical
  source (DPA template, TOM annex, RoPA, support framework, pentest
  report, threat model). Lets a prospect's reviewer clear an internal
  threshold before any sales contact, and lets the operator hand a
  single PDF in response to a questionnaire instead of re-deriving the
  answers each time.
- `docs/third-party-licenses.md` — OSS-license posture for the
  dual-license model: the runtime dependency tree is permissive or
  MPL-2.0 throughout; the only GPL pieces are in the native layer
  (`x265` bundled-but-never-invoked in the `pillow-heif` wheel; Debian's
  GPL FFmpeg, driven as a separate program), neither affecting
  FileMorph's own licensing; GPL-free builds are offered per Compliance
  agreement; everything verifiable against the release CycloneDX SBOM.
  The `License Map` in `docs/tech-stack-rationale.md` was refreshed to
  match (pikepdf MPL-2.0, mammoth, Babel; corrected `pillow-heif` /
  FFmpeg rows).
- `docs/security-pentest-report.md` gained a status banner and a
  per-finding (PT-001 … PT-013) resolution table marking it as a
  historical April-2026 self-assessment (not an external pen test)
  superseded by `docs/security-overview.md`.
- CycloneDX SBOM generation in CI (`.github/workflows/sbom.yml`),
  attached to every GitHub release.
- `/enterprise` Compliance-Edition landing page.
- `COMMERCIAL-LICENSE.md` rewritten with the Compliance Edition
  tier structure (Starter / Standard / Enterprise / KRITIS).

### Added — Compliance code (NEU-B)

- **Tamper-evident audit log** with SHA-256 hash chain
  (`app/core/audit.py`, migration 005, Postgres append-only trigger).
  ISO 27001 A.12.4.1 / BORA §50 / BeurkG §39a compatible. `verify_chain`
  helper detects retroactive edits from a SQL dump alone.
- `X-Output-SHA256` response header on `/convert` + `/compress`,
  computed via chunk-streamed SHA-256 (NEU-B.2).
- `RETENTION_HOURS` configurable retention window, periodic
  background sweep of stale temp dirs.
- `auth.{register,login,password_reset,email_verification,account_deletion}.*`
  events feed the audit chain with hashed-email actor identifiers (no
  raw email storage).
- `cosign` keyless OIDC signing of every container image push
  (`.github/workflows/docker.yml`) plus GPG-signed git tags via
  `.github/workflows/release.yml` and a maintainer key list at
  `docs/release-signing.md` — the maintainer Ed25519 signing key
  (`security@filemorph.io`) is now registered there, so `release.yml`
  can publish signed releases; the doc also gained a "First-time setup"
  walkthrough for generating / rotating the key.

### Added — Use-case openers (NEU-C)

- **PDF/A-2b conversion target** at `/api/v1/convert?target_format=pdfa`.
  Two-path orchestration: ghostscript re-render path
  (`app/converters/_ghostscript.py`) embeds fonts and applies
  `-dPDFA=2`; pikepdf markup pass writes XMP `pdfaid:part=2` /
  `conformance=B`, GTS_PDFA1 OutputIntent with embedded sRGB ICC, and
  strips PDF/A-forbidden surfaces. Falls back to markup-only when gs
  is not on PATH.
- **veraPDF CI gate** (`.github/workflows/verapdf.yml`) runs the
  official veraPDF Docker image against a converter-produced fixture
  on every PR to main; fails the workflow on any conformance error.
- **EXIF/XMP/IPTC stripped by default** on every image conversion +
  compression (`app/converters/_metadata.py`). ICC profile preserved.
- **`X-Data-Classification` header** middleware
  (`app/core/data_classification.py`): BSI-style taxonomy
  (`public` / `internal` / `confidential` / `restricted`); echoed
  back on responses; propagated into every convert/compress
  audit-log payload.

### Added — Capacity (NEU-D)

- **Concurrency limiter** (`app/core/concurrency.py`): global
  semaphore + per-actor tier-bound semaphore with 0.5s acquire
  timeout. 503 (global capacity) vs. 429 (per-actor) with
  `Retry-After`.
- `/pricing` page surfaces the per-tier concurrency + rate-limit
  contract so callers can size their client pools.

### Added — Monthly API-call quota (PR-M)

- The per-tier monthly call limits (`api_calls_per_month` in
  `app/core/quotas.py` — 500 Free / 10 000 Pro / 100 000 Business)
  are now **enforced**, not just informational. `app/core/usage.py`
  records one `UsageRecord` row per successful `/convert`,
  `/convert/batch`, `/compress`, `/compress/batch` and counts the
  current calendar month (UTC) before each call. Over the limit →
  `429 Too Many Requests` + `Retry-After` pointing at the next month
  boundary. A batch counts as one call. Anonymous tier (per-IP
  rate-limit only) and Enterprise (unlimited) are exempt. Migration
  007 adds the `(user_id, timestamp)` index that keeps the gate
  query sub-millisecond.

### Changed — JWT `iss` / `aud` claims (PR-J)

- **Breaking for in-flight tokens.** Every JWT FileMorph mints
  (access, refresh, password-reset, email-verify) now carries the
  RFC 7519 `iss` and `aud` claims from `JWT_ISSUER` (default
  `filemorph`) / `JWT_AUDIENCE` (default `filemorph-api`), and every
  decode path validates them. A token minted before this change — or
  by a different FileMorph deployment, or by another service that
  shares a leaked secret — is rejected even with a valid HMAC.
  Existing sessions invalidate on the next request after upgrade
  (same blast radius as rotating `JWT_SECRET`). Multi-instance
  operators behind one identity provider should give each instance a
  distinct `JWT_AUDIENCE`.

### Added — Stripe dunning webhooks (PR-J)

- Migration 008 adds `users.subscription_status` (mirrors Stripe's
  `Subscription.status`). The billing webhook now handles
  `invoice.payment_failed` and the full status-transition matrix on
  `customer.subscription.{created,updated,deleted}`: a failed charge
  sets `past_due`, fires a "payment failed — update your card" email
  **once per dunning cycle** (debounced on the status flag), and
  records `billing.subscription.payment_failed` +
  `billing.dunning_email_sent` audit events. The paid tier is kept
  during Stripe's retry window (`past_due` / `incomplete`); recovery
  back to `active` re-derives the tier and records
  `billing.subscription.recovered`; a terminal status (`canceled` /
  `unpaid` / `incomplete_expired`, or the `.deleted` event) drops the
  tier to Free with `billing.subscription.canceled`. An unknown Stripe
  status leaves the tier untouched (recorded, not acted on). New
  `app/templates/emails/dunning.{html,txt}`. `GET /api/v1/auth/me` now
  returns `subscription_status` so the dashboard can surface a
  payment-issue banner.

### Added — Email internationalisation (PR-i18n-3)

- Transactional email (verification, password-reset, account-deleted,
  the PR-J dunning notice) is now localised. `app/core/email.py` gains
  `render_email(stem, *, locale, **ctx) -> (subject, html, text)` — one
  entry point backed by a per-locale Jinja `Environment`; the eight
  `app/templates/emails/*.{html,txt}` templates use `{% trans %}` blocks
  and `<html lang="{{ locale }}">`. Subject lines live in `EMAIL_SUBJECTS`
  marked with `N_(...)` for extraction. German catalog updated; the
  per-route ad-hoc email Jinja envs are gone.
- Migration 009 adds `users.preferred_lang` (`de` / `en`; NULL = use
  `LANG_DEFAULT`). Seeded at `/register` from the locale the user signed
  up in. `/forgot-password`, `/resend-verification` and the deletion
  confirmation render in `preferred_lang` if set, otherwise the request
  locale; the dunning mail (fired from a Stripe webhook with no request
  context) reads `preferred_lang` directly.
- `PUT /api/v1/auth/account/language` (Bearer; body
  `{"preferred_lang": "de"|"en"}`, `422` on anything else) lets a user
  change it; surfaced as an "Email language" picker on `/dashboard`.
  `GET /api/v1/auth/me` now returns `preferred_lang`. The web-UI locale
  is unaffected — it stays URL-prefix driven (no cookie); a sticky
  web-UI preference for logged-in users is a tracked follow-up.

### Added — Cloud-Edition pre-launch hardening (NEU-B.3 b/c.1)

- **Email verification** (NEU-B.3 slice b): Migration 006 adds
  `users.email_verified_at`. JWT verify-token bound to email-at-
  issuance (`eat` claim), 7-day TTL. `POST /auth/verify-email` +
  `POST /auth/resend-verification` (auth-required to avoid spam-
  vector). Fire-and-forget at register-time. New email + landing
  page templates.
- **Account deletion self-service, free path** (NEU-B.3 slice c.1):
  `DELETE /api/v1/auth/account` with three-field re-confirmation
  (`password` + `confirm_email` + `confirm_word=='DELETE'`). Last-
  admin guard (409). Cascade: ApiKey CASCADE, FileJob/UsageRecord
  SET NULL, audit-events SET NULL on actor. Confirmation email after
  commit. Stripe-touched accounts return 409 directing to
  `privacy@filemorph.io` until the paid-path tax-retention flow
  (slice c.2 — HGB §257, AO §147) ships.

### Added — Internationalisation completeness (post-pivot polish)

- **Impressum fully translated.** `app/templates/impressum.html` was
  previously German-only with a small EN preamble explaining why the
  body stayed German. Now every section heading + prose paragraph
  flows through `{{ _('…') }}`; only the legally-binding § references
  (§ 5 DDG, § 19 UStG, § 139c AO, § 18 (2) MStV, § 36 VSBG) and the
  operator's name + address stay verbatim. The Imprint is reachable
  in English at `/en/imprint` (the locale alias for `/impressum`,
  resolved via `_PATH_ALIASES` in `app/core/i18n.py`); footer + language
  switcher route through `localized_url`, which collapses `/imprint`
  back to the canonical `/impressum` on a DE-locale switch.
- **Admin Cockpit fully i18n'd.** `app/templates/cockpit.html` carried
  0 of 213 lines through `_()` — every heading, dropdown label, table
  header, and modal chrome string is now wrapped, with 35 new German
  translations.
- **JS-side i18n catalogue.** `app/core/i18n.py::_js_i18n_strings` is
  the new single source of truth for runtime strings the front-end
  needs (`Convert` / `Compress` button labels, validation alerts, the
  dynamic logged-in nav `Dashboard / Sign Out`, …). Translated per
  request and JSON-encoded into `window.FM_I18N` via a
  `<script type="application/json" id="fm-i18n-strings">` block in
  `base.html`. Eight JS files (`app.js`, `auth.js`, `dashboard.js`,
  `login.js`, `register.js`, `forgot-password.js`, `pricing.js`,
  `cockpit.js`, `cockpit-metrics.js`) read from there instead of
  hardcoding English literals. `auth.js` also derives the active
  locale prefix from `<html lang>` so dynamic nav links keep the
  user in their currently-active locale namespace.
- **Sitemap hreflang.** `/sitemap.xml` now emits one `<url>` block per
  (route × locale) combination — five base routes × three variants
  (x-default + de + en) = 15 entries on a Community deployment — each
  carrying its full `<xhtml:link rel="alternate" hreflang="…">` siblings
  list. The impressum/imprint alias is honoured end-to-end (the EN
  alternate of `/impressum` is `/en/imprint`, matching the footer +
  language-switcher behaviour). Without this, Google indexed locale
  variants as duplicate content; with it, they're declared siblings.

### Hardened — Scope-guard deny-by-default + 4-layer parity

- **Strategic-doc filename patterns now deny-by-default.**
  `.githooks/pre-commit::INTERNAL_PATHS` was a literal blocklist of
  13 specific filenames; a future `docs/foo-strategy.md` or
  `docs/q3-roadmap.md` with a fresh name would have slipped past the
  hard gate. The rule is widened to a pattern set: `*-strategy.md`,
  `*-plan.md`, `*-roadmap.md`, `*-internal.md`, `*-runbook.md`,
  `marketing-*.md`, `persona-*.md`, `competitive-*.md`,
  `engineering-pm-*.md`, `business-case-*.md`, `sprint-*.md`,
  `launch-*-tracker.md`, `launch-*-snapshot.md`,
  `launch-*-readiness.md`. Synced into `.githooks/pre-push` and into a
  new "Block strategic / business-internal docs" step in
  `.github/workflows/scope-guard.yml` so a `--no-verify`-bypassed
  commit still fails the server-side gate.
- **Notify-Ops + Article 28/30 compliance templates whitelisted.**
  `.github/workflows/notify-ops.yml` legitimately references
  `OPS_REPO_DISPATCH_PAT` (the secret name; value lives in GitHub
  Secrets); the three compliance templates `dpa-tom-annex.md`,
  `records-of-processing-template.md`, and
  `commercial-license-agreement-template.md` legitimately carry the
  operator's legal address as part of the Art. 28 processor identity.
  Both groups are now in the `ALLOW_RE` allowlist so future edits
  don't trip the hook (see commits `147d1a4` + `4e33249`).

### Added — Project hygiene (Kleinkram-cleanup sprint)

- **Deprecated stdlib / Starlette / Stripe APIs replaced.** Eliminates
  the 14 DeprecationWarnings emitted on every test run:
  `HTTP_413_REQUEST_ENTITY_TOO_LARGE → HTTP_413_CONTENT_TOO_LARGE`,
  `HTTP_422_UNPROCESSABLE_ENTITY → HTTP_422_UNPROCESSABLE_CONTENT`
  (Starlette 0.40 rename), `stripe.error.SignatureVerificationError →
  stripe.SignatureVerificationError` (stripe-python 12.x flat
  namespace), `datetime.utcnow() → datetime.now(timezone.utc)` in
  `scripts/launch_gate_check.py` (PEP 668).
- **SPDX license header on every .py file.** Project convention from
  CLAUDE.md applied to the 41 source files still missing the
  `# SPDX-License-Identifier: AGPL-3.0-or-later` line. Helps SBOM
  tooling (CycloneDX, Scancode) attribute licence at file granularity.
- **Container hardening — defence in depth on the existing non-root
  user.** `docker-compose.yml` adds `security_opt:
  [no-new-privileges:true]` (blocks setuid-style escalation inside the
  container) and `cap_drop: [ALL]` (the app needs no Linux
  capabilities — port 8000 is unprivileged, no `CAP_NET_RAW` or
  `CAP_DAC_OVERRIDE` required by any converter). `read_only: true` +
  `tmpfs /tmp` is staged as commented opt-in for operators who want
  the stronger guarantee.
- **`.env.example` env-var discoverability.** Three missing knobs
  (`LANG_DEFAULT`, `SECURITY_CONTACT_EMAIL`, `SMTP_FROM_NAME`,
  `SMTP_REPLY_TO`) added; `SMTP_USER`/`SMTP_FROM` renamed to
  `SMTP_USERNAME`/`SMTP_FROM_EMAIL` to match the pydantic-settings
  attribute stems. `CORS_ORIGINS` default flipped from `*` to
  `http://localhost:8000` (the middleware refuses to combine `*` with
  `allow_credentials=true` anyway). `app.app_version` bumped to PEP 440
  dev marker `1.1.0.dev0`; `pyproject.toml::version` kept in sync.
- **CI / scope-guard workflows: concurrency groups.** `ci.yml`,
  `scope-guard.yml`, `verapdf.yml` now declare `concurrency:
  cancel-in-progress: true` on non-main / non-develop refs. A new push
  on the same PR branch cancels superseded queued runs; main /
  develop runs always complete (branch-protection gates).
- **PT-011 hardened.** `/api/v1/health` strips down to `{"status":
  "ok"}` — no version, no `ffmpeg_available` flag (see Security
  section above). `/api/v1/ready` carries the operational state.

### Added — Supply-chain hygiene (PR-S)

- All GitHub Actions `uses:` references pinned to a full 40-character
  commit SHA (with the `# vX.Y` comment Dependabot tracks), instead of
  mutable tags.
- `.github/dependabot.yml` (NEW): weekly update PRs for three
  ecosystems — `pip` (grouped minor/patch), `github-actions` (grouped),
  and `docker` (base-image digest) — so the manual pins stay current
  without manual chasing.
- Dockerfile base image pinned by `@sha256:` digest, with the
  `python:3.12-slim` tag kept in a trailing comment for Dependabot's
  `docker` updater.
- Every workflow declares an explicit least-privilege `permissions:`
  block for `GITHUB_TOKEN` (`contents: read` by default; `contents:
  write` only where a release-asset upload needs it; `{}` for the
  cross-repo-dispatch job that uses a separate PAT).
- `tests/test_supply_chain_hygiene.py` (NEW): regression guards that
  fail CI if an action pin reverts to a tag, the Dockerfile loses its
  digest, a workflow ships without a `permissions:` block, or
  `dependabot.yml` stops covering a pinned ecosystem.

### Operations

- Docker base image now bundles `ghostscript` so the PDF/A re-render
  path is on by default for self-hosters of the official image.
- CI workflow installs `ghostscript` so the converter exercises the
  full path under test.

### Test coverage

`tests/` grew from ~260 to **627 collected** (15 Windows-skipped —
the PDF/A test modules; see test_pdfa.py docstring for the qpdf
DLL-load conflict; Linux CI + production are unaffected). The 32
post-trust-foundation additions cover the i18n catalogue end-to-end
(FM_I18N JSON blob present + locale-resolved per request), the
impressum/imprint locale-alias mapping (forward + reverse), the
sitemap hreflang invariants, and the expanded scope-guard regex
positives + public-doc negatives.

---

## [1.0.2] — 2026-04-20

### Security
- **PT-002:** `validate_api_key()` now uses a `hmac.compare_digest` loop that always
  iterates all stored hashes — eliminates timing-attack vector on key enumeration
- **PT-008:** WeasyPrint `url_fetcher` blocked for Markdown→PDF conversion — prevents
  SSRF via embedded images or CSS `@import` in user-supplied Markdown
- **GDPR:** Temp files now use UUID stems instead of original filenames — eliminates
  PII from filesystem paths, OS logs, and crash dumps
- **CVE-2024-28219:** Raised `Pillow` minimum to `>=10.3.0`
- **CVE-2024-53981:** Raised `python-multipart` minimum to `>=0.0.18`

---

## [1.0.1] — 2026-04-19

### Fixed
- `TemplateResponse` call updated for Starlette 1.0 API compatibility
  (`TemplateResponse(request, name)` instead of deprecated `TemplateResponse(name, {"request": request})`)

### Added
- `dev.ps1` — Windows developer startup script: auto-creates venv, installs dependencies,
  generates API key on first run, starts uvicorn with `--reload`. Searches Windows Registry
  for Python installations so it works regardless of PATH configuration.
- `create-shortcut.ps1` — creates a Desktop shortcut that launches `dev.ps1` via PowerShell

### Changed
- GitHub Actions CI updated to Node.js 24 (Node.js 20 deprecated June 2026)

---

## [1.0.0] — 2026-04-15

### Added

**Converters**
- Image: HEIC/HEIF, JPG, PNG, WebP, BMP, TIFF, GIF, ICO — all combinations via Pillow + pillow-heif
- Documents: DOCX → PDF, DOCX → TXT, TXT → PDF, PDF → TXT
- Markdown: MD → HTML, MD → PDF (via WeasyPrint)
- Spreadsheets: XLSX ↔ CSV, CSV ↔ JSON
- Audio: MP3, WAV, FLAC, OGG, M4A, AAC, WMA, Opus — all combinations via pydub/ffmpeg
- Video: MP4, MOV, AVI, MKV, WebM, FLV, WMV — all combinations via ffmpeg-python

**Compression**
- Image quality compression: JPG, PNG, WebP, TIFF (Pillow quality parameter)
- Video CRF compression: MP4, MOV, AVI, MKV, WebM (ffmpeg libx264 CRF)

**REST API**
- `POST /api/v1/convert` — file conversion with optional quality parameter
- `POST /api/v1/compress` — quality-based file compression
- `GET /api/v1/formats` — list of all supported format pairs
- `GET /api/v1/health` — health check with ffmpeg availability flag
- API key authentication via `X-API-Key` header (SHA-256 hashed storage)
- Rate limiting: 60 requests/minute per IP (slowapi)
- CORS middleware (configurable origins)
- Upload size limit (configurable, default 100 MB)

**Web UI**
- Dark-mode interface with TailwindCSS
- Drag & drop file upload
- Dynamic format dropdown (shows only compatible targets for the uploaded file)
- Quality slider
- API key input
- Download result button
- Convert / Compress mode toggle

**Operations**
- Docker image with ffmpeg and libheif included
- `docker-compose.yml` with health check and data volume
- GitHub Actions CI (lint + test on every push)
- GitHub Actions Docker workflow (build + push to GHCR on version tags)
- `scripts/generate_api_key.py` — CLI key generator

**Documentation**
- `README.md` with UI mockup, quickstart, API examples
- `docs/installation.md` — Windows and Linux installation guide
- `docs/api-reference.md` — complete API reference with code examples (Python, JS, PHP, C#)
- `docs/self-hosting.md` — production deployment, nginx, SSL, internal network
- `docs/formats.md` — all formats with quality notes and use cases
- `docs/development.md` — project structure, adding converters, release process
- `CONTRIBUTING.md`
