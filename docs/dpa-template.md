# Data Processing Agreement (DPA) — Template

**Status:** Skeleton template, finalised individually in pilot conversations.
**Last reviewed:** 2026-05-08

This document is the starting point for a Data Processing Agreement (DPA)
under Article 28 GDPR between a FileMorph Compliance-Edition customer
(*controller*) and the FileMorph operator (*processor*). It is published
in the open-source repository so a procurement reviewer can read the
substance before requesting a binding contract.

The text below is **not a binding contract** as-is. The final DPA is
drafted in the pilot conversation with each customer, with the bracketed
placeholders filled in from the concrete deployment context (instance
location, scope of processing, named contact, etc.). When you are ready
to finalise, contact `legal@filemorph.io`.

For the public sub-processor list referenced in §6 below, see
[`docs/sub-processors.md`](sub-processors.md).

---

## 1. Parties

**Controller** (the customer):
- Legal name: `[CUSTOMER LEGAL NAME]`
- Address: `[CUSTOMER ADDRESS]`
- Authorised signatory: `[NAME, ROLE]`

**Processor** (the FileMorph operator):
- Legal name: Lennart Seidel
- Address: Reetwerder 25b, 21029 Hamburg, Germany
- Contact: `legal@filemorph.io`

The processor is the operator of the FileMorph Compliance-Edition
deployment named in §3 (the "Service"). For self-hosted deployments
operated entirely on the controller's own infrastructure, the controller
is also the operator and this template does not apply — there is no
processor relationship.

## 2. Subject matter and duration

The processor processes personal data on behalf of the controller for
the sole purpose of operating the Service. Processing begins on
`[EFFECTIVE DATE]` and continues for the term of the underlying service
agreement, ending no later than thirty (30) days after termination
(during which residual processing for deletion or export is permitted).

## 3. Nature and purpose of processing

The Service performs file conversion, compression, and integrity-attested
output generation for files uploaded by the controller's authorised
users. Processing operations include:

- Receiving uploaded files via HTTPS
- Running format conversion / compression in transient memory and
  ephemeral filesystem locations
- Returning the converted output and a SHA-256 integrity header
- Writing structured logs (no file content; only metadata: tier, format
  pair, byte counts, duration, success flag)
- Recording audit events for actions affecting accounts or entitlements
  (registration, login, key creation, deletion, billing changes)

The Service does **not** perform any analytics, profiling, advertising,
or data sale.

## 4. Categories of data subjects and personal data

**Data subjects:**
- The controller's employees, agents, or contractors who use the
  Service (the "users")
- Any natural persons whose personal data appears in files the users
  upload — categories not known to the processor in advance

**Personal data:**
- User identifiers: email address (registration), bcrypt password hash,
  IP address (request logs only, rotated within 30 days), session JWT
  identifiers
- File contents during processing — deleted from memory and disk
  immediately after the converted output is returned (typical
  retention: seconds; absolute upper bound: 10 minutes via startup
  sweep, see `app/main.py`)
- Audit-event records (see §5 below) — retained per the controller's
  configured retention policy

## 5. Audit log and integrity attestation

Every Compliance-Edition deployment writes a tamper-evident audit log
(SHA-256 hash chain, see `app/core/audit.py` and Migration 005). Each
entry contains:

- Event type, timestamp, actor identifier, actor IP, payload digest
- Hash of the previous event (chain integrity)

The audit log is a tamper-evident record of processing *operations* on
the controller's behalf — useful evidence for, but distinct from, the
controller's Article 30 *Verzeichnis von Verarbeitungstätigkeiten*
(Records of Processing Activities), for which see
[`docs/records-of-processing-template.md`](records-of-processing-template.md).
The audit-log retention period defaults to `[RETENTION DAYS]` and is
configurable via the `AUDIT_RETENTION_DAYS` environment variable.

Each converted output carries an `X-Output-SHA256` response header so
the controller can independently verify integrity.

## 6. Sub-processors

The processor uses the sub-processors listed in
[`docs/sub-processors.md`](sub-processors.md). The default list applies
unless the controller and processor agree in writing to a reduced
scope at finalisation.

