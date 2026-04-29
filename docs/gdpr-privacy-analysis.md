# FileMorph — Data Protection & GDPR Analysis

**Date:** 2026-04-20
**Scope:** Community Edition (current `main` branch) + Cloud Edition (planned via `docs/requirements-v2.md`)
**Analyst:** Automated compliance review
**Reviewer note:** This document is a technical privacy analysis intended for engineering and legal review. It does not constitute legal advice. Engage a qualified data protection lawyer before launching any paid SaaS tier in the EU.

---

## Executive Summary

The Community Edition (self-hosted) has a small but well-contained data footprint: files are processed ephemerally, API keys are SHA-256-hashed (not plaintext), and no analytics or tracking are present. However, the footer claim "Files are processed in memory and never stored permanently" is partially inaccurate — files are written to disk in `tempfile.mkdtemp` directories and are not deleted until after the HTTP response is sent, with no crash-recovery sweep. The planned Cloud Edition (Part C of `requirements-v2.md`) triggers substantial GDPR obligations: account registration collects email and passwords; per-user file history stores `original_name` (potential PII); Stripe introduces a sub-processor relationship; and Cloudflare R2 file storage may hold user-uploaded documents containing third-party PII. None of the GDPR-required artefacts (privacy policy, DPA with sub-processors, deletion flows, breach notification procedure) currently exist. These must be implemented before any EU-facing paid tier launches.

---

## Data Flow Map — Community Edition (Current)

### What enters the system

| Data element | Source | Transmitted to server? |
|---|---|---|
| File content (binary) | User upload via multipart/form-data | Yes — full file body |
| Original filename | `file.filename` field of upload | Yes — used to construct temp path |
| Target format | Form field `target_format` | Yes |
| Quality setting | Form field `quality` | Yes |
| API key (plaintext) | `X-API-Key` request header | Yes |
| Client IP address | TCP connection (used by slowapi) | Yes — used for rate limiting |
| Browser localStorage | `filemorph_api_key` key | Stored client-side only |

### What is processed

1. **Temp files on disk** — `convert.py:43` and `compress.py:34` call `tempfile.mkdtemp(prefix="filemorph_")`. The uploaded file is written to `<tmpdir>/<original_filename>` and the output is written to `<tmpdir>/<stem>.<target_ext>`. Both paths are on the server filesystem.

2. **Filename in temp path** — the original user-supplied filename (e.g. `my_passport_scan.pdf`) becomes part of the filesystem path. This is a PII leak risk: anyone with OS-level access to the temp directory can see filenames. Combined with the path traversal vulnerability (A-1 in requirements-v2.md), a crafted filename could also escape the temp directory.

3. **Uvicorn access log** — uvicorn logs each request in the format `INFO: <IP> - "POST /api/v1/convert HTTP/1.1" 200`. The original filename is **not** logged in the access log (it is in the body, not the URL). However, if `app_debug=true` is set, FastAPI/Starlette may produce additional debug output that could include headers.

4. **slowapi / rate limiter** — uses `get_remote_address` which extracts the client IP from the request. IP addresses are personal data under GDPR (Recital 30). slowapi stores rate-limit counters in memory (default: in-process dictionary, no persistence). These counters hold IPs as keys for the duration of the rate-limit window (1 minute). No log of IPs is written beyond what uvicorn already logs.

### What persists after the response

| Data element | Persistence | Duration | Risk |
|---|---|---|---|
| Temp directory + files | Disk (OS temp) | Until BackgroundTask runs post-response | Crash leaves files permanently |
| API key hashes | `data/api_keys.json` | Indefinitely | File is world-readable if Docker volume permissions not set |
| Uvicorn access logs | stdout / Docker log driver | Depends on Docker/host log rotation | Contains client IPs |
| Rate-limit counters (IP) | In-process memory | 1-minute window, then evicted | Ephemeral — no disk persistence |
| Browser localStorage | Client browser | Until user clears it | API key stored in plaintext in localStorage |

### What the footer claim says vs. reality

