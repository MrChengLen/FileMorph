# SPDX-License-Identifier: AGPL-3.0-or-later
"""Request-body limits (app/core/request_limits.py).

The size limits count the bytes that arrive, with or without a
``Content-Length`` header: ``MAX_UPLOAD_SIZE_MB`` on the upload routes, 1 MB
everywhere else. Form bodies must be UTF-8.
"""

import asyncio
from tempfile import SpooledTemporaryFile

import pytest
from starlette import formparsers
from starlette.formparsers import MultiPartParser

from app.core.config import settings
from app.core.request_limits import (
    SMALL_BODY_LIMIT_BYTES,
    UPLOAD_PATH_PREFIXES,
    RequestLimitsMiddleware,
)
from app.main import app

_MB = 1024 * 1024
_BOUNDARY = "fm-test-boundary"


def _multipart(fields: dict[str, str], name: str, data: bytes, mime: str) -> bytes:
    parts = [
        f'--{_BOUNDARY}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode()
        for key, value in fields.items()
    ]
    parts.append(
        f'--{_BOUNDARY}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
        f"Content-Type: {mime}\r\n\r\n".encode()
        + data
        + b"\r\n"
    )
    parts.append(f"--{_BOUNDARY}--\r\n".encode())
    return b"".join(parts)


def _chunks(body: bytes, size: int = 64 * 1024):
    # A generator body goes out without Content-Length (chunked). The
    # TestClient hands it to the app in one message; counting across several
    # messages is covered by the middleware tests at the end.
    for start in range(0, len(body), size):
        yield body[start : start + size]


@pytest.fixture
def one_mb_upload_cap(monkeypatch):
    monkeypatch.setattr(settings, "max_upload_size_mb", 1)


# ── Upload routes ────────────────────────────────────────────────────────────


def test_upload_without_content_length_over_the_cap_gets_413(
    client, auth_headers, sample_jpg, one_mb_upload_cap
):
    data = sample_jpg.read_bytes() + b"\0" * (2 * _MB)
    body = _multipart({"target_format": "png"}, "big.jpg", data, "image/jpeg")
    res = client.post(
        "/api/v1/convert",
        headers={**auth_headers, "content-type": f"multipart/form-data; boundary={_BOUNDARY}"},
        content=_chunks(body),
    )
    assert res.status_code == 413
    assert res.json()["detail"] == "File too large. Maximum size: 1 MB"


def test_upload_without_content_length_under_the_cap_is_converted(client, auth_headers, sample_jpg):
    body = _multipart({"target_format": "png"}, "sample.jpg", sample_jpg.read_bytes(), "image/jpeg")
    res = client.post(
        "/api/v1/convert",
        headers={**auth_headers, "content-type": f"multipart/form-data; boundary={_BOUNDARY}"},
        content=_chunks(body),
    )
    assert res.status_code == 200
    assert res.content.startswith(b"\x89PNG")


def test_upload_with_content_length_over_the_cap_gets_413(client, auth_headers, one_mb_upload_cap):
    res = client.post(
        "/api/v1/compress",
        headers=auth_headers,
        files={"file": ("big.jpg", b"\xff\xd8\xff\xe0" + b"\0" * (2 * _MB), "image/jpeg")},
        data={"quality": "85"},
    )
    assert res.status_code == 413
    assert res.json()["detail"] == "File too large. Maximum size: 1 MB"


# ── Every other route: 1 MB ──────────────────────────────────────────────────


@pytest.mark.parametrize("chunked", [False, True], ids=["content-length", "chunked"])
@pytest.mark.parametrize(
    "path", ["/api/v1/contact", "/api/v1/auth/login", "/api/v1/billing/webhook"]
)
def test_other_routes_take_at_most_one_megabyte(client, monkeypatch, path, chunked):
    # A configured webhook secret, so the webhook route reads the body.
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test_dummy")
    body = b'{"message": "' + b"a" * SMALL_BODY_LIMIT_BYTES + b'"}'
    res = client.post(
        path,
        content=_chunks(body) if chunked else body,
        headers={"content-type": "application/json", "stripe-signature": "t=0,v1=00"},
    )
    assert res.status_code == 413
    assert res.json()["detail"] == "Request too large. Maximum size: 1 MB"


