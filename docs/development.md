# Development Guide

This guide covers the project architecture, how to run tests, add new converters, and contribute code.

---

## Project structure

```
filemorph/
├── app/
│   ├── main.py                  # FastAPI app: middleware, routers, UI route
│   ├── compat.py                # Frozen (.exe) vs. source detection + path helpers
│   ├── api/
│   │   ├── deps.py              # API-Key authentication dependency
│   │   └── routes/
│   │       ├── convert.py       # POST /api/v1/convert
│   │       ├── compress.py      # POST /api/v1/compress
│   │       ├── formats.py       # GET  /api/v1/formats
│   │       └── health.py        # GET  /api/v1/health
│   ├── core/
│   │   ├── config.py            # Settings loaded from .env via pydantic-settings
│   │   └── security.py          # API key generation, hashing, validation
│   ├── converters/
│   │   ├── base.py              # AbstractConverter base class
│   │   ├── registry.py          # Converter registry (@register decorator)
│   │   ├── image.py             # Image conversions (Pillow + pillow-heif)
│   │   ├── document.py          # Document conversions (docx, pdf, txt, md)
│   │   ├── video.py             # Video conversions (ffmpeg-python)
│   │   ├── audio.py             # Audio conversions (ffmpeg-python)
│   │   └── spreadsheet.py       # Spreadsheet conversions (openpyxl, csv, json)
│   ├── compressors/
│   │   ├── image.py             # Image quality compression (Pillow)
│   │   └── video.py             # Video CRF compression (ffmpeg)
│   ├── models/
│   │   └── schemas.py           # Pydantic response schemas
│   ├── static/                  # CSS and JavaScript
│   └── templates/               # Jinja2 HTML templates
├── tests/
├── scripts/
│   ├── generate_api_key.py      # CLI key generator
│   └── first_run.py             # Called by Docker entrypoint on first start
├── data/
│   └── api_keys.json            # Hashed API keys (gitignored)
├── run.py                       # Entry point for PyInstaller .exe and direct Python
├── filemorph.spec               # PyInstaller build spec (bundles Python + ffmpeg)
├── dev.ps1                      # Windows developer startup script (auto-setup + server)
├── create-shortcut.ps1          # Creates a Desktop shortcut for dev.ps1
├── start.bat                    # Windows launcher: .exe mode or Docker mode
├── start.sh                     # Linux/macOS launcher: Docker mode
├── entrypoint.sh                # Docker container entrypoint (first-run key setup)
└── docker-compose.yml
```

---

## Development setup

### Windows (recommended — one command)

```powershell
git clone https://github.com/MrChengLen/FileMorph.git
cd FileMorph
.\dev.ps1
```

`dev.ps1` creates the virtual environment, installs dependencies, generates an API key on
first run, and starts uvicorn with `--reload`. Code changes are picked up automatically
without restarting the server.

### Linux / macOS

```bash
git clone https://github.com/MrChengLen/FileMorph.git
cd FileMorph

python3.11 -m venv .venv
source .venv/bin/activate

pip install -r requirements-dev.txt
cp .env.example .env
python scripts/generate_api_key.py

uvicorn app.main:app --reload
```

### Live reload

With `--reload`, uvicorn watches `Z:\Python\projects\filemorph` for file changes and
restarts the server process automatically. No manual restart needed when editing Python files.

---

## Running tests

```bash
pytest tests/ -v
```

Run a single test file:
```bash
pytest tests/test_convert_image.py -v
```

Run with coverage:
```bash
pytest tests/ --cov=app --cov-report=term-missing
```

---

## Linting and formatting

