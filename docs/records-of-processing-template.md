# Records of Processing Activities — Template (Art. 30 GDPR)

This document is a **template** for the *Verzeichnis von
Verarbeitungstätigkeiten* (Records of Processing Activities, "RoPA")
required under Article 30 GDPR. It is published in the open-source
repository so that:

- a **self-hoster** running FileMorph (Community or Compliance Edition)
  has a ready structure for their own Article 30 register — they are a
  *controller* for whatever personal data flows through their
  deployment, and Article 30(1) obliges them to keep one;
- a **procurement reviewer / DPO** evaluating the Compliance Edition can
  see what processing FileMorph performs, in the register format they
  work in;
- the FileMorph operator (filemorph.io) maintains its own filled-in
  register in this structure.

> **This is the structure — not the filled-in register, and not legal
> advice.** The application-level facts below are accurate for FileMorph
> as published; the `[operator: …]` placeholders are deployment-specific
> and must be filled by whoever runs the instance. Prune the activities
> that do not apply (a Community-Edition install with no user accounts,
> no database, no SMTP relay, and no Stripe key processes personal data
> under A1 and A6 only — A2–A5 and A7 are then not applicable). Have a
> DPO or counsel confirm the result reflects your actual processing. Companion
> documents: [`gdpr-privacy-analysis.md`](gdpr-privacy-analysis.md)
> (data-flow analysis), [`sub-processors.md`](sub-processors.md) (the
> recipient list), [`dpa-tom-annex.md`](dpa-tom-annex.md) (the Article 32
> TOMs referenced throughout), `privacy.html` (the public privacy
> notice, Art. 13/14).

---

## 0. Identification (Art. 30(1)(a), 30(2)(a))

| | |
|---|---|
| Controller / processor | `[operator: legal name and address — for filemorph.io: Lennart Seidel, Reetwerder 25b, 21029 Hamburg, Germany]` |
| Representative (Art. 27, if applicable) | `[operator: only if established outside the EU — n/a for an EU operator]` |
| Data protection officer | `[operator: name and contact if one is designated. A DPO is mandatory under §38 BDSG only above certain thresholds; for a solo operator it is usually not — document the assessment that led to that conclusion]` |
| Capacity | Controller for the activities in Part A; processor (on behalf of Compliance-Edition customers) for Part B |
| General description of technical and organisational measures (Art. 30(1)(g), 30(2)(d)) | See [`dpa-tom-annex.md`](dpa-tom-annex.md) — structured along the Art. 32 categories (confidentiality / integrity / availability & resilience / regular review) |

---

## Part A — Processing as controller (Art. 30(1))

### A1 — File conversion and compression

| Field | |
|---|---|
| Purpose | Provide the file-conversion / compression service requested by the user |
| Data subjects | Users of the service; any natural persons whose data appears in uploaded files (categories not known to the operator in advance) |
| Personal data | Uploaded file content while being processed (held in memory; if a temp path is needed, a UUID-named scratch file); request-log IP address; session JWT / API-key identifiers |
| Recipients | None for the conversion itself — the application transmits no file content, names, or hashes to any sub-processor (see [`sub-processors.md`](sub-processors.md)). An edge proxy in front of the service, if one is used (e.g. Cloudflare), terminates TLS and so carries uploads and results in transit. The server, and its access logs (A6), sit with the hosting provider. |
| Third-country transfers | None from the application. `[operator: if an edge proxy outside the EU carries the traffic (e.g. Cloudflare Inc., US), name it and the transfer safeguard]` |
| Retention / erasure | File content: ephemeral — deleted from memory and disk immediately after the output is returned (typically seconds). A temp directory left behind, e.g. by a crashed worker, is removed by the startup sweep or the hourly background sweep once it is older than 10 minutes — with the defaults (`TEMP_SWEEP_INTERVAL_MINUTES`, `TEMP_SWEEP_MAX_AGE_MINUTES`) within about 70 minutes. `RETENTION_HOURS` defaults to `0`. |
| TOMs | See [`dpa-tom-annex.md`](dpa-tom-annex.md) |

### A1b — PII redaction (Cloud-Edition add-on; omit if `AI_OPERATIONS_ENABLED` is unset)

