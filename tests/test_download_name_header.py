# SPDX-License-Identifier: AGPL-3.0-or-later
"""A result keeps its upload's name, whatever letters the name has.

The pages read a download's name from Content-Disposition, with a pattern for
``filename="…"`` only. Starlette sends a name with a space, an "ß" or any
letter beyond ASCII as ``filename*=utf-8''…`` alone, so "Mein Urlaub.jpg"
came back as "result.png". The PDF split and the AI redaction wrote the
header by hand and answered 500 for a name beyond Latin-1 ("Отчёт.pdf").

Every route now names its result through app/core/utils.py::content_disposition,
and the pages read the name through app/static/js/download-name.js. The
script runs here under Node — the repo has no JS test runner, and Node is on
the CI runners (as for tests/test_engine_modules.py) — and in Chromium and
WebKit in tests/browser/test_download_names.py.
"""

from __future__ import annotations

import ast
import io
import json
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image
from pypdf import PdfWriter

from app.api.routes.auth import get_optional_user
from app.core.batch import BATCH_ZIP_NAME
from app.core.utils import content_disposition
from app.main import app

ROOT = Path(__file__).resolve().parent.parent
JS = ROOT / "app" / "static" / "js"
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(
    NODE is None and not os.environ.get("CI"), reason="Node is not installed"
)

# Upload type, form fields and the suffix each route appends to the upload's
# stem (docs/api-reference.md, "Download names").
ROUTES = {
    "/api/v1/convert": ("jpg", {"target_format": "png"}, ".png"),
    "/api/v1/compress": ("jpg", {}, "_compressed.jpg"),
    "/api/v1/pdf/extract": ("pdf", {"pages": "1"}, "_pages.pdf"),
    "/api/v1/pdf/split": ("pdf", {}, "_pages.zip"),
    "/api/v1/pdf/compress": ("pdf", {"target_kb": "200"}, "_compressed.pdf"),
    "/api/v1/pdf/insert": ("pdf", {}, "_inserted.pdf"),
}


def _jpg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (200, 100, 50)).save(buf, format="JPEG")
    return buf.getvalue()


def _pdf() -> bytes:
    writer = PdfWriter()
    for _ in range(2):
        writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


_UPLOADS = {"jpg": (_jpg, "image/jpeg"), "pdf": (_pdf, "application/pdf")}


# A plain ASCII name with a space (filename="…" alone) and one beyond Latin-1
# (both forms) — the two the routes answered with "result" or a 500.
@pytest.mark.parametrize("stem", ["Mein Urlaub", "Отчёт"])
@pytest.mark.parametrize("endpoint", list(ROUTES))
def test_every_route_names_the_result_after_the_upload(client, auth_headers, endpoint, stem):
    ext, data, suffix = ROUTES[endpoint]
    build, mime = _UPLOADS[ext]
    files = [("file", (f"{stem}.{ext}", build(), mime))]
    if endpoint == "/api/v1/pdf/insert":
        files.append(("insert_file", ("Anhang.pdf", _pdf(), "application/pdf")))
    res = client.post(endpoint, headers=auth_headers, files=files, data=data)
    assert res.status_code == 200, res.text
    assert res.headers["content-disposition"] == content_disposition(stem + suffix)


@pytest.fixture
def free_user():
    """A Free account, whose batches take more than one file."""
    user = MagicMock()
    user.tier.value = "free"
    app.dependency_overrides[get_optional_user] = lambda: user
    yield
    app.dependency_overrides.pop(get_optional_user, None)


def test_batch_entries_keep_their_names(client, auth_headers, free_user):
    stems = ["Grüße an Oma", "Отчёт"]
    res = client.post(
        "/api/v1/convert/batch",
        headers=auth_headers,
        files=[("files", (f"{stem}.jpg", _jpg(), "image/jpeg")) for stem in stems],
        data={"target_formats": ["png", "png"]},
    )
    assert res.status_code == 200, res.text
    assert res.headers["content-disposition"] == content_disposition("filemorph-batch.zip")
    names = zipfile.ZipFile(io.BytesIO(res.content)).namelist()
    assert names == [f"{stem}.png" for stem in stems]


def test_no_route_writes_the_header_by_hand():
    """A header written by hand broke on the first name beyond Latin-1."""
    for path in sorted((ROOT / "app" / "api" / "routes").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        literals = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and re.search(r"filename\*?=", node.value)
        ]
        assert not literals, f"{path.name} writes Content-Disposition by hand: {literals}"


# ── The pages' side ──────────────────────────────────────────────────────────

_RUNNER = """\
const fs = require('fs');
const vm = require('vm');
const [script, input] = process.argv.slice(2);
const window = {};
vm.runInNewContext(fs.readFileSync(script, 'utf8'), { window });
const cases = JSON.parse(fs.readFileSync(input, 'utf8'));
const res = (header) => ({
  headers: { get: (key) => (key.toLowerCase() === 'content-disposition' ? header : null) },
});
console.log(JSON.stringify({
  names: cases.headers.map((header) => window.FM_downloadName(res(header), cases.fallback)),
  results: cases.sources.map(([name, suffix]) => window.FM_resultName(name, suffix)),
}));
"""

