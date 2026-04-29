# API Usage Guide

A workflow-oriented walkthrough for integrating FileMorph. Pairs with
[`api-reference.md`](api-reference.md) — that doc lists every endpoint
and field; this one shows how the pieces fit together for real
integrations (auth, batches, error handling, quotas, CORS).

**Audience**: developers building against FileMorph, whether against
the hosted API at `https://api.filemorph.io` or a self-hosted instance.

**Base URL convention**: examples below use `https://api.filemorph.io`.
If you're running self-hosted, substitute `http://localhost:8000`
(default) or your own host. The API path prefix `/api/v1/` is the same
either way.

**Versioning**: the API path is versioned. Breaking changes go to
`/api/v2/` rather than mutating `/api/v1/`. Track [`CHANGELOG.md`](../CHANGELOG.md)
for release notes.

---

## Quickstart — Anonymous in 30 Seconds

The fastest path to your first conversion: no account, no API key.

```bash
curl -X POST https://api.filemorph.io/api/v1/convert \
  -F "file=@photo.heic" \
  -F "target_format=jpg" \
  -F "quality=90" \
  --output photo.jpg
```

That's it. Anonymous calls work — they just have tighter limits:

- **20 MB** per file
- **1 file** per request (batch endpoints reject anonymous callers)
- **10 requests/min** (shared with all unauthenticated traffic from
  your IP)

For larger files, batches, or higher rate limits, get an account.

---

## Authentication — JWT vs. X-API-Key

FileMorph accepts two credentials on the same endpoints:

| Credential | Header | Best for | Lifetime |
|---|---|---|---|
| JWT | `Authorization: Bearer <token>` | Browser apps, SPAs, short-lived sessions | 15 min access, 30 day refresh |
| API key | `X-API-Key: <key>` | Backend integrations, CLIs, cron jobs | Until revoked |

Both can be sent on the same request. The server prefers `Bearer`; if
that fails (expired, malformed) it falls back to `X-API-Key`. Anonymous
callers are also accepted — you get the `anonymous` tier.

### Auth flow

```
┌──────────┐  POST /auth/register or /auth/login   ┌────────────┐
│  Client  │ ────────────────────────────────────► │  FileMorph │
│          │ ◄──── { access_token, refresh_token } │            │
└──────────┘                                       └────────────┘
     │                                                    ▲
     │  POST /api/v1/convert  (Authorization: Bearer …)   │
     ├────────────────────────────────────────────────────┤
     │  ◄──── 200 OK + file                               │
     │                                                    │
     │  ⏱ 15 min later: access token expires              │
     │                                                    │
     │  POST /api/v1/convert                              │
     │  ◄──── 401 { "detail": "Invalid token." }          │
     │                                                    │
     │  POST /auth/refresh  { refresh_token }             │
     │  ◄──── { access_token, refresh_token }  (rotated)  │
     │                                                    │
     │  POST /api/v1/convert  (new bearer)                │
     │  ◄──── 200 OK                                      │
```

### Register and log in

```bash
# Register — returns tokens immediately, no email confirmation gate
curl -X POST https://api.filemorph.io/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"a-strong-password"}'

# Response (201 Created)
# { "access_token": "eyJ…", "refresh_token": "eyJ…", "token_type": "bearer" }

# Or log in if you already have an account
curl -X POST https://api.filemorph.io/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"a-strong-password"}'
```

```python
import requests

def login(email: str, password: str) -> dict:
    r = requests.post(
        "https://api.filemorph.io/api/v1/auth/login",
        json={"email": email, "password": password},
        timeout=10,
    )
    r.raise_for_status()
    return r.json()  # { "access_token": ..., "refresh_token": ..., "token_type": "bearer" }
```

```javascript
async function login(email, password) {
  const r = await fetch("https://api.filemorph.io/api/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!r.ok) throw new Error(`Login failed: ${r.status}`);
  return r.json();
}
```

### Refresh the access token

When a request returns `401`, exchange your refresh token for a fresh
access token. Refresh tokens rotate — store the new one and discard
the old.

```bash
curl -X POST https://api.filemorph.io/api/v1/auth/refresh \
  -H "Content-Type: application/json" \
  -d '{"refresh_token":"eyJ…"}'
```

### Generate an API key

API keys are easier for backend integrations: they don't expire, you
don't deal with refresh logic, and they're managed from the dashboard
(`/dashboard`) or via the API.

