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

Either header satisfies the auth requirement on `/convert`, `/compress`, and their `/batch` variants. `/health` and `/formats` are public; the auth-flow endpoints (`/api/v1/auth/*`, `/api/v1/keys`, `/api/v1/billing/*`) require a JWT.

### API key (Community Edition)

Generate a key:
```bash
python scripts/generate_api_key.py
# or via Docker:
docker compose exec filemorph python scripts/generate_api_key.py
```

Keys are stored as SHA-256 hashes in `data/api_keys.json`. The plaintext key is shown exactly once at generation time. There is no key-rotation endpoint in the Community Edition — generate a new key and remove the old hash from the JSON file.

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

---

## Endpoints

### Cloud-Edition endpoints (account / billing / keys)

The endpoints in this section only respond when the Cloud overlay is configured (`DATABASE_URL` set, and where applicable `JWT_SECRET`, `STRIPE_SECRET_KEY`). Without those, they return `503 Service Unavailable`. All require `Authorization: Bearer <jwt>` unless noted.

**Auth (`/api/v1/auth/*`)**

| Method + Path | Auth | Purpose |
|---|---|---|
| `POST /api/v1/auth/register` | none | Create account; returns access + refresh tokens. Sends a verification email (fire-and-forget). |
| `POST /api/v1/auth/login` | none | Exchange email + password for access (15 min) + refresh (30 d) tokens. |
| `POST /api/v1/auth/refresh` | none (refresh-token in body) | Issue a new access token. |
| `GET /api/v1/auth/me` | Bearer | Return the currently authenticated user. |
| `POST /api/v1/auth/forgot-password` | none | Issue a single-use password-reset link via email (30 min TTL). |
| `POST /api/v1/auth/reset-password` | reset-token in body | Set a new password and invalidate older sessions via password-hash rotation. |
| `POST /api/v1/auth/verify-email` | verify-token | Mark the user's email as verified. |
| `POST /api/v1/auth/resend-verification` | Bearer | Re-send the verification mail (auth-required to avoid spam). |
| `DELETE /api/v1/auth/account` | Bearer | Self-service account deletion. Requires re-confirmation: current password, registered email, and the literal string `DELETE`. Free-tier accounts only — accounts with a Stripe customer ID return `409` and route to `privacy@filemorph.io` for the manual paid-tier path (HGB §257 / AO §147 retention). |

**API keys (`/api/v1/keys`)**

| Method + Path | Auth | Purpose |
|---|---|---|
| `POST /api/v1/keys` | Bearer | Create a new API key bound to the authenticated user. Plaintext key is shown exactly once in the response. |
| `GET /api/v1/keys` | Bearer | List the user's keys (id, name, prefix, created, last-used). |
| `DELETE /api/v1/keys/{id}` | Bearer | Revoke a key. |

**Billing (`/api/v1/billing/*`)**

| Method + Path | Auth | Purpose |
|---|---|---|
| `POST /api/v1/billing/checkout/{tier}` | Bearer | Start a Stripe Checkout for `pro` / `business`. Body MUST include `withdrawal_waiver_acknowledged: true` (BGB §356 (5) consent — see `terms.html` § 9). Returns the Stripe Checkout URL; an `auth.billing.withdrawal_waiver_recorded` audit event is written before the redirect. |
| `POST /api/v1/billing/portal` | Bearer | Return a Stripe Customer Portal URL so the user can manage card / cancel / re-subscribe. |
| `POST /api/v1/billing/webhook` | Stripe signature | Stripe → FileMorph webhook receiver. Handles `customer.subscription.{created,updated,deleted}`. Not exposed in OpenAPI. |

For schema details (request bodies, response shapes), open the auto-generated Swagger UI at `/docs` on the live deployment.

---

### POST `/api/v1/convert`

Convert a file from one format to another.

**Authentication**: Required (`X-API-Key` header)

**Request**: `multipart/form-data`