| Field | |
|---|---|
| Purpose | Assist users in removing structured personal data (email, IBAN, phone, IPv4, payment card) from uploaded TXT / DOCX / XLSX before they share or archive them |
| Data subjects | Natural persons whose data appears in uploaded files — the feature's purpose means inputs are routinely PII-dense; special-category data (Art. 9) may appear and is processed under the customer's own lawful basis, not certified by the operator |
| Personal data | Uploaded file content while being processed (in memory; UUID scratch only if needed). Detected values are never logged, stored, or written to the audit trail |
| Recipients | None — redaction runs locally; no file content is sent to any third party or external model |
| Third-country transfers | None |
| Retention / erasure | Inputs and outputs: ephemeral — deleted immediately after the redacted output is returned. The audit entry holds operation metadata only (operation, format, item count, tier), never content or detected values. `RETENTION_HOURS` defaults to `0`. |
| TOMs | See [`dpa-tom-annex.md`](dpa-tom-annex.md) |

### A2 — Account, API-key and administrative access management (Cloud features)

| Field | |
|---|---|
| Purpose | Authenticate users; issue and manage API keys; enforce per-tier quotas; administer the service via the admin cockpit |
| Data subjects | Registered users; administrators |
| Personal data | Email address; bcrypt password hash; API-key SHA-256 hashes; tier; `stripe_customer_id` (created when the account first starts a Stripe checkout); admin-role flag; usage records (operation type, byte counts, timestamp — no file content) |
| Recipients | Hosting provider (the server and database run there); an edge proxy in front of the service, if one is used, in transit (see A1). Payment and email: A3, A4 |
| Third-country transfers | None — the database is hosted in the EU. `[operator: an edge proxy outside the EU — as in A1]` |
| Retention / erasure | Until the user deletes the account (`DELETE /api/v1/auth/account`, Art. 17 — actor identifiers in `file_jobs` / `usage` are nulled, and in audit events on a hard delete (accounts without a Stripe customer id); `api_keys` rows removed), subject to statutory retention of tax-relevant records (HGB §257 / AO §147 — typically 10 years) for accounts that have had a billing relationship |
| TOMs | See [`dpa-tom-annex.md`](dpa-tom-annex.md) |

### A3 — Subscription billing (Cloud, paid tiers)

| Field | |
|---|---|
| Purpose | Process subscription payments and manage paid-tier entitlements |
| Data subjects | Paying customers |
| Personal data | Email address; internal user identifier. Card data is collected by Stripe directly and never reaches FileMorph. |
| Recipients | Stripe Inc. (payment processing) |
| Third-country transfers | United States — covered by the Stripe DPA and EU Standard Contractual Clauses |
| Retention / erasure | Tax-relevant records retained per HGB §257 / AO §147 (typically 10 years); other billing metadata until no longer needed for the subscription |
| TOMs | See [`dpa-tom-annex.md`](dpa-tom-annex.md) |

### A4 — Transactional email (Cloud features)

| Field | |
|---|---|
| Purpose | Deliver authentication / account / billing emails: email verification, password reset, payment-failure (dunning) notices, account-deletion confirmation. FileMorph sends no payment receipts |
| Data subjects | Registered users |
| Personal data | Recipient email address; email body (e.g. the reset link) |
| Recipients | Zoho Corporation B.V. (SMTP relay) |
| Third-country transfers | None — Zoho EU, data centres in Amsterdam (NL) and Dublin (IE) |
| Retention / erasure | Not persisted by FileMorph — emails are sent fire-and-forget; the relay's own retention is governed by its terms |
| TOMs | See [`dpa-tom-annex.md`](dpa-tom-annex.md) |

### A5 — Audit logging

| Field | |
|---|---|
| Purpose | Maintain a tamper-evident record of account and billing events (registration, login, email verification, password reset, account deletion, subscription and payment changes), of single-file conversion / compression operations, of contact-form messages and of PII redactions, for security and compliance evidence. API-key management, admin changes in the cockpit, batch jobs and the `/pdf/*` tools are not recorded |
| Data subjects | Registered users |
| Personal data | Account ID of the actor, where there is one (no email address stored); a SHA-256 hash of the email address for failed logins, duplicate registrations, password-reset requests and contact-form messages; the email domain for account deletions; actor IP address; event type; event payload (operation metadata such as format pair, byte counts, output hash — no file content); timestamp; hash of the previous event (chain integrity) |
| Recipients | None |
| Third-country transfers | None |
| Retention / erasure | `[operator: the audit log has no built-in retention period — rows are append-only and are not pruned automatically. State the period your privacy notice declares and how you prune (a privileged database role that bypasses the append-only trigger). On a hard delete (accounts without a Stripe customer id) the actor identifier is nulled while the event type and payload survive.]` |
| TOMs | See [`dpa-tom-annex.md`](dpa-tom-annex.md) |

### A6 — Server / access logging

