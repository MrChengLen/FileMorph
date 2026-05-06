# Installation Guide

This guide covers all installation methods for FileMorph on **Windows** and **Linux**.

The default mode is **Community Edition** — single-container, anonymous + API-key
auth, no database. The optional **Cloud Edition** overlay adds Postgres for user
accounts, JWT login, Stripe billing, and the admin cockpit.

---

## Method 1: Docker, Community Edition (recommended for self-hosting)

Docker bundles all system dependencies (Python, ffmpeg, libheif, ghostscript) in
one container. No accounts, no database — API keys live in `./data/api_keys.json`.

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Windows / macOS), or
- `docker` + `docker compose` v2 (Linux)

### Step 1 — Clone

```bash
git clone https://github.com/MrChengLen/FileMorph.git
cd FileMorph
```

### Step 2 — Start

**Windows** — double-click `start.bat`
**Linux / macOS** — run `./start.sh`

Both scripts:
1. Build the Docker image (first time: 2–5 minutes)
2. Wait until the healthcheck passes
3. Display your API key from the container logs
4. Open the browser at **http://localhost:8000**

### Manual start (without the launcher scripts)

```bash
docker compose up -d
docker compose logs --tail=30 filemorph   # shows API key on first run
```

### Stopping and starting

```bash
docker compose stop      # stop containers (keeps API keys)
docker compose start     # start again
docker compose down      # stop and remove containers (keys in ./data are preserved)
```

### Updating

```bash
git pull
docker compose build
docker compose up -d
```

---

## Method 2: Docker, Cloud Edition (user accounts + Stripe + cockpit)

The Cloud-Edition features (registration, JWT login, billing, admin cockpit,
audit log, daily metrics) need a Postgres database. The codebase ships a
Cloud overlay (`docker-compose.cloud.yml`) that adds the Postgres service
and switches the app into Cloud mode. The entrypoint runs
`alembic upgrade head` automatically on every Cloud-mode start.

### Step 1 — Configure secrets

```bash
cp .env.example .env
```

Then edit `.env` and set:

- `POSTGRES_PASSWORD` — a strong random string
- `JWT_SECRET` — at least 32 random characters

Optional but recommended for production:

- `CORS_ORIGINS` — your public origin(s) the browser is allowed to call from
- `APP_BASE_URL` — your public URL (used in email links and OG tags)
- `STRIPE_*` envs — if you want billing
- `SMTP_*` envs — if you want password-reset / email-verification flows

`.env.example` documents every supported variable with a one-line description.

### Step 2 — Start

```bash
docker compose -f docker-compose.yml -f docker-compose.cloud.yml up -d
```

The first boot:
1. Brings up the Postgres container and waits for the healthcheck
2. Builds the FileMorph image
3. Runs `alembic upgrade head` (creates all tables)
4. Generates the legacy single-user API key (still printed for backwards-compat)
5. Starts uvicorn

The Web UI at **http://localhost:8000** now exposes `/register`, `/login`,
`/dashboard`, and (for promoted admin users) `/cockpit`.

### Stopping the Cloud-mode stack

```bash
docker compose -f docker-compose.yml -f docker-compose.cloud.yml down
```

Add `-v` to also remove the `postgres_data` volume — destructive, deletes all
accounts and audit-log rows.

---

## Method 3: Local development — Windows (`dev.ps1`)

The easiest way to run FileMorph from source on Windows.
`dev.ps1` automates all setup steps and starts the server with live-reload.

### Prerequisites