| Field | Type | Required | Description |
|---|---|---|---|
| `file` | file | Yes | The file to convert |
| `target_format` | string | Yes | Target format extension, e.g. `jpg`, `pdf`, `mp3` |
| `quality` | integer | No | Quality 1–100 (default: 85). Applies to lossy formats (JPEG, WebP, video) |

**Response**: `200 OK` — the converted file as a download

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

**Authentication**: Required (`X-API-Key` header)

**Request**: `multipart/form-data`

| Field | Type | Required | Description |
|---|---|---|---|
| `file` | file | Yes | The file to compress |
| `quality` | integer | No | Quality 1 (smallest) – 100 (best). Defaults to 85. Mutually exclusive with `target_size_kb` |
| `target_size_kb` | integer | No | Target output size in KB. Activates binary-search-on-quality (JPEG/WebP only). Mutually exclusive with `quality` |

**Supported formats**: JPG, JPEG, PNG, WebP, TIFF · MP4, MOV, AVI, MKV, WebM

`target_size_kb` is JPEG/WebP only — PNG/TIFF are lossless and quality does not control size meaningfully. Sending `target_size_kb` with a PNG returns `415`.

**Response**: `200 OK` — the compressed file as a download (same format, `_compressed` suffix in filename).

When `target_size_kb` is set, the response also carries:

| Header | Description |
|---|---|
| `X-FileMorph-Achieved-Bytes` | Actual output size in bytes |
| `X-FileMorph-Final-Quality` | Quality value the search settled on (1–100) |

Tolerance is ±3 % of the requested target. If even quality `1` exceeds the target, the smallest possible output is returned anyway and the headers reveal the actual size.

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

### POST `/api/v1/convert/batch`

Convert several files in one request. Returns a ZIP archive with all converted outputs.

**Authentication**: Required (`X-API-Key` or `Authorization: Bearer`)

**Request**: `multipart/form-data`

| Field | Type | Required | Description |
|---|---|---|---|
| `files` | files (≥1) | Yes | One or more files to convert |
| `target_formats` | string[] | Yes | Target format per file. Either one value (applied to all) or one per file (length must match `files`) |
| `quality` | integer | No | Quality 1–100 (default 85). Applied uniformly. |

**Response**: `200 OK` (`application/zip`) — archive with one entry per successful conversion. If at least one file fails, a `manifest.json` is added at archive root listing per-file results (success ZIP-only is preferred for all-success runs to keep the output clean).

A run with **every** file failing returns `422 Unprocessable Content` with a JSON body listing per-file errors.

```bash
curl -X POST http://localhost:8000/api/v1/convert/batch \
  -H "X-API-Key: YOUR_KEY" \
  -F "files=@a.heic" -F "files=@b.png" -F "files=@c.gif" \
  -F "target_formats=jpg" \
  --output batch.zip
```

---

### POST `/api/v1/compress/batch`

Compress several files in one request. Same response shape as `/convert/batch`.

**Authentication**: Required

**Request**: `multipart/form-data`

| Field | Type | Required | Description |
|---|---|---|---|
| `files` | files (≥1) | Yes | One or more files to compress |
| `quality` | integer | No | Quality 1–100 (default 85). Mutually exclusive with `target_size_kb`. |
| `target_size_kb` | integer | No | Per-file target size. Mutually exclusive with `quality`. |

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

**Response**: `200 OK` — JSON

```json
{
  "conversions": {
    "jpg": ["png", "webp", "bmp", "tiff", "gif"],
    "heic": ["jpg", "png", "webp"],
    "docx": ["pdf", "txt"],
    "txt": ["pdf"],
    "csv": ["xlsx", "json"],
    "mp4": ["avi", "mov", "mkv", "webm"],
    "mp3": ["wav", "flac", "ogg", "m4a"]
  },
  "compression": {
    "image": ["jpg", "jpeg", "png", "webp", "tiff"],
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
{
  "status": "ok",
  "version": "1.0.0",
  "ffmpeg_available": true
}
```

`ffmpeg_available: false` means video and audio operations will fail — check your system setup.

---

## Response Headers

Every successful conversion / compression carries integrity and classification metadata in response headers. CORS-enabled deployments expose these to browser clients (see `expose_headers` in `app/main.py`).