> *"Files are processed in memory and never stored permanently."*

**Assessment: Partially false.** Files are written to disk (`shutil.copyfileobj` → file open with `"wb"`). They are transient and deleted after the response, but:

- They exist on disk during processing (seconds to minutes depending on file size and conversion time).
- If the server crashes or is SIGKILL'd mid-request, the `BackgroundTasks` cleanup never runs, leaving files on disk permanently.
- There is no startup sweep for stale temp directories (requirement A-8 in requirements-v2.md explicitly notes this gap).
- The `data/api_keys.json` file is stored permanently on disk and persists across restarts via Docker volume mount.

The footer should be corrected to: *"Uploaded files are temporarily stored on disk during processing and are automatically deleted after conversion. API keys are stored as cryptographic hashes. No analytics data is collected."*

---

## GDPR Compliance: Current State (Community Edition)

| Obligation | Article | Status | Notes |
|---|---|---|---|
| Data minimization | Art. 5(1)(c) | ⚠️ Partial | Filename is retained in temp path unnecessarily — could use a UUID instead |
| Purpose limitation | Art. 5(1)(b) | ✅ | Data used solely for requested conversion/compression |
| Storage limitation | Art. 5(1)(e) | ⚠️ Partial | Temp files deleted post-response in happy path; crash leaves files indefinitely |
| Integrity & confidentiality | Art. 5(1)(f) | ⚠️ Partial | No TLS enforced at app level; no encryption at rest for temp files; `data/api_keys.json` permissions not enforced |
| Lawful processing basis | Art. 6 | ✅ | Self-hosted: operator controls their own data; no third-party user accounts |
| Privacy notice (Art. 13) | Art. 13 | ❌ | No privacy policy exists anywhere in the codebase or linked from the UI |
| Right of access (Art. 15) | Art. 15 | N/A | Community Edition processes no persistent personal data beyond API key hashes |
| Right to erasure | Art. 17 | ⚠️ Partial | API key can be revoked via `revoke_api_key()`; no self-service UI; no automated temp file purge |
| Data portability | Art. 20 | N/A | No persistent user data to export |
| Privacy by design | Art. 25 | ⚠️ Partial | Ephemeral processing is a good default; temp filename exposure and `BackgroundTasks` gap undermine it |
| Security measures | Art. 32 | ⚠️ Partial | API keys hashed (SHA-256 — see note below); no TLS at app layer; CORS wildcard with `allow_credentials=True` (invalid config per CORS spec) |
| Breach notification | Art. 33 | ❌ | No process documented |
| Cookie notice | ePrivacy Dir. | ⚠️ | No cookies set by the app; however, localStorage stores `filemorph_api_key` without disclosure |
| DPA with sub-processors | Art. 28 | N/A | Community Edition: self-hosted, operator is controller; no Anthropic/cloud sub-processors |

### Security note on SHA-256 for API key hashing

`app/core/security.py:30` uses `hashlib.sha256(key.encode()).hexdigest()` to hash keys. SHA-256 is not a password-hashing function (it lacks salting and is computationally fast, enabling brute-force). However, the keys are generated by `secrets.token_urlsafe(32)` which produces ~256 bits of entropy — effectively making brute-force infeasible regardless of the hash algorithm. The design is acceptable for API keys but **must not be used for user passwords** in the Cloud Edition (bcrypt with cost factor ≥12 is specified in C-2, which is correct).

### CORS misconfiguration note

`app/main.py:53-59` sets `allow_credentials=True` with `allow_origins=["*"]`. This combination is rejected by all modern browsers (the CORS specification forbids it). While not a direct GDPR violation, it is a security misconfiguration that may give users a false sense of security. See requirement A-2 in requirements-v2.md.

---

## GDPR Gaps: Planned Cloud Edition (Part C)

### C-1 · Database Layer — UsageRecord model

**Personal data collected:** `user_id` (linkable to email), `api_key_id`, `endpoint`, `timestamp`, `file_size_bytes`, `duration_ms`.

