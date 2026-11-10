# SPDX-License-Identifier: AGPL-3.0-or-later
"""Test-only routes for the browser tests, added to the real app for the
session (tests/browser/conftest.py) and never part of it otherwise.

- ``GET /__bt/page/{profile}`` — a page under that CSP profile, chosen with
  ``use_csp_profile`` like any route, so the app's own middleware sets the
  header. It loads ``probe.js`` and holds a form for the form-post probe; its
  icon is a ``data:`` URL, so no browser asks for ``/favicon.ico``.
- ``GET /__bt/probe.js`` — tests/browser/probe.js.
- ``/__bt/hit/{channel}`` — the target of every probe, for any method. It
  answers 204; the recorder outside the app notes each request that arrives.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, Response

from app.core.csp import use_csp_profile

_PROBE_JS = Path(__file__).with_name("probe.js")

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Browser test: {profile}</title>
<link rel="icon" href="data:,">
<script src="/__bt/probe.js" defer></script>
</head>
<body>
<h1>{profile}</h1>
<form id="form-probe" method="post" action="/__bt/hit/form">
<input type="hidden" name="probe" value="form">
</form>
</body>
</html>
"""


def add_probe_routes(app: FastAPI) -> Callable[[], None]:
    """Add the /__bt/ routes to ``app``; returns the function that removes them."""

    async def page(request: Request, profile: str) -> HTMLResponse:
        use_csp_profile(request.scope, profile)
        return HTMLResponse(_PAGE.format(profile=profile))

    async def probe_js() -> Response:
        return Response(_PROBE_JS.read_bytes(), media_type="text/javascript; charset=utf-8")

    async def hit(channel: str) -> Response:
        return Response(status_code=204)

    before = list(app.router.routes)
    app.add_api_route("/__bt/page/{profile}", page, methods=["GET"], include_in_schema=False)
    app.add_api_route("/__bt/probe.js", probe_js, methods=["GET"], include_in_schema=False)
    app.add_api_route(
        "/__bt/hit/{channel}",
        hit,
        methods=["GET", "POST", "PUT", "HEAD", "OPTIONS"],
        include_in_schema=False,
    )
    added = [route for route in app.router.routes if route not in before]

    def remove() -> None:
        for route in added:
            app.router.routes.remove(route)

    return remove
