# SPDX-License-Identifier: AGPL-3.0-or-later
"""The ``local`` CSP profile, as Chromium and WebKit enforce it.

tests/test_csp_profiles.py pins the header the app sends. Whether that header
keeps a page from sending data is the browsers' part, and this file checks it:
a page under ``local`` tries each channel the profile refuses — fetch,
XMLHttpRequest, sendBeacon, WebSocket, EventSource and a form post — and none
of the requests reaches the server; the browser reports a CSP violation for
each instead. The same probes on a ``default`` page do reach the server: that
is what makes the first test mean something.

What ``local`` does not stop (navigation, pop-up windows, workers started
from outside the engine, WebRTC, requests for images and scripts from this
origin) is listed in app/core/csp.py; tests/test_engine_code.py looks for it
in the engine's own code.
"""

from __future__ import annotations

import time
import uuid

import pytest
from playwright.sync_api import Page

from app.main import _CSP_HEADERS

# Channel → the CSP directive that refuses it under ``local``.
_DATA_CHANNELS = {
    "fetch": "connect-src",
    "xhr": "connect-src",
    "beacon": "connect-src",
    "websocket": "connect-src",
    "eventsource": "connect-src",
    "form": "form-action",
}

# The channels a browser may report refused without the URL it refused.
_REPORTED_WITHOUT_URL = {"websocket", "form"}

# How long a refused request gets to show up anyway, after a later, allowed
# one has arrived: a beacon or a WebSocket takes a way of its own.
_GRACE = 1.0

# Pages of the app that must load without a single CSP violation.
_PAGES = ["/", "/de/tools", "/de/compress", "/en/convert/jpg-to-pdf"]


def _open(page: Page, server, profile: str) -> None:
    response = page.goto(f"{server.base_url}/__bt/page/{profile}")
    assert response is not None and response.status == 200
    assert response.headers["content-security-policy"] == _CSP_HEADERS[profile]
    page.wait_for_function("window.fmProbe !== undefined")


def _hit(channel: str, tag: str) -> str:
    return f"/__bt/hit/{channel}-{tag}"


@pytest.mark.parametrize("channel", sorted(_DATA_CHANNELS))
def test_a_local_page_refuses_every_data_channel(page: Page, server, channel: str):
    _open(page, server, "local")
    tag = uuid.uuid4().hex
    since = len(server.recorder.paths)
    page.evaluate("([channel, tag]) => window.fmProbe.run(channel, tag)", [channel, tag])
    # An allowed request after the refused one: once it has arrived, the
    # refused one would have too.
    page.evaluate("tag => window.fmProbe.run('image', tag)", tag)
    assert server.wait_for(_hit("image", tag)), "the allowed image request never arrived"
    time.sleep(_GRACE)
    # Everything of the probe page's that reached the server meanwhile, but a
    # late request of an earlier test (another tag, or an app page's own):
    # the allowed image, and nothing else.
    arrived = [
        path
        for path in server.recorder.paths[since:]
        if path.startswith("/__bt/") and (not path.startswith("/__bt/hit/") or path.endswith(tag))
    ]
    assert arrived == [_hit("image", tag)], (
        f"{channel}: requests reached the server from a page under the local profile: {arrived}"
    )
    violations = page.evaluate("window.fmProbe.violations")
    assert any(
        violation["directive"] == _DATA_CHANNELS[channel]
        and _hit(channel, tag) in (violation["blocked"] or "")
        for violation in violations
    ) or (
        channel in _REPORTED_WITHOUT_URL
        and any(
            violation["directive"] == _DATA_CHANNELS[channel] and not violation["blocked"]
            for violation in violations
        )
    ), f"{channel}: no {_DATA_CHANNELS[channel]} violation reported: {violations}"


@pytest.mark.parametrize("channel", sorted(_DATA_CHANNELS))
def test_a_default_page_does_send(page: Page, server, channel: str):
    """The control: the same probe on a page without the local profile reaches
    the server, so the recorder and the probes work."""
    _open(page, server, "default")
    tag = uuid.uuid4().hex
    page.evaluate("([channel, tag]) => window.fmProbe.run(channel, tag)", [channel, tag])
    assert server.wait_for(_hit(channel, tag)), (
        f"{channel}: the probe never reached the server, even without the local profile"
    )
    assert page.evaluate("window.fmProbe.violations") == []


def test_a_local_page_loads_its_scripts_and_engine_modules(page: Page, server):
    """Scripts and modules from this origin still load: the page's own, and a
    module from the engine mount with its type and its ``local`` headers."""
    _open(page, server, "local")
    url = f"{server.engine_url}/delivery.js"
    with page.expect_response(lambda response: response.url.endswith(url)) as served:
        names = page.evaluate("url => window.fmProbe.engine(url)", url)
    assert names == ["DELIVERY"]
    headers = served.value.headers
    assert headers["content-type"] == "text/javascript; charset=utf-8"
    assert headers["content-security-policy"] == _CSP_HEADERS["local"]
    assert page.evaluate("window.fmProbe.violations") == []


def test_a_local_page_is_silent_until_it_is_asked(page: Page, server):
    """Opening the page asks for the page and its script, nothing else. The
    browser's own request log says so, and the server's (which sees what the
    log leaves out, a favicon say); the log is shown to see a request too, or
    its silence would prove nothing."""
    requested: list[str] = []
    page.on("request", lambda request: requested.append(request.url))
    since = len(server.recorder.paths)
    _open(page, server, "local")
    page.wait_for_load_state("networkidle")
    loaded = ["/__bt/page/local", "/__bt/probe.js"]
    assert [url.removeprefix(server.base_url) for url in requested] == loaded
    assert [p for p in server.recorder.paths[since:] if not p.startswith("/__bt/hit/")] == loaded
    tag = uuid.uuid4().hex
    page.evaluate("tag => window.fmProbe.run('image', tag)", tag)
    assert server.wait_for(_hit("image", tag))
    assert f"{server.base_url}{_hit('image', tag)}" in requested


@pytest.mark.parametrize("path", _PAGES)
def test_the_app_s_pages_load_without_a_csp_violation(page: Page, server, path: str):
    """The app's own pages, under their real profiles: a script, style or
    image the CSP refuses shows up here before a visitor's console does."""
    # Playwright adds this listener before the page's own code runs; the
    # page's CSP does not apply to it.
    page.add_init_script(
        "window.__violations = [];"
        "document.addEventListener('securitypolicyviolation', (e) =>"
        " window.__violations.push(`${e.effectiveDirective} ${e.blockedURI}`));"
    )
    response = page.goto(f"{server.base_url}{path}")
    assert response is not None and response.status == 200
    page.wait_for_load_state("networkidle")
    assert page.evaluate("window.__violations") == []