The processor will inform the controller of any intended additions or
replacements at least thirty (30) days in advance. The controller may
object on reasonable grounds; in such case the parties will negotiate
in good faith, and absent agreement either party may terminate the
service agreement.

## 7. Technical and organisational measures (TOM)

The processor implements the measures documented in:
- [`docs/dpa-tom-annex.md`](dpa-tom-annex.md) — the structured TOM list
  (this is the template for "Annex II" referenced below)
- [`docs/security-overview.md`](security-overview.md)
- [`docs/threat-model.md`](threat-model.md)
- [`docs/patch-policy.md`](patch-policy.md)
- [`docs/incident-response.md`](incident-response.md)
- [`docs/release-signing.md`](release-signing.md)

These cover: encryption in transit (TLS 1.2+, HSTS), at-rest scope (no
persistent file storage by design), access control (timing-safe API key
validation, JWT-bound roles, admin role with database recheck per
request), key management, software-supply-chain hardening (cosign-signed
images, signed Git tags, CycloneDX SBOM), and incident-response
timelines — structured along the Article 32 GDPR categories
(confidentiality / integrity / availability & resilience / regular
review) in [`docs/dpa-tom-annex.md`](dpa-tom-annex.md).

At finalisation, [`docs/dpa-tom-annex.md`](dpa-tom-annex.md) is attached
as "Annex II — Technical and Organisational Measures" with its
`[operator: …]` placeholders filled in for the specific deployment.

## 8. Controller's instructions and rights

The processor processes personal data only on documented instructions
from the controller, including with regard to transfers to third
countries. The instructions are this DPA and any subsequent written
instructions from the named contact in §1.

The controller has the right to:

- Receive on request, in a commonly used machine-readable format, all
  personal data processed on its behalf (Art. 20 GDPR)
- Audit the processor's compliance with this DPA, on reasonable notice
  and at the controller's expense, no more than once per twelve months
  unless an incident has been reported
- Demand erasure of all personal data after termination, except where
  Union or Member-State law requires retention (notably: tax-relevant
  records under HGB §257 / AO §147, ten-year period)

## 9. Personal data breach notification

If the processor becomes aware of a personal data breach affecting the
controller's data, the processor will notify the controller without
undue delay and in any case **within 72 hours** of becoming aware. The
notification will include: nature of the breach, categories and
approximate number of data subjects and records concerned, likely
consequences, measures taken or proposed.

The processor's incident-response procedure (see
[`docs/incident-response.md`](incident-response.md)) governs the
internal handling of the breach.

## 10. Return or deletion at end of provision

Upon termination of the underlying service agreement, the processor
will, at the controller's choice:

- Return all personal data in a commonly used machine-readable format
  within thirty (30) days, or
- Delete all personal data and certify the deletion in writing

Records that the processor is legally obliged to retain (tax records,
fraud-prevention records under §257 HGB / §147 AO) are retained for
the statutory period and deleted thereafter without further request.

## 11. Liability and limitations

Liability for breach of this DPA is governed by the underlying service
agreement. Each party is liable for its own infringements of Articles
82–84 GDPR. Joint and several liability under Art. 82(4) GDPR is not
excluded.

## 12. Governing law

This DPA is governed by the laws of the Federal Republic of Germany.
Place of jurisdiction is Hamburg, Germany.

---

## How to finalise

1. Review the bracketed placeholders in §1 and §2 and fill them with
   the deployment context.
2. Replace `[RETENTION DAYS]` in §5 with the configured value.
3. Start from the [`docs/dpa-tom-annex.md`](dpa-tom-annex.md) template,
   fill its `[operator: …]` placeholders with the measures specific to
   the deployment (instance location, network segmentation, on-call,
   penetration-test status), and append it as "Annex II — Technical and
   Organisational Measures".
4. Both parties counter-sign a printed PDF or qualified-electronic
   signature; the FileMorph operator counter-signature is provided
   from `legal@filemorph.io` after the pilot conversation closes.

Send the completed draft to `legal@filemorph.io`. Turnaround is
typically two business days.
