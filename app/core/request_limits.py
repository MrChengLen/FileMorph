# SPDX-License-Identifier: AGPL-3.0-or-later
"""Request-body limits, enforced on the bytes that actually arrive.

Pure ASGI middleware, so it sees the body as it is received. A
``Content-Length`` header above the limit is refused before anything is
read; a body sent without one (chunked transfer encoding) is counted while
it arrives and refused once it passes the limit.

* Upload routes (convert, compress, PDF tools, AI) take at most
  ``MAX_UPLOAD_SIZE_MB`` per request; the per-tier file caps are checked in
  the routes afterwards.
* Every other route takes at most ``SMALL_BODY_LIMIT_BYTES``. Their JSON
  bodies (sign-in, contact, billing, keys, Stripe events) are a few KB.
* Form bodies must be UTF-8: a form ``Content-Type`` whose ``charset``
  parameter names any other encoding gets 415.

Starlette's own ``RequestBodyLimitMiddleware`` is not used: it has one limit
per app and answers a declared oversize length with a plain-text 413 instead
of the JSON ``{"detail": ...}`` every other error carries.

Registered in ``app/main.py`` as the innermost middleware, so its answers
carry the CORS and security headers like any route's.
"""

from python_multipart.multipart import parse_options_header
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import settings

_MB = 1024 * 1024

SMALL_BODY_LIMIT_BYTES = 1 * _MB

# Paths of the routes that take file uploads (``UploadFile`` parameters);
# tests/test_request_limits.py checks the list against the app's routes.
UPLOAD_PATH_PREFIXES = (
    "/api/v1/convert",
    "/api/v1/compress",
    "/api/v1/pdf/",
    "/api/v1/ai/",
)

_FORM_TYPES = ("multipart/form-data", "application/x-www-form-urlencoded")
_UTF8_NAMES = ("utf-8", "utf8")


def _limit_for(path: str) -> tuple[int, str]:
    """The largest body, in bytes, the route at ``path`` takes, and its 413 text."""
    if path.startswith(UPLOAD_PATH_PREFIXES):
        return (
            settings.max_upload_size_bytes,
            f"File too large. Maximum size: {settings.max_upload_size_mb} MB",
        )
    return (
        SMALL_BODY_LIMIT_BYTES,
        f"Request too large. Maximum size: {SMALL_BODY_LIMIT_BYTES // _MB} MB",
    )


def _is_non_utf8_form(content_type: str) -> bool:
    """True for a form ``Content-Type`` that names a charset other than UTF-8.

    Uses the same header parser as Starlette, so both read the same
    parameters.
    """
    if content_type.partition(";")[0].strip().lower() not in _FORM_TYPES:
        return False
    charset = parse_options_header(content_type)[1].get(b"charset")
    return charset is not None and charset.decode("latin-1").lower() not in _UTF8_NAMES


async def _answer(scope: Scope, receive: Receive, send: Send, status: int, detail: str) -> None:
    await JSONResponse({"detail": detail}, status_code=status)(scope, receive, send)


async def _too_large(scope: Scope, receive: Receive, send: Send, limit: int, detail: str) -> None:
    """The 413, with a code and the limit in MB, so a client can word it itself."""
    response = JSONResponse(
        {"detail": detail, "max_size_mb": limit // _MB},
        status_code=413,
        headers={"X-FileMorph-Error-Code": "request_too_large"},
    )
    await response(scope, receive, send)


class _BodyTooLarge(Exception):
    """Raised from ``receive`` once the body has passed the route's limit."""


class RequestLimitsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        if _is_non_utf8_form(headers.get("content-type", "")):
            await _answer(scope, receive, send, 415, "Form data must be UTF-8 encoded.")
            return

        # The path the router matches: without the mount prefix (root_path),
        # which the server may include in scope["path"].
        path, root_path = scope["path"], scope.get("root_path", "")
        if root_path and path.startswith(root_path):
            path = path[len(root_path) :]
        limit, too_large = _limit_for(path)
        declared = headers.get("content-length", "")
        if declared.isdecimal() and int(declared) > limit:
            await _too_large(scope, receive, send, limit, too_large)
            return

        received = 0
        exceeded = False
        response_started = False

        async def counting_receive() -> Message:
            nonlocal received, exceeded
            if exceeded:
                raise _BodyTooLarge
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    exceeded = True
                    raise _BodyTooLarge
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal response_started
            if exceeded and not response_started:
                # The route's own error for the cut-off body; the 413 below
                # replaces it.
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, guarded_send)
        except Exception:
            if not exceeded or response_started:
                raise
        if exceeded and not response_started:
            await _too_large(scope, receive, send, limit, too_large)