| Header | Value | Set on |
|---|---|---|
| `X-Output-SHA256` | Hex-encoded SHA-256 of the response body | every `/convert`, `/compress`, and their batch variants |
| `X-Data-Classification` | One of `public`, `internal`, `confidential`, `restricted` | every response — echoes the request header value, defaults to `internal` when absent (NEU-C.3 / BSI-style taxonomy) |
| `X-FileMorph-Achieved-Bytes` | Actual output size in bytes | only on `/compress` calls with `target_size_kb` |
| `X-FileMorph-Final-Quality` | Quality value the binary search settled on (1–100) | only on `/compress` calls with `target_size_kb` |
| `Retry-After` | Seconds the client should wait before retrying | only on `503 Service Unavailable` (concurrency cap) |

The `X-Data-Classification` value is also written to the audit-log entry for the request, so a downstream auditor can answer "what classification of data was processed in this call" from the database alone (see `app/core/audit.py`).

---

## Error Responses

All errors return JSON with a `detail` field:

```json
{
  "detail": "Conversion from 'jpg' to 'docx' is not supported."
}
```

| HTTP Status | Meaning |
|---|---|
| `400 Bad Request` | Missing or malformed request data (e.g. filename without extension) |
| `401 Unauthorized` | Missing or invalid `X-API-Key` / `Authorization: Bearer` |
| `403 Forbidden` | Authenticated but role/tier doesn't permit the action (e.g. non-admin hitting `/cockpit/*`) |
| `413 Content Too Large` | File exceeds `MAX_UPLOAD_SIZE_MB` (default: 100 MB) |
| `415 Unsupported Media Type` | `target_size_kb` set on a lossless format (PNG/TIFF), or otherwise incompatible request shape |
| `422 Unprocessable Content` | Unsupported format combination, missing form field, or every file in a batch failed |
| `429 Too Many Requests` | Rate limit exceeded (see Rate Limiting section below) |
| `500 Internal Server Error` | Conversion failed (e.g. corrupt file, missing binary) |
| `503 Service Unavailable` | Global concurrency cap reached (`MAX_GLOBAL_CONCURRENCY`). Response carries `Retry-After`. |

---

## Rate Limiting

Per-route limits (per IP address):

| Endpoint | Limit |
|---|---|
| `POST /api/v1/convert` | 10 / minute |
| `POST /api/v1/convert/batch` | 3 / minute |
| `POST /api/v1/compress` | 10 / minute |
| `POST /api/v1/compress/batch` | 3 / minute |
| `GET /api/v1/health`, `GET /api/v1/ready` | 30 / minute |
| `GET /api/v1/formats` | 120 / minute |
| Auth endpoints (`/api/v1/auth/*`) | 3–5 / minute |
| Billing endpoints (`/api/v1/billing/*`) | 5 / minute |
| Default (other routes) | 60 / minute |

When exceeded, the response is `429 Too Many Requests`. For higher
limits, self-host your own instance and adjust the decorators in
`app/api/routes/*.py` (slowapi `@limiter.limit("…/minute")`).

### Monthly call quota (per user)

Authenticated users on a paid tier are also limited per calendar
month, independently of the per-IP rate limits above:

| Tier | Monthly API calls |
|---|---|
| Anonymous | n/a (per-IP rate-limit only) |
| Free | 500 |
| Pro | 10 000 |
| Business | 100 000 |
| Enterprise | unlimited |

The gate counts every successful `POST /api/v1/convert`,
`/convert/batch`, `/compress`, and `/compress/batch` as **one**
call. A batch with 25 files counts as 1 call (matching the
pricing-page wording "API calls per month"). Failed conversions do
not count toward the quota.

When the limit is reached, the response is `429 Too Many Requests`
with a `Retry-After` header in seconds pointing at the start of the
next calendar month, and a body explaining the limit:

```json
{
  "detail": "Monthly API call limit reached (10000 per month for tier 'pro'). Quota resets 2026-06-01T00:00:00+00:00. Upgrade your plan or wait until the reset to continue."
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
