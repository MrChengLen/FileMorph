# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for FileMorph.

Bundles:
  - Python 3.12 runtime
  - All pip packages (FastAPI, Pillow, uvicorn, pydub, ffmpeg-python, ...)
  - ffmpeg binary (downloaded by the build workflow, placed at ./ffmpeg/)
  - HTML templates and static files
  - Scripts needed at runtime

Output: dist/FileMorph/ folder → zipped to FileMorph-Windows.zip by CI
"""

import sys
from pathlib import Path

SRC = Path(SPECPATH)

block_cipher = None

a = Analysis(
    [str(SRC / "run.py")],
    pathex=[str(SRC)],
    binaries=[
        # ffmpeg binary downloaded by the build script into ./ffmpeg/
        (str(SRC / "ffmpeg" / "ffmpeg.exe"), "ffmpeg"),
        (str(SRC / "ffmpeg" / "ffprobe.exe"), "ffmpeg"),
    ],
    datas=[
        # Templates and static assets
        (str(SRC / "app" / "templates"), "app/templates"),
        (str(SRC / "app" / "static"), "app/static"),
        # Scripts needed at runtime (first_run.py, generate_api_key.py)
        (str(SRC / "scripts"), "scripts"),
    ],
    hiddenimports=[
        # FastAPI / Starlette
        "starlette.routing",
        "starlette.middleware",
        "starlette.middleware.cors",
        "starlette.staticfiles",
        "starlette.templating",
        # uvicorn
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        # Converters (loaded dynamically via registry)
        "app.converters.image",
        "app.converters.document",
        "app.converters.video",
        "app.converters.audio",
        "app.converters.spreadsheet",
        # Pillow format plugins
        "PIL.JpegImagePlugin",
        "PIL.PngImagePlugin",
        "PIL.WebPImagePlugin",
        "PIL.BmpImagePlugin",
        "PIL.TiffImagePlugin",
        "PIL.GifImagePlugin",
        "PIL.IcoImagePlugin",
        # pillow-heif
        "pillow_heif",
        # pydantic
        "pydantic.deprecated.class_validators",
        "pydantic_settings",
        # slowapi
        "slowapi",
        "slowapi.util",
        "slowapi.errors",
        # Other
        "weasyprint",
        "markdown",
        "openpyxl",
        "docx",
        "pypdf",
        "reportlab",
        "pydub",
        "ffmpeg",
        "multipart",
        "jinja2",
        "anyio",
        "anyio._backends._asyncio",
        "anyio._backends._trio",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "scipy", "numpy", "pandas", "pytest"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FileMorph",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,   # Show terminal window (needed to display API key on first run)
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="FileMorph",
)