**Analysis:** UsageRecord is a per-user activity log. When linked to a registered user, each row is personal data. The table has no `expires_at` column and no documented retention period.

**GDPR obligations triggered:**
- **Art. 5(1)(e) Storage limitation:** Define and enforce a maximum retention period. Recommended: 12 months for billing/quota enforcement; aggregate/anonymize thereafter.
- **Art. 5(1)(c) Data minimization:** The `user_id` field can be pseudonymized (stored as a hash) in the usage table after account deletion while preserving aggregate analytics.
- **Art. 15 Right of access:** Users must be able to export their usage history.
- **Art. 17 Right to erasure:** Deleting a user account must trigger deletion or anonymization of all UsageRecord rows for that user. The schema lacks a cascade delete or soft-delete mechanism.

**Required retention policy:** Usage records required for active quota enforcement: retain for the billing cycle. Usage records required for invoicing/dispute: retain for the statutory accounting period (typically 10 years in Germany under HGB §257, but only aggregate figures are needed — individual rows can be anonymized after 90 days).

### C-2 · User Authentication

**Personal data collected:** `email` (unique identifier, plaintext), `password_hash`, `created_at`, `is_active`, JWT tokens in transit.

**GDPR obligations triggered:**

| Obligation | Requirement |
|---|---|
| Art. 5(1)(c) Minimization | Do not collect name or phone at registration unless required for a specific feature |
| Art. 6(1)(b) Legal basis | Contract performance — user registers to use the service |
| Art. 13 Privacy notice | Must disclose: email used for account authentication and optionally transactional emails; retention until account deletion |
| Art. 17 Erasure | `DELETE /api/v1/auth/account` endpoint required; must cascade to all linked tables: `api_keys`, `file_jobs`, `usage` |
| Art. 20 Portability | Export endpoint must include email, created_at, tier history, usage summary |
| Art. 32 Security | Passwords: bcrypt cost ≥12 (specified in C-2 — correct). Refresh tokens: stored hashed in DB (correct). Email: stored plaintext (necessary for authentication, but the column must be excluded from any non-production database dumps) |
| Art. 25 Privacy by design | Default tier is `free` (no persistent file storage) — correct privacy-preserving default |

**Password reset flow risk:** The `POST /api/v1/auth/reset-password/request { email }` endpoint must not confirm whether an email exists in the database (timing-safe response regardless of whether the email is registered) to prevent user enumeration.

### C-3 · Per-User API Key Management

**Personal data collected:** `ApiKey.label` (user-defined string — may contain PII such as "work laptop" or a project name), `last_used_at` (activity timestamp), `created_at`.

**GDPR obligations triggered:**
- **Art. 17 Erasure:** Deleting a user account must revoke and delete all linked API keys. The schema has `user_id FK -> users` — ensure the migration includes `ON DELETE CASCADE`.
- **Art. 15 Access:** Users must be able to list all their keys including `last_used_at` (already in the GET /api/v1/keys endpoint design).
- **Data minimization:** The `label` field has no length limit defined in the schema; enforce a reasonable maximum (e.g., 100 characters) to limit inadvertent PII collection.

### C-4 · File Storage — CRITICAL for GDPR

**Personal data collected:**
- `FileJob.original_name` — the original filename, e.g. `invoice_mueller_2025.pdf`, `selfie_for_passport.jpg`. Filenames frequently contain personal data.
- `FileJob.storage_key` — the R2 object key, which may embed the filename or user ID.
- The **file content itself** — this is the most significant risk. Users may upload:
  - Documents containing names, addresses, ID numbers (structured PII)
  - Photos of people (biometric data — Art. 9 **special category** if used for identification)
  - Medical reports (Art. 9 special category)
  - Legal documents containing third-party personal data
  - HR documents (salary slips, employment contracts)

**Controller vs. Processor distinction (Art. 28):**

FileMorph (the operator) acts as a **data processor** when storing user-uploaded files that contain third-party personal data (e.g., a user uploads a photo of their friend). The user is the **data controller** for that third-party data. However, for the user's own account data (email, usage), FileMorph is the **data controller**.

