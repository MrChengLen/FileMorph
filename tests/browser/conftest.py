# SPDX-License-Identifier: AGPL-3.0-or-later
"""A real server for real browsers.

The session serves the app (app.main) with uvicorn from a thread, on a free
port of 127.0.0.1, with the local engine switched on and a few test-only
routes under /__bt/ (tests/browser/probe.py). Outside the app sits a recorder
that notes the path of every request reaching the server, before any routing:
what the browser refused to send never shows up there.

The browsers come from the Playwright image browser.yml runs in; Playwright
itself from requirements-browser.lock. Each test runs in Chromium and in
WebKit (the engine of Safari on the iPhone).
"""

from __future__ import annotations

import os

# Before the app is imported, as in tests/conftest.py: slowapi reads it once.
os.environ["RATELIMIT_ENABLED"] = "0"

import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
import uvicorn
from playwright.sync_api import Browser, Page, Playwright, sync_playwright

from app.core.config import settings
from app.main import app
from tests.browser.probe import add_probe_routes


class Recorder:
    """The outermost ASGI layer: the path of every request that reaches the server."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.paths: list[str] = []

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] in ("http", "websocket"):
            self.paths.append(scope["path"])
        await self.inner(scope, receive, send)


@dataclass
class Server:
    base_url: str
    recorder: Recorder
    engine_url: str

    def wait_for(self, path: str, timeout: float = 5.0) -> bool:
        """True once a request for ``path`` reached the server."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if path in self.recorder.paths:
                return True
            time.sleep(0.05)
        return False


@pytest.fixture(scope="session")
def server() -> Iterator[Server]:
    from app.core.engine import ENGINE_URL_PREFIX, engine_tree_hash

    switched_on = settings.local_tools_enabled
    # The engine mount reads the switch on every request.
    settings.local_tools_enabled = True
    remove_probe_routes = add_probe_routes(app)
    recorder = Recorder(app)
    config = uvicorn.Config(recorder, host="127.0.0.1", port=0, log_level="warning")
    uv = uvicorn.Server(config)
    thread = threading.Thread(target=uv.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not uv.started:
        if time.monotonic() > deadline or not thread.is_alive():
            raise RuntimeError("the test server did not start")
        time.sleep(0.05)
    port = uv.servers[0].sockets[0].getsockname()[1]
    try:
        yield Server(
            base_url=f"http://127.0.0.1:{port}",
            recorder=recorder,
            engine_url=f"{ENGINE_URL_PREFIX}/{engine_tree_hash()}",
        )
    finally:
        uv.should_exit = True
        thread.join(timeout=10)
        remove_probe_routes()
        settings.local_tools_enabled = switched_on


@pytest.fixture(scope="session")
def playwright() -> Iterator[Playwright]:
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="session", params=["chromium", "webkit"])
def browser(request, playwright: Playwright) -> Iterator[Browser]:
    browser = playwright[request.param].launch()
    try:
        yield browser
    finally:
        browser.close()


@pytest.fixture
def page(browser: Browser) -> Iterator[Page]:
    # A fresh context per test: no cache, no service worker, no state from the
    # test before. bypass_csp stays off (the default), or nothing here would
    # prove anything.
    context = browser.new_context()
    try:
        yield context.new_page()
    finally:
        context.close()
