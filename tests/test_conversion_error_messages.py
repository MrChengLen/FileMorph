# SPDX-License-Identifier: AGPL-3.0-or-later
"""Error messages that reach the client must be written for the client.

The batch routes used to return ``str(e)`` for *any* ValueError. Library
exceptions subclass ValueError too — ``UnicodeDecodeError`` (a non-UTF-8
``.md``), ``JSONDecodeError`` (invalid ``.json``), some Pillow errors — so
their internals (codec, byte offset, parser position) landed in the per-file
error message, the ``X-FileMorph-Batch-Failures`` header and ``manifest.json``
(CWE-209). Only the routes' own messages and caller-safe converter errors may
reach the client; everything else is logged and reported generically. The
generic-path tests inject the ValueError so they keep guarding that contract
if a converter later learns a friendlier message for a specific input.

A text upload (Markdown, CSV, JSON) that isn't UTF-8 is a problem the user can
fix, so /convert and /convert/batch name the fix instead of failing opaquely.
"""

import dataclasses
import io
import json
import logging
import zipfile
from unittest.mock import MagicMock
from urllib.parse import unquote

import pytest
from PIL import Image

from app.api.routes.auth import get_optional_user
from app.converters.registry import get_converter
from app.core import quotas as quotas_module
from app.core.quotas import QUOTAS
from app.main import app


def _weasyprint_works() -> bool:
    try:
        import weasyprint

        weasyprint.HTML(string="<p>probe</p>").write_pdf()
        return True
    except Exception:
        return False


_skip_no_weasyprint = pytest.mark.skipif(
    not _weasyprint_works(),
    reason="WeasyPrint native deps (libgobject/pango) unavailable on this host",
)

# German text saved as windows-1252 — what older Windows editors and Excel's
# default "CSV (Comma delimited)" export write.
_NON_UTF8_MD = "# Überschrift\n\nGrüße aus Hamburg — äöüß\n".encode("cp1252")
_NON_UTF8_CSV = "Name,Stadt\nMüller,Köln\n".encode("cp1252")
_NON_UTF8_JSON = '[{"name": "Müller"}]'.encode("cp1252")
_NON_UTF8_CASES = [
    pytest.param("notes.md", _NON_UTF8_MD, "html", id="md-html"),
    pytest.param("notes.md", _NON_UTF8_MD, "pdf", id="md-pdf", marks=_skip_no_weasyprint),
    pytest.param("excel.csv", _NON_UTF8_CSV, "json", id="csv-json"),
    pytest.param("excel.csv", _NON_UTF8_CSV, "xlsx", id="csv-xlsx"),
    pytest.param("data.json", _NON_UTF8_JSON, "csv", id="json-csv"),
]
_UTF8_HINT = "not UTF-8 text"
_DECODER_INTERNALS = ("codec", "can't decode", "byte 0x", "position", "continuation")
_EXECUTABLE = b"MZ\x90\x00" + b"\x00" * 20


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
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), color=(200, 100, 50)).save(buf, format="JPEG")
    return buf.getvalue()


def _png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 40), color=(100, 180, 200)).save(buf, format="PNG")
    return buf.getvalue()


def _failure_reasons(header: str) -> dict[str, str]:
    """Decode ``X-FileMorph-Batch-Failures`` into ``{name: reason}``."""
    reasons = {}
    for entry in header.split(";"):
        name, _, reason = entry.partition("|")
        reasons[unquote(name)] = unquote(reason)
    return reasons


def _assert_no_decoder_internals(text: str) -> None:
    for needle in _DECODER_INTERNALS:
        assert needle not in text, f"decoder internals leaked ({needle!r}): {text!r}"


# ── Non-UTF-8 text uploads ───────────────────────────────────────────────────


