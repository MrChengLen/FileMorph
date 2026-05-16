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
