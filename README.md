# FileMorph

> **Open-source file conversion & compression you can read, run, and self-host.**

Convert images, documents, audio, video, and spreadsheets; compress to an exact
target size. AGPL-3.0, EU-hostable, stateless. Web UI + REST API. The full engine
is free with **no feature gates** — self-host it via Docker, or use the hosted
instance at [filemorph.io](https://filemorph.io). Integrable by any service via REST API.

[![CI](https://github.com/MrChengLen/FileMorph/actions/workflows/ci.yml/badge.svg)](https://github.com/MrChengLen/FileMorph/actions)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-blue)](LICENSE) [![Commercial](https://img.shields.io/badge/commercial-available-brightgreen)](COMMERCIAL-LICENSE.md)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org)
[![Docker](https://img.shields.io/badge/docker-ready-0db7ed)](https://ghcr.io/mrchenglen/filemorph)

---

## What is FileMorph?

FileMorph is an open-source file conversion service with two interfaces:

- **Web UI** — drag-and-drop files in the browser, pick a format, download the result
- **REST API** — send files programmatically, integrate into any application or workflow

```
┌─────────────────────────────────────────────────────────┐
│  FileMorph        Tools  Self-Hosted  API Docs  GitHub  │
├─────────────────────────────────────────────────────────┤
│                                                         │
│              Convert & Compress Files                   │
│ Images · PDF · Documents · Audio · Video · Spreadsheets │
│                                                         │
│            [ Convert ]  [ Compress ]                    │
│                                                         │
│     ┌─────────────────────────────────────────┐         │
│     │              ⬆                          │         │
│     │     Drag & drop your files here         │         │
│     │   or click to browse  (multi-file)      │         │
│     │                                         │         │
│     │  HEIC · HEIF · JPG · PNG · WebP · AVIF  │         │
│     │  BMP · TIFF · GIF · ICO · DOCX · PDF    │         │
│     │  TXT · MD · HTML · EML · XLSX · CSV     │         │
│     │  JSON · MP4 · MOV · AVI · MKV · WebM    │         │
│     │  FLV · WMV · MP3 · WAV · FLAC · OGG     │         │
│     │  M4A · AAC · WMA · OPUS                 │         │
│     └─────────────────────────────────────────┘         │
│                                                         │
│     Or choose directly ────────────────────────         │
│     [Compress PDF] [JPG to PDF] [Word to PDF]           │
│     [Split PDF] [Extract PDF pages] [HEIC to JPG]       │
│     [Compress image (KB/MB)]                            │
│     All tools →                                         │
│                                                         │
│     Target Format:  [ JPG                  ▼ ]          │
│     Quality:        ████████░░  85%                     │
│                                                         │
│                  [ Convert ]                            │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

Authentication is via the `X-API-Key` request header for the REST API,
or via the dashboard-stored key (per-browser, not shown in the form
itself) for the Web UI.

---

## Editions

FileMorph runs in three editions, all built from this repository:

| Edition | Where | What you get |
|---|---|---|
| **Community** | Self-hosted (Docker, source) | File conversion + compression, REST API, single-user API-key auth |
| **Cloud SaaS** | [filemorph.io](https://filemorph.io) | Community features + user accounts (JWT), tier quotas, Stripe billing, admin cockpit |
| **Compliance** | Self-hosted with commercial licence | Cloud-Edition features + tamper-evident audit log (SHA-256 hash chain), `X-Output-SHA256` integrity header, PDF/A-2b output (CI gate validated against veraPDF for a worst-case fixture), default-on EXIF/XMP/IPTC strip, `X-Data-Classification` header, self-service account deletion, signed images (cosign) + cryptographically signed releases. For DACH Behörden, Krankenhäuser, and Anwaltskanzleien. |

> **PII redaction** (commercial add-on, `app/ee/`, inert unless
> `AI_OPERATIONS_ENABLED`): detect + remove structured PII — IBAN, email, phone,
> IPv4, payment card — from TXT/DOCX/XLSX, with fail-closed verification. Honest
> scope: no free-text names/addresses yet (no NER), no PDF. See
> [`docs/pii-redaction.md`](docs/pii-redaction.md). It is **not** a format
> conversion, so it is absent from the Supported Formats table.

PDF/A-2b output, the default-on EXIF/XMP/IPTC strip and the `X-Output-SHA256`
header are part of the AGPL engine and work in every edition; the hash-chained
audit log is AGPL code too and records whenever `DATABASE_URL` is set (Cloud
overlay). What the Compliance Edition adds is the commercial licence, a DPA, a
support SLA and a liable contact — see [`COMMERCIAL-LICENSE.md`](COMMERCIAL-LICENSE.md).

The README and `docs/` are written for the **Community** edition. The
Cloud-Edition features (account registration, Stripe checkout, admin
cockpit, email verification, account deletion) ship in the same codebase
but stay dormant unless you enable the Cloud overlay (see Quickstart
Option B below) — see [docs/self-hosting.md](docs/self-hosting.md) for
the full stack and [docs/security-overview.md](docs/security-overview.md)
for the defensive-transparency overview. The Compliance-Edition contract
+ commercial licence are described at
[`/enterprise`](https://filemorph.io/enterprise) (live on filemorph.io)
and [`COMMERCIAL-LICENSE.md`](COMMERCIAL-LICENSE.md).

---

## Pricing & positioning

FileMorph is **free and self-hostable forever** under AGPL-3.0, with no feature
gates. Hosted plans on [filemorph.io](https://filemorph.io) add convenience
(accounts, volume quotas, API); the Compliance Edition adds a commercial licence
plus contracts for regulated administration.

**Hosted plans (filemorph.io)** — prices without VAT (the operator is a small
business under §19 UStG, Germany). Pre-launch: the Free tier is live; paid
checkout goes live once payment processing is set up. Self-hosting is always free.

| Plan | Price | File size | Batch | API calls/mo | Concurrency |
|---|---|---|---|---|---|
| Free | €0 | 100 MB | 10 | 1,000 | 1 |
| Pro | €3/mo | 250 MB | 50 | 25,000 | 3 |
| Business | €9/mo | 500 MB | 150 | 200,000 | 6 |

**Compliance Edition** (self-hosted + commercial licence) — for DACH Behörden,
Krankenhäuser, Anwaltskanzleien; data stays behind your firewall.

| Tier | Scope | Price/year |
|---|---|---|
| Starter | 1 server, ≤ 50 staff | €990 |
| Standard | 3 servers, ≤ 2,000 staff | €7,490 |
| Enterprise | unlimited servers, custom SLA | from €24,900 |

Includes the commercial licence, an Art. 28 GDPR DPA template, the SHA-256 audit
log, PDF/A-2b (veraPDF CI-gated), default-on EXIF/XMP strip, and signed images
(cosign) + SBOM. See [`/enterprise`](https://filemorph.io/enterprise) and
[`COMMERCIAL-LICENSE.md`](COMMERCIAL-LICENSE.md). Internal use by an authority is
already free under AGPL — the Compliance Edition sells accountability (DPA, SLA,
a liable EU contact), not permission. The audit log, PDF/A-2b and the EXIF/XMP
strip in that list are the same AGPL code every edition runs.

> **Honest maturity:** no external audit or ISO 27001 certification yet (both a
> Year-2 roadmap item). There is one tagged release so far — v1.1.0 (tagged 2026-06-01),
> with a CycloneDX SBOM and the image digest attached to the GitHub release;
> `main` has moved on since (see [`CHANGELOG.md`](CHANGELOG.md), `[Unreleased]`).
> Everything else above is in the repository today and auditable.

---

## Supported Formats

| Category      | Input formats                                                   | Output formats                                |
|---------------|------------------------------------------------------------------|-----------------------------------------------|
| **Images**    | HEIC, HEIF, JPG, JPEG, PNG, WebP, AVIF, BMP, TIFF, GIF, ICO     | JPG, PNG, WebP, AVIF, BMP, TIFF, GIF, ICO, PDF |
| **Documents** | DOCX, TXT, Markdown (`.md`)                                      | PDF, TXT, HTML                                |
| **Web & email** | HTML, EML                                                      | PDF                                           |
| **PDF**       | PDF                                                              | TXT, PDF/A-2b<sup>†</sup>                     |
| **Spreadsheets** | XLSX, CSV, JSON                                               | CSV, XLSX, JSON                               |
| **Audio**     | MP3, WAV, FLAC, OGG, M4A, AAC, WMA, Opus                        | MP3, WAV, FLAC, OGG, M4A, AAC, WMA, Opus     |
| **Video**     | MP4, MOV, AVI, MKV, WebM, FLV, WMV                              | MP4, MOV, AVI, MKV, WebM, FLV, WMV           |

**Compression** (quality-based or target-size, no re-encoding format change):
Images: JPG, PNG, WebP, AVIF, TIFF · Video: MP4, MOV, AVI, MKV, WebM
Compress mode supports both *by quality %* and *by target size MB*.
Target-size compression covers the lossy image formats (JPEG, WebP, AVIF); AVIF/AV1 encode is more CPU-intensive than JPEG/WebP.

**PDF tools:** split a PDF into single-page files, extract a page range, or compress toward a target size — via the web UI (`/pdf/split`, `/pdf/extract`, `/pdf/compress`) or the API; see [docs/formats.md](docs/formats.md#pdf-structural-operations). Image compression to an exact target size (video too, by quality) has its own page at `/compress`. All tool pages are listed at `/tools`.

<sup>†</sup> Full PDF/A-2b conformance (passes
[veraPDF](https://verapdf.org/) validation) requires
[Ghostscript](https://www.ghostscript.com/) on the host. The Docker
image bundles it; for local-Python installs see
[`docs/installation.md`](docs/installation.md). Without Ghostscript,
`pdf → pdfa` falls back to a markup-only output that veraPDF will
reject if the source PDF has unembedded fonts.

---

## Quickstart

### Option A — Docker, Community Edition (recommended for self-hosting)

> Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows/macOS) or `docker` + `docker compose` (Linux).

```bash
git clone https://github.com/MrChengLen/FileMorph.git
cd FileMorph
```

**Windows** — double-click `start.bat`
**Linux / macOS** — run `./start.sh`

Both scripts build the image (first run: 2–5 min), wait for the
healthcheck, print your API key from the container logs, and open the
browser at **http://localhost:8000**. API keys live under `./data/`
and survive `docker compose down`.

Manual start without the launcher script:

```bash
docker compose up -d
docker compose logs --tail=30 filemorph    # shows API key on first run
```

Stop:

```bash
docker compose down
```

**High-fidelity DOCX → PDF (office image):** the default image converts DOCX
with a pure-Python pipeline (mammoth + WeasyPrint), which simplifies
footnotes, headers/footers, multi-section page setup and similar Word layout.
For Word-grade output, layer the office overlay on top — it adds LibreOffice
(the image is about 280 MB larger):

```bash
docker compose -f docker-compose.yml -f docker-compose.office.yml up -d
```

`FILEMORPH_OFFICE_ENGINE` in `.env` picks the engine: `auto` (default) sends
only complex documents to LibreOffice, `libreoffice` sends every DOCX,
`mammoth` none. The pre-built image is `ghcr.io/mrchenglen/filemorph:office`.

### Option B — Docker, Cloud Edition (user accounts + Stripe + cockpit)

The Cloud-Edition features (registration, JWT login, billing, admin
cockpit, audit log, daily metrics) need a Postgres database. Layer on
the Cloud overlay:

```bash
cp .env.example .env                      # then set POSTGRES_PASSWORD + JWT_SECRET
docker compose -f docker-compose.yml -f docker-compose.cloud.yml up -d
```

The entrypoint runs `alembic upgrade head` on first boot (and on every
restart — idempotent). Cloud-Edition env vars (`STRIPE_*`, `SMTP_*`,
`CORS_ORIGINS`, `APP_BASE_URL`, …) are documented in `.env.example` and
in [docs/self-hosting.md](docs/self-hosting.md).

The admin cockpit (`/cockpit`) needs an admin account: register in the web
UI, then promote that address from the command line:

```bash
docker compose -f docker-compose.yml -f docker-compose.cloud.yml exec filemorph python scripts/promote_admin.py you@example.com
```

Stop:

```bash
docker compose -f docker-compose.yml -f docker-compose.cloud.yml down
```

### Option C — Local development (Windows)

> Requires Python 3.11+ and Git. No Docker needed. DOCX, Markdown, HTML and
> EML → PDF go through WeasyPrint, which needs the GTK/Pango libraries installed
> on Windows, and full PDF/A-2b needs Ghostscript — see
> [WeasyPrint's installation notes](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#installation)
> and [docs/installation.md](docs/installation.md).

```powershell
git clone https://github.com/MrChengLen/FileMorph.git
cd FileMorph
.\dev.ps1
```

On first run, `dev.ps1` creates the virtual environment, copies
`.env.example` to `.env` and generates your API key. On every start it runs
`pip install -r requirements.txt` (so new dependencies arrive after a
`git pull`) and then starts the server with live-reload at
**http://127.0.0.1:8000**.

**Optional — Desktop shortcut (double-click to start):**

```powershell
.\create-shortcut.ps1
```

This places a `FileMorph` shortcut on your Desktop.

---

## API Usage

All conversion endpoints accept the `X-API-Key` header.

```bash
# Convert HEIC → JPG
curl -X POST http://localhost:8000/api/v1/convert \
  -H "X-API-Key: YOUR_KEY" \
  -F "file=@photo.heic" \
  -F "target_format=jpg" \
  --output photo.jpg

# Compress an image to 70% quality
curl -X POST http://localhost:8000/api/v1/compress \
  -H "X-API-Key: YOUR_KEY" \
  -F "file=@large.jpg" \
  -F "quality=70" \
  --output smaller.jpg

# List all supported conversions
curl http://localhost:8000/api/v1/formats

# Interactive Swagger docs
open http://localhost:8000/docs
```

→ Full API reference: [docs/api-reference.md](docs/api-reference.md)

---

## Documentation

| Guide | Description |
|---|---|
| [Installation](docs/installation.md) | Step-by-step setup for Windows and Linux |
| [API Reference](docs/api-reference.md) | All endpoints, parameters, response formats, error codes |
| [API Usage Guide](docs/api-usage-guide.md) | Integration walkthrough: auth, batches, error handling, quotas, CORS |
| [Self-Hosting](docs/self-hosting.md) | Docker, production deployment, reverse proxy, SSL |
| [Security Overview](docs/security-overview.md) | Defensive transparency: auth, validation, headers, known limits |
| [Release Signing](docs/release-signing.md) | How to verify release tags and container images |
| [Formats](docs/formats.md) | All supported formats with use cases and notes |
| [Development](docs/development.md) | Add converters, run tests, project structure |
| [Contributing](CONTRIBUTING.md) | How to contribute to FileMorph |

For **procurement reviewers and DPOs** evaluating the Compliance Edition:
[`COMMERCIAL-LICENSE.md`](COMMERCIAL-LICENSE.md) (dual-license model, tiers,
licensing-vs-AGPL boundary) and
[`docs/dpa-template.md`](docs/dpa-template.md) (Article 28 GDPR DPA
skeleton) are the canonical entry points — both link out to the supporting
artefacts: [`docs/dpa-tom-annex.md`](docs/dpa-tom-annex.md) (Art. 32 TOMs),
[`docs/records-of-processing-template.md`](docs/records-of-processing-template.md)
(Art. 30 RoPA), [`docs/sub-processors.md`](docs/sub-processors.md),
[`docs/threat-model.md`](docs/threat-model.md),
[`docs/patch-policy.md`](docs/patch-policy.md),
[`docs/incident-response.md`](docs/incident-response.md),
[`docs/support-sla.md`](docs/support-sla.md),
[`docs/onboarding.md`](docs/onboarding.md),
[`docs/third-party-licenses.md`](docs/third-party-licenses.md), and the
signature-ready
[`docs/commercial-license-agreement-template.md`](docs/commercial-license-agreement-template.md).

---

## Use Cases

- **End users** — Convert iPhone photos (HEIC) to JPG, compress images before emailing, turn Word documents into PDFs
- **Organizations** — Integrate the API into document management systems, portals, or upload pipelines (DSGVO-compliant when self-hosted)
- **Developers** — Add format conversion to any app without implementing conversion logic

---

## System Requirements

| Method | Requirements |
|---|---|
| Docker (Option A or B) | Docker Desktop (Windows/macOS) or `docker` + `docker compose` (Linux) |
| Local dev (`dev.ps1`) | Python 3.11+, Git; GTK/Pango for WeasyPrint (DOCX/Markdown/HTML/EML → PDF), Ghostscript (PDF/A-2b) — see [installation](docs/installation.md) |
| Linux source | Python 3.11+, ffmpeg, Cairo/Pango, Ghostscript (PDF/A-2b); libheif comes with the `pillow-heif` wheel |

> **ffmpeg note:** Required for audio and video conversion. Not needed for images, documents, or spreadsheets. The Docker images include ffmpeg automatically.

---

## License

FileMorph is dual-licensed:

- **[AGPL-3.0](LICENSE)** — free for personal use, academic use, internal company use, and open-source projects. If you host a modified version as a public network service, you must publish the source of your modifications.
- **[Commercial License](COMMERCIAL-LICENSE.md)** — for closed-source SaaS, OEM / white-label, or any deployment that cannot meet the AGPL copyleft obligations. Contact **licensing@filemorph.io**.

One exception: everything under [`app/ee/`](app/ee/README.md) (the PII-redaction
add-on) is licensed **only** under the Commercial License. Its source is
published for review, but it is not AGPL and not open source.