@pytest.mark.parametrize(("name", "payload", "target"), _NON_UTF8_CASES)
def test_convert_batch_non_utf8_text_hides_decoder_details(
    client, auth_headers, override_free_user, name, payload, target
):
    files = [
        ("files", ("photo.jpg", _jpg_bytes(), "image/jpeg")),
        ("files", (name, payload, "text/plain")),
    ]
    r = client.post(
        "/api/v1/convert/batch",
        headers=auth_headers,
        data={"target_formats": ["png", target]},
        files=files,
    )
    assert r.status_code == 200, r.text
    out_name = f"{name.rsplit('.', 1)[0]}.{target}"
    header_reason = _failure_reasons(r.headers["X-FileMorph-Batch-Failures"])[out_name]
    manifest = json.loads(zipfile.ZipFile(io.BytesIO(r.content)).read("manifest.json"))
    manifest_reason = next(f["error_message"] for f in manifest["files"] if f["status"] == "error")
    for reason in (header_reason, manifest_reason):
        _assert_no_decoder_internals(reason)
        assert _UTF8_HINT in reason


@pytest.mark.parametrize(("name", "payload", "target"), _NON_UTF8_CASES)
def test_convert_non_utf8_text_returns_400_with_hint(client, auth_headers, name, payload, target):
    """Single /convert: a fixable input problem is a 400 naming the fix, not a
    generic 500 (which API clients would also retry pointlessly)."""
    r = client.post(
        "/api/v1/convert",
        headers=auth_headers,
        files={"file": (name, payload, "text/plain")},
        data={"target_format": target},
    )
    assert r.status_code == 400, r.text
    assert r.headers.get("X-FileMorph-Error-Code") == "invalid_input"
    detail = r.json()["detail"]
    _assert_no_decoder_internals(detail)
    assert _UTF8_HINT in detail


def test_csv_utf8_with_bom_converts_cleanly(client, auth_headers):
    """The hint recommends Excel's "CSV UTF-8", which starts with a BOM — it
    must not end up in the first column name."""
    r = client.post(
        "/api/v1/convert",
        headers=auth_headers,
        files={
            "file": (
                "excel.csv",
                b"\xef\xbb\xbfName,Stadt\r\nM\xc3\xbcller,K\xc3\xb6ln\r\n",
                "text/csv",
            )
        },
        data={"target_format": "json"},
    )
    assert r.status_code == 200, r.text
    assert json.loads(r.content) == [{"Name": "Müller", "Stadt": "Köln"}]


def test_csv_quoted_line_break_survives(client, auth_headers):
    """Line endings stay as uploaded, so a quoted multi-line cell keeps its CRLF."""
    r = client.post(
        "/api/v1/convert",
        headers=auth_headers,
        files={"file": ("cells.csv", b'a\r\n"x\r\ny"\r\n', "text/csv")},
        data={"target_format": "json"},
    )
    assert r.status_code == 200, r.text
    assert json.loads(r.content) == [{"a": "x\r\ny"}]


# ── Everything else stays generic (details only in the server log) ──────────


def test_convert_batch_unexpected_error_is_generic_and_logged(
    client, auth_headers, caplog, monkeypatch
):
    def _pillow_internal_error(self, *args, **kwargs):
        raise ValueError("Decompressed data too large for PngImagePlugin.MAX_TEXT_CHUNK")

    monkeypatch.setattr(type(get_converter("png", "jpg")), "convert", _pillow_internal_error)
    with caplog.at_level(logging.ERROR, logger="app.api.routes.convert"):
        r = client.post(
            "/api/v1/convert/batch",
            headers=auth_headers,
            data={"target_formats": ["jpg"]},
            files=[("files", ("logo.png", _png_bytes(), "image/png"))],
        )
    assert r.status_code == 422
    assert r.json()["files"][0]["error_message"] == "Conversion failed. Verify the file is valid."
    assert "MAX_TEXT_CHUNK" not in r.text
    assert any(
        rec.getMessage() == "Batch conversion error on one file"
        and rec.exc_info
        and "MAX_TEXT_CHUNK" in str(rec.exc_info[1])
        for rec in caplog.records
    )


