# SPDX-License-Identifier: AGPL-3.0-or-later
"""S3/Phase-D: guard that a request's temp dir (the upload and the result)
is gone once the request is over — after the response, however it is sent,
and when the request fails. Regression-guards against a path that leaves
`fm_*` dirs behind for the sweep."""

import dataclasses
import io
import sys
import tempfile
from pathlib import Path

import anyio
import httpx
import pytest
from PIL import Image
from pypdf import PdfWriter
from starlette import formparsers

from app.api.routes import compress as compress_route
from app.api.routes import convert as convert_route
from app.api.routes import pdf_pages as pdf_route
from app.core import quotas as quotas_module
from app.core.audit import AuditWriteError
from app.core.quotas import QUOTAS
from app.core.responses import TempDirFileResponse

# pikepdf's qpdf DLL clashes with the auth route's native deps on Windows (see
# test_pdf_compress.py); Linux CI and production run these.
_NEEDS_PIKEPDF = pytest.mark.skipif(
    sys.platform == "win32",
    reason="pikepdf qpdf DLL conflicts with auth-route native deps on Windows; "
    "Linux CI + production are unaffected.",
)


def _jpg_bytes(w: int = 50, h: int = 50) -> bytes:
    img = Image.new("RGB", (w, h), color=(100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _fm_dirs() -> set[Path]:
    tmp = Path(tempfile.gettempdir())
    return set(tmp.glob("fm_*"))


def test_convert_success_leaves_no_temp_dir(client, auth_headers):
    before = _fm_dirs()
    r = client.post(
        "/api/v1/convert",
        headers=auth_headers,
        files={"file": ("sample.jpg", _jpg_bytes(), "image/jpeg")},
        data={"target_format": "png"},
    )
    assert r.status_code == 200
    # Consume the body: the response removes the temp dir as it ends.
    assert len(r.content) > 0
    leaked = _fm_dirs() - before
    assert not leaked, f"Leaked temp dirs after successful convert: {leaked}"


def test_compress_success_leaves_no_temp_dir(client, auth_headers):
    before = _fm_dirs()
    r = client.post(
        "/api/v1/compress",
        headers=auth_headers,
        files={"file": ("sample.jpg", _jpg_bytes(), "image/jpeg")},
        data={"quality": "85"},
    )
    assert r.status_code == 200
    assert len(r.content) > 0
    leaked = _fm_dirs() - before
    assert not leaked, f"Leaked temp dirs after successful compress: {leaked}"


def test_convert_cap_rejection_leaves_no_temp_dir(client, auth_headers, monkeypatch):
    """The except-handler must clean up when the output-cap rejection fires:
    no response takes the temp dir over on that path."""
    original = QUOTAS["anonymous"]
    shrunk = dataclasses.replace(original, output_cap_bytes=100)
    monkeypatch.setitem(quotas_module.QUOTAS, "anonymous", shrunk)

    before = _fm_dirs()
    r = client.post(
        "/api/v1/convert",
        headers=auth_headers,
        files={"file": ("sample.jpg", _jpg_bytes(), "image/jpeg")},
        data={"target_format": "png"},
    )
    assert r.status_code == 413
    leaked = _fm_dirs() - before
    assert not leaked, f"Leaked temp dirs after rejected convert: {leaked}"


@pytest.mark.parametrize(
    ("route", "endpoint", "data"),
    [
        (convert_route, "/api/v1/convert", {"target_format": "png"}),
        (compress_route, "/api/v1/compress", {"quality": "85"}),
    ],
    ids=["convert", "compress"],
)
def test_a_failing_audit_write_does_not_keep_the_temp_dir(
    client, auth_headers, monkeypatch, route, endpoint, data
):
    """With the audit log failing closed (Compliance Edition), the error
    handler's audit write raises; the temp dir is gone before it runs."""

    async def audit_down(*args, **kwargs):
        raise AuditWriteError("the audit store is down")

    monkeypatch.setattr(route, "audit_record", audit_down)
    before = _fm_dirs()
    with pytest.raises(AuditWriteError):
        client.post(
            endpoint,
            headers=auth_headers,
            # Refused by the magic-byte check, inside the request's try block.
            files={"file": ("x.jpg", b"MZ" + bytes(64), "image/jpeg")},
            data=data,
        )
    leaked = _fm_dirs() - before
    assert not leaked, f"Leaked temp dirs after {endpoint}: {leaked}"


# ── Every route that answers with a file from its temp dir ───────────────────

_UPLOADS = {
    "jpg": lambda: ("sample.jpg", _jpg_bytes(), "image/jpeg"),
    "pdf": lambda: ("sample.pdf", _pdf_bytes(), "application/pdf"),
}

_FILE_ROUTES = [
    pytest.param("/api/v1/convert", {"file": "jpg"}, {"target_format": "png"}, id="convert"),
    pytest.param("/api/v1/compress", {"file": "jpg"}, {"quality": "85"}, id="compress"),
    pytest.param("/api/v1/pdf/extract", {"file": "pdf"}, {"pages": "1"}, id="pdf-extract"),
    pytest.param(
        "/api/v1/pdf/compress",
        {"file": "pdf"},
        {"target_kb": "100"},
        id="pdf-compress",
        marks=_NEEDS_PIKEPDF,
    ),
    pytest.param("/api/v1/pdf/insert", {"file": "pdf", "insert_file": "pdf"}, {}, id="pdf-insert"),
    # The one conversion whose result has the upload's name: written over it.
    pytest.param(
        "/api/v1/convert", {"file": "pdf"}, {"target_format": "pdf"}, id="convert-pdf-to-pdf"
    ),
]


@pytest.fixture
def spools(monkeypatch):
    """Every copy of an upload part the framework makes (a SpooledTemporaryFile,
    on disk above 1 MB)."""
    made: list = []

    class RecordingSpool(formparsers.SpooledTemporaryFile):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            made.append(self)

    monkeypatch.setattr(formparsers, "SpooledTemporaryFile", RecordingSpool)
    return made


@pytest.fixture
def answer_state(monkeypatch, spools):
    """What is on disk when a file route answers: the result's name, the
    names in the request dir, and (rolled to disk, closed) for each of the
    framework's copies of the uploads."""
    seen: list = []

    class Recording(TempDirFileResponse):
        def __init__(self, path, *args, tmp_dir, **kwargs):
            names = sorted(p.name for p in Path(tmp_dir).iterdir())
            copies = [(spool._rolled, spool.closed) for spool in spools]
            seen.append((Path(path).name, names, copies))
            super().__init__(path, *args, tmp_dir=tmp_dir, **kwargs)

    for route in (convert_route, compress_route, pdf_route):
        monkeypatch.setattr(route, "TempDirFileResponse", Recording)
    return seen


@pytest.mark.parametrize(("endpoint", "uploads", "data"), _FILE_ROUTES)
def test_only_the_result_is_left_when_the_response_starts(
    client, auth_headers, answer_state, endpoint, uploads, data
):
    """The upload goes as soon as the result exists, not when the download
    ends: the route's copy in the request dir, and the framework's own."""
    r = client.post(
        endpoint,
        headers=auth_headers,
        files={field: _UPLOADS[kind]() for field, kind in uploads.items()},
        data=data,
    )
    assert r.status_code == 200, r.text
    [(result, names, copies)] = answer_state
    assert names == [result]
    assert copies and all(closed for _rolled, closed in copies), copies


def test_a_large_upload_on_disk_is_closed_before_the_response(client, auth_headers, answer_state):
    """Above 1 MB the framework keeps its copy on disk, not in memory."""
    big = _jpg_bytes() + bytes(1_200_000)  # past the JPEG's end: ignored by the decoder
    r = client.post(
        "/api/v1/convert",
        headers=auth_headers,
        files={"file": ("big.jpg", big, "image/jpeg")},
        data={"target_format": "png"},
    )
    assert r.status_code == 200, r.text
    [(_result, _names, copies)] = answer_state
    assert copies == [(True, True)]


@pytest.mark.parametrize(
    ("route", "endpoint", "data"),
    [
        (convert_route, "/api/v1/convert/batch", {"target_formats": ["png"]}),
        (compress_route, "/api/v1/compress/batch", {"quality": "85"}),
    ],
    ids=["convert", "compress"],
)
def test_a_batch_closes_each_upload_before_its_zip(
    client, auth_headers, monkeypatch, spools, route, endpoint, data
):
    closed_at_zip: list[bool] = []
    real = route.build_batch_zip

    def spy(*args, **kwargs):
        closed_at_zip.extend(spool.closed for spool in spools)
        return real(*args, **kwargs)

    monkeypatch.setattr(route, "build_batch_zip", spy)
    # One file: the test client's tier takes one per batch.
    files = [("files", ("a.jpg", _jpg_bytes(), "image/jpeg"))]
    r = client.post(endpoint, headers=auth_headers, files=files, data=data)
    assert r.status_code == 200, r.text
    assert closed_at_zip == [True]


@pytest.mark.parametrize(("endpoint", "uploads", "data"), _FILE_ROUTES)
def test_a_download_cut_off_by_the_server_leaves_no_temp_dir(
    client, auth_headers, endpoint, uploads, data
):
    """Through the whole middleware stack: a server that reports a client
    gone mid-download (ASGI 2.4 — ``send`` raises) ends the response early,
    and the request's temp dir goes all the same."""
    request = httpx.Request(
        "POST",
        f"http://testserver{endpoint}",
        headers=auth_headers,
        files={field: _UPLOADS[kind]() for field, kind in uploads.items()},
        data=data,
    )
    body = request.read()
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": endpoint,
        "raw_path": endpoint.encode(),
        "root_path": "",
        "query_string": b"",
        "headers": [(name.lower(), value) for name, value in request.headers.raw],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
        "extensions": {},
        "state": {},
    }
    statuses: list[int] = []

    async def cut_off() -> None:
        gone = anyio.Event()
        received = False

        async def receive() -> dict:
            nonlocal received
            if not received:
                received = True
                return {"type": "http.request", "body": body, "more_body": False}
            await gone.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict) -> None:
            if message["type"] == "http.response.start":
                statuses.append(message["status"])
            elif message["type"] == "http.response.body":
                gone.set()
                raise OSError("the client went away")

        with anyio.fail_after(60), pytest.raises(OSError, match="the client went away"):
            await client.app(scope, receive, send)

    before = _fm_dirs()
    client.portal.call(cut_off)
    assert statuses == [200]
    leaked = _fm_dirs() - before
    assert not leaked, f"Leaked temp dirs after {endpoint}: {leaked}"


