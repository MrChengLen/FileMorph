# Vendor Security Questionnaire — Standard Answers

This document is FileMorph's standing answer to the recurring questions
that appear in procurement security questionnaires — VSA, SIG / SIG Lite,
CAIQ, BSI Grundschutz-style vendor reviews, KRITIS / B3S supplier
checklists, and the ad-hoc DPO worksheets used in the German public
sector and the *Heilberufe*. It exists so a prospect's reviewer can
read the substance in one place, without waiting for a sales cycle,
and so the operator (filemorph.io) can hand a single PDF in response
to a questionnaire instead of re-deriving the answers each time.

> **Status.** Plain-English answers that mirror the binding documents
> in `docs/` and `COMMERCIAL-LICENSE.md`. Where a reviewer needs the
> binding language for an Article 28 attachment or a contract Annex,
> follow the "See also" link at the end of each section — those are
> the canonical sources. The structure here is the *questionnaire*
> view; the structure there is the *contract* view. Where the two
> drift, the canonical source wins.
>
> This document covers the FileMorph **software** as published and the
> **filemorph.io** SaaS deployment operated on top of it. A self-hoster
> running the AGPL build is the controller / operator of their own
> deployment — application-level facts in this document are accurate for
> the code they are running; deployment-level questions (hosting,
> network, on-call, backup) they answer for themselves. The same split
> appears in [`dpa-tom-annex.md`](./dpa-tom-annex.md).

---

## 0. Vendor identification

