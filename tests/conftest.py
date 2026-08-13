# SPDX-License-Identifier: AGPL-3.0-or-later
import json
import os
from pathlib import Path

# Must be set before app modules are imported so slowapi reads it at Limiter init time.
os.environ["RATELIMIT_ENABLED"] = "0"

# Cockpit/auth tests opt into an in-memory SQLite database on demand via the
# `sqlite_db` fixture. By default, `DATABASE_URL` stays unset so the existing
# Community-Edition tests run exactly as before.

import pytest
from fastapi.testclient import TestClient

from app.core import security as sec_module
from app.main import app

TEST_KEY = "test-api-key-filemorph-ci"


@pytest.fixture(scope="session", autouse=True)
def setup_test_api_key(tmp_path_factory):
    """Create a temporary api_keys.json with a known test key."""
    tmp = tmp_path_factory.mktemp("data")
    keys_file = tmp / "api_keys.json"
    import hashlib

    key_hash = hashlib.sha256(TEST_KEY.encode()).hexdigest()
    keys_file.write_text(json.dumps({"keys": [key_hash]}))

    original = sec_module.settings.api_keys_file
    sec_module.settings.__dict__["api_keys_file"] = str(keys_file)
    yield
    sec_module.settings.__dict__["api_keys_file"] = original


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_headers():
    return {"X-API-Key": TEST_KEY}


@pytest.fixture
def sample_jpg(tmp_path) -> Path:
    from PIL import Image

    img = Image.new("RGB", (100, 100), color=(200, 100, 50))
    path = tmp_path / "sample.jpg"
    img.save(str(path), format="JPEG")
    return path


@pytest.fixture
def sample_png(tmp_path) -> Path:
    from PIL import Image

    img = Image.new("RGBA", (50, 50), color=(0, 128, 255, 200))
    path = tmp_path / "sample.png"
    img.save(str(path), format="PNG")
    return path


@pytest.fixture
def sample_txt(tmp_path) -> Path:
    path = tmp_path / "sample.txt"
    path.write_text("Hello FileMorph!\nLine two.\nLine three.")
    return path


@pytest.fixture
def redact_enabled():
    """Flip the AI-redaction gate on BOTH surfaces that read it: ``settings``
    (route-level 404 gate, read per request) and the Jinja global (template
    ``{% if %}``, set once at import). Shared by the redact-page, footer and
    homepage test modules — keep the two flips together or pages and their
    discovery surfaces disagree."""
    from app.core.config import settings
    from app.core.templates import templates

    s = settings.__dict__
    saved_s = {k: s.get(k) for k in ("ai_operations_enabled", "ai_eligible_tiers")}
    s.update(ai_operations_enabled=True, ai_eligible_tiers="pro,business,enterprise")
    g = templates.env.globals
    saved_g = {k: g.get(k) for k in ("ai_operations_enabled", "ai_eligible_tiers")}
    g["ai_operations_enabled"] = True
    g["ai_eligible_tiers"] = ["pro", "business", "enterprise"]
    yield
    s.update(saved_s)
    g.update(saved_g)
