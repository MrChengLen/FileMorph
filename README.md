# FileMorph

> **File conversion and compression — Web UI + REST API**

Convert between image, document, audio, video, and spreadsheet formats.
Compress files by quality. Self-hostable via Docker. Integrable by any service via REST API.

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
│  FileMorph                                  API Docs →  │
├─────────────────────────────────────────────────────────┤
│                                                         │
│              Convert & Compress Files                   │
│       Images · Documents · Audio · Video · Sheets       │
│                                                         │
│            [ Convert ]  [ Compress ]                    │
│                                                         │
│     ┌─────────────────────────────────────────┐         │
│     │              ⬆                          │         │
│     │     Drag & drop your files here         │         │
│     │   or click to browse  (multi-file)      │         │
│     │                                         │         │
│     │  HEIC · JPG · PNG · WebP · BMP · TIFF   │         │
│     │  GIF · DOCX · PDF · TXT · MD · XLSX     │         │
│     │  CSV · JSON · MP4 · MOV · AVI · MKV     │         │
│     │  WebM · MP3 · WAV · FLAC · OGG · M4A    │         │
│     └─────────────────────────────────────────┘         │
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

## Supported Formats

| Category      | Input formats                                                   | Output formats                                |
|---------------|------------------------------------------------------------------|-----------------------------------------------|
| **Images**    | HEIC, HEIF, JPG, JPEG, PNG, WebP, BMP, TIFF, GIF, ICO           | JPG, PNG, WebP, BMP, TIFF, GIF, ICO           |
| **Documents** | DOCX, TXT, Markdown (`.md`)                                      | PDF, TXT, HTML                                |
| **PDF**       | PDF                                                              | TXT, PDF/A-2b<sup>†</sup>                     |
| **Spreadsheets** | XLSX, CSV, JSON                                               | CSV, XLSX, JSON                               |
| **Audio**     | MP3, WAV, FLAC, OGG, M4A, AAC, WMA, Opus                        | MP3, WAV, FLAC, OGG, M4A, AAC, WMA, Opus     |
| **Video**     | MP4, MOV, AVI, MKV, WebM, FLV, WMV                              | MP4, MOV, AVI, MKV, WebM, FLV, WMV           |

**Compression** (quality-based or target-size, no re-encoding format change):
Images: JPG, PNG, WebP, TIFF · Video: MP4, MOV, AVI, MKV, WebM
Compress mode supports both *by quality %* and *by target size MB*.

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

Stop:

```bash
docker compose -f docker-compose.yml -f docker-compose.cloud.yml down
```

### Option C — Local development (Windows)

> Requires Python 3.11+ and Git. No Docker needed.

```powershell
git clone https://github.com/MrChengLen/FileMorph.git
cd FileMorph
.\dev.ps1
```

`dev.ps1` handles everything automatically on first run: creates the
virtual environment, installs dependencies, generates your API key,
and starts the server with live-reload at **http://127.0.0.1:8000**.
Subsequent starts skip all setup steps and launch in seconds.

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
| [Self-Hosting](docs/self-hosting.md) | Docker, production deployment, reverse proxy, SSL |
| [Security Overview](docs/security-overview.md) | Defensive transparency: auth, validation, headers, known limits |
| [Formats](docs/formats.md) | All supported formats with use cases and notes |
| [Development](docs/development.md) | Add converters, run tests, project structure |
| [Contributing](CONTRIBUTING.md) | How to contribute to FileMorph |

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
| Local dev (`dev.ps1`) | Python 3.11+, Git |
| Linux source | Python 3.11+, ffmpeg, libheif, libcairo |

> **ffmpeg note:** Required for audio and video conversion. Not needed for images, documents, or spreadsheets. The Docker images include ffmpeg automatically.

---

## License

FileMorph is dual-licensed:

- **[AGPL-3.0](LICENSE)** — free for personal use, academic use, internal company use, and open-source projects. If you host a modified version as a public network service, you must publish the source of your modifications.
- **[Commercial License](COMMERCIAL-LICENSE.md)** — for closed-source SaaS, OEM / white-label, or any deployment that cannot meet the AGPL copyleft obligations. Contact **licensing@filemorph.io**.
