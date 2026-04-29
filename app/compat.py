"""
Runtime compatibility layer for PyInstaller frozen builds vs. normal Python execution.

When the app is packaged with PyInstaller:
- sys.frozen is True
- sys._MEIPASS points to the temporary extraction directory
- All bundled data files (templates, static, ffmpeg) live under sys._MEIPASS

This module centralises all path resolution so the rest of the app
does not need to care whether it is frozen or running from source.
"""

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    """Return True when running inside a PyInstaller bundle."""
    return getattr(sys, "frozen", False)


def base_dir() -> Path:
    """Root directory for bundled resources (templates, static files, etc.)."""
    if is_frozen():
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    """Directory for persistent user data (API keys).

    When frozen: %APPDATA%\\FileMorph  (survives updates / re-extractions)
    When source: ./data  (project-local, convenient for development)
    """
    if is_frozen():
        appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
        d = Path(appdata) / "FileMorph"
    else:
        d = base_dir() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def setup_ffmpeg_path() -> None:
    """Add bundled ffmpeg to PATH so pydub / ffmpeg-python can find it."""
    if is_frozen():
        ffmpeg_bin = base_dir() / "ffmpeg"
        os.environ["PATH"] = str(ffmpeg_bin) + os.pathsep + os.environ.get("PATH", "")
