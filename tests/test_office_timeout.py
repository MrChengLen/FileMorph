# SPDX-License-Identifier: AGPL-3.0-or-later
"""Past its time limit, a LibreOffice conversion stops all of LibreOffice.

``soffice`` is a launcher; the conversion runs in a child of it
(``soffice.bin``). A stand-in launcher of the same shape — a shell script that
starts a worker and waits for it — shows that stopping only the launcher, as
``subprocess.run`` does past its timeout, leaves the worker running, and that
``_convert_via_libreoffice`` stops the worker as well. The real LibreOffice is
checked the same way in ``.github/workflows/docker-pr.yml``.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.converters import document

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="reads processes from /proc")


def _stand_in_soffice(tmp_path: Path) -> tuple[Path, Path]:
    """A launcher that starts a worker, writes the worker's PID to a file and
    waits for it. Returns the launcher and the PID file."""
    pid_file = tmp_path / "worker.pid"
    launcher = tmp_path / "soffice"
    launcher.write_text(
        f'#!/bin/sh\nsleep 60 &\necho $! > "{pid_file}"\nwait\n', encoding="utf-8", newline="\n"
    )
    launcher.chmod(0o755)
    return launcher, pid_file


def _running(pid: int) -> bool:
    """Whether ``pid`` runs; a process that ended but is not reaped yet counts as ended."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return False
    return stat.rsplit(")", 1)[1].split()[0] != "Z"


def test_a_plain_timeout_leaves_the_worker_running(tmp_path):
    # The case the fix is for, and proof that the stand-in shows it: without
    # this, the next test would also pass with a worker that ends on its own.
    launcher, pid_file = _stand_in_soffice(tmp_path)
    with pytest.raises(subprocess.TimeoutExpired):
        subprocess.run([str(launcher)], capture_output=True, timeout=1, check=False)
    worker = int(pid_file.read_text())
    alive = _running(worker)
    if alive:
        os.kill(worker, signal.SIGKILL)
    assert alive


def test_a_libreoffice_timeout_stops_the_worker_too(monkeypatch, tmp_path):
    launcher, pid_file = _stand_in_soffice(tmp_path)
    monkeypatch.setattr(document.shutil, "which", lambda name: str(launcher))
    src = tmp_path / "in.docx"
    src.write_bytes(b"PK\x03\x04")  # the stand-in never reads it
    with pytest.raises(subprocess.TimeoutExpired):
        document._convert_via_libreoffice(src, tmp_path / "out.pdf", timeout_s=1)
    worker = int(pid_file.read_text())
    deadline = time.monotonic() + 5
    while _running(worker) and time.monotonic() < deadline:
        time.sleep(0.05)
    alive = _running(worker)
    if alive:
        os.kill(worker, signal.SIGKILL)  # not left behind when the test fails
    assert not alive
