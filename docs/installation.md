# Installation Guide

This guide covers all installation methods for FileMorph on **Windows** and **Linux**.

---

## Method 1: Standalone App — Windows (recommended for end users)

**Zero dependencies. Nothing to install. Just download and run.**

1. Go to [github.com/MrChengLen/FileMorph/releases/latest](https://github.com/MrChengLen/FileMorph/releases/latest)
2. Download `FileMorph-Windows.zip`
3. Extract the ZIP anywhere
4. Double-click **`start.bat`**

On first start, your API key is displayed in the terminal — save it.
The browser opens automatically at **http://localhost:8000**.

> Bundled inside: Python 3.12, ffmpeg, and all libraries. No installation needed.

---

## Method 2: Local development — Windows (`dev.ps1`)

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

## Method 3: Docker (recommended for production and self-hosting)

Docker bundles all system dependencies (Python, ffmpeg, libheif) in one container.

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)

### Step 1 — Clone the repository

```bash
git clone https://github.com/MrChengLen/FileMorph.git
cd FileMorph
```

### Step 2 — Start

**Windows** — double-click `start.bat`
**Linux / macOS** — run `./start.sh`

Both scripts:
1. Build the Docker image (first time: 2–5 minutes)
2. Wait until the health check passes
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

## Method 4: Local Python — Linux (Ubuntu / Debian)

### Step 1 — Install system dependencies

```bash
sudo apt update
sudo apt install -y \
  python3.11 python3.11-venv python3-pip \
  ffmpeg \
  libheif-dev \
  libcairo2 libpangocairo-1.0-0 libgdk-pixbuf2.0-0
```

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

- **Windows:** `winget install ffmpeg` — restart PowerShell after
- **Linux:** `sudo apt install ffmpeg`
- **Standalone .exe:** ffmpeg is already bundled — no action needed

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
