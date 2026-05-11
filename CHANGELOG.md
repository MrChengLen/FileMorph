# Changelog

All notable changes to FileMorph are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versions follow [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

The Compliance-First strategic pivot (2026-05): FileMorph adds the
auditability + traceability surface that DACH Behörden, Krankenhäuser,
and Anwaltskanzleien expect. None of this changes the existing public
API behaviour for casual callers — every change is additive, defaulted
off where applicable, and optional at deploy time.

### Added — Trust foundation (NEU-A)

- `security.txt` (RFC 9116) under `/.well-known/security.txt` plus a
  human-readable `/security` page and `SECURITY.md`.
- Architecture overview, sub-processor list, STRIDE threat model,
  patch policy, incident-response playbook, AGPLv3 explainer for
  German Behörden — all under `docs/`.
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
  `docs/release-signing.md`.

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

### Operations

- Docker base image now bundles `ghostscript` so the PDF/A re-render
  path is on by default for self-hosters of the official image.
- CI workflow installs `ghostscript` so the converter exercises the
  full path under test.

### Test coverage

`tests/` grew from ~260 to **370 passed + 12 skipped** (the 12 are
the PDF/A test modules that skip on Windows — see test_pdfa.py
docstring for the qpdf DLL-load conflict; Linux CI + production
are unaffected).

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
