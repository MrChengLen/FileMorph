# SPDX-License-Identifier: AGPL-3.0-or-later
"""S4-foundation: structured log emission for convert/compress lifecycle.

Guards that every outcome (success + cap-rejection + batch summary) carries
enough context for dashboards: `tier`, `operation`, reason on failures,
and a cap-hit counter on batch summaries. Prevents regressions like the
earlier formatter that silently dropped extras to stdout."""

import dataclasses
import io
import json
import logging

from PIL import Image

from app.core import quotas as quotas_module
from app.core.logging_config import JsonLogFormatter
from app.core.quotas import QUOTAS


def _jpg_bytes(w: int = 50, h: int = 50) -> bytes:
    img = Image.new("RGB", (w, h), color=(100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _find(caplog, msg: str) -> list[logging.LogRecord]:
    return [rec for rec in caplog.records if rec.getMessage() == msg]


# ── Formatter unit test ──────────────────────────────────────────────────────


def test_json_formatter_emits_extras():
    """The formatter must include every non-reserved extra field, not swallow them."""
    formatter = JsonLogFormatter()
    record = logging.LogRecord(
        name="test.logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=0,
        msg="hello",
        args=None,
        exc_info=None,
    )
    # Simulate the `extra={...}` kwarg path: logging attaches them as attributes.
    record.tier = "pro"
    record.operation = "convert"
    record.output_size_bytes = 12345

    payload = json.loads(formatter.format(record))

    assert payload["msg"] == "hello"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "test.logger"
    assert payload["tier"] == "pro"
    assert payload["operation"] == "convert"
    assert payload["output_size_bytes"] == 12345


# ── Convert ──────────────────────────────────────────────────────────────────


def test_convert_success_log_has_tier(client, auth_headers, caplog):
    with caplog.at_level(logging.INFO, logger="app.api.routes.convert"):
        r = client.post(
            "/api/v1/convert",
            headers=auth_headers,
            files={"file": ("sample.jpg", _jpg_bytes(), "image/jpeg")},
            data={"target_format": "png"},
        )
    assert r.status_code == 200
    records = _find(caplog, "conversion complete")
    assert records, "no 'conversion complete' log record found"
    rec = records[0]
    assert getattr(rec, "tier", None) == "anonymous"
    assert getattr(rec, "operation", None) == "convert"
    assert getattr(rec, "success", None) is True


def test_convert_cap_rejection_emits_structured_log(client, auth_headers, caplog, monkeypatch):
    original = QUOTAS["anonymous"]
    shrunk = dataclasses.replace(original, output_cap_bytes=100)
    monkeypatch.setitem(quotas_module.QUOTAS, "anonymous", shrunk)

    with caplog.at_level(logging.INFO, logger="app.api.routes.convert"):
        r = client.post(
            "/api/v1/convert",
            headers=auth_headers,
            files={"file": ("sample.jpg", _jpg_bytes(), "image/jpeg")},
            data={"target_format": "png"},
        )
    assert r.status_code == 413
    records = _find(caplog, "conversion rejected")
    assert records, "no 'conversion rejected' log record found"
    rec = records[0]
    assert getattr(rec, "reason", None) == "output_cap"
    assert getattr(rec, "tier", None) == "anonymous"
    assert getattr(rec, "success", None) is False
    assert getattr(rec, "cap_bytes", None) == 100
    # And no success log for this request.
    assert not _find(caplog, "conversion complete")


# ── Compress ─────────────────────────────────────────────────────────────────


def test_compress_success_log_has_tier(client, auth_headers, caplog):
    with caplog.at_level(logging.INFO, logger="app.api.routes.compress"):
        r = client.post(
            "/api/v1/compress",
            headers=auth_headers,
            files={"file": ("sample.jpg", _jpg_bytes(), "image/jpeg")},
            data={"quality": "85"},
        )
    assert r.status_code == 200
    records = _find(caplog, "compression complete")
    assert records
    rec = records[0]
    assert getattr(rec, "tier", None) == "anonymous"
    assert getattr(rec, "operation", None) == "compress"


def test_compress_cap_rejection_emits_structured_log(client, auth_headers, caplog, monkeypatch):
    original = QUOTAS["anonymous"]
    shrunk = dataclasses.replace(original, output_cap_bytes=100)
    monkeypatch.setitem(quotas_module.QUOTAS, "anonymous", shrunk)

    with caplog.at_level(logging.INFO, logger="app.api.routes.compress"):
        r = client.post(
            "/api/v1/compress",
            headers=auth_headers,
            files={"file": ("sample.jpg", _jpg_bytes(), "image/jpeg")},
            data={"quality": "85"},
        )
    assert r.status_code == 413
    records = _find(caplog, "compression rejected")
    assert records
    rec = records[0]
    assert getattr(rec, "reason", None) == "output_cap"
    assert getattr(rec, "tier", None) == "anonymous"
    assert getattr(rec, "success", None) is False


# ── Batch summaries ──────────────────────────────────────────────────────────


def test_batch_convert_summary_counts_cap_rejections(client, auth_headers, caplog, monkeypatch):
    """When batch files overflow the cap, the batch-complete log must count them
    in `rejected_output_cap` so dashboards can slice cap-pressure per request."""
    from app.api.routes.auth import get_optional_user
    from app.main import app
    from unittest.mock import MagicMock

    fake_user = MagicMock()
    fake_user.tier.value = "free"
    app.dependency_overrides[get_optional_user] = lambda: fake_user

    original = QUOTAS["free"]
    shrunk = dataclasses.replace(original, output_cap_bytes=100)
    monkeypatch.setitem(quotas_module.QUOTAS, "free", shrunk)

    try:
        with caplog.at_level(logging.INFO, logger="app.api.routes.convert"):
            r = client.post(
                "/api/v1/convert/batch",
                headers=auth_headers,
                data={"target_formats": ["png", "png"]},
                files=[
                    ("files", ("a.jpg", _jpg_bytes(), "image/jpeg")),
                    ("files", ("b.jpg", _jpg_bytes(), "image/jpeg")),
                ],
            )
    finally:
        app.dependency_overrides.pop(get_optional_user, None)

    assert r.status_code == 422
    records = _find(caplog, "batch convert complete")
    assert records
    rec = records[0]
    assert getattr(rec, "tier", None) == "free"
    assert getattr(rec, "rejected_output_cap", None) == 2