FileMorph uses [ruff](https://docs.astral.sh/ruff/) for both linting and formatting.

```bash
# Check for issues
ruff check .

# Auto-fix fixable issues
ruff check --fix .

# Format code
ruff format .
```

CI will fail if either check fails — run both before pushing.

---

## How the converter registry works

The registry maps `(source_format, target_format)` pairs to converter classes.
Converters register themselves using the `@register` decorator:

```python
# app/converters/registry.py
from app.converters.registry import register
from app.converters.base import BaseConverter

@register(("txt", "pdf"))
class TxtToPdfConverter(BaseConverter):
    def convert(self, input_path: Path, output_path: Path, **kwargs) -> Path:
        # ... conversion logic ...
        return output_path
```

The `register` decorator accepts one or more `(src, tgt)` tuples:

```python
@register(("heic", "jpg"), ("heif", "jpg"))
class HeicToJpgConverter(BaseConverter):
    ...
```

The `_ensure_loaded()` function in `registry.py` imports all converter modules at startup
so their `@register` decorators run. Add new modules to `_ensure_loaded()` when creating
a new converter file.

> **Note:** the AI / PII-redaction feature under `app/ee/` is **not** a registry
> converter. It is commercial-licensed (`LicenseRef-FileMorph-Commercial`), lives
> outside the `@register` plugin model, is lazy-imported only by the gated
> `app/api/routes/ai.py`, and is inert unless `AI_OPERATIONS_ENABLED` is set —
> don't try to `@register` a redaction "format". See `docs/pii-redaction.md`.

---

## Adding a new converter

### Step 1 — Create or open the relevant converter file

Choose the appropriate file based on the category:
- `app/converters/image.py` — images
- `app/converters/document.py` — documents
- `app/converters/video.py` — video
- `app/converters/audio.py` — audio
- `app/converters/spreadsheet.py` — data files

For a completely new category, create a new file.

### Step 2 — Implement the converter

```python
# Example: adding EPUB → TXT support in a new app/converters/ebook.py

from pathlib import Path
from app.converters.base import BaseConverter
from app.converters.registry import register


@register(("epub", "txt"))
class EpubToTxtConverter(BaseConverter):
    def convert(self, input_path: Path, output_path: Path, **kwargs) -> Path:
        import ebooklib
        from ebooklib import epub
        from bs4 import BeautifulSoup

        book = epub.read_epub(str(input_path))
        texts = []
        for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
            soup = BeautifulSoup(item.get_content(), "html.parser")
            texts.append(soup.get_text())

        output_path.write_text("\n\n".join(texts), encoding="utf-8")
        return output_path
```

### Step 3 — Register the module in `_ensure_loaded()`

Open `app/converters/registry.py` and add the import:

```python
def _ensure_loaded() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    import app.converters.audio       # noqa: F401
    import app.converters.document    # noqa: F401
    import app.converters.ebook       # noqa: F401  ← add this
    import app.converters.image       # noqa: F401
    import app.converters.spreadsheet # noqa: F401
    import app.converters.video       # noqa: F401
```

### Step 4 — Add dependencies

Add any new Python packages to `requirements.txt`. Add system-level dependencies to `Dockerfile`.

### Step 5 — Write tests

```python
# tests/test_convert_ebook.py

def test_epub_to_txt(client, auth_headers, tmp_path):
    # Create a minimal EPUB for testing
    epub_path = tmp_path / "sample.epub"
    # ... create test epub ...

    with epub_path.open("rb") as f:
        res = client.post(
            "/api/v1/convert",
            headers=auth_headers,
            files={"file": ("sample.epub", f, "application/epub+zip")},
            data={"target_format": "txt"},
        )
    assert res.status_code == 200
    assert len(res.content) > 0
```

### Step 6 — Update format documentation

Add the new format to [docs/formats.md](formats.md).

---

## Adding a new compressor

Compressors live in `app/compressors/`. Each compressor is a plain function (not a class):

```python
# app/compressors/image.py (existing)

def compress_image(input_path: Path, output_path: Path, quality: int = 85) -> Path:
    ...
```

Add the new format to the `_SUPPORTED_FORMATS` list in the relevant compressor file,
and import + call it from `app/api/routes/compress.py`.

---

## API key internals

Key lifecycle:
1. `secrets.token_urlsafe(32)` generates a 256-bit random key
2. `hashlib.sha256(key.encode()).hexdigest()` produces the stored hash
3. On each request, the submitted key is hashed and compared against stored hashes
4. Plaintext keys never touch disk

All logic is in `app/core/security.py`.

---

## Environment variables reference

Defined in `app/core/config.py` using pydantic-settings:

```python
class Settings(BaseSettings):
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_debug: bool = False
    app_version: str = "1.0.0"
    api_keys_file: str = "data/api_keys.json"
    max_upload_size_mb: int = 100
    cors_origins: str = "*"
```

All settings can be overridden via environment variables or `.env` (uppercase, same names):
`APP_HOST`, `APP_PORT`, `APP_DEBUG`, `API_KEYS_FILE`, `MAX_UPLOAD_SIZE_MB`, `CORS_ORIGINS`

---

## Making a release

`main` is branch-protected, so the version bump goes through a PR; the
**signed** tag is cut afterwards on the merged commit. Release tags must be
GPG-signed — `.github/workflows/release.yml` rejects unsigned tags (fail-closed),
and only keys listed in [`release-signing.md`](release-signing.md) verify.

1. On a branch, bump the version in `pyproject.toml` and `app/core/config.py`
   (e.g. `1.1.0.dev0` → `1.1.0`), and roll `## [Unreleased]` in `CHANGELOG.md`
   into `## [X.Y.Z] — <date>` with a fresh empty `[Unreleased]` above it.
2. Open a PR, let CI go green, and merge it to `main`.
3. Cut the **signed** tag on the merged commit. On Windows do this in **Git Bash**
   (the GPG agent isn't reachable from PowerShell):
   ```bash
   git checkout main && git pull origin main
   git tag -s vX.Y.Z -m "release vX.Y.Z"   # prompts for the GPG passphrase
   git verify-tag vX.Y.Z                     # must print "Good signature"
   git push origin vX.Y.Z
   ```

The tag push triggers `release.yml` (verifies the signature, publishes the
GitHub Release with a source tarball + `IMAGE_DIGEST.txt`), `docker.yml`
(builds + cosign-signs the slim and office images to GHCR) and `sbom.yml`
(attaches the CycloneDX SBOM). See [`release-signing.md`](release-signing.md)
for key setup/rotation and `docs/patch-policy.md` for the versioning rules.