_FALLBACK = "picked_compressed.jpg"


def _run_js(tmp_path: Path, headers: list[str | None], sources: list[list[str]]) -> dict:
    """download-name.js under Node: the name each header gives, and what
    FM_resultName builds from each (source name, suffix)."""
    assert NODE, "CI must run download-name.js; Node is on the runners"
    runner = tmp_path / "run.cjs"
    runner.write_text(_RUNNER, encoding="utf-8", newline="\n")
    cases = tmp_path / "cases.json"
    cases.write_text(
        json.dumps({"headers": headers, "sources": sources, "fallback": _FALLBACK}),
        encoding="utf-8",
        newline="\n",
    )
    done = subprocess.run(
        [NODE, str(runner), str(JS / "download-name.js"), str(cases)],
        capture_output=True,
        encoding="utf-8",
        timeout=60,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


# Names as safe_download_name leaves them, and a few it never would: the
# pages read every one back from the header the server writes.
_ROUND_TRIP = [
    "Mein Urlaub.png",
    "Grüße an Oma.png",
    "Отчёт_pages.zip",
    "写真.png",
    "😀 Party.png",
    "foto (1).png",
    "50% Rabatt_compressed.jpg",
    "it's #1, ok.png",
    "a;b.png",
    'a"b.png',
    "Ünïcödé.redacted.txt",
    "x" * 196 + ".png",
]

# Headers of other shapes, and what the pages read from each.
_OTHER_HEADERS = {
    # Starlette's own form (charset in lower case), a token, escapes.
    "attachment; filename*=utf-8''Mein%20Urlaub.png": "Mein Urlaub.png",
    "attachment; filename=plain.png": "plain.png",
    'attachment; filename="a \\"b\\".png"': 'a "b".png',
    # A broken %-sequence or another charset: the plain form.
    "attachment; filename=\"x.png\"; filename*=UTF-8''%E0%A4%A": "x.png",
    "attachment; filename=\"x.png\"; filename*=ISO-8859-1''%E4.png": "x.png",
    # Nothing to read: the name the page built itself.
    "attachment": _FALLBACK,
    'attachment; filename=""': _FALLBACK,
}


@needs_node
def test_the_pages_read_the_name_the_server_writes(tmp_path):
    headers = [content_disposition(name) for name in _ROUND_TRIP]
    out = _run_js(tmp_path, [*headers, *_OTHER_HEADERS, None], [])
    assert out["names"] == [*_ROUND_TRIP, *_OTHER_HEADERS.values(), _FALLBACK]


@needs_node
def test_the_pages_fallback_is_the_picked_file_s_stem(tmp_path):
    """Without a readable header the name is the picked file's stem (as
    Python's Path.stem splits it, as the routes do) plus the tool's suffix.
    The browser cleans that name up for a download; the server's clean-up is
    not repeated."""
    sources = [
        ["Mein Urlaub.jpg", ".png"],
        ["Grüße.PDF", "_compressed.pdf"],
        ["archiv.tar.gz", "_pages.zip"],
        [".hidden", ".png"],
    ]
    out = _run_js(tmp_path, [], sources)
    assert out["results"] == [Path(name).stem + suffix for name, suffix in sources]


def _js_object(text: str, name: str) -> dict[str, str]:
    body = re.search(rf"const {name} = \{{(.*?)\}};", text, re.DOTALL)
    assert body, f"const {name} missing"
    return dict(re.findall(r"(\w+): '([^']*)'", body.group(1)))


def test_the_pdf_tools_fall_back_to_the_routes_suffixes():
    js = _js_object((JS / "pdf-tools.js").read_text(encoding="utf-8"), "RESULT_SUFFIX")
    pdf_routes = {e: suffix for e, (_, _, suffix) in ROUTES.items() if e.startswith("/api/v1/pdf/")}
    assert {f"/api/v1/pdf/{tool}": suffix for tool, suffix in js.items()} == pdf_routes


def test_the_converter_falls_back_to_the_routes_names():
    app_js = (JS / "app.js").read_text(encoding="utf-8")
    assert "'_compressed.' + getExtension(source)" in app_js
    assert f"let fallbackName = '{BATCH_ZIP_NAME}';" in app_js


@pytest.mark.parametrize("script", ["app.js", "pdf-tools.js", "redact.js"])
def test_every_tool_names_its_download_through_the_shared_script(script):
    text = (JS / script).read_text(encoding="utf-8")
    assert "FM_downloadName(res, " in text
    assert "filename=" not in text, f"{script} reads Content-Disposition with a pattern of its own"