- Python 3.11 or newer — [python.org](https://www.python.org/downloads/)
- Git — [git-scm.com](https://git-scm.com/)

> **Note on Python PATH:** `dev.ps1` automatically searches the Windows Registry for
> Python installations, so it works even if Python is not in your system PATH.
> This covers Anaconda, Miniconda, and non-standard install locations.

### Step 1 — Clone the repository

```powershell
git clone https://github.com/MrChengLen/FileMorph.git
cd FileMorph
```

### Step 2 — Start the server

```powershell
.\dev.ps1
```

On first run, `dev.ps1` automatically:

| Step | What happens |
|------|-------------|
| 1/4 | Creates `.venv` virtual environment |
| 2/4 | Installs all dependencies from `requirements.txt` |
| 3/4 | Copies `.env.example` to `.env` |
| 4/4 | Generates your API key (shown once — save it) |
| Done | Starts uvicorn at `http://127.0.0.1:8000` with `--reload` |

On subsequent starts, all setup steps are skipped. The server starts in seconds,
with no internet connection required.

### Optional — Desktop shortcut

```powershell
.\create-shortcut.ps1
```

Places a `FileMorph` shortcut on your Desktop. Double-clicking it starts the server
without opening a terminal manually. The window stays open so you can see server logs
and any errors.

### Stopping the server

Press `Ctrl+C` in the PowerShell window. This stops only the server process.
All installed packages, configuration, and API keys are preserved on disk.

### Updating FileMorph

```powershell
git pull
.\dev.ps1   # re-runs pip install to pick up any new dependencies
```

---

## Method 4: Local Python — Linux (Ubuntu / Debian)

### Step 1 — Install system dependencies

```bash
sudo apt update
sudo apt install -y \
  python3.11 python3.11-venv python3-pip \
  ffmpeg \
  ghostscript \
  libheif-dev \
  libcairo2 libpangocairo-1.0-0 libgdk-pixbuf2.0-0
```

> `ghostscript` is optional but enables full PDF/A-2b conformance. Without it,
> `pdf → pdfa` falls back to markup-only output. See
> [docs/self-hosting.md](self-hosting.md) for the trade-off.

### Step 2 — Clone and set up

```bash
git clone https://github.com/MrChengLen/FileMorph.git
cd FileMorph

python3.11 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env
python scripts/generate_api_key.py

uvicorn app.main:app --reload
```

Open **http://localhost:8000**.

---

## Verifying the installation

```bash
curl http://localhost:8000/api/v1/health
```

Expected response:
```json
{
  "status": "ok",
  "version": "1.0.0",
  "ffmpeg_available": true
}
```

If `ffmpeg_available` is `false`, ffmpeg is not on your PATH — video and audio conversion
will not work, but all other formats are unaffected.

---

## Troubleshooting

### "Python not found" when running `dev.ps1`

`dev.ps1` searches the Windows Registry for Python installations. If it still fails:

1. Install Python from [python.org](https://www.python.org/downloads/) — check **"Add Python to PATH"**
2. Restart PowerShell and try again

### "ffmpeg not found" warning in the server log

Audio and video conversion will not work until ffmpeg is installed.

- **Windows (dev.ps1):** `winget install ffmpeg` — restart PowerShell after
- **Linux:** `sudo apt install ffmpeg`
- **Docker:** ffmpeg is bundled in the image — no action needed

### Cloud-mode 500s on `/auth/register` after `docker compose up`

You started the default community-mode compose, which has no Postgres.
Either use the community-mode flow (no accounts), or layer the Cloud
overlay: `docker compose -f docker-compose.yml -f docker-compose.cloud.yml up -d`.

### pip times out during installation

On a slow connection, increase the timeout:

```powershell
.venv\Scripts\pip.exe install -r requirements.txt --timeout 120 --retries 5
```

`dev.ps1` already applies these settings automatically.

### Port 8000 already in use

Change the port in `.env`:

```env
APP_PORT=8080
```

Then restart the server.

### "ModuleNotFoundError: No module named 'pillow_heif'"

```bash
pip install pillow-heif
```

On Linux, also install: `sudo apt install libheif-dev`

### "DOCX to PDF conversion failed" (Linux)

On Linux, DOCX → PDF requires LibreOffice:

```bash
sudo apt install libreoffice
```

### Permission denied on `data/api_keys.json` (Linux)

```bash
chmod 600 data/api_keys.json
```