def test_limit_answers_carry_the_cors_and_security_headers(client):
    # Cross-origin callers (API_BASE_URL) can only read an answer with CORS headers.
    origin = settings.cors_origins_list[0]
    res = client.post(
        "/api/v1/contact",
        content=b"{" + b" " * SMALL_BODY_LIMIT_BYTES + b"}",
        headers={"content-type": "application/json", "origin": origin},
    )
    assert res.status_code == 413
    assert res.headers["access-control-allow-origin"] == origin
    assert res.headers["X-Content-Type-Options"] == "nosniff"


def test_webhook_without_signature_is_refused_unread(client, monkeypatch):
    monkeypatch.setattr(settings, "stripe_webhook_secret", "whsec_test_dummy")
    res = client.post(
        "/api/v1/billing/webhook", content=_chunks(b"x" * (SMALL_BODY_LIMIT_BYTES + 1))
    )
    # A route that read the body would have run into the 1 MB limit (413).
    assert res.status_code == 400


def test_upload_prefixes_cover_exactly_the_routes_that_take_files():
    # A route takes files exactly when its body is multipart (OpenAPI schema).
    # Routes left out of the schema (cockpit, pages, webhook, metrics) take
    # no files.
    routes = [
        (path, "multipart/form-data" in operation.get("requestBody", {}).get("content", {}))
        for path, operations in app.openapi()["paths"].items()
        for method, operation in operations.items()
        if method in ("post", "put", "patch", "delete")
    ]
    assert any(takes_files for _, takes_files in routes)
    for path, takes_files in routes:
        assert path.startswith(UPLOAD_PATH_PREFIXES) == takes_files, path


# ── Form charset ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize("charset", ["iso-8859-1", "utf-16", "windows-1252"])
def test_form_in_another_charset_gets_415(client, auth_headers, sample_jpg, monkeypatch, charset):
    def _parse(self):
        raise AssertionError("the form was parsed")

    monkeypatch.setattr(MultiPartParser, "parse", _parse)
    body = _multipart({"target_format": "png"}, "sample.jpg", sample_jpg.read_bytes(), "image/jpeg")
    res = client.post(
        "/api/v1/convert",
        headers={
            **auth_headers,
            "content-type": f"multipart/form-data; boundary={_BOUNDARY}; charset={charset}",
        },
        content=body,
    )
    assert res.status_code == 415
    assert res.json()["detail"] == "Form data must be UTF-8 encoded."


@pytest.mark.parametrize("charset", ["utf-8", "UTF-8", '"utf-8"', "utf8"])
def test_form_declared_as_utf8_is_accepted(client, auth_headers, sample_jpg, charset):
    body = _multipart({"target_format": "png"}, "sample.jpg", sample_jpg.read_bytes(), "image/jpeg")
    res = client.post(
        "/api/v1/convert",
        headers={
            **auth_headers,
            "content-type": f"multipart/form-data; boundary={_BOUNDARY}; charset={charset}",
        },
        content=body,
    )
    assert res.status_code == 200


def test_urlencoded_form_in_another_charset_gets_415(client):
    res = client.post(
        "/api/v1/convert",
        content=b"target_format=png",
        headers={"content-type": "application/x-www-form-urlencoded; charset=iso-8859-1"},
    )
    assert res.status_code == 415


# ── The middleware on its own ────────────────────────────────────────────────


async def _read_all_then_ok(scope, receive, send):
    while (await receive()).get("more_body"):
        pass
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"ok"})


async def _answer_400_on_read_error(scope, receive, send):
    status = 200
    try:
        while (await receive()).get("more_body"):
            pass
    except Exception:
        status = 400
    await send({"type": "http.response.start", "status": status, "headers": []})
    await send({"type": "http.response.body", "body": b""})


