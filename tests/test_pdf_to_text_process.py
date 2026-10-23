# SPDX-License-Identifier: AGPL-3.0-or-later
"""PDF → TXT runs pypdf in a child process with a time limit.

``PdfToTxtConverter`` starts ``app/converters/_pdf_text.py``, stops it after
``_TEXT_TIME_LIMIT_SECONDS`` and maps its outcome to the usual errors. The
encrypted / unreadable cases go through the real child in
tests/test_pdf_error_messages.py, test_pdf_unsupported_encryption.py and
test_pdf_unreadable.py.
"""

from __future__ import annotations

import io
import logging
import subprocess
import sys

import pytest
from pypdf import PdfWriter

from app.converters import _isolated, _pdf_text, document
from app.converters.base import (
    EncryptedPdfError,
    InvalidInputError,
    UnsupportedPdfEncryptionError,
)

_MIB = 1024 * 1024


def _pdf(pages: int) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _pdf_with_content(content: bytes) -> bytes:
    """One page drawing ``content``, with Helvetica as /F1."""
    stream = b"<< /Length %d >>\nstream\n" % len(content) + content + b"\nendstream"
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        stream,
    ]
    out = bytearray(b"%PDF-1.7\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def _to_txt(client, auth_headers, pdf: bytes):
    return client.post(
        "/api/v1/convert",
        headers=auth_headers,
        files={"file": ("doc.pdf", pdf, "application/pdf")},
        data={"target_format": "txt"},
    )


# ── Through the route, with the real child ───────────────────────────────────


def test_pdf_over_the_page_cap_gets_400(client, auth_headers, monkeypatch):
    monkeypatch.setattr(document, "_TEXT_MAX_PAGES", 2)
    res = _to_txt(client, auth_headers, _pdf(3))
    assert res.status_code == 400
    assert res.json()["detail"] == document._TEXT_TOO_MANY_PAGES
    assert res.headers["X-FileMorph-Error-Code"] == "invalid_input"


def test_pdf_at_the_page_cap_is_converted(client, auth_headers, monkeypatch):
    monkeypatch.setattr(document, "_TEXT_MAX_PAGES", 2)
    assert _to_txt(client, auth_headers, _pdf(2)).status_code == 200


def test_extraction_past_the_time_limit_gets_400(client, auth_headers, monkeypatch):
    monkeypatch.setattr(document, "_TEXT_TIME_LIMIT_SECONDS", 0.01)
    res = _to_txt(client, auth_headers, _pdf(1))
    assert res.status_code == 400
    assert res.json()["detail"] == document._TEXT_TOO_LARGE


def test_text_is_extracted(client, auth_headers):
    res = _to_txt(client, auth_headers, _pdf_with_content(b"BT /F1 12 Tf 20 100 Td (Hallo) Tj ET"))
    assert res.status_code == 200
    assert "Hallo" in res.text


# ── The parent's side, with a stand-in child ─────────────────────────────────


def _fake_child(stdout: str, returncode: int = 0, seen: dict | None = None):
    def run(command, **kwargs):
        if seen is not None:
            seen.update(kwargs, command=command)
        return subprocess.CompletedProcess(command, returncode, stdout, None)

    return run


def test_the_child_gets_no_secrets_no_stdin_and_no_stderr_pipe(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "not-for-the-child")
    seen: dict = {}
    monkeypatch.setattr(document.subprocess, "run", _fake_child("ok", seen=seen))
    document.PdfToTxtConverter().convert(tmp_path / "in.pdf", tmp_path / "out.txt")
    assert "JWT_SECRET" not in seen["env"]
    assert seen["stdin"] is subprocess.DEVNULL
    assert seen["stderr"] is subprocess.DEVNULL
    assert seen["command"][:3] == [sys.executable, "-m", "app.converters._pdf_text"]
    assert seen["timeout"] == document._TEXT_TIME_LIMIT_SECONDS


@pytest.mark.parametrize(
    ("stdout", "error", "detail"),
    [
        ("too_large", InvalidInputError, document._TEXT_TOO_LARGE),
        ("too_many_pages", InvalidInputError, document._TEXT_TOO_MANY_PAGES),
        ("encrypted", EncryptedPdfError, EncryptedPdfError.message),
        (
            "unsupported_encryption",
            UnsupportedPdfEncryptionError,
            UnsupportedPdfEncryptionError.message,
        ),
        (
            "unreadable LimitReachedError",
            InvalidInputError,
            "Could not read the PDF. Verify the file is valid.",
        ),
    ],
)
def test_child_outcomes_map_to_the_usual_errors(tmp_path, monkeypatch, stdout, error, detail):
    monkeypatch.setattr(document.subprocess, "run", _fake_child(stdout))
    with pytest.raises(error) as caught:
        document.PdfToTxtConverter().convert(tmp_path / "in.pdf", tmp_path / "out.txt")
    assert type(caught.value) is error
    assert str(caught.value) == detail


def test_an_unreadable_pdf_logs_the_error_class_only(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(document.subprocess, "run", _fake_child("unreadable LimitReachedError"))
    with caplog.at_level(logging.INFO, logger="app.converters.document"):
        with pytest.raises(InvalidInputError):
            document.PdfToTxtConverter().convert(tmp_path / "in.pdf", tmp_path / "out.txt")
    assert "unreadable PDF: LimitReachedError" in caplog.messages


def test_a_child_stopped_by_a_limit_gets_400(tmp_path, monkeypatch):
    # Stopped by a signal (the CPU limit, the kernel's OOM killer): no outcome.
    monkeypatch.setattr(document.subprocess, "run", _fake_child("", returncode=-9))
    with pytest.raises(InvalidInputError) as caught:
        document.PdfToTxtConverter().convert(tmp_path / "in.pdf", tmp_path / "out.txt")
    assert str(caught.value) == document._TEXT_TOO_LARGE


def test_a_failed_child_is_logged_by_type(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(document.subprocess, "run", _fake_child("failed KeyError", returncode=1))
    with caplog.at_level(logging.WARNING, logger="app.converters.document"):
        with pytest.raises(RuntimeError):
            document.PdfToTxtConverter().convert(tmp_path / "in.pdf", tmp_path / "out.txt")
    assert "pdf to txt child failed (status 1): KeyError" in caplog.messages


@pytest.mark.parametrize("stdout", ["", "failed KeyError", "something else"])
def test_any_other_child_outcome_is_a_server_error(tmp_path, monkeypatch, stdout):
    monkeypatch.setattr(document.subprocess, "run", _fake_child(stdout, returncode=1))
    with pytest.raises(RuntimeError, match="pdf to txt child failed"):
        document.PdfToTxtConverter().convert(tmp_path / "in.pdf", tmp_path / "out.txt")


# ── The child itself ─────────────────────────────────────────────────────────


def test_the_child_writes_the_text(tmp_path):
    src = tmp_path / "in.pdf"
    src.write_bytes(_pdf(2))
    assert _pdf_text.extract(src, tmp_path / "out.txt", max_pages=2) == "ok"
    assert (tmp_path / "out.txt").read_text(encoding="utf-8") == "\n\n"


def test_the_child_writes_no_diagnostics(tmp_path):
    # Content pypdf repairs, with a warning for each operator.
    src = tmp_path / "in.pdf"
    src.write_bytes(_pdf_with_content(b"/X Do\n" * 1000))
    res = subprocess.run(
        [sys.executable, "-m", "app.converters._pdf_text", str(src), str(tmp_path / "o"), "10"],
        capture_output=True,
        encoding="utf-8",
        cwd=_isolated._APP_ROOT,
        check=True,
    )
    assert res.stdout.strip() == "ok"
    assert res.stderr == ""


@pytest.mark.skipif(sys.platform != "linux", reason="the limits apply on Linux")
def test_the_child_caps_its_memory_cpu_time_and_file_size(tmp_path):
    src, out = tmp_path / "in.pdf", tmp_path / "out.txt"
    src.write_bytes(_pdf(1))
    probe = (
        "import ctypes, resource, runpy, signal, sys; "
        f"sys.argv = ['x', {str(src)!r}, {str(out)!r}, '10']; "
        "runpy.run_module('app.converters._pdf_text', run_name='__main__'); "
        "print(*('%d/%d' % resource.getrlimit(limit) for limit in (resource.RLIMIT_AS, "
        "resource.RLIMIT_CPU, resource.RLIMIT_FSIZE, resource.RLIMIT_CORE)), "
        "ctypes.CDLL(None).prctl(3, 0, 0, 0, 0), "  # PR_GET_DUMPABLE
        "signal.getsignal(signal.SIGXFSZ) == signal.SIG_DFL)"
    )
    res = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        encoding="utf-8",
        cwd=_isolated._APP_ROOT,
        check=True,
    )
    # Each limit soft/hard alike, so the child can't raise it again.
    caps = (1024 * _MIB, _pdf_text._CPU_LIMIT_SECONDS, 1024 * _MIB, 0)
    assert res.stdout.split() == ["ok", *(f"{cap}/{cap}" for cap in caps), "0", "True"]
