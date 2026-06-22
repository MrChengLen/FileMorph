# Self-Hosting Guide

FileMorph is designed to be self-hosted. This guide covers production deployments with Docker,
reverse proxy setup (Caddy or nginx), HTTPS/SSL, and operational best practices.

---

## Why self-host?

- **Data privacy (DSGVO / GDPR)**: Files never leave your own infrastructure
- **No rate limits**: Control throughput yourself
- **Custom access**: Issue API keys to your own users or services
- **Integration**: Run FileMorph inside your existing network, accessible only to internal services

---

## Production setup with Docker

### 1. Clone and configure

```bash
git clone https://github.com/MrChengLen/FileMorph.git
cd filemorph
cp .env.example .env
```

Edit `.env` for production:

```env
APP_HOST=0.0.0.0
APP_PORT=8000
APP_DEBUG=false

API_KEYS_FILE=data/api_keys.json

MAX_UPLOAD_SIZE_MB=100

# Restrict to your own domain in production
CORS_ORIGINS=https://yourapp.example.com,https://portal.example.com

# Optional: route heavy upload POSTs (convert/compress, single + batch) through
# a separate subdomain. Empty string = same-origin (default, simplest). Set
# only when the main site sits behind a proxy that caps request bodies and
# uploads must bypass it via a tunnel subdomain. The browser then cross-origins
# those POSTs to the listed URL; `CORS_ORIGINS` must include the main site
# origin so the preflight passes. Format-list GET + auth stay same-origin.
API_BASE_URL=

# Default UI locale for visitors with no signal (no cookie, no
# Accept-Language match, no /de|/en URL prefix). Upstream defaults to `de`
# (Hamburg-based operator). Self-hosters targeting an EN-first audience
# can flip this to `en` to render unprefixed routes (`/`, `/pricing`, …)
# in English. Supported values: `de`, `en`. The /de/... and /en/...
# prefixed routes always render in their respective locale regardless.
LANG_DEFAULT=de
```

### 2. Start the container

```bash
docker compose up -d
```