def test_no_route_answers_with_a_bare_file_response():
    """A result in a request's temp dir goes out as a TempDirFileResponse: a
    FileResponse would remove the dir only through a background task, which
    runs after a complete send."""
    app_dir = Path(__file__).resolve().parents[1] / "app"
    hits = [
        f"{path.relative_to(app_dir.parent)}:{number}"
        for path in sorted(app_dir.rglob("*.py"))
        if path.name != "responses.py"
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if "FileResponse(" in line.replace("TempDirFileResponse(", "")
    ]
    assert not hits, hits


# ── The response itself: the dir goes however the send ends ──────────────────


def _request_dir(tmp_path: Path) -> tuple[Path, Path]:
    tmp_dir = tmp_path / "fm_request"
    tmp_dir.mkdir()
    (tmp_dir / "upload.bin").write_bytes(b"upload")
    result = tmp_dir / "result.bin"
    result.write_bytes(b"x" * 200_000)  # a few chunks
    return tmp_dir, result


def _scope(spec: str) -> dict:
    # ASGI 2.3 (uvicorn): send goes quiet once the client is gone and the
    # response listens for the disconnect; ASGI 2.4: send raises.
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": spec},
        "method": "POST",
        "path": "/",
        "headers": [],
        "extensions": {},
    }


