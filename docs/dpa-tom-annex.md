# Annex II — Technical and Organisational Measures (TOM)

This is the template for the **"Annex II"** referenced in
[`dpa-template.md`](dpa-template.md) §7 and its "How to finalise"
checklist. It is published in the open-source repository so a procurement
reviewer or data-protection officer can read the substance before
requesting a binding contract. At finalisation it is attached to the
signed DPA with the `[operator: …]` placeholders filled in for the
concrete deployment; the version attached to the counter-signed DPA is
the binding one — this file is the starting point.

> **Two layers.** The measures below split into:
>
> - **Application-level measures** — implemented *by the FileMorph
>   software itself*, identical in every deployment of the same version,
>   verifiable in the source. Stated here as facts, with the code anchor,
>   for the current code on `main`; the only tagged release so far,
>   v1.1.0 (2026-06-01), predates some of them — see
>   [`CHANGELOG.md`](../CHANGELOG.md).
> - **Deployment-level measures** — implemented *by whoever operates the
>   deployment* (hosting, network, backups, on-call). Shown as
>   `[operator: …]` placeholders: a self-hoster fills them with their own
>   arrangements, the FileMorph operator fills them at DPA finalisation.
>   They are deliberately not pinned in the public repo because they vary
>   by deployment.
>
> Narrative reference for the application-level measures (with code
> anchors): [`security-overview.md`](security-overview.md). See also
> [`threat-model.md`](threat-model.md), [`patch-policy.md`](patch-policy.md),
> [`incident-response.md`](incident-response.md),
> [`release-signing.md`](release-signing.md),
> [`sub-processors.md`](sub-processors.md),
> [`third-party-licenses.md`](third-party-licenses.md).

## I. Confidentiality (Vertraulichkeit) — Art. 32(1)(b) GDPR

### Physical access control (Zutrittskontrolle)

`[operator: physical security of the hosting facility — e.g. "Hetzner
Online GmbH — data centre in the EU, ISO 27001-certified,
24/7 access control, CCTV, mantrap"; or the customer's own datacentre
measures for an on-prem deployment]`. The FileMorph software holds no
physical assets of its own.

### System access control (Zugangskontrolle)

- API authentication: keys stored as SHA-256 hashes (never raw); the
  key file is validated via `hmac.compare_digest` (constant-time),
  per-user keys by lookup of that hash, revoked keys are rejected —
  `app/core/security.py`.
- Password authentication (Cloud features): bcrypt with an adaptive cost
  factor — `app/core/auth.py`.
- Session tokens: short-lived JWTs, 15-minute access / 30-day refresh —
  `app/core/tokens.py`.
- Administrative interface (`/cockpit`): requires a valid JWT *and*
  `role='admin'`, re-checked against the database on every request — a
  stale token cannot escalate after a role change.
- Upload pipeline: a magic-byte deny-list (`BLOCKED_MAGIC` in
  `app/core/processing.py`) rejects files that start with a PE, ELF,
  shell-script or PHP signature before any decoder runs; the converter
  is chosen from the file extension, not detected from content.
- `[operator: OS-level access — SSH key-only login, no password auth,
  restricted sudo, host firewall]`.

### Data access control (Zugriffskontrolle)

- Per-tier quotas (file size, batch size, output cap) enforced
  server-side — `app/core/quotas.py`.
- Endpoints are role-bound; tier limits apply via whichever
  authentication path produced the caller — `app/api/routes/auth.py::get_optional_user`.
- No cross-request file access: each request decodes into its own
  in-memory buffer; where a temp path is needed it is a per-request UUID
  stem under an `fm_`-prefixed directory, removed in the request
  `finally` block.
- `[operator: database credentials in environment only; least-privilege
  DB role; backup storage access-restricted]`.

### Separation control (Trennungskontrolle)

- Conversions are stateless — no persistent file storage by design;
  nothing accumulates across requests or tenants.
