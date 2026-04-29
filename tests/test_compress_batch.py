# SPDX-License-Identifier: AGPL-3.0-or-later
import io
import zipfile
from unittest.mock import MagicMock

import pytest
from PIL import Image

from app.api.routes.auth import get_optional_user
from app.main import app


def _fake_user(tier: str):
    u = MagicMock()
    u.tier.value = tier
    return u


@pytest.fixture
def override_free_user():
    app.dependency_overrides[get_optional_user] = lambda: _fake_user("free")
    yield
    app.dependency_overrides.pop(get_optional_user, None)


def _jpg_bytes() -> bytes:
    img = Image.new("RGB", (120, 120), color=(200, 100, 50))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


def test_compress_batch_two_jpegs(client, auth_headers, override_free_user):
    files = [
        ("files", ("a.jpg", _jpg_bytes(), "image/jpeg")),
        ("files", ("b.jpg", _jpg_bytes(), "image/jpeg")),
    ]
    r = client.post(
        "/api/v1/compress/batch",
        headers=auth_headers,
        data={"quality": "70"},
        files=files,
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/zip")
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    assert "manifest.json" not in names
    compressed = [n for n in names if "_compressed" in n]
    assert len(compressed) == 2