| | |
|---|---|
| Vendor legal name | Lennart Seidel (sole proprietor, Germany) |
| Vendor address | Reetwerder 25b, 21029 Hamburg, Germany |
| Vendor tax status | Kleinunternehmer per §19 UStG (no VAT on invoices) |
| Primary contact | `hallo@filemorph.io` (sales / general) |
| Security contact | `security@filemorph.io` ([`SECURITY.md`](../SECURITY.md)) |
| Licensing contact | `licensing@filemorph.io` ([`COMMERCIAL-LICENSE.md`](../COMMERCIAL-LICENSE.md)) |
| Support contact | `support@filemorph.io` ([`support-sla.md`](./support-sla.md)) |
| Public source code | [`github.com/MrChengLen/FileMorph`](https://github.com/MrChengLen/FileMorph) |
| Product editions | **Community Edition** (AGPL-3.0, self-host, anonymous conversions) and **Compliance Edition** (per-server commercial licence, `app/ee/`-features unlocked via licence key) — see [`COMMERCIAL-LICENSE.md`](../COMMERCIAL-LICENSE.md) |

## 1. Product overview

### 1.1 What does the product do?

FileMorph is a self-hostable file-conversion service. It accepts an
upload over HTTPS, decodes the file in transient memory, runs the
requested conversion or compression (PDF/A-2b, image format pairs,
video transcodes, document extracts), and streams the converted bytes
back with a SHA-256 integrity header. No file content is persisted by
the application after the response is returned.

### 1.2 Where does it run?

The product is a single Linux container — Python 3.11 + FastAPI on
Uvicorn. It runs behind any reverse proxy (the deployment templates use
Caddy with automatic HTTPS) on any host the customer chooses. The
public SaaS at filemorph.io runs on Hetzner Online GmbH in Frankfurt,
Germany. Self-hosted deployments place themselves wherever the
customer requires — on-premises, sovereign cloud, air-gapped.

### 1.3 What deployment models are supported?

- **SaaS** at `filemorph.io`, operated by the vendor — for casual use
  and small business plans.
- **Self-hosted Community Edition** under AGPL-3.0 — operator runs the
  unmodified container; no licence cost.
- **Self-hosted Compliance Edition** under the per-server commercial
  licence — adds the `app/ee/` feature set (audit-chain hard-mode,
  PDF/A-2b validation gate, signed release-tag verification, dedicated
  support, offline-update tooling); details in
  [`COMMERCIAL-LICENSE.md`](../COMMERCIAL-LICENSE.md).

### 1.4 Who is the typical customer?

German public bodies, hospitals, law firms (Kanzleien), insurers, and
their service providers — buyers who require on-premises / sovereign
deployment, an audit trail, a signed contract chain (DPA + TOM +
licence agreement), and a named support escalation path. The product
is deliberately not aimed at the consumer "free online converter"
segment.

**See also:** [`docs/architecture.md`](./architecture.md),
[`docs/self-hosting.md`](./self-hosting.md),
[`COMMERCIAL-LICENSE.md`](../COMMERCIAL-LICENSE.md).

---

## 2. Hosting, data residency, and data flow

### 2.1 Where is data hosted?

For the SaaS at filemorph.io: Hetzner Online GmbH, Frankfurt / Falkenstein,
Germany (EU). Hetzner's datacentres are ISO 27001-certified. For a
self-hosted deployment: wherever the customer runs the container —
their answer governs.

### 2.2 What data leaves the application?

By design, the FileMorph application code does not transmit user file
content, file names, or file hashes to any third party. The only
outbound calls in the application code are:

- PostgreSQL queries to the configured database (Cloud features).
- SMTP submissions to the configured relay for authentication / billing
  emails — never for file content (Cloud features).
- Stripe Checkout-Session creation and webhook responses (paid tiers
  only).

There is no analytics beacon, no telemetry endpoint, no "phone home"
call, no third-party CDN for static assets. Tailwind, fonts, and the
Chart.js library used by the admin cockpit are all served from the
deployment's own origin.

### 2.3 Are there third-country transfers?

For the SaaS:

- Payment processing for paid subscriptions transits **Stripe Inc.** in
  the United States, covered by the Stripe DPA and EU Standard
  Contractual Clauses (SCCs). Card data is collected by Stripe directly
  and never reaches FileMorph.
- Transactional email transits **Zoho Corporation B.V.**, hosted in
  Frankfurt, Germany — no third-country transfer.
- Server hosting and DNS sit on Hetzner Online GmbH — no third-country
  transfer.

For a self-hoster: their own configuration governs. The application
defaults emit no third-country traffic unless the operator wires Stripe
or a non-EU SMTP relay.

### 2.4 Sub-processors

Default sub-processors for an operator that enables every Cloud feature:
Hetzner (hosting), Cloudflare (optional edge), Stripe (payments), Zoho
(transactional email), GitHub (source distribution and issue tracking).
Each is listed with data category, region, and the toggle that disables
it in [`docs/sub-processors.md`](./sub-processors.md). A Community-Edition
self-host with no database, no SMTP relay, and no Stripe key contacts
**no sub-processors at all** at runtime.

**See also:** [`docs/sub-processors.md`](./sub-processors.md),
[`docs/gdpr-privacy-analysis.md`](./gdpr-privacy-analysis.md),
[`docs/records-of-processing-template.md`](./records-of-processing-template.md).

---

## 3. GDPR / Article 28 readiness

### 3.1 Will the vendor sign a Data Processing Agreement?

Yes. The template DPA is published in
[`docs/dpa-template.md`](./dpa-template.md) so a counsel or DPO can
review the substance before requesting the binding instrument. The
template:

- mirrors Article 28(3) GDPR clauses (subject matter, duration, nature
  and purpose, type of personal data, controller obligations, processor
  obligations);
- references [`docs/dpa-tom-annex.md`](./dpa-tom-annex.md) for the
  Article 32 TOMs ("Annex II");
- references [`docs/sub-processors.md`](./sub-processors.md) for the
  sub-processor list ("Annex III") with the 30-day prior-notice rule
  for any addition or replacement.

The vendor is willing to counter-sign reasonable controller-supplied
DPA variants instead, provided the substance matches the template.

### 3.2 Is there a Record of Processing Activities (Art. 30)?

Yes. [`docs/records-of-processing-template.md`](./records-of-processing-template.md)
contains the Article 30 register in the structure a DPO works in,
filled with the application-level facts and `[operator: …]`
placeholders for deployment-specific entries (legal entity, retention
values, DPO assessment). The operator (filemorph.io) maintains its own
filled-in register in this structure; a self-hoster forks the template
into their own register.

### 3.3 Where are the technical and organisational measures (Art. 32)?

In [`docs/dpa-tom-annex.md`](./dpa-tom-annex.md), grouped along the
four Article 32 categories — confidentiality, integrity, availability
and resilience, regular review. The annex is the "Annex II" the DPA
refers to and attaches to the counter-signed contract.

### 3.4 What is the lawful basis for processing?

- **A1 / file conversion:** Article 6(1)(b) GDPR — performance of the
  service contract requested by the user.
- **A2 / account management:** Article 6(1)(b) for paid customers,
  Article 6(1)(f) (legitimate interest) for free-tier account
  administration.
- **A3 / subscription billing:** Article 6(1)(b) + statutory retention
  duties under HGB §257 / AO §147 (typically 10 years for
  tax-relevant records) under Article 6(1)(c).
- **A4 / transactional email:** Article 6(1)(b) — performance of the
  service contract.
- **A5 / audit logging:** Article 6(1)(c) + Article 6(1)(f) —
  compliance with security obligations and operator's legitimate
  interest in defensible records.
- **A6 / server access logs:** Article 6(1)(f) — legitimate interest
  in operating and securing the service.

### 3.5 How are data-subject rights handled?

- **Access (Art. 15):** by request to `hallo@filemorph.io`. The data
  set is small — email, tier, usage records, audit-event payload
  digests — and can be exported as JSON.
- **Rectification (Art. 16):** users update email and password from the
  dashboard; tier changes happen via the Stripe customer portal.
- **Erasure (Art. 17):** self-service at `DELETE /api/v1/auth/account`.
  Two modes:
  - **Free / never-paid accounts** → hard delete (cascades).
  - **Paid accounts** → restricted delete (HGB §257 / AO §147,
    Art. 17(3)(b)): `email`, `stripe_customer_id`, `tier`, `created_at`
    retained for tax purposes; the rest is nulled, `password_hash` is
    replaced with a sentinel, `deleted_at` is set; ApiKeys deleted,
    FileJob / UsageRecord anonymised; Stripe subscriptions cancelled
    first.
  Full design in [`docs/gdpr-account-deletion-design.md`](./gdpr-account-deletion-design.md).
- **Portability (Art. 20):** the export above is JSON; nothing is held
  in a proprietary format.
- **Restriction / objection (Art. 18 / 21):** by request to
  `hallo@filemorph.io`.

### 3.6 What is the retention regime?

- **File content:** ephemeral — deleted from memory and any temp path
  immediately after the response is returned. `RETENTION_HOURS`
  defaults to `0`. A startup sweep and a background sweep every
  `TEMP_SWEEP_INTERVAL_MINUTES` (default 60 min) remove any
  `fm_`-prefixed temp directory older than `TEMP_SWEEP_MAX_AGE_MINUTES`
  (default 10 min).
- **Account data:** until the user deletes the account.
- **Billing records:** statutory retention under HGB §257 / AO §147
  (typically 10 years from the end of the calendar year of the last
  transaction).
- **Audit log:** governed by `AUDIT_RETENTION_DAYS`, set by the
  operator to match the privacy notice. On account deletion the
  actor identifier is nulled; the event type and payload digest
  survive.
- **Server access logs:** operator-side, per the operator's log-rotation
  policy.

**See also:** [`docs/dpa-template.md`](./dpa-template.md),
[`docs/dpa-tom-annex.md`](./dpa-tom-annex.md),
[`docs/records-of-processing-template.md`](./records-of-processing-template.md),
[`docs/gdpr-privacy-analysis.md`](./gdpr-privacy-analysis.md),
[`docs/gdpr-account-deletion-design.md`](./gdpr-account-deletion-design.md).

---

## 4. Encryption

### 4.1 In transit

TLS 1.2 or higher between client and reverse proxy; HSTS
(`Strict-Transport-Security: max-age=31536000; includeSubDomains`)
emitted on every HTTPS response. The application itself is HTTP-only
inside the trust boundary — TLS is terminated at the operator's
reverse proxy. The deployment template uses Caddy, which provisions
and renews certificates automatically.

### 4.2 At rest

- **File content:** never written to disk under its original name; any
  temp path uses a UUID stem under an `fm_`-prefixed directory and is
  removed in the request's `finally` block. Disk-level encryption is
  the operator's choice — Hetzner volumes can be LUKS-encrypted at
  provisioning.
- **Passwords:** bcrypt with an adaptive cost factor —
  `app/core/auth.py`. Never reversible; never logged.
- **API keys:** SHA-256 hashes only — `app/core/security.py`. Raw key
  is shown once at creation and never logged.
- **Audit log:** plain Postgres rows protected by an append-only
  trigger and a SHA-256 hash chain — `app/core/audit.py`, Migration
  005. Backups protect the integrity of the at-rest copy; the chain
  detects retroactive edits from a SQL dump alone.
- **Database backups:** operator-side. The Compliance Edition deployment
  encrypts backups at rest and stores them off-site; the AGPL operator
  documents their own equivalent in their DPA Annex II.

### 4.3 Key management

- **`JWT_SECRET`** lives only in the environment of the application
  process (Cloud features). Rotation invalidates all active sessions —
  the documented response to suspected compromise.
- **Stripe webhook secret** lives only in the environment; rotation
  invalidates any intercepted webhook URL.
- **GPG release-signing key:** documented setup in
  [`docs/release-signing.md`](./release-signing.md). The public key is
  published; the private key never leaves the maintainer's machine.

### 4.4 Cryptographic primitives

| Use | Primitive | Code anchor |
|---|---|---|
| API-key hashing | SHA-256 | `app/core/security.py` |
| API-key comparison | `hmac.compare_digest` (constant-time) | `app/core/security.py::validate_api_key` |
| Password hashing | bcrypt, adaptive cost | `app/core/auth.py::hash_password` |
| Password verification | bcrypt `checkpw` | `app/core/auth.py::verify_password` |
| Session tokens | JWT HS256, 15-min access + 30-day refresh | `app/core/auth.py::create_access_token` |
| Audit-log integrity | SHA-256 hash chain | `app/core/audit.py` |
| Output integrity | Streaming SHA-256, returned as `X-Output-SHA256` header and recorded in the audit-log payload | `app/core/audit.py`, `app/api/routes/convert.py`, `compress.py` |
| Release signing | GPG (OpenPGP) | [`docs/release-signing.md`](./release-signing.md) |
| Container-image signing | cosign keyless OIDC | [`docs/release-signing.md`](./release-signing.md) |

**See also:** [`docs/security-overview.md`](./security-overview.md),
[`docs/release-signing.md`](./release-signing.md).

---

## 5. Authentication and access control

### 5.1 How are end-users authenticated?

Two paths share the same comparison primitive:

- **API key** (`X-API-Key` header) — single static key for Community
  Edition (`data/api_keys.json`), per-user keys for Cloud Edition.
  SHA-256 hash, `hmac.compare_digest` for verification.
- **Email + password** (Cloud Edition) — bcrypt hash, short-lived JWT
  (15-min access / 30-day refresh).

Email verification is sent fire-and-forget at registration (JWT bound
to the email-at-issuance via the `eat` claim, 7-day TTL). Operators
who want a hard log-in gate add the check in `get_current_user`; the
verified-state flag is recorded on `users.email_verified_at` either
way.

Password reset uses a JWT + password-hash-version (`phv`) claim,
30-minute TTL, single-use (current `phv` invalidates after reset).

### 5.2 How are administrators authenticated?

The administrative cockpit (`/cockpit`) requires both a valid JWT and
`role='admin'` on the user record. The role is rechecked against the
database on every request — a stale token cannot escalate after a
role change.

### 5.3 Is SSO / SAML / OIDC supported?

FileMorph does not bundle an OAuth provider, SAML SSO, or built-in
multi-factor authentication. Operators who require SSO front the
deployment with a reverse-proxy authenticator (Authelia, oauth2-proxy,
or the customer's existing IdP). SSO / SAML / OIDC as a built-in
feature is on the Compliance / KRITIS roadmap, build-on-demand for a
concrete customer engagement.

### 5.4 What about MFA?

End-user MFA is not currently bundled. Operators who require MFA front
the log-in path with a reverse-proxy MFA enforcer (Authelia, Cloudflare
Access). The same applies to the administrative cockpit. Built-in MFA
is on the roadmap.

### 5.5 What about password policy?

Passwords are bcrypt-hashed with an adaptive cost factor. There is no
forced complexity rule beyond a minimum length — current research
(NIST SP 800-63B §5.1.1.2) favours length over composition rules,
which is what FileMorph follows. Operators with a stricter internal
policy can apply it at the reverse proxy or via an SSO front-end.

### 5.6 Are there role-based access controls?

Two roles: `user` and `admin`. Admin gates the cockpit; everything
else is per-user. Multi-role RBAC, team accounts, and SCIM
provisioning are roadmap items for the Enterprise / KRITIS tier and
are not in the AGPL or default-Compliance build today.

**See also:** [`docs/security-overview.md`](./security-overview.md)
§ "Authentication & Authorization".

---

## 6. Application security

### 6.1 What is the input-validation regime?

Every upload passes through:

1. **Magic-byte allow-list** — `BLOCKED_MAGIC = [b"MZ", b"\x7fELF",
   b"#!/", b"<?ph"]` rejects PE / ELF / shell / PHP payloads before
   any decoder runs.
2. **MIME type from content, not client** — the `Content-Type` claimed
   by the client is informational; the actual format is determined
   from bytes.
3. **Path safety** — the original filename is never used as a
   filesystem path. Temp paths use UUID stems under `fm_`-prefixed
   directories.
4. **Size cap, per tier** — anonymous 20 MB; Free, Pro, Business,
   Enterprise scale up. See `app/core/quotas.py`.
5. **Output cap, per tier** — bandwidth-amplification guard: a
   converter that turns 50 MB JPG into 500 MB PNG is rejected with
   HTTP 413 before the response is streamed.

### 6.2 Are OWASP Top 10 categories addressed?

The internal static code review
([`docs/security-pentest-report.md`](./security-pentest-report.md))
walks each OWASP Top 10 (2021) category and maps it to a code anchor
in [`docs/security-overview.md`](./security-overview.md). Highlights:

- **A01 Broken Access Control** — `get_optional_user` resolves the
  caller from JWT or API key; admin role is DB-rechecked per request.
- **A02 Cryptographic Failures** — bcrypt for passwords, SHA-256 for
  API keys, constant-time comparison; TLS terminated at the proxy;
  HSTS emitted.
- **A03 Injection** — SQLAlchemy parametrised queries throughout; no
  string-built SQL in the codebase.
- **A04 Insecure Design** — explicit threat model in
  [`docs/threat-model.md`](./threat-model.md); ephemeral-by-default
  data flow.
- **A05 Security Misconfiguration** — defensive headers (HSTS, CSP,
  X-Frame-Options, Referrer-Policy, Permissions-Policy); CORS allow-list;
  health endpoint discloses no version (PT-011 fixed in `a521459`).
- **A06 Vulnerable and Outdated Components** — `pip-audit` blocking CI
  gate; pinned dependencies; SBOM per release.
- **A07 Identification and Authentication Failures** — see §5 above.
- **A08 Software and Data Integrity Failures** — SBOM + cosign image
  signatures + GPG-signed Git tags; audit-log hash chain; output-
  integrity SHA-256 header.
- **A09 Security Logging and Monitoring** — structured logs, tamper-
  evident audit chain, `/api/v1/health` (liveness) and `/api/v1/ready`
  (DB + tempdir readiness).
- **A10 Server-Side Request Forgery** — WeasyPrint `url_fetcher`
  rejects every URL unconditionally; no other component opens
  outbound HTTP from request-derived data.

### 6.3 What about CSP, CORS, and security headers?

- **CSP:** `default-src 'self'`; `script-src 'self' 'sha256-…'` (the
  only inline script is the Tailwind config in the page head, pinned
  by its SHA-256 hash; drift invalidates the hash and the script
  refuses to run); `connect-src 'self'` extended to `API_BASE_URL`
  when set; `frame-ancestors 'none'`.
- **CORS:** `CORS_ORIGINS` allow-list, never `*` with credentials;
  `expose_headers=["Content-Disposition"]` so cross-origin client
  code can read the download filename.
- **Defensive headers:** HSTS (HTTPS only), `X-Content-Type-Options:
  nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy:
  strict-origin-when-cross-origin`, `Permissions-Policy` locking out
  camera / microphone / geolocation / payment / USB / FLoC.

Regression guards in `tests/test_security_headers.py` and
`tests/test_batch_ui_sanity.py` pin these mechanically.

### 6.4 Rate limiting and concurrency

- **Per-endpoint slowapi limits** — `app/core/rate_limit.py`.
  In-memory; effective for a single instance. Multi-instance
  deployments need an external store (Redis); on the backlog.
- **Concurrency limiter** — global semaphore + per-actor tier-bound
  semaphore with 0.5 s acquire timeout returns 503 (global capacity)
  / 429 (per-actor) with `Retry-After`. Every synchronous C-binding
  call (FFmpeg, WeasyPrint, Pillow, pypdf) runs in a worker thread,
  never on the event loop — a single user cannot stall the worker.

### 6.5 What about XSS, CSRF?

- **XSS:** Jinja2 autoescape on; no `safe` filter on user-derived
  values in templates. CSP `script-src 'self' 'sha256-…'` is the
  second line of defence.
- **CSRF:** the auth surface uses `X-API-Key` header or JWT bearer
  token, neither of which is sent automatically by the browser cross-
  origin. Cookie-based session state is not used for authenticated
  API calls — see the cookie-hygiene CI guard
  (`tests/test_no_cookies.py`).

### 6.6 Are there file-format risks?

The threat model lists the known classes:

- **Decompression bombs (image)** — Pillow's `MAX_IMAGE_PIXELS`
  default (~89 megapixels) is in effect; the per-tier output cap
  rejects oversized output even when the input passes. Tightening
  this to `DecompressionBombError` is on the backlog (open-tasks
  P3-4).
- **Zip slip / archive escape** — extraction routines normalise paths
  to a fixed temp directory and reject `..` components.
- **PDF metadata injection** — PDF/A-2b conversion strips uncontrolled
  metadata; the integrity gate (veraPDF where available) verifies
  conformance before the response is streamed.
- **EXIF / GPS leakage** — image conversions and compressions strip
  EXIF / XMP / IPTC metadata by default; ICC colour profile preserved
  so wide-gamut workflows are not visibly desaturated.

**See also:** [`docs/security-overview.md`](./security-overview.md),
[`docs/security-pentest-report.md`](./security-pentest-report.md),
[`docs/threat-model.md`](./threat-model.md).

---

## 7. Audit logging and integrity

### 7.1 What is logged?

Structured logs record operation metadata: operation type, format
pair, byte counts (in / out), duration, success flag, tier, data
classification. **No file content** is logged. The regression guard is
`tests/test_observability_logs.py`.

### 7.2 Is there a tamper-evident audit trail?

Yes. The audit log is a SHA-256 hash chain over append-only Postgres
rows protected by a database trigger
(`app/core/audit.py`, Migration 005). The `verify_chain` helper
detects retroactive edits from a SQL dump alone — compatible with
ISO 27001 A.12.4.1, BORA §50, and BeurkG §39a expectations.

The chain records actor identifiers as hashed-email values, not raw
emails. Account-affecting events (registration, login, API-key
creation, password reset, email change, account deletion) and every
conversion / compression land in the chain.

### 7.3 What about output integrity?

Every successful conversion / compression response carries an
`X-Output-SHA256` header — a streaming SHA-256 of the bytes the
client receives. The same hash lands in the audit-log payload
(`output_sha256`), so an external auditor can verify a file matches
the attestation FileMorph made at conversion time without trusting
the application path. This is the anchor that turns the audit-log
hash chain into something a downstream archival workflow (GoBD,
beA-Anhang-Trail, eDiscovery) can act on.

### 7.4 What about logs as a data category?

Audit-log retention is governed by `AUDIT_RETENTION_DAYS`, set by
the operator to match their privacy notice. On account deletion the
actor identifier is nulled while the event type and payload digest
survive — the chain integrity is preserved.

Server access logs (IP, request time, URL, status, response size)
are written by the OS-level web server, not the FileMorph
application. Retention is per the operator's log-rotation policy.

**See also:** [`docs/security-overview.md`](./security-overview.md)
§ "Audit logging",
[`docs/records-of-processing-template.md`](./records-of-processing-template.md) A5.

---

## 8. Vulnerability management and patching

### 8.1 What is the patch policy?

[`docs/patch-policy.md`](./patch-policy.md) defines the post-triage
SLAs:

| Severity | CVSS v3.x | Patched release within |
|---|---|---|
| Critical | 9.0 – 10.0 | 7 days |
| High | 7.0 – 8.9 | 30 days |
| Medium | 4.0 – 6.9 | next regular release |
| Low | 0.1 – 3.9 | next regular release |

A *regular release* historically lands every 1–4 weeks. Enterprise /
KRITIS customers contract for backports onto a fixed `vX.Y` line
plus offline-update tooling — see
[`COMMERCIAL-LICENSE.md`](../COMMERCIAL-LICENSE.md).

### 8.2 How are dependency vulnerabilities found?

- **`pip-audit -r requirements.txt`** runs as a blocking CI gate on
  every push. A finding fails the build until it is either fixed by
  bumping the dependency or explicitly ignored via `--ignore-vuln`
  with a named, justified comment.
- Direct dependencies are pinned in `requirements.txt`. Transitive
  dependencies are pinned in `requirements.lock` (where used).
- A CycloneDX SBOM (`filemorph-{version}.cdx.json`) is attached to
  each release so downstream operators can diff their own copy.

### 8.3 Are releases signed?

- **Container images** are cosign-signed using keyless OIDC against
  the GitHub Actions identity that built them.
- **Git tags** are GPG-signed by the maintainer's key (setup and
  rotation procedure in [`docs/release-signing.md`](./release-signing.md)).
- The public GPG key is published; the private key never leaves the
  maintainer's machine.

### 8.4 Is there a public disclosure channel?

Yes. [`SECURITY.md`](../SECURITY.md) describes the disclosure
process:

| Stage | Target |
|---|---|
| Acknowledgement | Within 72 hours |
| Initial triage | Within 7 days |
| Patch and disclosure | Within 90 days |

Critical / High issues are also published as GitHub Security
Advisories out-of-band from the regular release cycle. Bug-bounty
rewards are not currently offered. PGP-encrypted reports are on the
backlog; plain email to `security@filemorph.io` is the current
channel.

### 8.5 What about penetration testing?

The findings document
([`docs/security-pentest-report.md`](./security-pentest-report.md))
is a **self-conducted** code review: automated static analysis plus
a manual walkthrough, 2026-04-19, by the maintainer. No external
auditor and no third-party penetration tester has reviewed the code
or a live instance. Customers requiring an external pentest can
commission one against their own deployment; the application code is
public and the threat model is documented.

External penetration testing is on the roadmap and will be
commissioned ahead of the first KRITIS-tier customer engagement
that contractually requires it.

**See also:** [`docs/patch-policy.md`](./patch-policy.md),
[`SECURITY.md`](../SECURITY.md),
[`docs/release-signing.md`](./release-signing.md),
[`docs/security-pentest-report.md`](./security-pentest-report.md).

---

## 9. Incident response

### 9.1 What is the incident-response process?

[`docs/incident-response.md`](./incident-response.md) defines the
sequence:

1. **Confirm** the finding (reproduce it, identify the affected
   versions / deployments).
2. **Contain** (revoke compromised keys, rotate secrets, take the
   affected endpoint offline if necessary).
3. **Notify** affected controllers within 72 hours of becoming aware
   of a personal-data breach (DPA §9, GDPR Art. 33). The
   notification includes the nature of the breach, the categories
   and approximate number of data subjects affected, the likely
   consequences, and the measures taken or proposed.
4. **Remediate** with a patched release on the patch-policy timeline.
5. **Post-mortem** documented and shared with the affected
   controllers; the relevant entries land in the audit chain.

### 9.2 Personal-data-breach notification SLA

Notification to the controller within 72 hours of becoming aware
(DPA §9 mirroring GDPR Art. 33). The breach-notification clause is
in the standard DPA template (§9) and remains in force as long as
the DPA is in force.

### 9.3 Status page / customer notification

A status page is not currently published. Material incidents are
communicated by email to the named contacts on the affected
contracts and via GitHub Security Advisories where appropriate.
A formal status page (filemorph.io/status) is on the roadmap before
the first KRITIS-tier engagement.

**See also:** [`docs/incident-response.md`](./incident-response.md),
[`docs/dpa-template.md`](./dpa-template.md) §9.

---

## 10. Business continuity, backup, and DR

### 10.1 What is backed up?

For the SaaS at filemorph.io:

- **Database** (Postgres) — daily snapshots, encrypted at rest, retained
  per the operator's published retention policy. The audit log is a
  Postgres table and is part of the same backup set.
- **Application code and configuration** — Git is the source of truth;
  releases are tagged, signed, and published as immutable container
  images.
- **Files** — there is no file store to back up. Conversions are
  ephemeral; nothing accumulates across requests.

For a self-hosted deployment: the operator answers per their backup
regime. The application is stateless beyond the database and the
environment configuration — recovery is "restore the database,
redeploy the signed image"; there is no separate file store to
rebuild.

### 10.2 RTO / RPO targets

The SaaS operator targets are documented in the published privacy
notice and reviewed annually. Self-hosters set their own targets in
their DPA Annex II `[operator: …]` placeholders.

For Compliance Edition customers the RTO / RPO targets are part of
the commercial agreement and may be tighter than the SaaS defaults
depending on the engagement (e.g. KRITIS B3S hospital deployments).

### 10.3 Restore testing

Backups are tested by a quarterly restore-to-staging drill on the
SaaS. Self-hosters document their own testing cadence in their
register.

---

## 11. Source code, supply chain, and SBOM

### 11.1 Is the source code available?

Yes. The full source is published at
[`github.com/MrChengLen/FileMorph`](https://github.com/MrChengLen/FileMorph)
under AGPL-3.0-or-later. Every Python file carries an SPDX header
(`# SPDX-License-Identifier: AGPL-3.0-or-later`). Compliance-Edition
features live in `app/ee/` under a separate commercial licence — the
source is in the same public repository but the feature is inert
without a valid licence key. The combined model and the rationale
for not splitting the repo are documented in
[`COMMERCIAL-LICENSE.md`](../COMMERCIAL-LICENSE.md).

### 11.2 What is in the SBOM?

A CycloneDX SBOM (`filemorph-{version}.cdx.json`) is generated per
release and attached to the GitHub release. It lists every direct
and transitive Python dependency with version pin, licence, and CPE
where available. Self-hosters who fork the repo regenerate it after
their dependency updates.

### 11.3 Third-party licence compliance

[`docs/third-party-licenses.md`](./third-party-licenses.md) lists the
licences of every direct dependency. The dependency set is curated
to AGPL-compatible licences (Apache-2.0, BSD, MIT, MPL-2.0,
ISC, Python-2.0). LGPL and copyleft dependencies are loaded
dynamically and isolated per AGPL §13 best practice.

### 11.4 Supply-chain controls

- Direct dependencies pinned in `requirements.txt`.
- `pip-audit` blocking CI gate.
- Container images cosign-signed (keyless OIDC).
- Git tags GPG-signed.
- SBOM attached to each release.
- Dependabot / Renovate auto-update is on the backlog.

**See also:** [`docs/release-signing.md`](./release-signing.md),
[`docs/third-party-licenses.md`](./third-party-licenses.md),
[`docs/patch-policy.md`](./patch-policy.md).

---

## 12. Compliance, certifications, and applicable law

### 12.1 Which certifications does FileMorph hold?

**None.** The vendor does not claim ISO 27001, SOC 2, BSI Grundschutz,
PCI-DSS, or HIPAA conformance. Where a control matches the shape of a
standard (e.g. tamper-evident audit logging matches ISO 27001
A.12.4.1), the documentation says so for orientation, not as a
conformance claim. See
[`docs/security-overview.md`](./security-overview.md) § "What this is
not".

### 12.2 Applicable law / jurisdiction

German law applies. Exclusive venue for disputes is Hamburg, Germany,
subject to mandatory consumer-protection law. The contract chain
(DPA, Commercial Licence Agreement, Support Framework) names this
explicitly.

### 12.3 Does FileMorph meet KRITIS / B3S / EVB-IT requirements?

The product is designed with the KRITIS / B3S buyer in mind —
audit-log hash chain, signed releases, on-premises / sovereign
deployment, AGPL source availability, DPA + TOM templates. Specific
conformance is engagement-by-engagement; the gaps (no external
pentest, no MFA, no SAML SSO) are listed in §5 and §8 above and are
on-demand build items via the Compliance Edition agreement.

### 12.4 What about export control?

The product is general-purpose application software (file conversion).
It does not contain cryptographic export-restricted components beyond
the standard TLS / hash primitives shipped with Python and OpenSSL,
which fall under ECCN 5D002 mass-market exemption.

**See also:** [`COMMERCIAL-LICENSE.md`](../COMMERCIAL-LICENSE.md),
[`docs/commercial-license-agreement-template.md`](./commercial-license-agreement-template.md).

---

## 13. Support and service levels

### 13.1 What support does an AGPL self-hoster get?

- Public release notes, signed images, SBOM per release.
- GitHub Security Advisories for Critical / High issues.
- Best-effort community support via GitHub issues and discussions.
  No guaranteed response time, no private channel.
- The vulnerability-disclosure process applies to every deployment.

### 13.2 What does a Compliance Edition licence add?

The support framework in [`docs/support-sla.md`](./support-sla.md)
describes the *shape* of a commercial agreement; the figures are
contracted per engagement (no published grid yet — design-partner
phase). Typical elements:

- Acknowledgement / first-response window per severity (P1 – P4 ticket
  severity, independent of the CVSS severity that drives the patch
  clock).
- Coverage hours — by default Mon–Fri business hours, Europe/Berlin;
  extendable to 24×7 for Enterprise / KRITIS.
- Named contact and escalation path.
- Priority notification of security advisories (ahead of public
  disclosure, on request).
- Backports onto a fixed `vX.Y` line.
- Offline-update tooling (Enterprise / KRITIS).

### 13.3 What is the support SLA model?

Two independent clocks:

- **Security-fix timeline** (everyone) — see §8.1 above. CVSS-driven.
- **Support SLA** (Compliance Edition) — ticket-severity-driven, named
  in the commercial agreement.

A paid SLA buys priority *attention*; it does not shorten the security-
fix clock.

### 13.4 What is out of scope of support?

- Writing custom integration code (the OEM tier covers redistribution
  rights, not bespoke development).
- Issues in third-party services (Hetzner, Stripe, Zoho, Cloudflare).
- The customer's operating system, container host, network, or
  hardware.
- Performance tuning of customer infrastructure.
- Training beyond the dedicated-onboarding scope of the Enterprise
  tier.

**See also:** [`docs/support-sla.md`](./support-sla.md),
[`COMMERCIAL-LICENSE.md`](../COMMERCIAL-LICENSE.md).

---

## 14. Termination, data portability, and exit

### 14.1 What happens at end of contract?

For Compliance Edition contracts, DPA §10 governs: at the controller's
choice the processor either returns all personal data or deletes it,
with confirmation in writing. The 30-day grace period covers an
orderly export.

For SaaS subscriptions, the user terminates from the dashboard
(Stripe customer portal) and triggers self-service account deletion;
the tax-retention path (HGB §257 / AO §147) keeps the four mandated
fields, the rest is nulled.

### 14.2 How is data exported?

JSON export of account data on request (Art. 20 GDPR). Conversion
results are downloaded by the user at conversion time; nothing is
held in a proprietary format. Audit-chain rows are SQL-dumpable for
migration to another system.

### 14.3 What about vendor lock-in?

The product is published under AGPL-3.0 in a single public repository
and runs on commodity infrastructure. A customer ending the engagement
can run the same container themselves with no re-implementation.
Compliance Edition features in `app/ee/` go inert without a licence
key; the AGPL base remains fully functional.

**See also:** [`docs/dpa-template.md`](./dpa-template.md) §10,
[`docs/gdpr-account-deletion-design.md`](./gdpr-account-deletion-design.md).

---

## 15. Personnel and operations

### 15.1 Who operates the SaaS?

The vendor is a sole proprietor; operations are carried out by the
named individual identified in §0. There is no separate operations
team. The Compliance Edition support framework is sized for this
reality — the trade-off (high transparency, signed release chain,
public source) is what the buyer gets in return.

### 15.2 Background checks

Not applicable — sole-proprietor operation. For the Compliance
Edition tier, identity is confirmed by the contract chain (counter-
signed DPA, Commercial Licence Agreement).

### 15.3 Subcontractors

The operator does not currently engage subcontractors who process
personal data on the FileMorph platform. Any future engagement
becomes a sub-processor under DPA §6 and is added to
[`docs/sub-processors.md`](./sub-processors.md) with the 30-day
prior-notice rule.

---

## 16. Privacy notice and public artefacts

| Artefact | Where |
|---|---|
| Public privacy notice | `https://filemorph.io/privacy` and `app/templates/privacy.html` |
| Imprint (TMG § 5 / DDG § 5) | `https://filemorph.io/impressum` and `app/templates/impressum.html` |
| Terms of service | `https://filemorph.io/terms` and `app/templates/terms.html` |
| Public contact form (DDG § 5 second channel) | `https://filemorph.io/contact` |
| Cookie / consent posture | No banner — the application uses no analytics, no third-party CDN, no advertising cookies. Session cookies (Cloud features) are strictly-necessary and not subject to consent under TTDSG § 25(2). The reasoning is documented in `app/templates/privacy.html`. |
| Sub-processors | [`docs/sub-processors.md`](./sub-processors.md) |
| DPA template | [`docs/dpa-template.md`](./dpa-template.md) + [`docs/dpa-tom-annex.md`](./dpa-tom-annex.md) |
| Records of processing | [`docs/records-of-processing-template.md`](./records-of-processing-template.md) |
| Account deletion design | [`docs/gdpr-account-deletion-design.md`](./gdpr-account-deletion-design.md) |
| Security overview | [`docs/security-overview.md`](./security-overview.md) |
| Pentest report (self-conducted) | [`docs/security-pentest-report.md`](./security-pentest-report.md) |
| Threat model | [`docs/threat-model.md`](./threat-model.md) |
| Patch policy | [`docs/patch-policy.md`](./patch-policy.md) |
| Release signing | [`docs/release-signing.md`](./release-signing.md) |
| Support framework | [`docs/support-sla.md`](./support-sla.md) |
| Commercial Licence Agreement template | [`docs/commercial-license-agreement-template.md`](./commercial-license-agreement-template.md) |
| Self-hosting guide | [`docs/self-hosting.md`](./self-hosting.md) |
| API reference | [`docs/api-reference.md`](./api-reference.md) |

---

## How a prospect uses this document

1. **Initial review (no contract required).** A prospect's reviewer
   reads this document plus the cross-referenced canonical sources to
   decide whether FileMorph clears their internal threshold. No NDA
   or sales engagement is needed — the substance is public.
2. **Questionnaire response.** Where the prospect's procurement
   uses a SIG / CAIQ / VSA spreadsheet, the answers in this document
   map cell-by-cell. Cite this document by section number plus the
   cross-referenced canonical source where the questionnaire asks for
   "evidence".
3. **Contract chain.** When the prospect proceeds, the binding
   instruments are signed in this order:
   - Commercial Licence Agreement
     ([`docs/commercial-license-agreement-template.md`](./commercial-license-agreement-template.md)).
   - DPA + Annex II (TOM) + Annex III (sub-processor list)
     ([`docs/dpa-template.md`](./dpa-template.md),
     [`docs/dpa-tom-annex.md`](./dpa-tom-annex.md),
     [`docs/sub-processors.md`](./sub-processors.md)).
   - Support Framework / SLA, individually figured
     ([`docs/support-sla.md`](./support-sla.md)).
4. **Annual refresh.** This document is reviewed at least annually and
   on any material change (new sub-processor, new feature touching
   network or storage, change of host). The "Last revised" line at
   the bottom records the most recent review.

---

## Open items the prospect should know about

The product is pre-launch (design-partner phase). The following are
documented gaps, not defects — each is on the roadmap with a stated
trigger:

- **External penetration test** — commissioned ahead of the first
  KRITIS-tier engagement that contractually requires it.
- **SSO / SAML / OIDC** — build-on-demand for the Enterprise tier.
- **Built-in MFA** — build-on-demand; reverse-proxy MFA is the
  current path.
- **Public status page** — before the first KRITIS-tier engagement.
- **Redis-backed multi-instance rate limiting** — when a customer
  deployment requires more than one instance.
- **`MAX_IMAGE_PIXELS` hard-error** — tightening from `DecompressionBomb
  Warning` to `DecompressionBombError`; tracked as open-tasks P3-4.
- **PGP key for `security@filemorph.io`** — on the backlog; plain
  email is the current channel.

The full list of open work is maintained in
`docs-internal/open-tasks.md` (operator-internal — not in the public
repo).

---

*Last revised: 2026-05-18.* This document is reviewed at least annually
and on any material change to the application, the sub-processor list,
or the contract chain.
