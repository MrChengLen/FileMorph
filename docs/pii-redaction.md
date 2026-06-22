# PII Redaction

FileMorph's PII redaction finds and removes **structured** personal data from
documents before you share or archive them. It is a commercial **Enterprise
Edition** add-on (lives under `app/ee/`, not the AGPL engine) and is **inert
unless `AI_OPERATIONS_ENABLED` is set** — on a default/Community build the
endpoints return 503 and the `/redact` page returns 404.

> It is deterministic — regex + structural checksums, **no language model and no
> external call**. "AI" appears only in the internal package name (`app/ee/ai_ops`),
> never as a capability claim.

## What it detects

| Type | Method |
|---|---|
| IBAN | regex + ISO 13616 mod-97 checksum |
| Email address | local-part + domain pattern |
| Phone number | leading-zero / international digit runs (confidence 0.85 — flagged for review) |
| IPv4 address | dotted quad + octet-range validation |
| Credit-card number | 13–19 digits passing the Luhn checksum |

Checksum/format validation gives effectively complete recall on these structured
types with near-zero false negatives.

## Supported formats

UTF-8 **text** (txt, md, csv, json, …), **DOCX** (Word) and **XLSX** (Excel).

## What it does NOT do (read this)

- **No free-text names or postal addresses.** Detecting those needs named-entity
  recognition (NER), which is a separate, planned checkpoint. A redacted file is
  **not** guaranteed to be fully anonymous — **review it before sharing.**
- **No PDF.** Safe PDF redaction must delete the text layer (a black box over
  text is trivially removable = a breach). We return 415 rather than ship a fake
  cover-only redaction. PDF support is on the roadmap.
- It **assists** a human review; it is not legal or compliance advice and gives
  no warranty of completeness (see Terms of Use).

## Two-phase flow

1. **`detect` (free, no account):** scan a file and get a findings list — type,
   value, location, confidence — and a credit estimate. Nothing is charged.
2. **`apply` (paid, credit-metered):** produce the redacted file. Each value is
   `replace`d with a `[TYPE]` label, `mask`ed with asterisks, or `remove`d — your
   choice. Paid-tier only.

## Fail-closed verification

After applying redactions, the engine re-opens the **serialized output package**
and re-runs detection across every XML part — body, document metadata
(`docProps/*`), comments, sheet names, and attribute values — not just the nodes
it edited. If any in-scope value is still detectable, **no file is returned**
(HTTP 500); you get an error, never a half-redacted document. Document
properties and custom properties are stripped; documents with embedded OLE
objects are refused (their binary parts can't be certified clean).

## Privacy / GDPR

- **Stateless:** the file is processed in memory and deleted immediately after
  the output is returned — nothing is stored. EU-hosted.
- **No external transmission:** redaction runs locally; file content never leaves
  the server or reaches any third party / model.
- **Metadata-only audit:** each redaction writes a tamper-evident audit entry with
  *operation, format, item count, tier* — never the content or any detected value.

See [`privacy.html`](../app/templates/privacy.html) §2g, the Terms of Use
redaction clause, [`dpa-tom-annex.md`](dpa-tom-annex.md) and
[`records-of-processing-template.md`](records-of-processing-template.md) (A1b).

## Configuration (self-host)

| Env var | Default | Purpose |
|---|---|---|
| `AI_OPERATIONS_ENABLED` | `false` | Master gate. Off ⇒ endpoints 503, `/redact` 404, engine never imported. |
| `AI_ELIGIBLE_TIERS` | `pro,business,enterprise` | Paid tiers allowed to run `apply` (free `detect` is open to all). |
| `AI_CREDIT_COST_REDACT` | `1` | Credits charged per `apply` (neutral usage unit). |

API request/response details: [`api-reference.md`](api-reference.md).