This dual role creates complexity:
- As **processor** of third-party data in uploaded files: FileMorph needs a Data Processing Agreement (DPA) with every registered user who uploads files containing third-party PII. In practice, this is addressed through a clear **Terms of Service** that defines the processing scope, and through technical controls (encryption, access restrictions, deletion).
- As **controller** of user account data: Standard privacy policy obligations apply.

**GDPR obligations triggered:**

| Obligation | Requirement |
|---|---|
| Art. 5(1)(e) Storage limitation | Retention tiers are defined (24h/7d/30d) — good. Must be enforced by the cleanup cron job. Must be disclosed in the privacy policy. |
| Art. 5(1)(f) Integrity | Files stored on Cloudflare R2 **must be encrypted at rest**. Cloudflare R2 encrypts at rest by default (AES-256). Verify and document this. |
| Art. 17 Erasure | `DELETE /api/v1/files/{id}` endpoint exists. Account deletion must also delete all R2 objects for that user. Implement as a cascading cleanup job. |
| Art. 9 Special categories | If the service accepts medical or biometric documents, it **may** be processing special category data without explicit consent. Options: (a) prohibit such uploads in ToS; (b) obtain explicit consent (Art. 9(2)(a)); (c) use technical controls to prevent storage of such content (not feasible for a general-purpose tool). Most file conversion SaaS platforms take option (a) — prohibit via ToS and add a risk disclaimer. |
| Art. 32 Security | Signed URLs (15-minute TTL) for downloads — correct. Ensure R2 bucket is not publicly readable. |
| Art. 28 Sub-processor | Cloudflare is a sub-processor for R2 storage. A DPA with Cloudflare is required. Cloudflare offers a standard DPA: https://www.cloudflare.com/cloudflare-customer-dpa/ |

**EU Data Residency:** Cloudflare R2 supports an `eu` location hint (`r2.cloudflarestorage.com/bucket?location=eu`). For EU users, the bucket **must** be created in the EU region to avoid international data transfers without SCCs. This must be a hard requirement, not optional configuration.

### C-5 · Tier Enforcement (Quota Middleware)

**Personal data collected:** Anonymous usage counters (quota checks). When linked to a user, quota state is implicitly tracked via `UsageRecord`.

**GDPR obligations triggered:**
- **Minimal additional obligations** beyond C-1 UsageRecord.
- The quota table in requirements-v2.md shows `anonymous | 25 conversions/day`. Anonymous quota enforcement requires tracking something — if tracked by IP, that is personal data. If tracked by session token, a cookie or localStorage disclosure is needed.

### C-6 · Billing (Stripe)

**Personal data collected and shared with Stripe:**
- Email address (used to create Stripe customer)
- Payment card details (handled entirely by Stripe, never touch FileMorph servers)
- Billing address (if collected by Stripe Checkout)
- `stripe_customer_id` stored in FileMorph `users` table
- Subscription status, plan tier, billing dates

**GDPR obligations triggered:**

| Obligation | Requirement |
|---|---|
| Art. 28 DPA with Stripe | Required. Stripe offers a standard DPA: https://stripe.com/legal/dpa. Must be signed/accepted before processing EU payment data. |
| Art. 13 Disclosure | Privacy policy must disclose Stripe as a payment processor, what data is shared, and link to Stripe's privacy policy. |
| Art. 6(1)(b) Legal basis | Contract performance — billing data is necessary to process payment for the service. |
| Art. 17 Erasure | Stripe customer data: Stripe retains financial transaction records for compliance with financial regulations (typically 7 years). The right to erasure does not override legal retention obligations (Art. 17(3)(b)). Document this exception in the privacy policy. |
| SCA (Strong Customer Authentication) | EU requires SCA (PSD2). Stripe Checkout handles SCA automatically — verify the integration uses Stripe Checkout or Payment Element, not the legacy Charges API. |
| Standard Contractual Clauses | Stripe Inc. is a US company. Stripe's DPA includes SCCs for EU-US data transfer. Verify the current version covers the post-Schrems II framework (EU SCCs 2021). |

