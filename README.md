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
┌─────────────────────────────────────────────────────┐
│  FileMorph                              API Docs →   │
├─────────────────────────────────────────────────────┤
│                                                     │
│          [ Convert ]  [ Compress ]                  │
│                                                     │
│   ┌─────────────────────────────────────────┐       │
│   │                                         │       │
│   │    Drop your file here, or click        │       │
│   │    to browse                            │       │
│   │                                         │       │
│   │  Supported: HEIC · JPG · PNG · WebP     │       │
│   │  DOCX · PDF · XLSX · CSV · JSON         │       │
│   │  MP4 · MOV · MP3 · WAV · FLAC          │       │
│   └─────────────────────────────────────────┘       │
│                                                     │
│   Target format:  [ JPG          ▼ ]                │
│   Quality:        ████████░░  85%                   │
│   API Key:        ••••••••••••••••••••              │
│                                                     │
│              [ Convert ]                            │
│                                                     │
└─────────────────────────────────────────────────────┘
```

---

## Editions

FileMorph runs in three editions, all built from this repository:

| Edition | Where | What you get |
|---|---|---|
| **Community** | Self-hosted (Docker, standalone `.exe`, source) | File conversion + compression, REST API, single-user API-key auth |
| **Cloud SaaS** | [filemorph.io](https://filemorph.io) | Community features + user accounts (JWT), tier quotas, Stripe billing, admin cockpit |
| **Compliance** | Self-hosted with commercial licence | Cloud-Edition features + tamper-evident audit log (SHA-256 hash chain), `X-Output-SHA256` integrity header, PDF/A-2b output (veraPDF-validated), default-on EXIF/XMP/IPTC strip, `X-Data-Classification` header, self-service account deletion, signed images (cosign) + signed releases (GPG). For DACH Behörden, Krankenhäuser, and Anwaltskanzleien. |

The README and `docs/` are written for the **Community** edition. The
Cloud-Edition features (account registration, Stripe checkout, admin
cockpit, email verification, account deletion) ship in the same codebase
but stay dormant unless you provide a Postgres instance, Stripe API keys,
and SMTP — see [docs/self-hosting.md](docs/self-hosting.md) for the full
stack and [docs/security-overview.md](docs/security-overview.md) for the
defensive-transparency overview. The Compliance-Edition contract +
commercial licence are described at
[`/enterprise`](https://filemorph.io/enterprise) (live on filemorph.io)
and [`COMMERCIAL-LICENSE.md`](COMMERCIAL-LICENSE.md).

---

## Supported Formats

| Category      | Input formats                                                   | Output formats                                |
|---------------|------------------------------------------------------------------|-----------------------------------------------|
| **Images**    | HEIC, HEIF, JPG, JPEG, PNG, WebP, BMP, TIFF, GIF, ICO           | JPG, PNG, WebP, BMP, TIFF, GIF, ICO           |
| **Documents** | DOCX, TXT, Markdown (`.md`)                                      | PDF, TXT, HTML                                |
| **PDF**       | PDF                                                              | TXT                                           |
| **Spreadsheets** | XLSX, CSV, JSON                                               | CSV, XLSX, JSON                               |
| **Audio**     | MP3, WAV, FLAC, OGG, M4A, AAC, WMA, Opus                        | MP3, WAV, FLAC, OGG, M4A, AAC, WMA, Opus     |
| **Video**     | MP4, MOV, AVI, MKV, WebM, FLV, WMV                              | MP4, MOV, AVI, MKV, WebM, FLV, WMV           |

**Compression** (quality-based, no re-encoding format change):
Images: JPG, PNG, WebP, TIFF · Video: MP4, MOV, AVI, MKV, WebM

---

## Quickstart

### Option A — Standalone App (recommended for end users)

**Zero dependencies. No installation. Just download and run.**

1. Download **[FileMorph-Windows.zip](https://github.com/MrChengLen/FileMorph/releases/latest)** from GitHub Releases
2. Extract the ZIP anywhere
3. Double-click **`Start FileMorph.bat`**

On first start, your API key is shown in the terminal — save it.
The browser opens automatically at **http://localhost:8000**.

> Bundled inside: Python 3.12 · ffmpeg · all libraries. Nothing to install.

### Option B — Local development (Windows, one command)

> Requires Python 3.11+ and Git. No Docker needed.

```powershell
git clone https://github.com/MrChengLen/FileMorph.git
cd FileMorph
.\dev.ps1
```

`dev.ps1` handles everything automatically on first run: creates the virtual environment,
installs dependencies, generates your API key, and starts the server with live-reload.
Subsequent starts skip all setup steps and launch in seconds — no internet required.

**Optional — Desktop shortcut (double-click to start):**

```powershell
.\create-shortcut.ps1
```

This places a `FileMorph` shortcut on your Desktop. Double-clicking it starts the server
in a PowerShell window without opening a terminal first.

### Option C — Docker (for self-hosting and production)

> Requires [Docker Desktop](https://www.docker.com/products/docker-desktop/)

```bash
git clone https://github.com/MrChengLen/FileMorph.git
cd FileMorph
```

**Windows** — double-click `start.bat`
**Linux / macOS** — run `./start.sh`

API key is generated and shown automatically on first start.

### Stop (Docker)

```bash
docker compose down
```

---

## API Usage

All conversion endpoints require the `X-API-Key` header.

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
| Standalone `.exe` | None — Python, ffmpeg, and all libraries are bundled |
| Local dev (`dev.ps1`) | Python 3.11+ (any install location), Git |
| Docker | Docker Desktop |
| Linux source | Python 3.11+, ffmpeg, libheif, libcairo |

> **ffmpeg note:** Required for audio and video conversion. Not needed for images, documents, or spreadsheets. The standalone `.exe` includes ffmpeg automatically.

---

## License

FileMorph is dual-licensed:

- **[AGPL-3.0](LICENSE)** — free for personal use, academic use, internal company use, and open-source projects. If you host a modified version as a public network service, you must publish the source of your modifications.
- **[Commercial License](COMMERCIAL-LICENSE.md)** — for closed-source SaaS, OEM / white-label, or any deployment that cannot meet the AGPL copyleft obligations. Contact **licensing@filemorph.io**.