async def _receive() -> dict:
    # The body came with the request; a connected client sends nothing more.
    await anyio.sleep_forever()
    return {"type": "http.disconnect"}


@pytest.mark.parametrize("spec", ["2.3", "2.4"])
async def test_a_send_that_fails_midway_still_removes_the_temp_dir(tmp_path, spec):
    tmp_dir, result = _request_dir(tmp_path)

    async def send(message):
        if message["type"] == "http.response.body":
            raise OSError("the client went away")

    with pytest.raises(OSError):
        await TempDirFileResponse(result, tmp_dir=tmp_dir)(_scope(spec), _receive, send)
    assert not tmp_dir.exists()


@pytest.mark.parametrize("spec", ["2.3", "2.4"])
async def test_a_cancelled_send_still_removes_the_temp_dir(tmp_path, spec):
    """Cancelled the way a middleware stops a response whose client went
    away: the removal still runs, shielded from the cancellation."""
    tmp_dir, result = _request_dir(tmp_path)
    sending = anyio.Event()

    async def send(message):
        sending.set()
        await anyio.sleep_forever()

    async with anyio.create_task_group() as tg:
        tg.start_soon(TempDirFileResponse(result, tmp_dir=tmp_dir), _scope(spec), _receive, send)
        await sending.wait()
        tg.cancel_scope.cancel()
    assert not tmp_dir.exists()


# ── Scratch files of the programs a conversion starts ────────────────────────


@_NEEDS_PIKEPDF
def test_the_pdfa_intermediate_is_written_into_the_request_dir(monkeypatch, tmp_path):
    """Ghostscript's PDF/A rendering goes next to the result, so it leaves
    with the request's temp dir even when the conversion stops halfway."""
    from app.converters import _ghostscript as gs
    from app.converters.pdfa import PdfToPdfaConverter

    class Stop(Exception):
        pass

    written = []

    def rerender(src, dst, **kwargs):
        written.append(dst)
        raise Stop

    monkeypatch.setattr(gs, "is_available", lambda: True)
    monkeypatch.setattr(gs, "rerender_to_pdfa", rerender)
    request_dir = tmp_path / "fm_request"
    request_dir.mkdir()
    src = request_dir / "in.pdf"
    src.write_bytes(_pdf_bytes())

    with pytest.raises(Stop):
        PdfToPdfaConverter().convert(src, request_dir / "out.pdf")
    assert [p.parent for p in written] == [request_dir]