This builds and runs the **slim** image (`filemorph:latest`, ~150 MB).
For Word documents with footnotes, headers, multi-section layout, or
table-of-contents, see the [office image variant](#image-variants) below.

### 3. Generate API keys

```bash
docker compose exec filemorph python scripts/generate_api_key.py
```

The key is stored as a hash in `./data/api_keys.json` (bind-mounted into the container).

### 4. Verify

```bash
curl http://localhost:8000/api/v1/health
```

---

## Image variants

FileMorph ships in two image flavours so self-hosters can match the
attack surface and disk footprint to what they actually convert.

### `filemorph:latest` — slim image

The default. ~150 MB. Includes ffmpeg, Cairo / Pango (for WeasyPrint),
Ghostscript (for the PDF/A-2b re-render path), and the pure-Python
conversion stack. Use this image when your deployment:

- converts images, audio, video, markdown, or txt; or
- accepts the mammoth-based fidelity ceiling for DOCX → PDF (no
  footnotes / headers / footers / multi-section layout / TOC).

```yaml
# docker-compose.yml — default, builds the slim image
services:
  filemorph:
    image: ghcr.io/mrchenglen/filemorph:latest
    # or: build: { context: ., target: base }
```

### `filemorph:office` — high-fidelity DOCX → PDF

Adds LibreOffice headless + OFL Calibri/Arial/Times-metric fonts on
top of the slim image. ~430 MB. Use this image when:

- your deployment converts Word documents with footnotes, headers,
  footers, table-of-contents, multi-section layout, multi-level
  numbered lists, OLE objects, or equations; or
- you are running the **Compliance Edition** for Behörden / Kanzleien /
  Klinik buyers — Word-grade fidelity is part of the trust contract
  there.

The complexity router auto-detects which engine each DOCX needs (see
[`docs/formats.md`](./formats.md#notes-on-docx--pdf)); simple
documents still take the fast pure-Python path.

```bash
# Pre-built image:
docker pull ghcr.io/mrchenglen/filemorph:office

# Or layer the office overlay on top of the default compose:
docker compose -f docker-compose.yml -f docker-compose.office.yml up -d
```

The overlay sets `FILEMORPH_OFFICE_ENGINE=auto` (the default — route
complex DOCX through LibreOffice, simple ones through mammoth). To
force every conversion through LibreOffice, set
`FILEMORPH_OFFICE_ENGINE=libreoffice` in your `.env` (recommended in
the office image when you never want the fallback — it makes a missing
`soffice` fail loud instead of silently degrading).

### Verifying signatures

Both images are cosign-signed (keyless OIDC, no long-lived signing
key). After pulling, verify with:

```bash
cosign verify ghcr.io/mrchenglen/filemorph:office \
  --certificate-identity-regexp "^https://github\\.com/MrChengLen/FileMorph/" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

See [`docs/release-signing.md`](./release-signing.md) for the full
trust chain (cosign images + GPG-signed Git tags).

---

## Reverse proxy (HTTPS)

Place FileMorph behind a reverse proxy to handle SSL termination, domain routing, and request-body limits.

### Option A — Caddy (recommended)

Caddy auto-provisions and renews Let's Encrypt certificates without an extra agent. A
single config file, no certbot, no manual renewal cron. This is the path the FileMorph
team uses in production.

```bash
sudo apt install -y caddy
sudo $EDITOR /etc/caddy/Caddyfile
```

```caddyfile
# /etc/caddy/Caddyfile
filemorph.example.com {
    encode zstd gzip
    request_body {
        max_size 200MB
    }
    reverse_proxy 127.0.0.1:8000 {
        transport http {
            read_timeout  5m
            write_timeout 5m
        }
    }
}
```

```bash
sudo systemctl reload caddy
```

Caddy reads the host from `Caddyfile`, requests an ACME certificate on first hit,
and renews automatically. No further setup. Logs: `journalctl -u caddy -f`.

### Option B — nginx + Certbot

Use nginx if you already have it deployed for other services. Certbot handles certificate
issuance and renewal.

```nginx
# /etc/nginx/sites-available/filemorph

server {
    listen 80;
    server_name filemorph.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name filemorph.example.com;

    ssl_certificate     /etc/letsencrypt/live/filemorph.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/filemorph.example.com/privkey.pem;

    # Increase for large file uploads
    client_max_body_size 200M;

    location / {
        proxy_pass         http://127.0.0.1:8000;
        proxy_set_header   Host $host;
        proxy_set_header   X-Real-IP $remote_addr;
        proxy_set_header   X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;

        # Increase timeouts for large file conversions
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
}
```

Enable and reload:
```bash
sudo ln -s /etc/nginx/sites-available/filemorph /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d filemorph.example.com
```

Certbot automatically renews certificates every 90 days.

---

## Restrict to internal network only

If FileMorph should only be accessible within your organization (no public internet):

**Option A — Bind to internal IP only**

In `.env`:
```env
APP_HOST=192.168.1.50    # your server's internal IP
```

**Option B — Use a firewall**

```bash
# Allow only internal subnet
sudo ufw allow from 192.168.1.0/24 to any port 8000
sudo ufw deny 8000
```

**Option C — Docker network only** (FileMorph as a microservice)

```yaml
# docker-compose.yml — no port exposed externally
services:
  filemorph:
    build: .
    expose:
      - "8000"          # accessible only within Docker network
    networks:
      - internal

  your-app:
    image: your-app
    networks:
      - internal

networks:
  internal:
    driver: bridge
```

Your application calls FileMorph at `http://filemorph:8000` (Docker service name).

---

## Monitoring & metrics

FileMorph exposes Prometheus metrics at **`GET /api/v1/metrics`** when
`METRICS_ENABLED=true` (the default). Set `METRICS_ENABLED=false` to
remove the endpoint entirely on a single-tenant deployment that doesn't
run Prometheus — when disabled, no instrumentation is attached and the
route returns 404.

### What's exposed

| Metric family | Type | Labels | Use |
|---|---|---|---|
| `http_requests_total` | counter | `handler`, `method`, `status` | Throughput + error rate per route |
| `http_request_duration_seconds` | histogram | `handler`, `method` | Latency percentiles (p50/p95/p99) |
| `http_request_size_bytes` / `http_response_size_bytes` | summary | `handler` | Upload / download volume |
| `filemorph_conversions_total` | counter | `operation`, `src`, `tgt`, `status` | Per-format-pair conversion KPIs |

The endpoint emits only aggregate counters and timings — never file
contents, user identifiers, or secrets.

**Cardinality is bounded.** `src` / `tgt` come from user input, so any
format not in the converter registry collapses to `other`. The label
space is therefore `operations × (known_formats + 1) × statuses`, not
unbounded — a caller cannot explode the time-series count by POSTing
fake extensions.

### Scraping it

`/api/v1/metrics` is **unauthenticated** (the standard Prometheus
pattern). Keep it reachable only from your scraper — never the public
internet. Restrict it at the reverse proxy. Caddy:

```caddyfile
filemorph.example.com {
    @metrics path /api/v1/metrics
    handle @metrics {
        @notprom not remote_ip 10.0.0.0/8 127.0.0.1
        respond @notprom 403
        reverse_proxy 127.0.0.1:8000
    }
    reverse_proxy 127.0.0.1:8000
}
```

Minimal Prometheus scrape config:

```yaml
scrape_configs:
  - job_name: filemorph
    metrics_path: /api/v1/metrics
    scrape_interval: 15s
    static_configs:
      - targets: ["filemorph:8000"]
```

Grafana dashboards and alert rules (uptime, error-rate, p95 latency)
are not bundled in this repo — wire your own against the metric families
above, or use the dashboards the Compliance Edition ships.

---

## API Key management

### Generate a new key

```bash
docker compose exec filemorph python scripts/generate_api_key.py
```

### Revoke a key

Keys are stored as SHA-256 hashes in `data/api_keys.json`:

```json
{
  "keys": [
    "abc123hash...",
    "def456hash..."
  ]
}
```

To revoke, delete the corresponding hash entry and save the file.
No restart required — keys are re-read on every request.

### Rotate a key

1. Generate a new key: `python scripts/generate_api_key.py`
2. Update your application/service with the new key
3. Remove the old hash from `data/api_keys.json`

---

## AI file operations (commercial add-on)

PII redaction (`POST /api/v1/ai/redact/{detect,apply}`, the `/redact` page) is a
commercial **Enterprise-Edition** add-on under `app/ee/` — **not** part of the
AGPL engine. It is **inert by default**: with `AI_OPERATIONS_ENABLED` unset, the
engine is never imported, `/redact` returns 404, and the API endpoints return
`503` (the endpoints still appear in `/docs` — that's expected; they 503 until
enabled). Configure via three env vars (details + opacity note in `.env.example`):

| Env var | Default | Gates |
|---|---|---|
| `AI_OPERATIONS_ENABLED` | `false` | the whole feature (page, API, engine import) |
| `AI_ELIGIBLE_TIERS` | `pro,business,enterprise` | which paid tiers may run the paid `apply` (free `detect` is open to all) |
| `AI_CREDIT_COST_REDACT` | `1` | credits charged per `apply` (neutral usage unit; no euro price here) |

AI usage is metered in its own credit unit and is **not** counted against the
convert/compress `api_calls` monthly quota. Capability, limits and the GDPR
posture: [`pii-redaction.md`](pii-redaction.md).

---

## Operational notes

### Automatic restart

Docker Compose is configured with `restart: unless-stopped` — FileMorph restarts automatically after a server reboot or crash.

Enable your Docker daemon to start on boot:
```bash
sudo systemctl enable docker
```

### Health monitoring

The health endpoint is designed for monitoring tools and load balancers:

```
GET /api/v1/health
```

Example with **uptime monitoring** (e.g. UptimeRobot, Gatus):
- URL: `https://filemorph.example.com/api/v1/health`
- Expected keyword: `"status":"ok"`

### Log access

```bash
docker compose logs -f filemorph
```

### Disk space

All file processing happens in temporary directories that are cleaned up automatically after each request. FileMorph does not store uploaded or converted files permanently.

The only persistent data is `data/api_keys.json`.

### Capacity tuning (NEU-D.1 concurrency limiter)

`/convert` and `/compress` enforce a global parallelism cap and a
per-actor cap so a single tenant cannot OOM the worker. The
defaults are sized for a 4 GB host:

| Env var | Default | What it controls |
|---|---|---|
| `MAX_GLOBAL_CONCURRENCY` | `4` | Total parallel conversions across all callers. Past the cap → `503 Service Unavailable` + `Retry-After`. Raise this to roughly the CPU count on a bigger box. |
| `CONCURRENCY_ACQUIRE_TIMEOUT_SECONDS` | `0.5` | How long a request waits for a free slot before giving up. Small values fail fast; raise to absorb longer micro-bursts. |
| `CONCURRENCY_RETRY_AFTER_SECONDS` | `5` | Value sent in the `Retry-After` response header. Should match the typical drain time of a saturated pool. |

Per-actor limits (per user for authenticated callers, per IP for
anonymous) are tier-bound and not env-tunable: anonymous and free
get 1 concurrent request, Pro 2, Business 5, Enterprise 10. A
request past the per-actor cap returns `429 Too Many Requests`
with `Retry-After`. These numbers are documented on the public
[`/pricing`](/pricing) page so callers can size their own client
pools to match.

A batch endpoint (`/convert/batch`, `/compress/batch`) holds **one**
concurrency slot for the whole batch — files inside the batch are
processed sequentially. Increasing batch size therefore lengthens
slot-hold time linearly without inflating the parallelism cost.

### PDF/A-2b conformance (optional ghostscript)

The `pdf → pdfa` conversion target has two paths and falls back
automatically:

- **Markup-only** (always available): pikepdf writes the PDF/A-2b
  markers — XMP `pdfaid:part=2` / `conformance=B`, the `GTS_PDFA1`
  OutputIntent, a fresh `/ID` array, and strips PDF/A-forbidden
  surfaces. Sufficient when the source already has embedded fonts.
- **Ghostscript re-render** (when `gs` is on PATH): runs the source
  through `gs -dPDFA=2` first, which subset-embeds every font and
  drops features PDF/A-2 forbids. Required for sources that
  reference standard-14 fonts without embedding glyph data.

The official Docker image bundles ghostscript so the upgrade path
is on by default. On a custom build or systemd install:

```bash
sudo apt-get install -y ghostscript
```

Without `gs`, `pdf → pdfa` still succeeds — it just produces
markup-only output that veraPDF will reject if the source has
unembedded fonts. The structured log records `mode=rerender` vs
`mode=markup` for each conversion so you can spot the gap.

### Auth flows (Cloud Edition)

These endpoints ship in the same codebase but only become useful
when the Cloud Edition is on (Postgres + SMTP configured):

| Endpoint | Purpose | Notes |
|---|---|---|
| `POST /api/v1/auth/register` | Sign up | Fires a verification email best-effort; SMTP failure does not block registration. |
| `POST /api/v1/auth/verify-email` | Mark `users.email_verified_at` | Token bound to email-at-issuance (`eat` claim, 7-day TTL). Email rotation silently invalidates stale links. |
| `POST /api/v1/auth/resend-verification` | New verify link | Auth-required (no spam vector). 200 no-op when already verified. |
| `DELETE /api/v1/auth/account` | Self-service delete | Three-field re-confirmation; last-active-admin guard returns 409; Stripe-touched accounts return 409 directing to your support contact. Confirmation email sent post-commit. |

All four endpoints write `auth.*` events to the audit-log hash
chain. Outbound email uses the same `SMTP_*` configuration as
password-reset; the FROM address, reply-to, and the body's
"contact us" link are taken from `SMTP_FROM_EMAIL` /
`SMTP_REPLY_TO`. There are no hardcoded operator-domain addresses
in the user-facing copy — self-hosters ship their own support
identity. See [`docs/email-setup.md`](email-setup.md) for the SMTP
walkthrough (provider options, port/TLS choice, sandbox-mode pitfalls,
DSGVO sub-processor disclosure).

### Updating

```bash
git pull
docker compose build --no-cache
docker compose up -d
```

API keys in `./data/` are preserved across updates.

---

## systemd service (without Docker)

For running FileMorph directly as a Linux service:

```ini
# /etc/systemd/system/filemorph.service

[Unit]
Description=FileMorph file conversion service
After=network.target

[Service]
Type=simple
User=filemorph
WorkingDirectory=/opt/filemorph
Environment="PATH=/opt/filemorph/.venv/bin"
ExecStart=/opt/filemorph/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now filemorph
sudo systemctl status filemorph
```

---

## Security checklist

- [ ] Set `CORS_ORIGINS` to your specific domain(s), not `*`
- [ ] Set `APP_DEBUG=false` in production
- [ ] Keep `data/api_keys.json` out of version control (it is in `.gitignore`)
- [ ] Use HTTPS (see nginx + Certbot above)
- [ ] Set `MAX_UPLOAD_SIZE_MB` to a sensible limit for your use case
- [ ] Restrict network access if the service is internal-only
- [ ] Rotate API keys regularly
- [ ] Monitor disk usage (temp files are cleaned up, but check `/tmp` if issues occur)
