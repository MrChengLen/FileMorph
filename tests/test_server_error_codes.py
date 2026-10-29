# SPDX-License-Identifier: AGPL-3.0-or-later
"""Errors the server words in English carry ``X-FileMorph-Error-Code``, so the
web UI (app.js, pdf-tools.js) can show the text in the page's language from
FM_I18N.

For convert_failed, compress_failed and server_busy the UI's English text is
the server's own, so English pages read as before; file_type_not_permitted
says why and what next; request_too_large takes its number from
``max_size_mb`` in the body (tests/test_request_limits.py); decompression_bomb
has one text in both scripts.
"""

import io
import json
import re
from pathlib import Path

import pytest
from PIL import Image

from app.converters.registry import get_converter
from app.core.concurrency import ConcurrencyExhausted
from app.core.i18n import _js_i18n_strings

CATALOGUE = _js_i18n_strings(lambda s: s)
_JS = Path(__file__).resolve().parent.parent / "app" / "static" / "js"


def _code_only(name: str) -> str:
    """A script without its line comments: a comment that names a code is no handling."""
    return re.sub(r"(?m)^\s*//.*$", "", (_JS / name).read_text(encoding="utf-8"))


APP_JS = _code_only("app.js")
PDF_TOOLS_JS = _code_only("pdf-tools.js")
BLOCKED = b"MZ" + bytes(64)
BLOB = re.compile(r'<script id="fm-i18n-strings" type="application/json">(.*?)</script>', re.DOTALL)


def _image(fmt: str) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), "white").save(buf, format=fmt)
    return buf.getvalue()


def _code(r) -> str | None:
    return r.headers.get("X-FileMorph-Error-Code")


def test_a_failed_conversion_carries_convert_failed(client, auth_headers, monkeypatch):
    def _internal_error(self, *args, **kwargs):
        raise ValueError("internal detail")

    monkeypatch.setattr(type(get_converter("png", "jpg")), "convert", _internal_error)
    r = client.post(
        "/api/v1/convert",
        headers=auth_headers,
        files={"file": ("a.png", _image("PNG"), "image/png")},
        data={"target_format": "jpg"},
    )
    assert (r.status_code, _code(r)) == (500, "convert_failed")
    assert r.json()["detail"] == CATALOGUE["errorConvertFailed"]
    assert "internal detail" not in r.text


def test_a_failed_compression_carries_compress_failed(client, auth_headers, monkeypatch):
    def _internal_error(*args, **kwargs):
        raise ValueError("internal detail")

    monkeypatch.setattr("app.api.routes.compress.compress_image", _internal_error)
    r = client.post(
        "/api/v1/compress",
        headers=auth_headers,
        files={"file": ("a.jpg", _image("JPEG"), "image/jpeg")},
        data={"quality": "70"},
    )
    assert (r.status_code, _code(r)) == (500, "compress_failed")
    assert r.json()["detail"] == CATALOGUE["errorCompressFailed"]
    assert "internal detail" not in r.text


@pytest.mark.parametrize(
    "path, name, data",
    [
        ("/api/v1/convert", "a.png", {"target_format": "jpg"}),
        ("/api/v1/compress", "a.jpg", {"quality": "70"}),
        ("/api/v1/pdf/split", "a.pdf", {}),
    ],
)
def test_a_blocked_file_type_carries_its_code(client, auth_headers, path, name, data):
    r = client.post(
        path,
        headers=auth_headers,
        files={"file": (name, BLOCKED, "application/octet-stream")},
        data=data,
    )
    assert (r.status_code, _code(r)) == (400, "file_type_not_permitted")
    assert r.json()["detail"] == "File type not permitted."
    # The UI's text starts with the server's, then says why and what next.
    assert CATALOGUE["errorFileTypeNotPermitted"].startswith(r.json()["detail"] + " ")


def test_only_the_global_cap_is_server_busy():
    busy = ConcurrencyExhausted(scope="global", retry_after_seconds=5)
    assert busy.headers["X-FileMorph-Error-Code"] == "server_busy"
    assert busy.headers["Retry-After"] == "5"
    assert busy.detail == CATALOGUE["errorServerBusy"]
    # The per-actor 429 is worded by its status.
    assert (
        "X-FileMorph-Error-Code"
        not in ConcurrencyExhausted(scope="per_actor", retry_after_seconds=5).headers
    )


# Each code a script handles, and the catalogue key it shows for it.
_APP_JS_KEYS = [
    ("convert_failed", "errorConvertFailed"),
    ("compress_failed", "errorCompressFailed"),
    ("decompression_bomb", "pdfImageTooLarge"),
    ("file_type_not_permitted", "errorFileTypeNotPermitted"),
    ("request_too_large", "errorRequestTooLargeBatch"),
    ("request_too_large", "errorRequestTooLarge"),
    ("server_busy", "errorServerBusy"),
]
_PDF_TOOLS_KEYS = [
    ("decompression_bomb", "pdfImageTooLarge"),
    ("file_type_not_permitted", "errorFileTypeNotPermitted"),
    ("request_too_large", "errorRequestTooLarge"),
    ("server_busy", "errorServerBusy"),
]


@pytest.mark.parametrize("code, key", _APP_JS_KEYS)
def test_the_converter_words_each_code(code, key):
    assert re.search(rf"errCode === '{code}'[\s\S]{{0,700}}?\b{key}\b", APP_JS), (code, key)


@pytest.mark.parametrize("code, key", _PDF_TOOLS_KEYS)
def test_the_pdf_tools_word_each_code(code, key):
    assert re.search(rf"code === '{code}'[\s\S]{{0,400}}?\b{key}\b", PDF_TOOLS_JS), (code, key)


def test_the_texts_are_german_on_de(client):
    blobs = {}
    for lang in ("de", "en"):
        match = BLOB.search(client.get(f"/{lang}/").text)
        assert match, f"FM_I18N script tag missing on /{lang}/"
        blobs[lang] = json.loads(match.group(1))
    for key in {key for _code, key in _APP_JS_KEYS + _PDF_TOOLS_KEYS}:
        assert blobs["de"][key] not in ("", blobs["en"][key]), key