| Field | |
|---|---|
| Purpose | Operate, troubleshoot, and secure the service |
| Data subjects | Visitors to the service |
| Personal data | IP address; request timestamp; requested URL; HTTP status; response size — written by the reverse proxy, and by the application server: uvicorn's per-request access line (client address, method, path, status) is on in the shipped container (`entrypoint.sh`) |
| Recipients | Hosting provider |
| Third-country transfers | `[operator: none for an EU host such as Hetzner; state otherwise if your host is elsewhere]` |
| Retention / erasure | `[operator: your log-rotation period — e.g. rotated within 30 days]` |
| TOMs | See [`dpa-tom-annex.md`](dpa-tom-annex.md) |

### A7 — Contact form

| Field | |
|---|---|
| Purpose | Answer messages sent through the public contact form (`/contact`) |
| Data subjects | People who send a message through the form |
| Personal data | Name (optional); email address; subject (optional); message; page language. An audit event `contact.message.received` records a SHA-256 hash of the email address and the language (see A5). If the form's spam trap is triggered, the application log records the client IP and nothing is sent. The rate limiter (5 messages per hour per IP) holds the client IP in memory only |
| Recipients | The SMTP relay (A4), which delivers the message to the operator's mailbox with the sender's address as `Reply-To` |
| Third-country transfers | As A4 for the relay; an edge proxy as in A1 |
| Retention / erasure | Not stored by FileMorph — the message exists only as the delivered email. `[operator: how long contact messages are kept in the mailbox]` |
| TOMs | See [`dpa-tom-annex.md`](dpa-tom-annex.md) |

> A Community-Edition deployment that runs anonymous conversions only and
> configures no database, no SMTP relay, and no Stripe key processes
> personal data under **A1 and A6 only** — A2–A5 and A7 are then not
> applicable and should be removed from your register.

---

## Part B — Processing as processor (Art. 30(2))

### B1 — Operating the FileMorph Service on behalf of a Compliance-Edition customer

| Field | |
|---|---|
| Controller | `[operator: the customer — legal name and contact, per the customer's DPA §1]` |
| Categories of processing performed | Receiving uploaded files via HTTPS; running format conversion / compression in transient memory and ephemeral filesystem locations; returning the converted output and a SHA-256 integrity header; writing structured logs (operation metadata only, no file content); recording audit events for account and billing actions (registration, login, email verification, password reset, account deletion, subscription changes) and for single-file conversions and compressions — not for API-key management, admin changes in the cockpit, batch jobs, or the `/pdf/*` tools |
| Categories of personal data | As specified in the customer's DPA §4 — not determined by the processor in advance |
| Recipients / sub-processors | As listed in [`sub-processors.md`](sub-processors.md), or the reduced set agreed in the customer's DPA §6 |
| Third-country transfers | None — except, where the customer's own subscription is billed through Stripe, the transfer described in A3 (US; Stripe DPA + SCCs) |
| Retention / erasure | Per the customer's DPA — file content ephemeral; audit log per the retention period agreed with the customer (no built-in pruning); deletion / return at end of provision per DPA §10 |
| TOMs | See [`dpa-tom-annex.md`](dpa-tom-annex.md), finalised for the deployment in the customer's DPA Annex II |

(One B1 entry per Compliance-Edition customer — see [`dpa-template.md`](dpa-template.md).)

---

## How to use this template

1. Fill the `[operator: …]` placeholders in section 0 and throughout
   with your deployment's specifics (legal entity, DPO assessment,
   retention values, host).
2. Remove the activities that do not apply to your deployment (see the
   Community-Edition note above).
3. Add any processing activities you have introduced that FileMorph does
   not perform out of the box (an object-storage backend, an external
   auth provider, an analytics integration) — and update
   [`sub-processors.md`](sub-processors.md) accordingly.
4. Keep the register current — review it at least annually and on any
   material change (new sub-processor, new feature, changed retention).
5. Have a DPO or counsel confirm it reflects your actual processing.

## See also

- [`gdpr-privacy-analysis.md`](gdpr-privacy-analysis.md) — the data-flow analysis these records summarise.
- [`sub-processors.md`](sub-processors.md) — the recipient / sub-processor list referenced throughout.
- [`dpa-template.md`](dpa-template.md) + [`dpa-tom-annex.md`](dpa-tom-annex.md) — the Art. 28 DPA and the Art. 32 TOM annex.
- [`gdpr-account-deletion-design.md`](gdpr-account-deletion-design.md) — the Art. 17 erasure flow.
- `privacy.html` — the public privacy notice (Art. 13/14).