**Webhook security:** `POST /api/v1/billing/webhook` must verify Stripe's webhook signature (`stripe.Webhook.construct_event`) before processing. This is not mentioned in the requirements but is critical — an unverified webhook endpoint allows any actor to simulate payment events.

### C-7 · Account Dashboard (Web UI)

**Personal data displayed:**
- File history including `original_name` — filenames may contain PII of the uploader or third parties.
- Usage statistics per user.
- Subscription details.

**GDPR obligations triggered:**
- **Art. 15 Right of access:** The dashboard implicitly fulfills this for file history and usage. Ensure a machine-readable export option (Art. 20) is also available.
- **Art. 17 Erasure:** Account deletion UI must be available in Settings. Must trigger cascading deletion of all personal data across all tables and R2 storage.
- **Session security:** Dashboard pages require authentication. Implement CSRF protection on all state-changing actions. Session tokens must be transmitted over HTTPS only (`Secure` cookie flag).

---

## Required Actions Before Cloud Launch (Prioritized)

### CRITICAL — Blocking for any EU user data processing

1. **[CRITICAL] Draft and publish a Privacy Policy** covering: data controller identity, data collected, legal basis for each processing activity, retention periods, sub-processors (Cloudflare, Stripe, hosting provider), user rights, contact for DPA requests, and supervisory authority information. Must be accessible from every page via a footer link.

2. **[CRITICAL] Sign Data Processing Agreements with all sub-processors:**
   - Cloudflare (R2 storage): https://www.cloudflare.com/cloudflare-customer-dpa/
   - Stripe (billing): https://stripe.com/legal/dpa
   - Hosting/VPS provider (wherever the application server runs)
   - Any email provider used for transactional email (password reset, receipts)

3. **[CRITICAL] Enforce EU data residency for Cloudflare R2.** Create the R2 bucket with location hint `eu`. Do not offer a global bucket as default.

4. **[CRITICAL] Implement account deletion with full cascade.** When a user deletes their account, the following must be deleted within 30 days (immediately where technically feasible):
   - `users` row
   - All `api_keys` rows for the user
   - All `file_jobs` rows and corresponding R2 objects
   - All `usage` rows (or anonymize by nulling `user_id`)
   - Stripe: cancel subscription, request customer data deletion where not required for financial records

5. **[CRITICAL] Fix the footer claim.** Change "Files are processed in memory and never stored permanently" to accurately reflect: (a) temporary disk storage during processing in Community Edition; (b) tier-based persistent storage in Cloud Edition.

6. **[CRITICAL] Implement crash-safe temp file cleanup.** Add a startup sweep of `filemorph_*` temp directories older than a configurable threshold (e.g., 10 minutes) to prevent file leakage after server crashes. See requirement A-8 in requirements-v2.md.

### HIGH — Required before paid tier launch

7. **[HIGH] Define and enforce UsageRecord retention.** Add an `expires_at` or `purge_after` column to the `usage` table. Implement a cron job to delete records older than 12 months (or anonymize by nulling `user_id`).

8. **[HIGH] Add localStorage disclosure.** The UI stores `filemorph_api_key` in browser localStorage without any disclosure. Add a notice in the API key input field: "Your API key is saved in your browser's local storage for convenience. Clear your browser data to remove it."

9. **[HIGH] Validate Stripe webhook signatures.** Ensure `stripe.Webhook.construct_event(payload, sig_header, webhook_secret)` is called before processing any webhook event.

10. **[HIGH] Protect the password reset endpoint from user enumeration.** `POST /api/v1/auth/reset-password/request` must return the same response regardless of whether the email exists in the database.

11. **[HIGH] Add `ON DELETE CASCADE` to all foreign keys referencing `users.id`** in the database migration. Verify with an integration test that deleting a user removes all child records.

