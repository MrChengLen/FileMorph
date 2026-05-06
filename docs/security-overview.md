# Security Overview

This document is a defensive-transparency snapshot of FileMorph's
security posture. It synthesises the internal code review captured in
[`security-pentest-report.md`](./security-pentest-report.md) (a
*static* analysis — see "What this is not" below), maps each historical
finding to the current code anchor that addresses it, and lists the
remaining limitations a self-hoster needs to be aware of when running
FileMorph in production.

It is written for three audiences at once:

- **Self-hosters** deploying FileMorph behind their own reverse proxy
  who need a checklist of operational settings that affect security.
- **Contributors** evaluating the codebase before adding a feature
  that touches authentication, file handling, or network boundaries.
- **Security researchers** looking for the disclosure path before
  reporting a finding.

## What this is

A single-page summary of the defenses in the codebase today, the
findings from a self-conducted code review (SAST plus manual review,
2026-04-19), and the operational steps a self-hoster takes to make
those defenses effective.

## What this is not

- **Not an external audit.** The findings document
  (`security-pentest-report.md`) was produced by automated static
  analysis and a manual code walkthrough. No external auditor and no
  third-party penetration tester has reviewed the code or a live
  instance. The report itself states this in its closing paragraph
  and labels its tester as "Automated static analysis + manual code
  review".
- **Not a compliance certification.** FileMorph is not ISO 27001,
  SOC 2, BSI Grundschutz, or PCI-DSS certified. Where this document
  references standards (OWASP, NIST), it does so to describe the
  shape of a control, not to claim conformance.
- **Not a runtime test report.** Dynamic testing (active fuzzing,
  timing measurements against a live instance, network-level SSRF
  verification) has not been carried out. Self-hosters and operators
  who require dynamic verification should commission their own.
- **Not exploit documentation.** Where findings are referenced, they
  are described conceptually with the code anchor of the fix. No
  step-by-step reproduction is included.

## Cross-references

| Topic | Document |
|---|---|
| Detailed findings list (PT-001 … PT-013) | [`docs/security-pentest-report.md`](./security-pentest-report.md) |
| Privacy and data flow (Community + Cloud Edition) | [`docs/gdpr-privacy-analysis.md`](./gdpr-privacy-analysis.md) |
| Deployment configuration | [`docs/self-hosting.md`](./self-hosting.md) |
| Library and dependency rationale | [`docs/tech-stack-rationale.md`](./tech-stack-rationale.md) |

---

## Threat Model

### What FileMorph aims to protect

- **User-uploaded files.** Treated as potentially sensitive. Files
  are decoded into `BytesIO` in memory and, where a temporary
  directory is required (multi-step conversions), into a UUID-named
  scratch path that is removed in the request's `finally` block.
  Originals are never written to disk under their original filename.
- **User credentials (Cloud Edition).** Passwords are bcrypt-hashed
  with an adaptive cost factor before persistence. Authentication
  artefacts on the wire are short-lived JWTs (15-minute access /
  30-day refresh).
- **API keys (Cloud Edition).** Stored as SHA-256 hashes; raw keys
  are revealed once at creation and never logged.

### What is intentionally out of scope

- **OS-level multi-tenant sandboxing.** All requests share a worker.
  Per-request isolation is logical (separate `BytesIO` instances,
  separate temp paths), not a sandbox-per-user. A self-hoster who
  needs OS-level isolation should run one instance per tenant.
- **Application-level DoS resistance.** Rate limiting is in-memory
  and per-instance; behind a single instance the limiter is
  effective, but multi-instance deployments need an external store
  (see "Known Limitations").
- **Side-channel resistance.** Library-level timing leaks (in
  Pillow encoding, WeasyPrint rendering, ffmpeg processing) are not
  mitigated.
- **Client-device security.** localStorage handling of API keys is
  documented as a known trade-off; clients on compromised devices
  are out of the threat model.

### Trust boundaries

A typical deployment crosses these boundaries, in order:

1. Client → reverse proxy (Caddy or nginx) — TLS termination.
2. Reverse proxy → FileMorph application container — HTTP loopback.
3. Application → Postgres (Cloud Edition) — credentials in env.
4. Application → outbound services (Stripe API, Zoho SMTP) over
   TLS, both with secrets in env.

