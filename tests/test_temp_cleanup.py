# SPDX-License-Identifier: AGPL-3.0-or-later
"""S3/Phase-D: guard that FileResponse's BackgroundTask actually cleans up
the per-request temp dir. Regression-guards against someone dropping the
`background=BackgroundTask(...)` from the return and leaking `fm_*` dirs
on every successful request."""

import dataclasses
import io
import tempfile
from pathlib import Path

from PIL import Image

from app.core import quotas as quotas_module
from app.core.quotas import QUOTAS


def _jpg_bytes(w: int = 50, h: int = 50) -> bytes:
    img = Image.new("RGB", (w, h), color=(100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _fm_dirs() -> set[Path]:
    tmp = Path(tempfile.gettempdir())
    return set(tmp.glob("fm_*"))


def test_convert_success_leaves_no_temp_dir(client, auth_headers):
    before = _fm_dirs()
    r = client.post(
        "/api/v1/convert",
        headers=auth_headers,
        files={"file": ("sample.jpg", _jpg_bytes(), "image/jpeg")},
        data={"target_format": "png"},
    )
    assert r.status_code == 200
    # Consume body so FileResponse finishes streaming and BackgroundTask fires.
    assert len(r.content) > 0
    leaked = _fm_dirs() - before
    assert not leaked, f"Leaked temp dirs after successful convert: {leaked}"


def test_compress_success_leaves_no_temp_dir(client, auth_headers):
    before = _fm_dirs()
    r = client.post(
        "/api/v1/compress",
        headers=auth_headers,
        files={"file": ("sample.jpg", _jpg_bytes(), "image/jpeg")},
        data={"quality": "85"},
    )
    assert r.status_code == 200
    assert len(r.content) > 0
    leaked = _fm_dirs() - before
    assert not leaked, f"Leaked temp dirs after successful compress: {leaked}"


def test_convert_cap_rejection_leaves_no_temp_dir(client, auth_headers, monkeypatch):
    """The except-handler must clean up when output-cap rejection fires,
    since the BackgroundTask only runs on the success path."""
    original = QUOTAS["anonymous"]
    shrunk = dataclasses.replace(original, output_cap_bytes=100)
    monkeypatch.setitem(quotas_module.QUOTAS, "anonymous", shrunk)

    before = _fm_dirs()
    r = client.post(
        "/api/v1/convert",
        headers=auth_headers,
        files={"file": ("sample.jpg", _jpg_bytes(), "image/jpeg")},
        data={"target_format": "png"},
    )
    assert r.status_code == 413
    leaked = _fm_dirs() - before
    assert not leaked, f"Leaked temp dirs after rejected convert: {leaked}"