def _run(
    inner,
    chunks: list[bytes],
    headers: dict[str, str] | None = None,
    receive=None,
    path: str = "/api/v1/contact",
    root_path: str = "",
):
    messages = [
        {"type": "http.request", "body": chunk, "more_body": i < len(chunks) - 1}
        for i, chunk in enumerate(chunks)
    ]
    sent: list[dict] = []

    async def _receive():
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    async def _send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "root_path": root_path,
        "query_string": b"",
        "headers": [(k.encode(), v.encode()) for k, v in (headers or {}).items()],
    }
    asyncio.run(RequestLimitsMiddleware(inner)(scope, receive or _receive, _send))
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


def test_bytes_are_counted_across_chunks():
    third = b"x" * (SMALL_BODY_LIMIT_BYTES // 2)
    assert _run(_read_all_then_ok, [third, third, third]) == 413


def test_route_error_for_the_cut_off_body_becomes_413():
    third = b"x" * (SMALL_BODY_LIMIT_BYTES // 2)
    assert _run(_answer_400_on_read_error, [third, third, third]) == 413


def test_body_exactly_at_the_limit_passes():
    half = b"x" * (SMALL_BODY_LIMIT_BYTES // 2)
    assert _run(_read_all_then_ok, [half, half]) == 200


def test_errors_below_the_limit_propagate():
    async def _fails(scope, receive, send):
        await receive()
        raise RuntimeError("route failed")

    with pytest.raises(RuntimeError):
        _run(_fails, [b"x"])


def test_declared_length_over_the_limit_is_refused_unread():
    async def _receive():
        raise AssertionError("the body was read")

    headers = {"content-length": str(SMALL_BODY_LIMIT_BYTES + 1)}
    assert _run(_read_all_then_ok, [], headers=headers, receive=_receive) == 413


def test_upload_path_under_a_root_path_keeps_the_upload_limit():
    two_mb = [b"x" * _MB, b"x" * _MB]
    assert _run(_read_all_then_ok, two_mb, path="/files/api/v1/convert", root_path="/files") == 200
    assert _run(_read_all_then_ok, two_mb, path="/files/api/v1/contact", root_path="/files") == 413


def test_the_limits_are_the_innermost_middleware():
    # Outer middlewares must not read the body (app/main.py); this one has
    # to stay innermost for its answers to carry the CORS headers.
    assert app.user_middleware[-1].cls is RequestLimitsMiddleware


def test_upload_cut_off_mid_body_closes_the_spooled_file(monkeypatch):
    """Through the whole app: the parser's temp file is closed, the rest unread."""
    closed = []

    class _RecordingFile(SpooledTemporaryFile):
        def close(self):
            closed.append(self)
            super().close()

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", _RecordingFile)
    monkeypatch.setattr(settings, "max_upload_size_mb", 2)
    head = (
        f'--{_BOUNDARY}\r\nContent-Disposition: form-data; name="file"; filename="big.jpg"\r\n'
        "Content-Type: image/jpeg\r\n\r\n"
    ).encode()
    chunk = b"\xff" * (64 * 1024)
    messages = [head] + [chunk] * 64  # 4 MB of file data in 64 KB messages
    read = []
    sent = []

    async def _receive():
        if len(read) < len(messages):
            read.append(messages[len(read)])
            return {"type": "http.request", "body": read[-1], "more_body": True}
        return {"type": "http.disconnect"}

    async def _send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/convert",
        "raw_path": b"/api/v1/convert",
        "root_path": "",
        "query_string": b"",
        "headers": [
            (b"content-type", f"multipart/form-data; boundary={_BOUNDARY}".encode()),
            (b"transfer-encoding", b"chunked"),
        ],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }
    asyncio.run(app(scope, _receive, _send))
    assert next(m["status"] for m in sent if m["type"] == "http.response.start") == 413
    assert closed  # the spooled upload was closed
    assert len(read) <= 2 * 16 + 2  # stopped at the 2 MB limit, not at 4 MB
