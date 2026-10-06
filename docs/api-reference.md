# API Reference

FileMorph provides a REST API for programmatic file conversion and compression.
All responses are either a file download (`application/octet-stream`) or JSON.

**Base URL**: `http://localhost:8000/api/v1`

---

## Authentication

FileMorph supports two parallel authentication schemes:

| Scheme | Header | Issued by | Use case |
|---|---|---|---|
| **API key** (Community) | `X-API-Key: <key>` | `scripts/generate_api_key.py` | Self-host scripts, automation, CLI tooling |
| **JWT Bearer** (Cloud overlay) | `Authorization: Bearer <token>` | `POST /api/v1/auth/login` | Browser sessions, multi-user deployments |

The file endpoints (`/convert`, `/compress`, their `/batch` variants, `/pdf/*` and `/ai/redact/*`) take either header but need neither: a request without credentials runs on the anonymous tier (so `/ai/redact/apply`, which needs a paid plan, answers it with `403`). Credentials you do send are checked. An `X-API-Key` must be valid — a key from `scripts/generate_api_key.py` or an active key created in the dashboard (`POST /api/v1/keys`) — otherwise the answer is `401`, and `429` once your IP has sent 30 rejected keys in a minute (see [Failed API-key attempts](#failed-api-key-attempts)). An invalid or expired Bearer token is not rejected on these endpoints: it is ignored, and the request runs without your account — refresh the token before it expires (see the [API usage guide](api-usage-guide.md#refresh-the-access-token)). `/health`, `/ready`, `/formats` and `/contact` are public; the account endpoints (`/api/v1/auth/*`, `/api/v1/keys`, `/api/v1/billing/*`) require a JWT unless the tables below say otherwise.

### API key (Community Edition)

Generate a key:
```bash
python scripts/generate_api_key.py
# or via Docker:
docker compose exec filemorph python scripts/generate_api_key.py
```

Keys are stored as SHA-256 hashes in `data/api_keys.json`. The plaintext key is shown exactly once at generation time. There is no key-rotation endpoint in the Community Edition — generate a new key and remove the old hash from the JSON file.

Requests with these keys run on the anonymous tier unless `API_KEYS_FILE_TIER` names another one — see [Limits on a Community Edition instance](self-hosting.md#limits-on-a-community-edition-instance).

### JWT Bearer (Cloud overlay)

When `DATABASE_URL` is configured, the Cloud overlay enables registration / login / refresh:

```bash
# Register (returns access + refresh tokens)
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"alice@example.com","password":"correct-horse-battery-staple"}'

# Login on a returning device
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"alice@example.com","password":"correct-horse-battery-staple"}'

# Use the access token
curl http://localhost:8000/api/v1/auth/me \
  -H "Authorization: Bearer <access-token>"

# Refresh expired access tokens (15 min TTL on access, 30 d on refresh)
curl -X POST http://localhost:8000/api/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token":"<your-refresh-token>"}'
```

Logged-in users can also generate API keys bound to their account at `POST /api/v1/keys`; those keys count against the user's tier quota rather than the anonymous tier.

All tokens (access, refresh, password-reset, email-verify) carry the RFC 7519 `iss` and `aud` claims — `iss=JWT_ISSUER` (default `filemorph`), `aud=JWT_AUDIENCE` (default `filemorph-api`) — and every decode path validates them. A token minted by a different FileMorph deployment, or by anything that shares a leaked `JWT_SECRET` but uses a different audience, is rejected before any business logic runs. Multi-instance operators behind one identity provider should set a distinct `JWT_AUDIENCE` per instance. Changing either value invalidates every in-flight token on the next request.

---

## Endpoints

### Cloud-Edition endpoints (account / billing / keys)

The endpoints in this section only respond when the Cloud overlay is configured (`DATABASE_URL` set, and where applicable `STRIPE_SECRET_KEY`). Without those, they return `503 Service Unavailable`. With `DATABASE_URL` set, the app does not start at all unless `JWT_SECRET` is at least 32 characters and not a published placeholder (see [`docs/self-hosting.md`](self-hosting.md#jwt-secret-cloud-edition)). All require `Authorization: Bearer <jwt>` unless noted.

**Auth (`/api/v1/auth/*`)**

| Method + Path | Auth | Purpose |
|---|---|---|
| `POST /api/v1/auth/register` | none | Create account; returns access + refresh tokens. Sends a verification email (fire-and-forget) in the request locale, and stores that locale as `preferred_lang`. |
| `POST /api/v1/auth/login` | none | Exchange email + password for access (15 min) + refresh (30 d) tokens. |
| `POST /api/v1/auth/refresh` | none (refresh-token in body) | Issue a new access token. The refresh token in the response is the one you sent, so a sign-in ends 30 d after login. |
| `GET /api/v1/auth/me` | Bearer | Return the currently authenticated user (`id`, `email`, `tier`, `role`, `created_at`, `subscription_status`, `preferred_lang`). |
| `PUT /api/v1/auth/account/language` | Bearer | Set the language for this user's transactional email. Body: `{"preferred_lang": "de"\|"en"}` — an unsupported value is a `422`. Returns the updated user object. This is **email** locale only; the web-UI locale stays URL-prefix driven (no cookie). |
| `POST /api/v1/auth/forgot-password` | none | Issue a single-use password-reset link via email (30 min TTL). |
| `POST /api/v1/auth/reset-password` | reset-token in body | Set a new password. Every access and refresh token issued before the reset stops working, so all existing sign-ins end. |
| `POST /api/v1/auth/verify-email` | verify-token | Mark the user's email as verified. |
| `POST /api/v1/auth/resend-verification` | Bearer | Re-send the verification mail (auth-required to avoid spam). |
| `DELETE /api/v1/auth/account` | Bearer | Self-service account deletion (GDPR Art. 17). Requires re-confirmation: current password, registered email, and the literal string `DELETE`. Success is `204`. Free / never-paid accounts are hard-deleted; an account linked to Stripe is retained in a restricted state — only `email`, the Stripe customer id, the last `tier`, and `created_at` are kept for the 10-year HGB §257 / AO §147 invoice record (permitted by GDPR Art. 17(3)(b)), every other personal field is erased, and the row is hard-deleted at the end of the retention period. Any active Stripe subscription is cancelled first; a Stripe API error returns `500` and leaves the account unchanged. See [`docs/gdpr-account-deletion-design.md`](./gdpr-account-deletion-design.md). |

**API keys (`/api/v1/keys`)**

| Method + Path | Auth | Purpose |
|---|---|---|
| `POST /api/v1/keys` | Bearer | Create a new API key bound to the authenticated user (`201`). Plaintext key is shown exactly once in the response. JSON body `{"label": "…"}` — `label` is optional (at most 100 characters, default `My API Key`), the body is not: send `{}` for the default. An account holds at most 25 active keys; beyond that the response is `409 Conflict` — revoke a key you no longer use first. |
| `GET /api/v1/keys` | Bearer | List the user's active keys (`id`, `label`, `created_at`, `last_used_at`, `is_active`). The key itself is never shown again. |
| `DELETE /api/v1/keys/{id}` | Bearer | Revoke a key. |

**Billing (`/api/v1/billing/*`)**

| Method + Path | Auth | Purpose |
|---|---|---|
| `POST /api/v1/billing/checkout/{tier}` | Bearer | Start a Stripe Checkout for `pro` / `business`. Body MUST include `withdrawal_waiver_acknowledged: true` (BGB §356 (5) consent — see `terms.html` § 9). Returns the Stripe Checkout URL; a `billing.checkout.withdrawal_waiver_recorded` audit event is written before the redirect. |
| `POST /api/v1/billing/portal` | Bearer | Return a Stripe Customer Portal URL so the user can manage card / cancel / re-subscribe. |
| `POST /api/v1/billing/cancellation` | none | Cancel a Pro / Business contract online without logging in (§ 312k BGB). JSON body: `email` (identifies the account; the confirmation goes to the address stored on a matching account, otherwise to this one), `contract` (`pro` / `business`), `kind` (`ordinary` / `extraordinary`), `reason` (at most 1000 characters, kept only for `extraordinary`, with control and invisible formatting characters removed), `end` (`earliest` / `date`) and `end_date` (ISO date, required for `end: "date"`, not before yesterday in UTC, so the visitor's own today is accepted in every time zone) — anything else is a `422`. Answers every valid request with `200 {"received_at": "2026-09-29T12:05:31Z", "email_sent": true}`, the same whether or not the address belongs to an account; `email_sent` is `false` when the confirmation (content, time of receipt, end of the contract) could not be handed to the mail server or was held back (filled honeypot, below). The reason is repeated in the confirmation only for an address that belongs to an account. An ordinary cancellation at the earliest date for an account with exactly one live subscription of that plan is set to end with the billing period in Stripe; every other case is emailed to the operator (`CONTACT_FORM_RECIPIENT_EMAIL` → `SMTP_REPLY_TO` → `SMTP_FROM_EMAIL`) to handle. Writes the audit events `billing.cancellation.received` and `billing.cancellation.scheduled` or `billing.cancellation.manual_review` (hashed email only, no IP address); with `AUDIT_FAIL_CLOSED`, a receipt that can't be recorded is a `500` before anything is done. Unlike `/contact`, a filled honeypot field is not dropped — a password manager may fill it on a real cancellation: the request goes to the operator marked as suspected spam, nothing is changed in Stripe, no confirmation is sent, and the answer says `email_sent: false`. `503` when `STRIPE_SECRET_KEY` or `DATABASE_URL` is unset. |
| `POST /api/v1/billing/webhook` | Stripe signature | Stripe → FileMorph webhook receiver. Handles `customer.subscription.{created,updated,deleted}` (tier sync from price + status) and `invoice.payment_failed` (dunning: marks `subscription_status=past_due`, sends a "payment failed — update your card" email once per retry cycle, keeps the paid tier during Stripe's grace window, and downgrades to Free only on a terminal status). Not exposed in OpenAPI. |

For schema details (request bodies, response shapes), open the auto-generated Swagger UI at `/docs` on the live deployment.

### AI operations — PII redaction (Enterprise Edition add-on)

Respond only when `AI_OPERATIONS_ENABLED` is set; otherwise `503 ai_unavailable`.
Two-phase. See [`pii-redaction.md`](pii-redaction.md) for capability + limits.

| Method | Endpoint | Body | Notes |
|---|---|---|---|
| `POST` | `/api/v1/ai/redact/detect` | `file`, `entity_types` (optional CSV) | **Free**, open to anonymous/free. Returns JSON `{findings:[{entity_type,value,location,confidence}], count, credits_estimate, credits_remaining}`. |
| `POST` | `/api/v1/ai/redact/apply` | `file`, `entity_types` (optional), `mode` (`replace`\|`mask`\|`remove`, default `replace`) | **Paid-tier only, credit-metered.** Returns the redacted file as a download — DOCX and XLSX keep their format, every text input comes back as UTF-8 text named `<name>.redacted.txt` — with headers `X-FileMorph-AI-Entities-Redacted`, `X-FileMorph-AI-Credits-Cost` and, when your tier has a monthly credit limit, `X-FileMorph-AI-Credits-Remaining`. |

`entity_types` is a comma-separated subset of `EMAIL`, `IBAN`, `PHONE`, `IPV4`,
`CREDIT_CARD` (case-insensitive); empty means all of them.

Each successful `apply` costs `AI_CREDIT_COST_REDACT` credits (default `1`),
counted against your tier's monthly allotment (calendar month, UTC;
`ai_credits_per_month` in `app/core/quotas.py`, unlimited on Enterprise). The
charge is made only after the output passed verification, so a failed run
costs nothing. `detect` is free: `credits_estimate` is what `apply` would
charge, and `credits_remaining` is `null` when there is no limit to count
against (anonymous callers, unlimited tiers).

Supported inputs: UTF-8 text (`.txt`, `.md`, `.csv`, `.tsv`, `.json`, `.xml`,
`.html`, `.yaml`, `.ini`, `.log` and a few aliases, or no extension), DOCX,
XLSX. Responses are credit-denominated only —
no model id, token count, or euro cost. Error codes (`X-FileMorph-Error-Code`):
`ai_unavailable` (503), `ai_plan_required` (403), `ai_credits_exhausted` (402),
`unsupported_format` (415, incl. PDF by design), `input_too_large` (413),
`unknown_entity_type` (400), `document_unreadable` (400),
`redaction_verification_failed` (500, fail-closed — no file returned),
`output_cap_exceeded` (413).

---

### POST `/api/v1/convert`

Convert a file from one format to another.

**Authentication**: Optional — `X-API-Key` or `Authorization: Bearer`; without credentials the request runs on the anonymous tier (see [Authentication](#authentication))

**Request**: `multipart/form-data`

| Field | Type | Required | Description |
|---|---|---|---|
| `file` | file | Yes | The file to convert |
| `target_format` | string | Yes | Target format extension, e.g. `jpg`, `pdf`, `mp3` |
| `quality` | integer | No | Quality 1–100 (default: 85). Applies to lossy targets (JPEG, WebP, AVIF, video, lossy audio) |

**Response**: `200 OK` — the converted file as a download, named `<name>.<target_format>` — `<name>_pdfa.pdf` for `target_format=pdfa` (see [Download names](#download-names)). A DOCX → PDF conversion whose layout had to be simplified also carries `X-FileMorph-Warnings` (see [Conversion warnings](#conversion-warnings)).

**Example — HEIC to JPG**
```bash
curl -X POST http://localhost:8000/api/v1/convert \
  -H "X-API-Key: YOUR_KEY" \
  -F "file=@photo.heic" \
  -F "target_format=jpg" \
  -F "quality=90" \
  --output photo.jpg
```

**Example — DOCX to PDF**
```bash
curl -X POST http://localhost:8000/api/v1/convert \
  -H "X-API-Key: YOUR_KEY" \
  -F "file=@document.docx" \
  -F "target_format=pdf" \
  --output document.pdf
```

**Example — Python (requests)**
```python
import requests

key = "YOUR_KEY"
with open("photo.heic", "rb") as f:
    response = requests.post(
        "http://localhost:8000/api/v1/convert",
        headers={"X-API-Key": key},
        files={"file": ("photo.heic", f, "image/heic")},
        data={"target_format": "jpg", "quality": 85},
    )

with open("photo.jpg", "wb") as out:
    out.write(response.content)
```

**Example — JavaScript (fetch)**
```javascript
const formData = new FormData();
formData.append("file", fileInput.files[0]);
formData.append("target_format", "jpg");
formData.append("quality", "85");

const response = await fetch("http://localhost:8000/api/v1/convert", {
  method: "POST",
  headers: { "X-API-Key": "YOUR_KEY" },
  body: formData,
});

const blob = await response.blob();
const url = URL.createObjectURL(blob);
// use url for download link
```

---

### POST `/api/v1/compress`

Reduce a file's size by re-encoding at a lower quality, keeping the same format.

**Authentication**: Optional — `X-API-Key` or `Authorization: Bearer`; without credentials the request runs on the anonymous tier (see [Authentication](#authentication))

**Request**: `multipart/form-data`

| Field | Type | Required | Description |
|---|---|---|---|
| `file` | file | Yes | The file to compress |
| `quality` | integer | No | Quality 1 (smallest) – 100 (best). Defaults to 85. Mutually exclusive with `target_size_kb` |
| `target_size_kb` | integer | No | Target output size in KB, at least `5`. Activates binary-search-on-quality (JPEG/WebP/AVIF only). Mutually exclusive with `quality` |

**Supported formats**: JPG, JPEG, PNG, WebP, AVIF, TIFF, TIF · MP4, MOV, AVI, MKV, WebM. FLV and WMV can be converted but not compressed (`422`). A video keeps its container; see [`formats.md`](formats.md#video) for the codecs and how `quality` maps onto them.

`target_size_kb` is JPEG/WebP/AVIF only — PNG/TIFF are lossless and quality does not control size meaningfully. Sending `target_size_kb` with a PNG returns `415`. AVIF/AV1 encode is more CPU-intensive than JPEG/WebP, and target-size runs several encode passes.

**Response**: `200 OK` — the compressed file as a download (same format, `_compressed` suffix in filename).

When `target_size_kb` is set, the response also carries:

| Header | Description |
|---|---|
| `X-FileMorph-Achieved-Bytes` | Actual output size in bytes |
| `X-FileMorph-Final-Quality` | Quality value the search settled on (1–100) |

Tolerance is ±3 % of the requested target: the result is at most 3 % over it, but can be smaller (an image that already fits at quality 95 is returned at 95). If even quality `1` exceeds the target, the smallest possible output is returned anyway and the headers reveal the actual size.

**Example — Compress a JPG to 70% quality**
```bash
curl -X POST http://localhost:8000/api/v1/compress \
  -H "X-API-Key: YOUR_KEY" \
  -F "file=@large_photo.jpg" \
  -F "quality=70" \
  --output smaller_photo.jpg
```

**Example — Compress a JPG to a 500 KB target**
```bash
curl -X POST http://localhost:8000/api/v1/compress \
  -H "X-API-Key: YOUR_KEY" \
  -F "file=@large_photo.jpg" \
  -F "target_size_kb=500" \
  -D headers.txt \
  --output capped_photo.jpg

# headers.txt now contains X-FileMorph-Achieved-Bytes / X-FileMorph-Final-Quality
```

**Example — Compress a video**
```bash
curl -X POST http://localhost:8000/api/v1/compress \
  -H "X-API-Key: YOUR_KEY" \
  -F "file=@recording.mp4" \
  -F "quality=60" \
  --output recording_compressed.mp4
```

**Quality guide for images**

| Quality | Typical size reduction | Visual difference |
|---|---|---|
| 90 | ~20% | Nearly invisible |
| 80 | ~40% | Very subtle |
| 70 | ~55% | Slightly noticeable on close inspection |
| 60 | ~65% | Noticeable, acceptable for web thumbnails |
| 50 | ~70% | Clearly visible, good for previews |

---

### POST `/api/v1/pdf/extract`

Write a new PDF containing only a selected page range — a structural *morph*,
not a format conversion. Text, fonts and vector content are copied intact.

**Authentication**: Optional — `X-API-Key` or `Authorization: Bearer`; without credentials the request runs on the anonymous tier (see [Authentication](#authentication))

**Request**: `multipart/form-data`

| Field | Type | Required | Description |
|---|---|---|---|
| `file` | file | Yes | The source PDF (must be a `.pdf`) |
| `pages` | string | Yes | 1-based page selection — comma-separated singletons and `a-b` ranges, e.g. `1-3,5`. Sorted + de-duplicated. |

**Response**: `200 OK` (`application/pdf`) — the extracted pages as a download
(`_pages.pdf` suffix). An empty / reversed (`5-3`) / out-of-range / non-numeric
selection is a `400`; a non-PDF input is a `422`. A selection may resolve to at
most 10 000 pages.

```bash
curl -X POST http://localhost:8000/api/v1/pdf/extract \
  -H "X-API-Key: YOUR_KEY" \
  -F "file=@report.pdf" \
  -F "pages=1-3,5" \
  --output report_pages.pdf
```

---

### POST `/api/v1/pdf/split`

Split a PDF into one single-page PDF per page, bundled as a ZIP.

**Authentication**: Optional — `X-API-Key` or `Authorization: Bearer`; without credentials the request runs on the anonymous tier (see [Authentication](#authentication))

**Request**: `multipart/form-data`

| Field | Type | Required | Description |
|---|---|---|---|
| `file` | file | Yes | The source PDF (must be a `.pdf`) |

**Response**: `200 OK` (`application/zip`) — one entry per page
(`page_001.pdf`, `page_002.pdf`, … zero-padded to the page count's width, so
entries sort correctly), `_pages.zip` suffix. A non-PDF input is a `422`; a
document over **10 000 pages** is a `400` (rejected before any work). The
assembled ZIP must also fit the tier output cap (`413` otherwise).

```bash
curl -X POST http://localhost:8000/api/v1/pdf/split \
  -H "X-API-Key: YOUR_KEY" \
  -F "file=@report.pdf" \
  --output report_pages.zip
```

---

### POST `/api/v1/pdf/compress`

Shrink a PDF toward a byte budget by recompressing its embedded raster images.
Page count and every glyph are preserved; text/fonts/vector content are left
intact. Honest by design — a PDF with no recompressible images comes back valid
and unchanged-in-content (see the headers below), never a fake compression
claim.

**Authentication**: Optional — `X-API-Key` or `Authorization: Bearer`; without credentials the request runs on the anonymous tier (see [Authentication](#authentication))

**Request**: `multipart/form-data`

| Field | Type | Required | Description |
|---|---|---|---|
| `file` | file | Yes | The source PDF (must be a `.pdf`) |
| `target_kb` | integer | Yes | Target output size in KB (`> 0`). The embedded images are recompressed toward this budget via binary search on a global JPEG quality. |

**Response**: `200 OK` (`application/pdf`) — the compressed PDF as a download
(`_compressed.pdf` suffix), plus:

| Header | Description |
|---|---|
| `X-FileMorph-Achieved-Bytes` | Actual output size in bytes |
| `X-FileMorph-Converged` | `true` if the output reached the target within tolerance, else `false` |
| `X-FileMorph-Recompressible-Images` | How many embedded images the engine could recompress (`0` ⇒ nothing to shrink) |

A `target_kb` above the tier output cap is a `413` (rejected before any work);
a value beyond a 2 GB sanity ceiling, or a non-PDF / corrupt input, is a
`422` / `400`. A text/vector-only PDF returns `200` with
`X-FileMorph-Converged: false` and `X-FileMorph-Recompressible-Images: 0`.

```bash
curl -X POST http://localhost:8000/api/v1/pdf/compress \
  -H "X-API-Key: YOUR_KEY" \
  -F "file=@scan.pdf" \
  -F "target_kb=500" \
  -D headers.txt \
  --output scan_compressed.pdf

# headers.txt now carries X-FileMorph-Achieved-Bytes / -Converged /
# -Recompressible-Images
```

---

### POST `/api/v1/convert/batch`

Convert several files in one request. Returns a ZIP archive with all converted outputs.

**Authentication**: Optional — `X-API-Key` or `Authorization: Bearer`; without credentials the request runs on the anonymous tier (see [Authentication](#authentication))

**Request**: `multipart/form-data`

| Field | Type | Required | Description |
|---|---|---|---|
| `files` | files (≥1) | Yes | One or more files to convert |
| `target_formats` | string[] | Yes | Target format per file, repeated once per file in the same order (length must match `files`, otherwise `422`) |
| `quality` | integer | No | Quality 1–100 (default 85). Applied uniformly. |

**Response**: `200 OK` (`application/zip`, named `filemorph-batch.zip`) — archive with one entry per successful conversion. If at least one file fails, a `manifest.json` is added at archive root listing per-file results (success ZIP-only is preferred for all-success runs to keep the output clean). The `X-FileMorph-Batch-*` headers carry the counts and the failed files (see [Batch headers](#batch-headers)); `X-FileMorph-Batch-Failed` above `0` means the ZIP holds a `manifest.json`.

A run with **every** file failing returns `422 Unprocessable Content` with a JSON body listing per-file errors.

```bash
curl -X POST http://localhost:8000/api/v1/convert/batch \
  -H "X-API-Key: YOUR_KEY" \
  -F "files=@a.heic" -F "files=@b.png" -F "files=@c.gif" \
  -F "target_formats=jpg" -F "target_formats=jpg" -F "target_formats=jpg" \
  --output batch.zip
```

---

### POST `/api/v1/compress/batch`

Compress several files in one request. Same response shape as `/convert/batch`.

**Authentication**: Optional — `X-API-Key` or `Authorization: Bearer`; without credentials the request runs on the anonymous tier (see [Authentication](#authentication))

**Request**: `multipart/form-data`

| Field | Type | Required | Description |
|---|---|---|---|
| `files` | files (≥1) | Yes | One or more files to compress |
| `quality` | integer | No | Quality 1–100 (default 85). Mutually exclusive with `target_size_kb`. |
| `target_size_kb` | integer | No | Target size in KB (at least `5`), applied to each file. JPEG/WebP/AVIF only — any other file in the batch fails on its own, with an `error_message` saying so. Mutually exclusive with `quality`. |

```bash
curl -X POST http://localhost:8000/api/v1/compress/batch \
  -H "X-API-Key: YOUR_KEY" \
  -F "files=@photo1.jpg" -F "files=@photo2.jpg" \
  -F "quality=70" \
  --output batch.zip
```

---

### GET `/api/v1/formats`

Returns all supported conversion and compression formats.

**Authentication**: Not required

**Response**: `200 OK` — JSON. An excerpt: `conversions` has one key per
source format, and only seven of them are shown here.

```json
{
  "conversions": {
    "jpg": ["jpeg", "png", "webp", "bmp", "tiff", "tif", "gif", "ico", "avif", "pdf"],
    "heic": ["jpg", "jpeg", "png", "webp", "bmp", "tiff", "tif", "gif", "ico", "avif", "pdf"],
    "docx": ["pdf", "txt"],
    "txt": ["pdf"],
    "csv": ["xlsx", "json"],
    "mp4": ["avi", "mov", "mkv", "webm", "flv", "wmv"],
    "mp3": ["wav", "flac", "ogg", "m4a", "aac", "wma", "opus"]
  },
  "compression": {
    "image": ["jpg", "jpeg", "png", "webp", "tiff", "tif", "avif"],
    "video": ["mp4", "avi", "mov", "mkv", "webm"]
  }
}
```

Use this endpoint to populate format selection dropdowns in your application.

---

### GET `/api/v1/health`

Health check for monitoring and load balancer probes.

**Authentication**: Not required

**Response**: `200 OK` — JSON

```json
{"status": "ok"}
```

`/api/v1/health` is the unauthenticated liveness probe — it stays deliberately minimal
(no version or codec flags) so a public hit does not disclose deployment internals
(pentest finding PT-011). For readiness, use `GET /api/v1/ready`: it checks that the
database answers (reported as `skipped` when none is configured) and that the temp
directory is writable, e.g. `{"status": "ready", "checks": {"database": "ok",
"tempdir": "ok"}}`, and returns `503` with `"status": "not_ready"` when a check
fails. It does not check ffmpeg — the startup log warns when ffmpeg is missing.

---

### POST `/api/v1/contact`

Public contact form, linked from the German Impressum as the second, fast-direct contact channel required by DDG §5 (ECJ C-298/07). Anonymous; works on the Community edition too — the message is emailed to the operator (recipient resolved from `CONTACT_FORM_RECIPIENT_EMAIL` → `SMTP_REPLY_TO` → `SMTP_FROM_EMAIL`), with `Reply-To` set to the submitter. **The message is not persisted server-side** — only an audit event with a hashed email + the visitor's locale is recorded.

**Authentication**: Not required · **Rate limit**: 5 / hour per IP

**Request body** (JSON): `email` (required), `message` (required, 20–5000 chars), `name` (optional, ≤120), `subject` (optional, ≤160). Anti-spam: a hidden honeypot field plus the rate limit — automated-looking submissions receive a normal `200` and are silently dropped.

**Responses**: `200 {"detail": "Message sent."}` on success; `422` on validation errors; `429` when rate-limited; `502` if delivery fails (the UI then offers the direct `mailto:` fallback).

---

## Response Headers

Every successful conversion / compression carries integrity and classification metadata in response headers. CORS-enabled deployments expose these to browser clients (see `expose_headers` in `app/main.py`).

| Header | Value | Set on |
|---|---|---|
| `X-Output-SHA256` | Hex-encoded SHA-256 of the response body | every single-file `/convert` and `/compress` (not the batch ZIPs) |
| `X-Data-Classification` | One of `public`, `internal`, `confidential`, `restricted` | every response — echoes the request header value, defaults to `internal` when absent (NEU-C.3 / BSI-style taxonomy) |
| `X-FileMorph-Achieved-Bytes` | Actual output size in bytes | on `/compress` calls with `target_size_kb`, and on `/pdf/compress` |
| `X-FileMorph-Final-Quality` | Quality value the binary search settled on (1–100) | only on `/compress` calls with `target_size_kb` |
| `X-FileMorph-Batch-Total`, `X-FileMorph-Batch-Succeeded`, `X-FileMorph-Batch-Failed` | File counts of the batch | every `200` from `/convert/batch` and `/compress/batch` |
| `X-FileMorph-Batch-Failures` | The failed files and why (see [Batch headers](#batch-headers)) | batch `200` responses in which at least one file failed |
| `X-FileMorph-Error-Code` | A fixed code for the reason of an error (see [Error codes](#error-codes)) | the error responses listed there |
| `X-FileMorph-Warnings` | Comma-separated `key=value` tokens (see [Conversion warnings](#conversion-warnings)) | `/convert` DOCX → PDF, when the layout had to be simplified |
| `Retry-After` | Seconds the client should wait before retrying | on `503 Service Unavailable` (global concurrency cap) and on every `429` except the rate limiter's (slowapi, see Rate Limiting) — e.g. the per-tier concurrency cap and the monthly call quota |

The `X-Data-Classification` value is also written to the audit-log entry for the request, so a downstream auditor can answer "what classification of data was processed in this call" from the database alone (see `app/core/audit.py`).

### Batch headers

`X-FileMorph-Batch-Failures` lists each failed file as `<name>|<reason>`,
entries separated by `;`. Name and reason are percent-encoded, so a `|` or `;`
inside them cannot break the list — for example
`two.png|Conversion%20failed.%20Verify%20the%20file%20is%20valid.`. The header
is capped at about 4 KB: a longer list is cut and ends with the entry `...`,
while `manifest.json` in the ZIP always lists every file. The three count
headers always carry the full totals. A batch in which every file failed
returns the `422` JSON body instead, without these headers.

### Error codes

Some error responses carry `X-FileMorph-Error-Code`, a fixed string a client
can branch on (the `detail` text may change):

| Code | Status | Meaning |
|---|---|---|
| `input_too_large` | `413` | A file is larger than your tier allows per file |
| `output_cap_exceeded` | `413` | The result is larger than your tier's output cap |
| `target_size_exceeds_cap` | `413` | `target_size_kb` (`/compress`, `/compress/batch`) or `target_kb` (`/pdf/compress`) is above your tier's output cap — rejected before any work |
| `decompression_bomb` | `400` | The image's dimensions exceed the decoder's safety limit (`/convert`, `/compress`) |
| `invalid_input` | `400` | A problem you can fix, named in `detail` — e.g. a Markdown, CSV or JSON file that isn't UTF-8, a PDF that can't be read, or a PDF → PDF conversion of a document over 10 000 pages (`/convert`) |
| `invalid_page_selection` | `400` | `/pdf/extract`: the `pages` selection is invalid |
| `invalid_pdf` | `400` | `/pdf/extract`, `/pdf/split`, `/pdf/compress`: the PDF can't be read; `/pdf/extract` and `/pdf/split` also for a PDF with no pages, `/pdf/split` for one over 10 000 pages |
| `pdf_encrypted` | `400` | The PDF needs a password to open (`/pdf/extract`, `/pdf/split`, `/pdf/compress`, `/convert`); remove the password and upload it again |

The redaction endpoints add codes of their own, listed under
[AI operations](#ai-operations--pii-redaction-enterprise-edition-add-on).
Errors without the header — for example validation errors (`422`), a blocked
file type (`400 "File type not permitted."`), rate limits and most `500`s —
are identified by status and `detail`.

### Conversion warnings

`/convert` sets `X-FileMorph-Warnings` when a DOCX → PDF conversion ran on the
pure-Python engine and its layout had to be simplified. The PDF is still
returned (`200`). The tokens, comma-separated:

- `engine=mammoth_fallback` — the document needed LibreOffice, but the
  pure-Python engine ran; `reason=soffice_unavailable` (LibreOffice is not
  installed, e.g. in the slim image) or `reason=soffice_runtime_error`
  (LibreOffice failed) says why.
- `simplified=<feature>` — one per feature the pure-Python engine dropped or
  flattened: `footnotes`, `endnotes`, `headers`, `footers`, `ole_objects`,
  `multi_section_layout`, `equations`, `multilevel_lists`.
- `fidelity=reduced` — the pure-Python engine reported other simplifications.

For example `engine=mammoth_fallback,reason=soffice_unavailable,simplified=footnotes`.
The engine routing is described in [`formats.md`](formats.md#notes-on-docx--pdf).

### Download names

`Content-Disposition` names the download after the uploaded file:

| Endpoint | Download name |
|---|---|
| `/convert` | `<name>.<target_format>`; `<name>_pdfa.pdf` for `target_format=pdfa` |
| `/compress`, `/pdf/compress` | `<name>_compressed.<ext>` |
| `/pdf/extract`, `/pdf/split` | `<name>_pages.pdf`, `<name>_pages.zip` |
| `/ai/redact/apply` | `<name>.redacted.<ext>` — `<name>.redacted.txt` for every text input |
| `/convert/batch`, `/compress/batch` | `filemorph-batch.zip`; the entries inside are named like single-file results |

The name is sanitised: accents and other combining marks are dropped
(`Café` → `Cafe`), and every character other than a letter, digit, space,
`_`, `-` or `.` is removed. It is capped at 200 characters by shortening only
`<name>`, so the extension and suffixes such as `_compressed` are kept.

---

## Error Responses

Errors return JSON with a `detail` field:

```json
{
  "detail": "Conversion from 'jpg' to 'docx' is not supported."
}
```

Two exceptions: a `429` from the rate limiter (slowapi) reads
`{"error": "Rate limit exceeded: 10 per 1 minute"}` — with the limit of
the route you called — and has no `Retry-After` header; a batch in which
every file failed returns `422` with `{"summary": …, "files": […]}`.

| HTTP Status | Meaning |
|---|---|
| `400 Bad Request` | Missing or malformed request data (e.g. filename without extension), or file content that has to be fixed first — e.g. a Markdown, CSV or JSON file that isn't UTF-8 (`X-FileMorph-Error-Code: invalid_input`; `detail` names the fix) or a password-protected PDF (`pdf_encrypted`) |
| `401 Unauthorized` | An `X-API-Key` was sent but is not valid, or an endpoint that needs an account (`/auth/me`, `/keys`, `/billing/*`, …) got no valid `Authorization: Bearer` token. The file endpoints need no credentials: without them — or with an expired Bearer token — they run on the anonymous tier (see [Authentication](#authentication)) |
| `403 Forbidden` | Authenticated but role/tier doesn't permit the action (e.g. non-admin hitting `/cockpit/*`) |
| `413 Content Too Large` | Request exceeds `MAX_UPLOAD_SIZE_MB` (default: 100 MB), a file exceeds your tier's size cap, or the output exceeds your tier's output cap |
| `415 Unsupported Media Type` | `target_size_kb` set on a lossless format (PNG/TIFF), or otherwise incompatible request shape |
| `422 Unprocessable Content` | Unsupported format combination, missing form field, `target_formats` count ≠ `files` count, or every file in a batch failed |
| `429 Too Many Requests` | Rate limit exceeded (see Rate Limiting section below), per-tier concurrency cap reached, monthly call quota used up, or too many rejected API keys from your IP (see Rate Limiting — fix the key; waiting won't help) |
| `500 Internal Server Error` | Conversion failed (e.g. corrupt file, missing binary) |
| `503 Service Unavailable` | Global concurrency cap reached (`MAX_GLOBAL_CONCURRENCY`). Response carries `Retry-After`. |

---

## Rate Limiting

Every endpoint in a row has its own budget (`/convert` and `/compress`
allow 10 per minute each), and a path parameter does not split it:
`DELETE /api/v1/keys/{key_id}` has one budget, whichever key it names.
Most limits count per client IP address. The account endpoints for API
keys, billing and the email language count per signed-in account instead,
so colleagues behind one office IP don't share a budget. Every API
endpoint is listed, including the four that are deliberately not limited;
there is no catch-all limit, so the HTML pages and `/static` are not
rate-limited.

The client IP is the address uvicorn sees. Behind a reverse proxy that is
the visitor's address only when `FORWARDED_ALLOW_IPS` trusts the proxy —
and, if a CDN sits in front of the proxy, only when the proxy takes the
visitor's address from the CDN's header rather than passing on the CDN's
own. Otherwise all visitors share one budget per IP-counted endpoint (see
[`security-overview.md`](./security-overview.md) § Operational Hardening,
item 3).

| Endpoint | Limit | Counted per |
|---|---|---|
| `POST /api/v1/convert`, `POST /api/v1/compress` | 10 / minute | IP |
| `POST /api/v1/convert/batch`, `POST /api/v1/compress/batch` | 3 / minute | IP |
| `POST /api/v1/pdf/extract`, `POST /api/v1/pdf/split`, `POST /api/v1/pdf/compress` | 10 / minute | IP |
| `POST /api/v1/ai/redact/detect` | 20 / minute | IP |
| `POST /api/v1/ai/redact/apply` | 10 / minute | IP |
| `GET /api/v1/formats` | 120 / minute | IP |
| `GET /api/v1/health`, `GET /api/v1/ready` | 30 / minute | IP |
| `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `POST /api/v1/auth/reset-password` | 5 / minute | IP |
| `POST /api/v1/auth/forgot-password`, `POST /api/v1/auth/resend-verification` | 3 / minute | IP |
| `POST /api/v1/auth/verify-email` | 10 / minute | IP |
| `DELETE /api/v1/auth/account` | 1 / minute | IP |
| `PUT /api/v1/auth/account/language` | 10 / minute | account |
| `POST /api/v1/keys` | 10 / minute | account |
| `GET /api/v1/keys` | 120 / minute | account |
| `DELETE /api/v1/keys/{key_id}` | 30 / minute | account |
| `POST /api/v1/billing/checkout/{tier}`, `POST /api/v1/billing/portal` | 5 / minute | account |
| `POST /api/v1/billing/cancellation` | 10 / hour | IP |
| `GET /api/v1/cockpit/stats`, `GET /api/v1/cockpit/users`, `GET /api/v1/cockpit/timeseries`, `GET /api/v1/cockpit/usage-summary` | 30 / minute | IP |
| `PATCH /api/v1/cockpit/users/{user_id}`, `DELETE /api/v1/cockpit/users/{user_id}` | 10 / minute | IP |
| `POST /api/v1/contact` | 5 / hour | IP |
| `POST /api/v1/auth/refresh` | not limited — a request costs one signature check, and a failed refresh signs the web user out, so a shared limit would let junk requests sign out everyone behind an IP | — |
| `GET /api/v1/auth/me` | not limited — the token check does the work before any limit could apply, and the web UI calls it on every page view | — |
| `POST /api/v1/billing/webhook` | not limited — Stripe signs every delivery and retries failed ones | — |
| `GET /api/v1/metrics` | not limited — Prometheus scrape target; restrict it at your proxy (see [`security-overview.md`](./security-overview.md)) | — |

When exceeded, the response is `429 Too Many Requests`. For higher
limits, self-host your own instance and adjust the decorators in
`app/api/routes/*.py` (slowapi `@limiter.limit("…/minute")`).

### Failed API-key attempts

An `X-API-Key` the server does not accept is answered with `401` for the
first 30 attempts per minute per IP address, counted across every
endpoint that takes the header. After that, each further rejected key
from that address gets `429 Too Many Requests`, with a `Retry-After`
header (seconds until the minute is over) and this body:

```json
{
  "detail": "Too many invalid API key attempts. Try again later."
}
```

A valid key is never refused and never counts, and requests without
`X-API-Key` are not affected. The budget is set in
`app/core/rate_limit.py`.

### Monthly call quota (per user)

Authenticated users are also limited per calendar month,
independently of the per-IP rate limits above:

| Tier | Monthly API calls |
|---|---|
| Anonymous | n/a (per-IP rate-limit only) |
| Free | 1,000 |
| Pro | 25,000 |
| Business | 200,000 |
| Enterprise | unlimited |

The gate counts every successful `POST /api/v1/convert`,
`/convert/batch`, `/compress`, `/compress/batch`, `/pdf/extract`,
`/pdf/split`, and `/pdf/compress` as **one** call. A batch with 25
files counts as 1 call (matching the pricing-page wording "API calls
per month"). Failed conversions do not count toward the quota.

When the limit is reached, the response is `429 Too Many Requests`
with a `Retry-After` header in seconds pointing at the start of the
next calendar month, and a body explaining the limit:

```json
{
  "detail": "Monthly API call limit reached (25000 per month for tier 'pro'). Quota resets 2026-06-01T00:00:00+00:00. Upgrade your plan or wait until the reset to continue."
}
```

The quota window is **calendar-month UTC** — the counter resets at
`00:00 UTC` on the 1st of every month. The pricing page advertises
identical figures; this gate is the runtime side of that promise.

---

## Swagger / OpenAPI

FileMorph auto-generates interactive API documentation:

- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`
- **OpenAPI JSON**: `http://localhost:8000/openapi.json`

The Swagger UI lets you test all endpoints directly in the browser.

---

## Integration Examples

### PHP

```php
$ch = curl_init('http://localhost:8000/api/v1/convert');
curl_setopt_array($ch, [
    CURLOPT_POST => true,
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_HTTPHEADER => ['X-API-Key: YOUR_KEY'],
    CURLOPT_POSTFIELDS => [
        'file' => new CURLFile('/path/to/photo.heic', 'image/heic', 'photo.heic'),
        'target_format' => 'jpg',
        'quality' => '85',
    ],
]);
$result = curl_exec($ch);
file_put_contents('/path/to/photo.jpg', $result);
```

### Node.js

```javascript
const FormData = require('form-data');
const fs = require('fs');
const axios = require('axios');

const form = new FormData();
form.append('file', fs.createReadStream('document.docx'));
form.append('target_format', 'pdf');

const response = await axios.post(
  'http://localhost:8000/api/v1/convert',
  form,
  {
    headers: { ...form.getHeaders(), 'X-API-Key': 'YOUR_KEY' },
    responseType: 'arraybuffer',
  }
);
fs.writeFileSync('document.pdf', response.data);
```

### C# / .NET

```csharp
using var client = new HttpClient();
client.DefaultRequestHeaders.Add("X-API-Key", "YOUR_KEY");

using var form = new MultipartFormDataContent();
form.Add(new StreamContent(File.OpenRead("photo.heic")), "file", "photo.heic");
form.Add(new StringContent("jpg"), "target_format");

var response = await client.PostAsync(
    "http://localhost:8000/api/v1/convert", form);
await File.WriteAllBytesAsync("photo.jpg", await response.Content.ReadAsByteArrayAsync());
```