Each boundary is the responsibility of the operator to configure
correctly; the application makes a number of assumptions about its
environment that are listed under "Operational Hardening" below.

---

## Authentication & Authorization

### API-key authentication

Used by both Community Edition (single static key in
`data/api_keys.json`) and Cloud Edition (per-user keys in the
`api_keys` table).

| Property | Implementation | Code anchor |
|---|---|---|
| Storage | SHA-256 hash, never raw | `app/core/security.py` |
| Comparison | `hmac.compare_digest` (constant-time) | `app/core/security.py::validate_api_key` |
| Reveal policy | Once, at creation; never logged | `app/api/routes/dashboard.py` (Cloud) |

The Community-Edition single-key path and the Cloud-Edition
per-user-key path share the same comparison primitive.

### Password authentication (Cloud Edition)

| Property | Implementation | Code anchor |
|---|---|---|
| Hashing | bcrypt, adaptive cost factor | `app/core/auth.py::hash_password` |
| Verification | bcrypt `checkpw` | `app/core/auth.py::verify_password` |
| Session token | JWT, 15-minute access + 30-day refresh | `app/core/auth.py::create_access_token` |

bcrypt is the standard choice for memorised-secret hashing per
OWASP's Password Storage Cheat Sheet, and is accepted under
NIST SP 800-63B §5.1.1.2 as a "memorized secret" hashing primitive.

### Why two hashing schemes

API keys are high-entropy (32 random bytes) and are checked on
every request — fast, constant-time SHA-256 comparison is the right
trade-off. Passwords are low-entropy and infrequent — bcrypt's
adaptive cost is the right trade-off. The two paths are
deliberately separate.

### Admin role

The administrative cockpit (`/cockpit`) requires both a valid JWT
and `role='admin'` on the user record. The role is rechecked
against the database on every request — a stale token cannot
escalate after a role change.

### Authentication resolution

`get_optional_user` in `app/api/routes/auth.py` resolves the
caller from either an `Authorization: Bearer` JWT or an
`X-API-Key` header. Tier-based quotas (batch size, output cap)
are enforced through whichever path produced the user. The
regression guard in
`tests/test_upload_auth_resolution.py` covers both paths.

### Historical findings addressed in this area

- **PT-002 (Critical).** Non-constant-time API-key comparison was
  replaced with `hmac.compare_digest` in `app/core/security.py`.
- **PT-006 (High).** Rate-limit bypass via `X-Forwarded-For`
  spoofing requires the deployment to terminate trust at the
  reverse proxy. The "Operational Hardening" section below lists
  the proxy-side configuration that closes this.

### What is not provided

FileMorph does not bundle an OAuth provider, SAML SSO, or built-in
multi-factor authentication. Operators who require those should
front the deployment with a reverse-proxy authenticator such as
Authelia or oauth2-proxy.

---

## Input Validation

### Upload pipeline

Every upload passes through these checks before it reaches a
converter:

1. **Magic-byte allow-list.** The first bytes of the upload are
   compared against `BLOCKED_MAGIC` (`[b"MZ", b"\x7fELF", b"#!/",
   b"<?ph"]`). PE/ELF binaries, shell scripts, and PHP source
   files are rejected before any decoder touches them.
2. **MIME type from content, not client.** The
   `Content-Type` claimed by the client is informational only;
   the actual format is determined from bytes.
3. **Path safety.** The original filename is never used as a
   filesystem path. Where a temporary path is needed, it uses a
   UUID stem under a `fm_`-prefixed scratch directory.
4. **Size cap, per tier.** Anonymous uploads cap at 20 MB; Free,
   Pro, Business, Enterprise scale up — see `app/core/quotas.py`.

### Download pipeline

The original filename is preserved only in the
`Content-Disposition` header, where it is filtered through
`safe_download_name()` in `app/core/utils.py`. ASCII-unsafe
characters are stripped or RFC 5987-encoded, so a malicious
filename cannot inject header bytes or break the parser.

### WeasyPrint SSRF hardening