12. **[HIGH] Assess need for a Data Protection Officer (DPO).** A DPO is mandatory under Art. 37 GDPR if the core activity involves large-scale processing of special category data or systematic monitoring. As a file conversion SaaS that may process documents containing health/biometric data, obtain legal opinion on DPO requirement. Designate a privacy contact email (e.g., privacy@filemorph.io) in any case.

### MEDIUM — Required within 90 days of launch

13. **[MEDIUM] Add privacy notice to registration flow.** The `POST /api/v1/auth/register` endpoint must present a checkbox linking to the Privacy Policy and Terms of Service before account creation. Store the consent version and timestamp in the `users` table.

14. **[MEDIUM] Implement data export (Art. 20 portability).** Add `GET /api/v1/account/export` returning a ZIP containing: account details (JSON), usage history (CSV or JSON), list of stored files (JSON with metadata, not file content unless the user requests it).

15. **[MEDIUM] Restrict access to `data/api_keys.json`** in Community Edition. Set file permissions to `600` (owner read/write only) in the Docker image and document this in the self-hosting guide.

16. **[MEDIUM] Add Tailwind CDN disclosure or remove CDN.** The Tailwind CDN (`cdn.tailwindcss.com`) can log request IPs. Bundle Tailwind locally (requirement B-7) to eliminate this third-party data transfer.

17. **[MEDIUM] Address special category data risk.** Add a clause to the Terms of Service prohibiting uploads of special category data (medical records, biometric data) without explicit consent. Add a technical disclaimer on the dashboard.

18. **[MEDIUM] Establish a breach notification procedure (Art. 33/34).** Document internally: how to detect a breach, who is the responsible person, the 72-hour reporting obligation to the lead supervisory authority, and the process for notifying affected users.

---

## Recommended Privacy Policy Sections

The privacy policy at `https://filemorph.io/privacy` must cover the following sections. Engage a lawyer admitted in an EU member state to draft the final document.

### 1. Controller Identity
- Legal name and address of the entity operating FileMorph
- Contact email: privacy@filemorph.io
- (If appointed) Data Protection Officer name and contact

### 2. Scope
- This policy applies to filemorph.io (Cloud Edition) and does not apply to self-hosted Community Edition deployments (the self-hosting operator is the controller)

### 3. Data We Collect and Why

| Data | Purpose | Legal Basis | Retention |
|---|---|---|---|
| Email address | Account authentication, transactional email | Art. 6(1)(b) contract | Until account deletion |
| Password (hashed) | Authentication | Art. 6(1)(b) contract | Until account deletion |
| Uploaded files | Conversion/compression service delivery | Art. 6(1)(b) contract | Per tier: 24h / 7d / 30d |
| Original filenames | File management, download labeling | Art. 6(1)(b) contract | Same as file retention |
| Usage records | Quota enforcement, billing | Art. 6(1)(b) contract + Art. 6(1)(f) legitimate interest | 12 months (anonymized) |
| IP address | Rate limiting, security | Art. 6(1)(f) legitimate interest | 30 days in logs |
| Payment data | Billing via Stripe | Art. 6(1)(b) contract | Per financial regulations |
| API key hashes | Authentication of API requests | Art. 6(1)(b) contract | Until key revoked or account deleted |

### 4. Sub-Processors

| Sub-processor | Purpose | Location | DPA |
|---|---|---|---|
| Cloudflare R2 | File storage | EU (eu region) | Cloudflare DPA |
| Stripe | Payment processing | US (SCCs in place) | Stripe DPA |
| [Hosting provider] | Application hosting | [Location] | [DPA reference] |
| [Email provider] | Transactional email | [Location] | [DPA reference] |

### 5. Uploaded File Content
- We process files solely to perform the requested conversion or compression.
- We do not analyze file content, train AI models on it, or share it with third parties except for storage (Cloudflare R2).
- Files may not contain special category data (medical, biometric, etc.) without prior written agreement.
- Files are permanently deleted after the retention period expires.