```bash
# Requires a valid bearer token in scope
curl -X POST https://api.filemorph.io/api/v1/keys \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"label":"prod-pipeline"}'

# Response (201 Created) — the plaintext "key" is shown ONCE
# {
#   "id": "9f5a…",
#   "label": "prod-pipeline",
#   "created_at": "2026-04-27T10:00:00Z",
#   "last_used_at": null,
#   "is_active": true,
#   "key": "sk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
# }
```

⚠️ **The plaintext `key` field is revealed exactly once**, in the
creation response. The server stores only its SHA-256 hash. If you
lose it, revoke the key (`DELETE /api/v1/keys/{id}`) and create a
new one.

**Storage advice**: load keys from environment variables, not from
checked-in config:

```bash
export FILEMORPH_API_KEY="sk_…"
```

```python
import os, requests
key = os.environ["FILEMORPH_API_KEY"]
requests.post(url, headers={"X-API-Key": key}, files=…)
```

Never commit a `.env` containing real keys. Add `.env` to `.gitignore`
and use a secrets manager (AWS Secrets Manager, Doppler, Vault, etc.)
for production deploys.

---

## Single-File Conversion

The full field reference lives in [`api-reference.md`](api-reference.md#post-apiv1convert).
This section focuses on **handling the response** correctly.

```python
import requests, re

def convert(path: str, target_format: str, key: str, quality: int = 85) -> tuple[bytes, str]:
    with open(path, "rb") as f:
        r = requests.post(
            "https://api.filemorph.io/api/v1/convert",
            headers={"X-API-Key": key},
            files={"file": (path, f)},
            data={"target_format": target_format, "quality": quality},
            timeout=60,
            stream=True,  # don't buffer in memory for large outputs
        )
    r.raise_for_status()
    # Server sets the filename in Content-Disposition; parse it for
    # display, but you can save under any name you want.
    cd = r.headers.get("Content-Disposition", "")
    m = re.search(r'filename="([^"]+)"', cd)
    suggested = m.group(1) if m else f"output.{target_format}"
    return r.content, suggested
```

**Response anatomy**:

- `Content-Type: application/octet-stream`
- `Content-Disposition: attachment; filename="<original-stem>.<target-ext>"`
- Body: the converted file, raw bytes.

**Quality semantics** vary by format:

- **JPEG, WebP, video** — `quality` (1–100) maps directly to encoder
  quality. Default `85` is a good general trade-off.
- **PNG, TIFF (lossless)** — `quality` is ignored; output is always
  lossless.
- **Audio** — bitrate is derived from quality; defaults are sensible
  but you can pass an explicit value.

---

## Compress to a Target Size

Sometimes you don't care about quality — you care about a hard size
cap. Email gateways with 25 MB attachment limits, embedded systems
with constrained storage, archive jobs trying to fit a year of photos
into a fixed budget. For these, send `target_size_kb` instead of
`quality`:

```bash
curl -X POST https://api.filemorph.io/api/v1/compress \
  -H "X-API-Key: $FILEMORPH_API_KEY" \
  -F "file=@photo.jpg" \
  -F "target_size_kb=500" \
  -D headers.txt \
  --output photo_capped.jpg

# Inspect achieved size:
grep -i x-filemorph headers.txt
# X-FileMorph-Achieved-Bytes: 489214
# X-FileMorph-Final-Quality: 72
```

The server runs a binary search on quality (1–100) and returns the
output that lands within ±3 % of the target.

**Constraints:**

- **JPEG / WebP only.** PNG and TIFF are lossless — quality does not
  control size meaningfully. Sending `target_size_kb` with a PNG
  returns `415`.
- **Mutually exclusive with `quality`.** Send one or the other; sending
  both returns `400`.
- **Tier-capped.** `target_size_kb` larger than your tier's output cap
  returns `413` *before* any encoding work, so a typo doesn't burn CPU.
- **Below-floor edge case.** If even quality `1` exceeds the target
  (the input simply can't be that small without resizing), the server
  returns the smallest possible output anyway — status `200`, and
  `X-FileMorph-Achieved-Bytes` reveals the actual size so your client
  can react.

**Python:**

```python
import requests

def compress_to_target(path: str, target_kb: int, key: str) -> tuple[bytes, int]:
    with open(path, "rb") as f:
        r = requests.post(
            "https://api.filemorph.io/api/v1/compress",
            headers={"X-API-Key": key},
            files={"file": f},
            data={"target_size_kb": target_kb},
            timeout=120,
        )
    r.raise_for_status()
    achieved = int(r.headers["X-FileMorph-Achieved-Bytes"])
    return r.content, achieved
```

**JavaScript (browser):**

```javascript
const fd = new FormData();
fd.append("file", file);
fd.append("target_size_kb", "500");

const res = await fetch("https://api.filemorph.io/api/v1/compress", {
  method: "POST",
  headers: { "X-API-Key": API_KEY },
  body: fd,
});
const blob = await res.blob();
const achieved = parseInt(res.headers.get("X-FileMorph-Achieved-Bytes"), 10);
console.log(`Output: ${(achieved / 1024 / 1024).toFixed(2)} MB`);
```

The batch endpoint accepts the same parameter; it applies the target
to every file in the request:

```bash
curl -X POST https://api.filemorph.io/api/v1/compress/batch \
  -H "X-API-Key: $FILEMORPH_API_KEY" \
  -F "files=@one.jpg" \
  -F "files=@two.jpg" \
  -F "target_size_kb=300" \
  --output capped.zip
```

---

## Batch Conversion — The Three Response Shapes

`POST /api/v1/convert/batch` and `POST /api/v1/compress/batch` cut
request overhead when you have many files. The wire format is
straightforward, but the response branches three ways depending on
which files succeeded.

### Multipart layout

```bash
curl -X POST https://api.filemorph.io/api/v1/convert/batch \
  -H "X-API-Key: $FILEMORPH_API_KEY" \
  -F "files=@one.jpg" \
  -F "files=@two.jpg" \
  -F "files=@three.heic" \
  -F "target_formats=png" \
  -F "target_formats=png" \
  -F "target_formats=jpg" \
  --output result.zip
```

`files` and `target_formats` are repeated multipart fields. They must
have **the same length and the same order** — `target_formats[i]` is
the desired output for `files[i]`. Mismatch → `400 Bad Request`.

### The three response shapes

| Outcome | Status | Content-Type | Body |
|---|---|---|---|
| All files succeeded | `200 OK` | `application/zip` | ZIP of converted files (no manifest) |
| Some succeeded, some failed | `200 OK` | `application/zip` | ZIP of successful files **plus** `manifest.json` |
| Every file failed | `422 Unprocessable Entity` | `application/json` | `{ summary, files[] }` (no ZIP) |

Your client has to inspect Content-Type before parsing.

### Python — handle all three shapes

```python
import io, json, zipfile, requests

def batch_convert(paths: list[str], targets: list[str], key: str) -> dict:
    files = [("files", (p, open(p, "rb"))) for p in paths]
    data = [("target_formats", t) for t in targets]
    r = requests.post(
        "https://api.filemorph.io/api/v1/convert/batch",
        headers={"X-API-Key": key},
        files=files,
        data=data,
        timeout=300,
    )
    ctype = r.headers.get("Content-Type", "")

    if r.status_code == 422 and "application/json" in ctype:
        # Shape C: everything failed
        return {"status": "all_failed", "body": r.json()}

    if r.status_code == 200 and "application/zip" in ctype:
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        names = set(zf.namelist())
        if "manifest.json" in names:
            # Shape B: partial success — manifest tells you which is which
            manifest = json.loads(zf.read("manifest.json"))
            return {"status": "partial", "zip": zf, "manifest": manifest}
        # Shape A: clean all-success
        return {"status": "ok", "zip": zf}

    r.raise_for_status()
    raise RuntimeError(f"Unexpected response: {r.status_code} {ctype}")
```

### JavaScript — browser upload

```javascript
async function batchConvert(fileList, targets, apiKey) {
  const fd = new FormData();
  for (const f of fileList) fd.append("files", f);
  for (const t of targets) fd.append("target_formats", t);

  const r = await fetch("https://api.filemorph.io/api/v1/convert/batch", {
    method: "POST",
    headers: { "X-API-Key": apiKey },
    body: fd,
  });
  const ctype = r.headers.get("Content-Type") || "";

  if (r.status === 422 && ctype.includes("application/json")) {
    return { status: "all_failed", body: await r.json() };
  }
  if (r.ok && ctype.includes("application/zip")) {
    const blob = await r.blob();
    // Use JSZip or the browser's built-in DecompressionStream to inspect
    // manifest.json (if present) and extract files.
    return { status: "ok_or_partial", blob };
  }
  throw new Error(`Unexpected response: ${r.status} ${ctype}`);
}
```

### Manifest schema

When `manifest.json` is present (partial-success ZIP) or as the body
of a 422, it has this shape:

```json
{
  "summary": {
    "operation": "convert_batch",
    "total": 3,
    "succeeded": 2,
    "failed": 1,
    "total_bytes_in": 4194304,
    "total_bytes_out": 1572864,
    "duration_ms": 412
  },
  "files": [
    { "name": "one.jpg",   "status": "ok",    "size_in": 1048576, "size_out": 786432, "error_message": "" },
    { "name": "two.jpg",   "status": "ok",    "size_in": 2097152, "size_out": 786432, "error_message": "" },
    { "name": "three.heic","status": "error", "size_in": 1048576, "size_out": 0,      "error_message": "Output too large; try WebP/AVIF or upgrade." }
  ]
}
```

Common per-file `error_message` values:

- `"Output too large; try WebP/AVIF or upgrade."` — output exceeded
  your tier's `output_cap_bytes`.
- `"Conversion from 'docx' to 'mp4' is not supported."` — no
  converter for that pair.
- `"File type not permitted."` — magic-byte filter rejected the
  upload (executable / script content).

### Duplicate filenames

If two inputs convert to the same output name (`a.jpg` and `a.JPG`
both → `a.png`), the second one gets `_2` appended (`a_2.png`),
and so on. The order in `files[]` decides which wins the unsuffixed
name.

---

## Tier Quotas & Discovery

| Tier      | Max file size | Max files / batch | Output cap | API/min | API/month |
|-----------|---------------|-------------------|------------|---------|-----------|
| anonymous |     20 MB     |         1         |     60 MB  |   10    |    n/a    |
|   free    |       50 MB   |          5        |     150 MB |  10     |     500   |
| pro       | 100 MB        | 25                | 300 MB     | 60      | 10,000    |
| business  | 500 MB        | 100               | 500 MB     | 60      | 100,000   |
| enterprise| 500 MB        | 250               | 500 MB     | 60      | unlimited |

Exact values live in [`app/core/quotas.py`](../app/core/quotas.py)
and may be tuned over time — call `/api/v1/auth/me` at runtime if
you need the live numbers.

### Discover your tier

```bash
curl https://api.filemorph.io/api/v1/auth/me \
  -H "Authorization: Bearer $ACCESS_TOKEN"

# {
#   "id": "9f5a-…",
#   "email": "you@example.com",
#   "tier": "pro",
#   "role": "user",
#   "created_at": "2026-01-15T08:30:00Z"
# }
```

Note: `/auth/me` only accepts JWT, not `X-API-Key`. If you only have
an API key in your client, store the tier alongside the key when you
mint it.

### What happens at each cap

- **File size exceeded** → `413 Request Entity Too Large` with a
  hint like `"File too large; max 100 MB for your plan."`
- **Batch size exceeded** → `400 Bad Request` with
  `"Batch size N exceeds tier limit of M."`
- **Output cap exceeded** → `413` with `"Output too large; try
  WebP/AVIF or upgrade."` Note this is checked **after** the
  conversion runs — your CPU and API-call budget are still consumed.
- **Rate limit exceeded** → `429 Too Many Requests` (no
  `Retry-After` header — see backoff guidance below).

### Why the output cap exists

A 5 MB JPEG re-encoded to PNG can balloon to 50+ MB; MP3 → WAV is
~11×. Without an output cap, a single request could push gigabytes
out of the server. The cap is generous (3× input on tiers below
business) but enforced post-conversion. To stay under it: pick
modern lossy formats (WebP, AVIF, MP3 at lower bitrate) where you
have a choice.

---

## Error Handling — Standard Patterns

### Error envelope

All 4xx and 5xx responses share the FastAPI default JSON shape:

```json
{ "detail": "Human-readable error message." }
```

For Pydantic validation failures (422) you also get a structured
`errors` array describing each invalid field.

### Status code matrix

| Code | Meaning | Retry? |
|---|---|---|
| `400` | Validation: missing field, mismatched arrays, batch over tier | No — fix the request |
| `401` | Missing or invalid auth | No — refresh JWT or check key |
| `403` | Authenticated but not allowed (admin-only routes) | No |
| `409` | Conflict — usually email already registered | No |
| `413` | File or output exceeds cap | No — reduce size or upgrade |
| `422` | Unsupported format pair, or batch where every file failed | Per-file decision |
| `429` | Rate limit | Yes, with backoff |
| `5xx` | Server error | Yes, with backoff |

### Retry policy

Only `429` and `5xx` are worth retrying. `4xx` other than `429` means
the request is wrong; retrying without changes is a waste.

```python
import time, requests

def with_backoff(fn, max_attempts: int = 4):
    delay = 1.0
    for attempt in range(max_attempts):
        r = fn()
        if r.status_code == 429:
            time.sleep(60)  # global limit is per-minute; one full window
        elif 500 <= r.status_code < 600:
            time.sleep(delay)
            delay *= 2
        else:
            return r
    return r  # final attempt's response, even if still failing
```

There is **no `Retry-After` header**. Start at 60 seconds for `429`
(the global rate window) and exponential (1s → 2s → 4s → 8s) for
`5xx`.

### Magic-byte filter

Before any converter runs, the server peeks at the first few bytes
and rejects anything that looks like an executable or script:

- `MZ` (Windows PE / DOS executables)
- `\x7fELF` (Unix binaries)
- `#!/` (shebang scripts)
- `<?php` (PHP source)

This applies regardless of the file extension and regardless of
whether a converter for that pair exists. Rejected with
`400 "File type not permitted."` — there's no retry that helps.

---

## Format Discovery — `GET /api/v1/formats`

Use this to populate dropdowns dynamically and to skip uploads for
unsupported pairs.

```bash
curl https://api.filemorph.io/api/v1/formats
# Returns the list of converter pairs and compressible formats.
```

```python
import requests
formats = requests.get("https://api.filemorph.io/api/v1/formats").json()

def can_convert(src: str, tgt: str) -> bool:
    return any(p["src"] == src and p["tgt"] == tgt for p in formats["convert"])
```

```javascript
const formats = await fetch("https://api.filemorph.io/api/v1/formats").then(r => r.json());
```

The endpoint is anonymous-OK and unlimited — safe to cache for an
hour or so on the client. See [`formats.md`](formats.md) for the
human-readable catalogue.

---

## Cross-Origin Notes (CORS)

Most integrations hit the API from a backend, where CORS doesn't
apply. The CORS section matters only when **a browser** is calling
the API on a different origin — for example, a SPA on
`https://yourapp.com` calling `https://api.filemorph.io`.

### What to expect

The browser sends an `OPTIONS` preflight before the real request.
The server responds with the allowed origin, methods, and exposed
headers. If the preflight fails, the real request is never sent —
you'll see a CORS error in the dev console with no network tab
entry for the actual upload.

### Reading the filename

`Content-Disposition` is in the server's `expose_headers` list, so
this works:

```javascript
const res = await fetch(uploadUrl, { method: "POST", body: fd });
const cd = res.headers.get("Content-Disposition");  // "attachment; filename=\"photo.png\""
```

If you forget the cross-origin allowlist on a self-hosted instance,
the browser will hide the header silently and you'll fall back to
`"result"` as the filename. This is a frequent source of "downloads
have no extension" bugs in self-hosted setups.

### Self-hosted CORS setup

Set the `CORS_ORIGINS` environment variable to the front origin(s)
that should be allowed:

```bash
export CORS_ORIGINS="https://yourapp.com,https://www.yourapp.com"
```

See [`self-hosting.md`](self-hosting.md) for the full deployment
context including reverse proxy and `API_BASE_URL` split-domain
deployments.

---

## Practical Patterns

### Synchronous-only

Every request blocks until the conversion finishes. There's no async
job queue, no polling endpoint, no webhook callback. Plan your
client timeouts accordingly:

- Image conversion: <2 s typical
- Document conversion: 1–5 s
- Audio (re-encode): 2–10 s
- Video (FFmpeg): can take **30+ seconds** for large inputs

Use a generous client timeout (`requests.post(..., timeout=300)`) for
video, and avoid wrapping the call in tight per-request UI feedback.

### Idempotency

There is no `Idempotency-Key` header. Retrying a successful upload
runs the conversion again and returns equivalent output. Convertions
are deterministic for a given `(file, target_format, quality)` tuple,
so this is safe but wasteful — design your retry logic to only fire
on errors, not on network blips that may have actually succeeded.

### Concurrency

The server processes requests in parallel up to a concurrency limit
set at deploy time. As a client, you can pipeline up to your tier's
`API/min` budget — 60/min for paid tiers means roughly 1 request per
second. Beyond that you'll start seeing `429`s.

---

## Resources

- [`api-reference.md`](api-reference.md) — per-endpoint reference (fields, status codes, language snippets)
- [`formats.md`](formats.md) — supported conversion pairs and compression formats
- [`installation.md`](installation.md) — local setup
- [`self-hosting.md`](self-hosting.md) — production deployment, reverse proxy, env vars
- [`CHANGELOG.md`](../CHANGELOG.md) — release notes
- [Swagger UI](https://api.filemorph.io/docs) — auto-generated OpenAPI spec for machine-readable exploration

**Bug reports & feature requests**: [github.com/MrChengLen/FileMorph/issues](https://github.com/MrChengLen/FileMorph/issues)