WeasyPrint accepts HTML and CSS, both of which can reference
external URLs. To prevent server-side request forgery, every
`weasyprint.HTML(...)` call passes `url_fetcher=_deny_url_fetcher`,
defined in `app/converters/document.py` and applied at the only
call-site there. The fetcher rejects every URL unconditionally —
WeasyPrint never opens a network connection. Self-hosters should
not disable this.

### Decompression bombs

Pillow's `Image.MAX_IMAGE_PIXELS` default (around 89 megapixels)
is in effect, and the per-tier output cap (see "Output Bandwidth
Guards") rejects oversized output even when the input passes the
pixel check.

### Historical findings addressed in this area

- **PT-001 (Critical).** Path traversal via the upload filename
  was closed by switching to UUID stems and never trusting the
  client-supplied name as a path component.
- **PT-007 (Medium).** Missing magic-byte validation was closed
  by introducing `BLOCKED_MAGIC` in the upload routes.
- **PT-008 (Medium).** WeasyPrint SSRF was closed by the
  `_deny_url_fetcher` callback.
- **PT-013 (Medium).** Output filename injection in
  `Content-Disposition` was closed by `safe_download_name()`.

---

## Output Bandwidth Guards

A converter that takes a 50 MB JPG and produces a 500 MB PNG is
not a bug in the converter — it is the JPG-to-PNG ratio. But it
*is* a bandwidth-amplification risk: a single anonymous request
costing 50 MB of ingress can cost 500 MB of egress. On a
metered-bandwidth host this directly maps to cost.

### Per-tier output cap

After conversion, but before the response is streamed, the byte
length of the produced output is compared against
`quota.output_cap_bytes` (`app/core/quotas.py`). If it exceeds the
cap, the request returns HTTP 413 with a structured error and the
output is discarded.

The caps are monotone: anonymous &lt; free &lt; pro &lt; business
≤ enterprise. The exact values live in code rather than in this
document so they evolve with the quotas without requiring a doc
update.

### Logging

Cap rejections emit a structured log line carrying
`reason=output_cap`, `tier`, `operation`, and `cap_bytes`, so
operational dashboards can distinguish "user hit a cap" from
"converter failed". The regression guard is
`tests/test_observability_logs.py`.

### What is not capped

Currently the cap is **per file**, not aggregated across a batch.
A batch of small files that each fit under the cap can still
produce a large total response. This is listed as a known
limitation below.

---

## Transport & Headers

### TLS

FileMorph itself is HTTP-only; TLS is terminated at the reverse
proxy. The deployment template in `docs/self-hosting.md` uses
Caddy, which provisions and renews certificates automatically.

### Content Security Policy

The CSP is built in `app/main.py::_build_csp_header`. Highlights:

- `default-src 'self'` — no third-party content by default.
- `script-src 'self' 'sha256-…'` — the only inline script allowed
  is the Tailwind config block in the page head, pinned by its
  SHA-256 hash. Any drift in that block invalidates the hash and
  the script will not run.
- `connect-src 'self'` — extended to include `API_BASE_URL` when
  that environment variable is set, so cross-origin uploads to a
  separate API subdomain pass through the policy.
- `frame-ancestors 'none'` — not embeddable in another origin.

### CORS

`CORS_ORIGINS` is an allow-list, never `*` when credentials are
sent. The default in `.env.example` is `http://localhost:8000` —
self-hosters set the actual production origin(s) explicitly.

`expose_headers=["Content-Disposition"]` is set on the
`CORSMiddleware` so cross-origin client code can read the
download filename. Without it, browsers hide the header from
JavaScript and downloads silently lose their filename.

### Defensive headers

All headers below are set by the `security_headers` middleware in
`app/main.py`. Regression guards live in
`tests/test_security_headers.py`.

| Header | Value | Purpose |
|---|---|---|
| `Strict-Transport-Security` | `max-age=31536000; includeSubDomains` (HTTPS only) | Force HTTPS on subsequent visits. The middleware reads `request.url.scheme` so the header is only emitted when the proxy reports `X-Forwarded-Proto: https` — adding HSTS to plaintext responses is meaningless and noisy in dev. |
| `X-Content-Type-Options` | `nosniff` | Prevent MIME-sniffing |
| `X-Frame-Options` | `DENY` | Defence-in-depth alongside `frame-ancestors` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Limit referrer leakage |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()` | Lock the converter site out of features it never needs; future XSS or third-party include cannot prompt the user for camera/mic/geolocation. |

### Network-layer change discipline

A change that introduces a new cross-origin endpoint or upload
route must audit four hardening points in the same commit — CSP
`connect-src`, `CORS_ORIGINS`, `expose_headers`, and the
`.env.example` plus self-hosting docs. Regression tests in
`tests/test_batch_ui_sanity.py` enforce two of those checks
mechanically.

### Historical findings addressed in this area

- **PT-003 (High).** The previously broken combination of
  `allow_origins=["*"]` with `allow_credentials=True` was
  replaced by the `CORS_ORIGINS` allow-list described above.
- **PT-004 (High).** Internal exception details no longer reach
  the client — the global error handler returns a generic
  message and logs the stack trace server-side.
- **PT-005 (High).** The defensive headers in the table above
  were absent in the audited revision and were added in
  `app/main.py`'s middleware stack.

---

## Data Privacy

### File data

- Files are decoded into `BytesIO` in memory; nothing is written
  to disk under the original filename.
- Where a temp path is needed for a multi-step pipeline, the path
  uses a `fm_`-prefixed directory and a UUID stem.
- Cleanup runs in the request's `finally` block via
  `shutil.rmtree`.
- A startup sweep, plus a periodic background sweep
  (`TEMP_SWEEP_INTERVAL_MINUTES`, default 60 min), removes any
  `fm_`-prefixed directory older than `TEMP_SWEEP_MAX_AGE_MINUTES`
  (default 10 min) — defence in depth for the case where a worker
  was killed before its `finally` could execute.
- Image conversions and compressions strip EXIF / XMP / IPTC
  metadata (GPS coordinates, camera serial, photographer name,
  capture timestamps) by default — see
  [`app/converters/_metadata.py`](../app/converters/_metadata.py).
  ICC colour profiles are preserved so wide-gamut workflows are
  not visibly desaturated. There is no per-request opt-out: a
  caller who needs metadata kept holds the original.
- Successful conversion and compression responses carry an
  `X-Output-SHA256` header — a streaming SHA-256 of the bytes the
  client receives. The same hash lands in the audit-log payload
  (`output_sha256`), so an external auditor can verify the file
  they hold matches the attestation FileMorph made at the moment
  of conversion. This is the integrity-anchor that turns the
  audit-log hash chain (NEU-B.1) into something a downstream
  workflow (GoBD-archival, beA-Anhang-Trail, eDiscovery) can act
  on without trusting the application path.
- `RETENTION_HOURS` is an informational knob (default `0` =
  ephemeral by design; the Cloud edition's published privacy
  position). Compliance-edition self-hosters who plan to use the
  reserved `FileJob.expires_at` column for a future storage-key
  pipeline set it to the value their privacy policy declares.

### Account data (Cloud Edition)

- Email and bcrypt-hashed password live in Postgres (`users`
  table).
- API keys live as SHA-256 hashes in `api_keys`.
- File-content hashes, original filenames, or upload metadata are
  not persisted. The `usage_records` table records only an
  operation type, byte counts, and a timestamp.
- **Self-service account deletion** lives at `DELETE
  /api/v1/auth/account` (Art. 17 GDPR). The free path is fully
  self-service: three-field re-confirmation (`password`,
  `confirm_email`, `confirm_word="DELETE"`), last-active-admin
  guard returning 409, and a confirmation email after commit.
  Cascade is hybrid: `api_keys` rows are removed, `file_jobs` and
  `usage_records` actor IDs are nulled (analytics integrity
  preserved), audit-event `actor_user_id` is nulled (the
  `event_type` and payload survive). Accounts that have ever
  touched Stripe are refused with 409 directing the user to the
  operator support contact until the paid-path tax-retention
  flow ships under HGB §257 / AO §147 — see
  [`gdpr-account-deletion-design.md`](./gdpr-account-deletion-design.md)
  § 5.B for the design.

The full data-flow analysis, including the sub-processor list
(Cloudflare for DNS / WAF, Stripe for payments, Zoho for
transactional email), lives in
[`gdpr-privacy-analysis.md`](./gdpr-privacy-analysis.md).

---

## Operational Hardening (Self-Hoster Checklist)

The application's defences depend on the deployment configuration
to be effective. The following list is grouped by importance.

### Mandatory

1. **Set `CORS_ORIGINS` to your actual origin.** Never leave it
   empty, never set it to `*`, never include scheme variants you
   do not actually serve. The default in `.env.example` is a
   localhost placeholder for development.
2. **Run behind a reverse proxy.** Do not expose Uvicorn directly
   to the public internet. Caddy and nginx are both well-trodden
   choices; the deployment template in `docs/self-hosting.md`
   uses Caddy.
3. **Configure trust-proxy correctly.** The rate limiter and any
   IP-based logging trust the `X-Forwarded-For` header. That
   header must only be honoured when set by *your* proxy. In
   nginx, that means `set_real_ip_from <proxy-ip>;`. In Caddy,
   the `trusted_proxies` directive. Without this, anonymous
   clients can rotate IPs and bypass the rate limiter.
4. **Use a strong `JWT_SECRET` (Cloud Edition).** Minimum 32
   bytes of cryptographic randomness. Rotation invalidates all
   active sessions, which is the desired behaviour after a
   suspected compromise.
5. **`pip-audit -r requirements.txt` is a blocking gate in CI.**
   Every push fails the build on any finding it cannot ignore. If
   an upstream advisory is genuinely unfixable, add the ID to
   `--ignore-vuln` in `.github/workflows/ci.yml` with a comment
   naming the package and reason — never silence the whole step.
   Self-hosters running an out-of-tree fork should run `pip-audit`
   on the same cadence as their dependency updates.

### Recommended

6. **Run the container as a non-root user.** The provided
   Dockerfile does this; verify in any custom build.
7. **Add an upload size cap at the proxy.** The application
   enforces per-tier caps, but a proxy-level cap (in Caddy:
   `request_body { max_size 100MB }`) trims malicious requests
   earlier and avoids the application even decoding them.
8. **Throttle authentication endpoints.** fail2ban, Caddy's
   rate-limit module, or nginx's `limit_req` against
   `/auth/login` will dampen credential-stuffing.
9. **Encrypt Postgres backups at rest** (Cloud Edition).
   Backups contain bcrypt-hashed passwords and API-key hashes;
   neither is reversible, but both are sensitive in aggregate.

### Cloud Edition specific

10. **Rotate the Stripe webhook secret on suspicion.** Webhooks
    are signed with that secret; rotation invalidates any
    intercepted webhook URL.
11. **Keep SMTP credentials in environment, not in `.env`
    committed to a repo.** `.env.example` is the template.

---

## Known Limitations

These are documented gaps, not defects. Each is shipped as-is
because the trade-off is intentional or because the fix is on the
backlog.

### Single-instance rate limiting

The slowapi limiter (`app/core/rate_limit.py`) uses in-memory
storage. A multi-instance deployment will give each worker its
own bucket, multiplying the effective ceiling. The replacement is
an external Redis backend, which is not currently installed.
Single-instance deployments are not affected.

### Stripe webhook coverage

The webhook handler currently dispatches on
`customer.subscription.*` and `checkout.session.completed`.
`invoice.payment_failed` and `invoice.payment_succeeded` are not
yet wired, so dunning state on a failed renewal will not flow
back to the application until the next subscription event.

### Email verification

Registration dispatches a fire-and-forget verification email to
the address the caller registered with. The link carries a JWT
bound to the email at issuance (`eat` claim, 7-day TTL) — a later
email change silently invalidates the link without a per-token DB
row. `POST /auth/verify-email` and `POST /auth/resend-verification`
land the result. Verification is **not** currently a gate on
log-in; verified state is recorded on `users.email_verified_at`
and is available to features that need it (e.g. billing flows).
Operators who want a hard log-in gate add the check in
`get_current_user` before this lands as a default.

### Monitoring not yet wired

`/metrics`, Prometheus-FastAPI-Instrumentator, and a Grafana
dashboard are not deployed today. Without them there is no
runtime visibility into rate-limit hits, error rates, or latency
percentiles. Treat this as required before public launch.

### API key in browser localStorage (PT-010)

The web UI persists the API key in `localStorage` so users do not
re-enter it on each visit. An XSS that bypasses the CSP could
read it. The CSP is the primary defence; the trade-off is
documented in the pentest report and accepted.

### Output cap is per-file, not per-batch

Bandwidth amplification is bounded per file, not aggregated
across the files in a batch upload. A batch designed to scrape
the per-file cap many times over could still produce a large
total egress. An aggregate cap is on the backlog.

### No PGP key for security@

`security@filemorph.io` accepts plain email today. Publishing a
PGP key for encrypted reports is on the backlog.

### No public bug-bounty programme

Reports are welcomed and acknowledged (see "Disclosure" below),
but monetary rewards are not offered.

---

## Disclosure & Update Process

### Reporting a finding

Send email to `security@filemorph.io`. Plain email is acceptable;
encryption is not currently offered.

In the report, please include:

- A description of the issue and where in the code or live
  service it manifests.
- The version or commit you tested against.
- A proof of concept where possible. A code snippet or
  request-trace is enough; full exploit code is appreciated but
  not required.
- Your preferred attribution (real name, handle, or anonymous).

### Service-level expectations

| Stage | Target |
|---|---|
| Acknowledgement | Within 72 hours |
| Initial triage | Within 7 days |
| Patch and disclosure | Within 90 days |

The 90-day window is the industry-standard expectation; severe
findings are typically patched faster.

### Out of scope

- Denial-of-service tests against `filemorph.io`.
- Social-engineering of maintainers or contributors.
- Findings on abandoned branches.
- Issues that depend on a compromised end-user device (e.g. an
  attacker who already has shell access).

### CVE history in dependencies

Two dependency CVEs were addressed by version pinning in
`requirements.txt`:

| CVE | Affected dependency | Fix |
|---|---|---|
| CVE-2024-28219 | Pillow &lt; 10.3.0 (heap buffer overflow in `_imagingcms`) | `Pillow>=10.3.0` |
| CVE-2024-53981 | python-multipart &lt; 0.0.18 (ReDoS in boundary parsing) | `python-multipart>=0.0.18` |

Self-hosters who fork this repository should re-run
`pip-audit -r requirements.txt` after updating dependencies.

### Update cadence

- `pip-audit` runs in CI as a non-blocking check today;
  promotion to a blocking gate is on the backlog.
- A Dependabot or Renovate configuration is on the backlog.
- Code-level security fixes are released on the same cadence as
  feature releases — there is no separate security-only release
  channel today.

---

## Source code anchors referenced in this document

For readers who want to jump directly to the code:

| Concern | File |
|---|---|
| API-key hashing and verification | `app/core/security.py` |
| Password hashing and JWT issuance | `app/core/auth.py` |
| Rate limiter | `app/core/rate_limit.py` |
| Magic-byte allow-list | `app/api/routes/convert.py`, `app/api/routes/compress.py` (search `BLOCKED_MAGIC`) |
| WeasyPrint SSRF hardening | `app/converters/document.py` (search `_deny_url_fetcher`) |
| Security-headers middleware (HSTS, Permissions-Policy, CSP, etc.) | `app/main.py::security_headers` |
| CSP and CORS middleware | `app/main.py::_build_csp_header` |
| Per-tier quotas and output cap | `app/core/quotas.py` |
| Filename sanitisation | `app/core/utils.py::safe_download_name` |
| Auth resolution (Bearer + API key) | `app/api/routes/auth.py::get_optional_user` |
| Bandwidth-cap regression test | `tests/test_bandwidth.py` |
| Structured-logging regression test | `tests/test_observability_logs.py` |
| Auth-resolution regression test | `tests/test_upload_auth_resolution.py` |

---

*Last revised 2026-05-06. The findings synthesised here are
sourced from the static code review dated 2026-04-19 and the
current state of the repository. The 2026-05-06 revision lands
the self-service account-deletion endpoint, the email-verification
flow, and the deployment-agnostic support contact (no FileMorph
SaaS addresses leak into self-hosted error messages).*