### 6. Cookies and Browser Storage
- We do not set cookies for tracking or analytics.
- The web interface stores your API key in browser localStorage for convenience. This data never leaves your browser and is not transmitted to our servers (except as the API key in request headers when you initiate a conversion).

### 7. Your Rights (EU/EEA users)
- **Access (Art. 15):** Request a copy of your personal data via the dashboard export feature or by emailing privacy@filemorph.io.
- **Rectification (Art. 16):** Update your email in Settings.
- **Erasure (Art. 17):** Delete your account in Settings → Danger Zone. Files are deleted immediately; financial records are retained per legal obligation.
- **Portability (Art. 20):** Download your data via Settings → Export My Data.
- **Objection (Art. 21):** Object to processing based on legitimate interest by contacting privacy@filemorph.io.
- **Lodge a complaint:** Contact your national data protection authority. For Germany: Bundesbeauftragte für den Datenschutz und die Informationsfreiheit (BfDI).

### 8. International Transfers
- Stripe is based in the US. Transfer is covered by Standard Contractual Clauses (EU Commission Decision 2021/914). A copy of the SCCs is available on request.
- Cloudflare R2 storage uses the EU region. No transfer outside the EEA for file storage.

### 9. Security Measures (Art. 32)
- Files are encrypted in transit (TLS 1.2+) and at rest on Cloudflare R2 (AES-256).
- Passwords are hashed with bcrypt (cost factor 12).
- API keys are stored as cryptographic hashes.
- Access tokens expire after 15 minutes.

### 10. Changes to This Policy
- We will notify registered users of material changes by email at least 30 days before they take effect.

---

## Technical Recommendations

These are specific, implementable changes to improve the privacy posture of the codebase. **Do not modify source files without reviewing security implications.** These are recommendations only.

### T-1: Replace filename in temp path with UUID (minimization)

In `app/api/routes/convert.py` and `app/api/routes/compress.py`, replace the original filename with a UUID for the on-disk temp file. Preserve the original filename only for the `FileResponse` download name:

```python
import uuid
# Instead of:
input_path = Path(tmp_dir) / file.filename
# Use:
safe_name = Path(file.filename or "upload").name or "upload"
suffix = Path(safe_name).suffix
input_path = Path(tmp_dir) / f"{uuid.uuid4()}{suffix}"
# Retain safe_name only for Content-Disposition header
```

This prevents the original filename (which may contain PII) from appearing in filesystem paths visible to OS-level monitoring tools, process lists, or crash dumps.

### T-2: Add startup sweep of stale temp directories

In `app/main.py` lifespan, add:

```python
import glob, time
async def sweep_stale_temps(max_age_seconds: int = 600):
    pattern = str(Path(tempfile.gettempdir()) / "filemorph_*")
    for tmp_dir in glob.glob(pattern):
        try:
            age = time.time() - os.path.getmtime(tmp_dir)
            if age > max_age_seconds:
                shutil.rmtree(tmp_dir, ignore_errors=True)
                logger.info("Swept stale temp dir: %s", tmp_dir)
        except Exception:
            pass
```

This closes the crash-recovery gap and aligns with the "never stored permanently" marketing claim.

### T-3: Add `Referrer-Policy` and `Permissions-Policy` headers

Extend the planned security headers middleware (requirement A-4) to include:

```python
response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
```

`Permissions-Policy` prevents the browser from prompting for camera/microphone access (not needed for a file conversion service). `Referrer-Policy` limits the information sent to Tailwind CDN and any future third-party resources.

### T-4: Self-host Tailwind CSS

Remove `<script src="https://cdn.tailwindcss.com">` from `app/templates/base.html`. Bundle Tailwind locally as per requirement B-7. This eliminates the data transfer to Tailwind's CDN (IP address of each visitor is sent to Tailwind's servers with every page load).

### T-5: Enforce `data/api_keys.json` file permissions

Add to `Dockerfile`:

```dockerfile
RUN chmod 600 /app/data/api_keys.json 2>/dev/null || true
```

And document in `docs/self-hosting.md` that the `./data` volume mount should be owned by the application user, not root.

