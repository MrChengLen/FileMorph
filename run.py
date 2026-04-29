#!/usr/bin/env python3
"""Entry point for both source (uvicorn --reload) and PyInstaller (.exe) runs."""

import threading
import time
import webbrowser

import uvicorn

from app.compat import is_frozen, setup_ffmpeg_path
from app.core.config import settings
from app.core.security import _load_hashes, generate_api_key


def _first_run_setup() -> None:
    """Generate and display API key on first run (frozen / .exe mode only)."""
    if _load_hashes():
        return  # Keys already exist

    key = generate_api_key()
    border = "=" * 64
    print(f"\n{border}")
    print("  FileMorph — First Run Setup")
    print(border)
    print(f"  API KEY: {key}")
    print(border)
    print("  IMPORTANT: Save this key — it will NOT be shown again.")
    print("  Enter it in the Web UI under the 'API Key' field.")
    print(f"{border}\n")


def _open_browser_delayed(url: str, delay: float = 2.0) -> None:
    """Open the browser after a short delay so the server has time to start."""

    def _open():
        time.sleep(delay)
        webbrowser.open(url)

    threading.Thread(target=_open, daemon=True).start()


if __name__ == "__main__":
    setup_ffmpeg_path()

    if is_frozen():
        # Running as standalone .exe
        _first_run_setup()
        _open_browser_delayed(f"http://localhost:{settings.app_port}")
        print(f"  FileMorph running at http://localhost:{settings.app_port}")
        print("  Close this window to stop the server.\n")

    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=False,  # reload not supported in frozen mode
    )
