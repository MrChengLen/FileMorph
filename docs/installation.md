# Installation Guide

This guide covers all installation methods for FileMorph on **Windows** and **Linux**.

The default mode is **Community Edition** — single-container, anonymous + API-key
auth, no database. The optional **Cloud Edition** overlay adds Postgres for user
accounts, JWT login, Stripe billing, and the admin cockpit.

Without accounts, every caller gets the anonymous limits — 30 MB per file,
1 file per batch — API keys included, unless you give your keys a bigger tier
with `API_KEYS_FILE_TIER` (see
[Limits on a Community Edition instance](self-hosting.md#limits-on-a-community-edition-instance)).

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
- `JWT_SECRET` — at least 32 random characters, e.g. from
  `python -c "import secrets; print(secrets.token_urlsafe(32))"`; uncomment
  its line in `.env`. Without it `docker compose` stops with an error, and the
  app refuses to start with a shorter secret or one of the placeholders
  published in this repository (see
  [`docs/self-hosting.md`](self-hosting.md#jwt-secret-cloud-edition))

Optional but recommended for production:

- `CORS_ORIGINS` — your public origin(s) the browser is allowed to call from
- `APP_BASE_URL` — your public URL (used in email links and OG tags)
- `STRIPE_*` envs — if you want billing
- `SMTP_*` envs — if you want password-reset / email-verification flows
  (see [`docs/email-setup.md`](email-setup.md) for a step-by-step walkthrough)

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

`dev.ps1` automates four steps on every start, then launches the server:

| Step | What happens |
|------|-------------|
| 1/4 | Creates `.venv` virtual environment (skipped once it exists) |
| 2/4 | Installs / verifies dependencies from `requirements.txt` |
| 3/4 | Copies `.env.example` to `.env` (skipped once `.env` exists) |
| 4/4 | Generates your API key (skipped once one exists — shown once, save it) |
| Done | Starts uvicorn at `http://127.0.0.1:8000` with `--reload` |

Steps 1, 3 and 4 are skipped once their target already exists, so a repeat
start is fast — but step 2 runs `pip install` **every time**, not just on
first run, so a `git pull` that added a dependency is picked up
automatically. That means every start needs network access to reach the
package index, even when nothing actually changed (a no-op check, but
not an offline one).

### Optional — Desktop shortcut

```powershell
.\create-shortcut.ps1
```

Places a `FileMorph` shortcut on your Desktop. Double-clicking it starts the server
without opening a terminal manually. The window stays open so you can see server logs
and any errors.

### Optional — PDF rendering support (WeasyPrint, Ghostscript)

DOCX, Markdown, HTML and EML → PDF render through WeasyPrint, which needs
the Pango/GTK native libraries; TXT → PDF does not (it uses `reportlab`,
pure Python, no extra install). On Windows, the pinned WeasyPrint version
(`weasyprint>=69.0,<70`) looks for those libraries in
`C:\msys64\mingw64\bin` or `C:\Program Files\GTK3-Runtime Win64\bin` by
default (override with the `WEASYPRINT_DLL_DIRECTORIES` env var, `;`-separated) —
install either an MSYS2 `mingw64` environment with Pango, or the standalone
GTK3 Runtime Win64 installer. Full steps:
[doc.courtbouillon.org/weasyprint/stable/first_steps.html#installation](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#installation).
Without it, those four conversions fail at request time; everything else
(images, audio, video, spreadsheets, TXT → PDF) is unaffected.

`pdf → pdfa` (full PDF/A-2b conformance) needs Ghostscript on PATH —
install it from [ghostscript.com](https://www.ghostscript.com/releases/)
and make sure its `bin` folder (containing `gswin64c.exe`) is on PATH.
Without it, `pdf → pdfa` still works but falls back to a markup-only
output that veraPDF rejects if the source has unembedded fonts — same
trade-off as the Docker image, see
[`docs/self-hosting.md`](self-hosting.md#pdfa-2b-conformance-optional-ghostscript).

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
  python3 python3-venv python3-pip \
  ffmpeg \
  ghostscript \
  libcairo2 libpangocairo-1.0-0 libgdk-pixbuf2.0-0
python3 --version   # must be 3.11 or newer
```

HEIC input needs no system package: the `pillow-heif` wheel that pip installs
in Step 2 bundles its own libheif. Only on a platform without such a wheel does
pip compile it, and then it needs libheif 1.23.4 or newer (the minimum of the
pillow-heif version FileMorph pins; later releases can raise it) — see the
HEIC note in [formats.md](formats.md).

`python3.11` as a specific apt package name is a moving target — current
Ubuntu (24.04+) and Debian (13+) ship a newer default `python3` (3.12 /
3.13) and no longer carry a `python3.11` package at all, so pinning that
exact name in the install command fails on a fresh system. Use the
distro's own `python3` and confirm the version is ≥ 3.11; if your distro's
default is older, add the [deadsnakes PPA](https://launchpad.net/~deadsnakes/+archive/ubuntu/ppa)
(Ubuntu) or use `pyenv` instead of chasing a specific apt package name.

> `ghostscript` is optional but enables full PDF/A-2b conformance. Without it,
> `pdf → pdfa` falls back to markup-only output. See
> [docs/self-hosting.md](self-hosting.md) for the trade-off.

### Step 2 — Clone and set up

```bash
git clone https://github.com/MrChengLen/FileMorph.git
cd FileMorph

python3 -m venv .venv
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
{"status": "ok"}
```

`/api/v1/health` is the unauthenticated liveness probe — minimal by design so it
discloses no version or codec details. `GET /api/v1/ready` reports whether the app
can actually serve traffic: the database (Cloud Edition; reported `skipped` when
none is configured) and the tempdir are writable. It does **not** check ffmpeg —
if ffmpeg is missing, `/ready` still reports healthy, and the only signal is a
`ffmpeg not found on PATH` line in the startup log (video/audio conversion then
fails at request time instead).

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

### Cloud-mode 503s (`Database not configured.`) on `/auth/register`

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

`APP_PORT` in `.env` is read only by `run.py` (the PyInstaller / direct
`python run.py` entry point) — it does **not** change the port for the
other three installation methods, which all hardcode `8000`:

- **Docker** (Methods 1 and 2): the container always listens on `8000`
  internally (`entrypoint.sh`). Change the **host** side of the port
  mapping in `docker-compose.yml` instead — e.g. `"8080:8000"` — and
  reach the app at `http://localhost:8080`.
- **`dev.ps1`** (Method 3): also starts uvicorn on a hardcoded `8000`.
  Edit the `--port 8000` argument in `dev.ps1` itself if you need a
  different port.
- **Manual `uvicorn app.main:app`** (Method 4): pass `--port 8080` on
  the command line; `APP_PORT` has no effect here either since
  `uvicorn`'s CLI flags take precedence over anything in `.env`.
- **`python run.py`**: this is the one path that honours `APP_PORT` —
  set it in `.env` and restart.

### "ModuleNotFoundError: No module named 'pillow_heif'"

```bash
pip install pillow-heif
```

On 64-bit x86 and ARM (Linux, macOS, Windows) that is all: the wheel bundles
libheif. If pip has to compile `pillow-heif` instead (no wheel for your
platform), it needs libheif 1.23.4 or newer (for the pillow-heif version
FileMorph pins; later releases can raise it) — see the HEIC note in
[formats.md](formats.md).

### Permission denied on `data/api_keys.json` (Linux)

Usually a UID mismatch on the bind-mounted `./data` directory: the
Docker image runs as a non-root `appuser` (a system user whose UID the
Dockerfile does not pin, typically 999), so if the host
`./data` directory is owned by root or by your own user account, the
container can't create or update files inside it. Look up the UID and GID the container actually runs as,
then give `./data` to them:

```bash
docker compose run --rm --entrypoint id filemorph
# prints e.g. uid=999(appuser) gid=999(appuser) groups=999(appuser)

sudo chown -R <uid>:<gid> ./data    # the two numbers from that line
docker compose restart filemorph
```

If the container is already running, `docker compose exec filemorph id`
prints the same line.

Running outside Docker (Method 4), the file is owned by whoever
generated it — `chmod 600 data/api_keys.json` restricts it to that
user if it was created with looser permissions.