### T-6: Add `X-Request-ID` correlation header for log tracing

Add a middleware that generates a UUID per request and sets `X-Request-ID` in the response. Include the request ID in all log messages. This supports breach investigation and incident response without logging additional PII.

### T-7: Separate log streams by sensitivity

Configure uvicorn's access log separately from the application log. For Cloud Edition, the access log (which contains IP addresses) should have a shorter retention period (30 days) than the application log. Document this in the deployment runbook.

### T-8: Cookie/localStorage consent notice

Add a dismissible notice (not a cookie banner, since no cookies are set) informing users that the API key is stored in localStorage:

```html
<p class="text-xs text-gray-600 mt-1">
  Your API key is saved in your browser's local storage.
  <button onclick="localStorage.removeItem('filemorph_api_key'); location.reload();"
          class="underline ml-1">Clear saved key</button>
</p>
```

---

## EU-Specific Considerations

### Cloudflare R2 EU Data Residency
R2 supports an `eu` jurisdiction configuration. Creating a bucket with `--location-hint eu` restricts data to Cloudflare's EU data centers. This must be a hard requirement for the Cloud Edition, not an optional configuration. Document the bucket creation command in the deployment runbook.

### Standard Contractual Clauses (SCCs)
- **Stripe:** Transfer to the US is covered by Stripe's DPA which incorporates the 2021 EU SCCs. Verify Stripe's DPA version at https://stripe.com/legal/dpa is current.
- **Hosting provider:** If the application server is hosted outside the EEA (e.g., on a US cloud provider), SCCs or an equivalent transfer mechanism is required. Consider EU-based hosting (Hetzner, OVH, IONOS) to avoid this requirement.

### Special Category Data (Art. 9)
Medical documents, legal ID documents, and photos of individuals are commonly converted by file conversion services. Processing these as a data processor (on behalf of the user) is permissible under Art. 9(2)(a) (explicit consent by the data subject whose data appears in the file) or under the explicit consent of the user for their own data. In practice:
- Add a ToS clause prohibiting upload of third-party sensitive data without appropriate consent.
- Add a privacy risk disclaimer on the dashboard for users who have file storage enabled.
- Do NOT advertise the service as suitable for healthcare or legal document processing without a proper Art. 9 compliance assessment.

### Data Protection Officer (DPO) — Art. 37
A DPO is **mandatory** if processing is carried out on a large scale and involves special categories of data (Art. 37(1)(b)). As a file conversion SaaS, the service may incidentally process special category data at scale. Obtain legal opinion before launch. At minimum, designate a privacy contact (privacy@filemorph.io) and document this in the privacy policy.

### Right to be Forgotten — Timeline
Under Art. 17, erasure must be completed "without undue delay." The EDPB recommends completing erasure within one month of the request. Design the account deletion flow to execute R2 object deletion synchronously (or within a guaranteed 24-hour background job), not on a weekly cleanup cycle.

---

## Summary Risk Matrix

| Risk | Likelihood | Impact | Priority |
|---|---|---|---|
| Crash leaves temp files with sensitive content on disk | Medium | High | CRITICAL |
| Footer claim creates legal liability ("never stored") | High | High | CRITICAL |
| No privacy policy — regulatory fine risk | High | Very High | CRITICAL |
| No DPA with Cloudflare R2 sub-processor | Medium | High | CRITICAL |
| No DPA with Stripe | Medium (at billing launch) | High | CRITICAL |
| User uploads Art. 9 special category data | High | High | HIGH |
| UsageRecord has no retention limit | High | Medium | HIGH |
| localStorage storage undisclosed | Medium | Low | MEDIUM |
| Tailwind CDN leaks visitor IPs | Low | Low | MEDIUM |
| SHA-256 for API keys (acceptable entropy, but not password-safe algo) | Low | Low | LOW |

---

*Analysis performed on: 2026-04-20*
*Based on codebase state: branch `main`, latest commit `b3870f4`*
*Requirements document: `docs/requirements-v2.md`, Draft 2026-04-19*