def test_compress_batch_unexpected_error_is_generic_and_logged(
    client, auth_headers, caplog, monkeypatch
):
    def _pillow_internal_error(*args, **kwargs):
        raise ValueError("tile cannot extend outside image")

    monkeypatch.setattr("app.api.routes.compress.compress_image", _pillow_internal_error)
    with caplog.at_level(logging.ERROR, logger="app.api.routes.compress"):
        r = client.post(
            "/api/v1/compress/batch",
            headers=auth_headers,
            data={"quality": "70"},
            files=[("files", ("photo.jpg", _jpg_bytes(), "image/jpeg"))],
        )
    assert r.status_code == 422
    assert r.json()["files"][0]["error_message"] == "Compression failed. Verify the file is valid."
    assert "tile cannot extend" not in r.text
    assert any(
        rec.getMessage() == "Batch compression error on one file"
        and rec.exc_info
        and "tile cannot extend" in str(rec.exc_info[1])
        for rec in caplog.records
    )


# ── Messages written for the client keep reaching it ────────────────────────


def test_json_to_csv_shape_hint_reaches_client(client, auth_headers):
    """The converter's own hint was only visible in batch (as a ValueError);
    it is caller-safe, so both routes show it — single /convert as a 400."""
    hint = "JSON must be a non-empty array of objects for CSV conversion."
    payload = b'{"name": "not an array"}'
    single = client.post(
        "/api/v1/convert",
        headers=auth_headers,
        files={"file": ("data.json", payload, "application/json")},
        data={"target_format": "csv"},
    )
    assert single.status_code == 400, single.text
    assert single.json()["detail"] == hint
    batch = client.post(
        "/api/v1/convert/batch",
        headers=auth_headers,
        data={"target_formats": ["csv"]},
        files=[("files", ("data.json", payload, "application/json"))],
    )
    assert batch.status_code == 422
    assert batch.json()["files"][0]["error_message"] == hint


def test_convert_batch_keeps_route_messages(client, auth_headers, override_free_user, monkeypatch):
    shrunk = dataclasses.replace(QUOTAS["free"], max_file_size_bytes=100)
    monkeypatch.setitem(quotas_module.QUOTAS, "free", shrunk)
    files = [
        ("files", ("evil.jpg", _EXECUTABLE, "image/jpeg")),
        ("files", ("README", b"plain text", "text/plain")),
        ("files", ("big.jpg", _jpg_bytes(), "image/jpeg")),  # ~660 B > 100 B cap
    ]
    r = client.post(
        "/api/v1/convert/batch",
        headers=auth_headers,
        data={"target_formats": ["png", "pdf", "png"]},
        files=files,
    )
    assert r.status_code == 422
    reasons = [f["error_message"] for f in r.json()["files"]]
    assert reasons[0] == "File type not permitted."
    assert reasons[1] == "Cannot determine source format from filename."
    assert reasons[2].startswith("File too large (")


def test_compress_batch_keeps_route_messages(client, auth_headers, override_free_user, monkeypatch):
    shrunk = dataclasses.replace(QUOTAS["free"], max_file_size_bytes=300)
    monkeypatch.setitem(quotas_module.QUOTAS, "free", shrunk)
    files = [
        ("files", ("README", b"plain text", "text/plain")),
        ("files", ("notes.txt", b"plain text", "text/plain")),
        ("files", ("big.jpg", _jpg_bytes(), "image/jpeg")),  # ~660 B > 300 B cap
        ("files", ("evil.jpg", _EXECUTABLE, "image/jpeg")),
        ("files", ("logo.png", _png_bytes(), "image/png")),  # target size is lossy-only
    ]
    r = client.post(
        "/api/v1/compress/batch",
        headers=auth_headers,
        data={"target_size_kb": "50"},
        files=files,
    )
    assert r.status_code == 422
    reasons = [f["error_message"] for f in r.json()["files"]]
    assert reasons[0] == "Cannot determine format from filename."
    assert reasons[1] == "Compression not supported for '.txt'."
    assert reasons[2].startswith("File too large (")
    assert reasons[3] == "File type not permitted."
    assert reasons[4].startswith("Target-size compression supports only JPEG, WebP and AVIF.")