- A self-hoster needing OS-level multi-tenant isolation runs one instance
  per tenant (see `security-overview.md` § Threat Model, "what is
  intentionally out of scope").
- `[operator: production separated from staging/development; distinct
  credentials per environment]`.

### Pseudonymisation (Pseudonymisierung) — Art. 32(1)(a) GDPR

- Uploaded files are never written to disk under their original filename
  — UUID stems only; the original name survives only in the
  `Content-Disposition` response header, filtered through
  `safe_download_name()` — `app/core/utils.py`.
- The audit log identifies an actor by account ID (a random UUID), never
  by email address. A failed login, a duplicate registration, a
  password-reset request and a contact-form message also store a
  SHA-256 hash of the lower-cased email address — a pseudonym, not an
  anonymisation: a known address can be hashed and matched —
  `app/core/audit.py`, `app/api/routes/auth.py`,
  `app/api/routes/contact.py`.
- API keys are stored only as SHA-256 hashes; raw keys are shown once at
  creation and never logged.
- Image conversions and compressions strip EXIF / XMP / IPTC metadata
  (GPS coordinates, camera serial, photographer name, capture
  timestamps) by default — `app/converters/_metadata.py` (ICC colour
  profile preserved so wide-gamut workflows are not desaturated).
- PII redaction (Cloud/EE add-on, where `AI_OPERATIONS_ENABLED` is set)
  processes uploaded documents in memory and writes neither the content nor any
  detected value to logs or the audit trail; the audit entry records operation
  metadata and a redacted-item count only — `app/api/routes/ai.py`,
  `app/ee/ai_ops/`. Redaction runs locally with no external model call.
  **Honest limit:** it covers structured identifiers (email, IBAN, phone, IPv4,
  payment card) by deterministic match; free-text identifiers (names, addresses)
  are out of scope pending NER, and a redacted file is not certified as fully
  anonymous.

## II. Integrity (Integrität) — Art. 32(1)(b) GDPR

### Transfer control (Weitergabekontrolle)

- In transit: TLS 1.2+; HSTS emitted when the proxy reports HTTPS and
  uvicorn is configured to trust it —
  `app/main.py::security_headers`; on filemorph.io the header is served
  from the Cloudflare edge instead (`max-age=15552000`). TLS is
  terminated at the operator's reverse proxy — `[operator: proxy configuration; certificate
  management, e.g. Caddy automatic HTTPS]`.
- CORS is an allow-list, never `*` with credentials — `CORS_ORIGINS`
  environment variable.
- The FileMorph application transmits no file content, file names, or
  file hashes to any sub-processor — see [`sub-processors.md`](sub-processors.md);
  the only outbound calls are to the configured database, the SMTP relay
  (account and billing mail, and contact-form messages and cancellations
  that need manual handling to the operator), and Stripe (creating the
  customer and the Checkout / Billing-Portal sessions, setting a
  subscription to end when its holder cancels online, and cancelling
  subscriptions when an account is deleted;
  Stripe's webhook calls come in the other direction and are
  signature-checked).
- Output integrity: every file returned by the single-file `/convert`
  and `/compress` endpoints carries an `X-Output-SHA256` response header
  (streaming SHA-256 of the delivered bytes); the same hash lands in the
  audit-log payload, so the controller can verify a file matches the
  attestation made at conversion time. Batch ZIPs, the `/pdf/*` tools
  and PII redaction return no such header.

### Input control (Eingabekontrolle)

- Tamper-evident audit log: SHA-256 hash chain, Postgres append-only
  trigger — `app/core/audit.py`, Migration 005; the `verify_chain`
  helper detects retroactive edits from a SQL dump alone. Compatible with
  ISO 27001 A.12.4.1 / BORA §50 / BeurkG §39a. It records registration,
  login, email verification, password reset and account deletion;
  subscription and payment events, including the withdrawal waiver at
  checkout; single-file conversions and compressions; contact-form
  messages; and PII redactions. It does not record API-key creation or
  revocation, admin changes in the cockpit, batch jobs, or the `/pdf/*`
  tools.
- Structured logs record operation metadata (operation, format pair,
  byte counts, duration, success flag, tier, data classification) and no
  file content — regression guard `tests/test_observability_logs.py`.
- `X-Data-Classification` header (BSI-style taxonomy: `public` /
  `internal` / `confidential` / `restricted`) echoed on responses and
  propagated into the convert/compress audit payload —
  `app/core/data_classification.py`.

## III. Availability and resilience (Verfügbarkeit und Belastbarkeit) — Art. 32(1)(b),(c) GDPR

### Availability control (Verfügbarkeitskontrolle)

- Single-user denial-of-service resistance: a concurrency limiter (global
  semaphore + per-actor tier-bound semaphore, 0.5 s acquire timeout)
  returns 503 (global capacity) / 429 (per-actor) with `Retry-After` —
  `app/core/concurrency.py`. Every synchronous C-binding call (FFmpeg,
  WeasyPrint, Pillow, pypdf) runs in a worker thread, never on the event
  loop.
- Rate limiting: explicit slowapi limits per API endpoint, from 1 to
  120 requests per minute (the contact form: 5 per hour), counted per
  client IP — per signed-in account on the account endpoints (API keys,
  billing, email language); every limit, and the four endpoints exempt
  on purpose, are listed in
  [`api-reference.md` § Rate Limiting](api-reference.md#rate-limiting).
  Rejected `X-API-Key` attempts have their own budget of 30 per minute
  per IP, then get `429`; a valid key is never refused. The limiter's
  own log lines, which carry the client IP or account ID, are
  suppressed — `app/core/rate_limit.py` (in-memory; effective for a
  single instance — a multi-instance deployment needs an external store,
  noted in `security-overview.md` § Known Limitations).
- Readiness probe `/api/v1/ready` reports database + tempdir health so an
  orchestrator can gate traffic correctly; `/api/v1/health` is a cheap
  liveness probe that exposes only `{"status":"ok"}`.
- `[operator: hosting uptime target / SLA; load balancer; redundancy;
  DDoS protection, e.g. Cloudflare]`.

### Rapid restorability (rasche Wiederherstellbarkeit) — Art. 32(1)(c) GDPR

- The application is stateless beyond the database and environment
  configuration — recovery is "restore the database, redeploy the
  signed image"; there is no separate file store to rebuild.
- The audit log is plain Postgres rows, SQL-dumpable for export or
  migration.
- `[operator: backup regime — frequency, retention, off-site copy,
  encryption at rest; tested restore procedure; RTO / RPO targets]`.

## IV. Procedures for regular review, assessment and evaluation — Art. 32(1)(d) GDPR

### Data-protection management

- Privacy policy maintained (`privacy.html`); sub-processor list
  maintained ([`sub-processors.md`](sub-processors.md)); this annex
  reviewed `[operator: cadence — e.g. annually and on any material
  change]`.
- Privacy by design / by default (Art. 25 GDPR): metadata stripped by
  default, processing ephemeral by default (`RETENTION_HOURS=0`), no
  analytics, no telemetry, no third-party CDN — see `security-overview.md`
  § Data Privacy.
- Data-subject rights: self-service account deletion at
  `DELETE /api/v1/auth/account` (Art. 17) with multi-field
  re-confirmation; data export available on request (Art. 20) — see
  [`gdpr-account-deletion-design.md`](gdpr-account-deletion-design.md).

### Incident-response management

- Documented vulnerability-disclosure and incident-response process —
  [`SECURITY.md`](../SECURITY.md), [`incident-response.md`](incident-response.md);
  personal-data-breach notification to the controller within 72 hours
  (DPA §9); GitHub Security Advisories for Critical / High issues.

### Sub-processor control (Auftragskontrolle)

- Sub-processors enumerated with data category, region, and disabling
  toggle ([`sub-processors.md`](sub-processors.md)); a DPA is in place
  with each; at least 30 days' advance notice on any addition or
  replacement (DPA §6).

### Software supply-chain controls

- Python dependencies: `requirements.lock` pins every direct and
  transitive dependency to an exact version and hash, and the image
  installs from it with `pip install --require-hashes`
  (`requirements.txt` states version ranges, not exact pins) —
  `Dockerfile`.
- `pip-audit -r requirements.lock` is a blocking CI gate. It checks the
  pinned versions the image installs (not `pip` itself or the base
  image's OS packages), and a finding passes only if waived by an
  `--ignore-vuln` entry justified in a comment —
  `.github/workflows/ci.yml`; regression guard for the audit target:
  `tests/test_supply_chain_hygiene.py`.
- A CycloneDX SBOM (`filemorph-{version}.cdx.json`) is attached to each
  release; container images are cosign-signed (keyless OIDC); Git tags
  are GPG-signed; patch timelines per [`patch-policy.md`](patch-policy.md)
  (Critical 7 days / High 30 days / Medium-Low next regular release);
  third-party-license posture in
  [`third-party-licenses.md`](third-party-licenses.md).
- Release workflow in two jobs: `sbom` installs the image's dependency
  set and the SBOM generator with read-only repository access;
  `verify-and-publish` checks the tag's GPG signature and publishes with
  write access, installs nothing, and receives the SBOM as an artifact.
  Neither job restores a cache or keeps the checkout's credentials. The
  generator is installed hash-pinned and wheels-only from
  `requirements-sbom.lock` — `.github/workflows/release.yml`; regression
  guard `tests/test_supply_chain_hygiene.py`.
- `.dockerignore` keeps secrets and local state (`.env*`, the API-key
  file in `data/`, `.git`, Python environments) out of the image build
  context — regression guard `tests/test_dockerignore.py`.
- `[operator: dependency-update cadence on the running deployment; how
  SBOM diffs are reviewed before deploying]`.

---

## How to fill this in at finalisation

1. Replace every `[operator: …]` placeholder with the concrete
   arrangement for the deployment named in DPA §3.
2. Add the deployment's instance location, network segmentation, on-call
   arrangement, and current penetration-test status (see the DPA "How to
   finalise" checklist, step 3).
3. Date the annex and attach it to the counter-signed DPA.

**Self-hosters:** the application-level rows are facts about the
FileMorph code you are running and need no editing; fill the
`[operator: …]` rows with your own infrastructure measures and attach
this to your own Article 28 documentation. The file
[`sub-processors.md`](sub-processors.md) has the same "copy and prune"
guidance for the sub-processor list.

## See also

- [`dpa-template.md`](dpa-template.md) — the DPA this is Annex II to.
- [`security-overview.md`](security-overview.md) — the controls in
  narrative form, with code anchors.
- [`sub-processors.md`](sub-processors.md) — the sub-processor list (DPA §6).
- [`threat-model.md`](threat-model.md) · [`incident-response.md`](incident-response.md) · [`patch-policy.md`](patch-policy.md) · [`release-signing.md`](release-signing.md) · [`third-party-licenses.md`](third-party-licenses.md) · [`support-sla.md`](support-sla.md).
