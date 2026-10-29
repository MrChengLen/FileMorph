# SPDX-License-Identifier: AGPL-3.0-or-later
"""Server logs leave out the personal data the privacy notice says they leave out.

Pins six properties:

1. Email links carry their token in the URL fragment, and both landing
   pages read it from there — the browser never sends it to the server.
   Builder and page script must change together (propagation guard).
2. uvicorn's access-log line keeps the path but drops the query string —
   checked against a real uvicorn server, so a uvicorn upgrade that logs
   the request differently turns this red instead of leaking quietly.
3. An SMTP send logs neither the recipient address nor the subject, and a
   failure chains no exception whose text could quote the address.
4. The concurrency limiter logs the actor kind only — no IP, no account id.
5. A tripped contact-form honeypot logs no IP, and a database error's text
   carries no statement values.
6. A logged exception keeps its types and traceback but not its text; the
   loggers of WeasyPrint, fontTools and pypdf and library warnings are
   silent; uvicorn's own exception line drops the text too; and the tools'
   stderr reaches an error only with APP_DEBUG — all of these can quote the
   uploaded file.
"""

from __future__ import annotations

import asyncio
import errno
import logging
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from unittest.mock import AsyncMock

import aiosmtplib
import pytest
import uvicorn
from uvicorn.logging import AccessFormatter

from app.api.routes.auth import _build_reset_url, _build_verify_url
from app.core import concurrency as concurrency_module
from app.core import email as email_mod
from app.core.concurrency import ConcurrencyExhausted, acquire_slot
from app.core.config import settings
from app.core.logging_config import _ACCESS_LOG_PATH_ONLY, JsonLogFormatter

STATIC_JS = Path(__file__).resolve().parents[1] / "app" / "static" / "js"


# ── 1. Tokens in the fragment ─────────────────────────────────────────────────


def test_link_builders_put_the_token_in_the_fragment():
    assert _build_verify_url("tok").endswith("/verify-email#token=tok")
    assert _build_reset_url("tok").endswith("/reset-password#token=tok")


@pytest.mark.parametrize("script", ["verify-email.js", "reset-password.js"])
def test_landing_page_scripts_read_the_fragment(script):
    source = (STATIC_JS / script).read_text(encoding="utf-8")
    assert "window.location.hash" in source
    # A link mailed before the change (?token=) is moved behind "#".
    assert "window.history.replaceState" in source


# ── 2. Access log without query string ───────────────────────────────────────


def _access_record(path: str) -> logging.LogRecord:
    # Same message and argument tuple uvicorn's HTTP protocols log.
    return logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("203.0.113.7:51234", "GET", path, "1.1", 200),
        None,
    )


def test_access_log_line_drops_the_query_string():
    record = _access_record("/verify-email?token=eyJhbGciOi.secret.sig&lang=de")
    assert _ACCESS_LOG_PATH_ONLY.filter(record) is True
    line = AccessFormatter(
        '%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False
    ).format(record)
    assert '"GET /verify-email HTTP/1.1" 200' in line
    assert "token" not in line and "lang" not in line


def test_access_log_line_without_query_is_unchanged():
    record = _access_record("/de/pricing")
    _ACCESS_LOG_PATH_ONLY.filter(record)
    assert record.getMessage() == '203.0.113.7:51234 - "GET /de/pricing HTTP/1.1" 200'


def test_app_attaches_the_access_log_filter_once(client):
    # configure_logging() runs at import and again at startup.
    assert logging.getLogger("uvicorn.access").filters.count(_ACCESS_LOG_PATH_ONLY) == 1


def test_real_uvicorn_access_line_has_no_query(client, caplog):
    """The installed uvicorn, serving a real socket, logs the path only."""

    async def asgi_app(scope, receive, send):
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    server = uvicorn.Server(
        uvicorn.Config(asgi_app, host="127.0.0.1", port=0, lifespan="off", log_config=None)
    )
    thread = threading.Thread(target=server.run, daemon=True)
    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        thread.start()
        deadline = time.monotonic() + 10
        while not server.started:
            assert time.monotonic() < deadline, "uvicorn did not start"
            time.sleep(0.02)
        port = server.servers[0].sockets[0].getsockname()[1]
        url = f"http://127.0.0.1:{port}/verify-email?token=secret-token&lang=de"
        with urllib.request.urlopen(url, timeout=10) as response:
            assert response.status == 204
        server.should_exit = True
        thread.join(timeout=10)

    lines = [r.getMessage() for r in caplog.records if r.name == "uvicorn.access"]
    assert any('"GET /verify-email HTTP/1.1" 204' in line for line in lines), lines
    assert not [line for line in lines if "secret-token" in line or "lang=" in line]


# ── 3. SMTP logging ───────────────────────────────────────────────────────────


@pytest.fixture
def smtp_configured(monkeypatch):
    monkeypatch.setattr(settings, "smtp_host", "smtp.example.invalid")
    monkeypatch.setattr(settings, "smtp_from_email", "no-reply@example.org")


async def test_failed_send_logs_no_address_or_subject(smtp_configured, monkeypatch, caplog):
    refused = aiosmtplib.SMTPRecipientsRefused(
        [
            aiosmtplib.SMTPRecipientRefused(
                550, "5.1.1 <victim@example.com>: no", "victim@example.com"
            )
        ]
    )
    monkeypatch.setattr(email_mod.aiosmtplib, "send", AsyncMock(side_effect=refused))

    with caplog.at_level(logging.INFO), pytest.raises(email_mod.EmailSendError) as excinfo:
        await email_mod.send_email(
            to="victim@example.com", subject="[FileMorph Kontakt] private words", html="x", text="x"
        )

    assert excinfo.value.__cause__ is None
    assert excinfo.value.__suppress_context__ is True
    assert "victim@" not in caplog.text
    assert "private words" not in caplog.text
    assert "error=SMTPRecipientsRefused detail=[550]" in caplog.text
    assert "to_domain=example.com" in caplog.text


async def test_failed_connect_logs_aiosmtplibs_own_text(smtp_configured, monkeypatch, caplog):
    error = aiosmtplib.SMTPConnectError(
        "Error connecting to smtp.example.invalid on port 587: [Errno 111] Connection refused"
    )
    monkeypatch.setattr(email_mod.aiosmtplib, "send", AsyncMock(side_effect=error))

    with caplog.at_level(logging.INFO), pytest.raises(email_mod.EmailSendError):
        await email_mod.send_email(to="bob@example.com", subject="s", html="x", text="x")

    assert "error=SMTPConnectError" in caplog.text
    assert "on port 587" in caplog.text
    assert "bob@" not in caplog.text


async def test_unconfigured_send_logs_no_subject(monkeypatch, caplog):
    monkeypatch.setattr(settings, "smtp_host", "")

    with caplog.at_level(logging.INFO):
        await email_mod.send_email(
            to="carol@example.com", subject="[FileMorph Kontakt] private words", html="x", text="x"
        )

    assert "SMTP not configured (to_domain=example.com)" in caplog.text
    assert "private words" not in caplog.text
    assert "carol@" not in caplog.text


async def test_successful_send_logs_no_subject(smtp_configured, monkeypatch, caplog):
    monkeypatch.setattr(email_mod.aiosmtplib, "send", AsyncMock())

    with caplog.at_level(logging.INFO):
        await email_mod.send_email(
            to="alice@example.com", subject="[FileMorph Kontakt] private words", html="x", text="x"
        )

    assert "send_email ok to_domain=example.com" in caplog.text
    assert "private words" not in caplog.text
    assert "alice@" not in caplog.text


# ── 4. Concurrency limiter ────────────────────────────────────────────────────


@pytest.fixture
def fresh_limiter(monkeypatch):
    concurrency_module._reset_for_tests()
    monkeypatch.setattr(settings, "concurrency_acquire_timeout_seconds", 0.05)
    monkeypatch.setattr(settings, "concurrency_retry_after_seconds", 1)
    yield
    concurrency_module._reset_for_tests()


async def _hold_one_slot(actor_id: str, tier: str) -> tuple[asyncio.Task, asyncio.Event]:
    entered, release = asyncio.Event(), asyncio.Event()

    async def _hold():
        async with acquire_slot(actor_id=actor_id, tier=tier):
            entered.set()
            await release.wait()

    task = asyncio.create_task(_hold())
    await asyncio.wait_for(entered.wait(), timeout=1)
    return task, release


def _assert_limiter_logs_kind_only(caplog, *secrets: str) -> None:
    records = [r for r in caplog.records if r.getMessage().startswith("concurrency:")]
    assert records
    for record in records:
        rendered = JsonLogFormatter().format(record)
        assert record.actor_kind in {"ip", "user"}
        for secret in secrets:
            assert secret not in rendered


async def test_per_actor_log_names_no_ip(fresh_limiter, caplog):
    actor = "ip:203.0.113.7"
    task, release = await _hold_one_slot(actor, "anonymous")
    with caplog.at_level(logging.INFO), pytest.raises(ConcurrencyExhausted):
        async with acquire_slot(actor_id=actor, tier="anonymous"):
            pass
    release.set()
    await task
    _assert_limiter_logs_kind_only(caplog, "203.0.113.7")


async def test_global_log_names_no_account_id(fresh_limiter, monkeypatch, caplog):
    monkeypatch.setattr(settings, "max_global_concurrency", 1)
    concurrency_module._reset_for_tests()
    account = "7f9c0d2e-1111-4222-8333-444455556666"
    task, release = await _hold_one_slot("user:someone-else", "pro")
    with caplog.at_level(logging.INFO), pytest.raises(ConcurrencyExhausted):
        async with acquire_slot(actor_id=f"user:{account}", tier="pro"):
            pass
    release.set()
    await task
    _assert_limiter_logs_kind_only(caplog, account)


# ── 5. Contact-form honeypot ──────────────────────────────────────────────────


def test_honeypot_log_has_no_ip(client, monkeypatch, caplog):
    monkeypatch.setattr(email_mod, "send_email", AsyncMock())
    monkeypatch.setattr("app.api.routes.contact.audit_record", AsyncMock())

    with caplog.at_level(logging.INFO):
        r = client.post(
            "/api/v1/contact",
            json={
                "email": "bot@example.com",
                "message": "y" * 30,
                "website": "http://spam.example/",
            },
        )

    assert r.status_code == 200
    assert "honeypot tripped" in caplog.text
    # TestClient connects as host "testclient"; the old line logged it.
    assert "testclient" not in caplog.text


def test_database_errors_hide_statement_values():
    # A failed INSERT would otherwise print its values — an email address,
    # a password hash — into the error the 500 handler logs. The engine is
    # built at import only when DATABASE_URL is set, so pin the source.
    source = (Path(__file__).resolve().parents[1] / "app" / "db" / "base.py").read_text(
        encoding="utf-8"
    )
    assert "hide_parameters=True" in source


# ── 6. Error texts from tools and libraries ──────────────────────────────────


def _logged_failure(exception_text: bool) -> str:
    # Built at runtime: the traceback quotes this file's source lines, and
    # those must not contain the marker themselves.
    cause_text, failure_text = "SECRET" + "-CAUSE", "SECRET" + "-FRAGMENT"
    try:
        try:
            raise ValueError(cause_text)
        except ValueError as cause:
            raise RuntimeError(failure_text) from cause
    except RuntimeError:
        record = logging.getLogger("t").makeRecord(
            "t",
            logging.ERROR,
            __file__,
            0,
            "Conversion error: %s -> %s",
            ("pdf", "txt"),
            sys.exc_info(),
        )
    return JsonLogFormatter(exception_text=exception_text).format(record)


def test_logged_failure_keeps_types_and_frames_but_not_text():
    line = _logged_failure(exception_text=False)
    assert "RuntimeError" in line and "ValueError" in line
    assert "test_log_privacy.py" in line  # the frames stay
    assert "direct cause of the following exception" in line
    assert "SECRET" not in line


def _text_free(exc: BaseException) -> str:
    from app.core.logging_config import _exception_without_text

    return _exception_without_text(exc)


def test_implicit_context_and_from_none_follow_python():
    secret = "SECRET" + "-CONTEXT"
    try:
        try:
            raise KeyError(secret)
        except KeyError:
            raise ValueError(secret)  # noqa: B904 — the implicit context is the point
    except ValueError as exc:
        implicit = _text_free(exc)
    try:
        try:
            raise KeyError(secret)
        except KeyError:
            raise ValueError(secret) from None
    except ValueError as exc:
        suppressed = _text_free(exc)
    assert "During handling of the above exception" in implicit and "KeyError" in implicit
    assert "KeyError" not in suppressed
    assert secret not in implicit + suppressed


def test_oserror_keeps_its_errno_name():
    line = _text_free(OSError(errno.ENOSPC, "SECRET" + "-PATH"))
    assert "OSError [ENOSPC]" in line and "SECRET" not in line


def test_app_debug_logs_the_failure_text():
    line = _logged_failure(exception_text=True)
    assert "SECRET-FRAGMENT" in line and "SECRET-CAUSE" in line


def test_document_libraries_are_silenced(client):
    # configure_logging() ran at import and at startup.
    for name in ("weasyprint", "fontTools", "pypdf", "py.warnings"):
        assert logging.getLogger(name).level == logging.CRITICAL, name


def test_uvicorn_exception_line_drops_the_text(client):
    from app.core.logging_config import _UVICORN_EXCEPTION_WITHOUT_TEXT

    assert _UVICORN_EXCEPTION_WITHOUT_TEXT in logging.getLogger("uvicorn.error").filters
    marker = "SECRET" + "-ASGI"  # the traceback quotes the raise line below
    try:
        raise RuntimeError(marker)
    except RuntimeError:
        record = logging.getLogger("uvicorn.error").makeRecord(
            "uvicorn.error",
            logging.ERROR,
            __file__,
            0,
            "Exception in ASGI application\n",
            (),
            sys.exc_info(),
        )
    assert _UVICORN_EXCEPTION_WITHOUT_TEXT.filter(record) is True
    assert record.exc_info is None
    assert "RuntimeError" in record.getMessage() and "SECRET" not in record.getMessage()


def _malformed_pdf(marker: str) -> bytes:
    # A page dictionary with a stray word where a key belongs: pypdf warns
    # about it and quotes the raw bytes around it.
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] "
        b"/PieceInfo << /Note Patient " + marker.encode() + b" DOB 1980 >> /Contents 4 0 R >>",
        b"<< /Length 0 >>\nstream\n\nendstream",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objs) + 1,
        xref,
    )
    return bytes(out)


def test_malformed_pdf_quotes_nothing_into_the_log(client, tmp_path, caplog):
    from app.converters.pdf_pages import extract_pages

    marker = "Muster" + "mann"
    src = tmp_path / "in.pdf"
    src.write_bytes(_malformed_pdf(marker))
    with caplog.at_level(logging.DEBUG):
        extract_pages(src, tmp_path / "out.pdf", "1")
    assert marker not in caplog.text


def _failed_run(*args, **kwargs):
    return subprocess.CompletedProcess(args, 1, b"", b"title : SECRET-METADATA\nboom")


@pytest.mark.parametrize("debug", [False, True])
def test_tool_errors_quote_stderr_only_with_app_debug(monkeypatch, tmp_path, debug):
    import ffmpeg

    from app.converters import _ffmpeg, _ghostscript, document

    monkeypatch.setattr(settings, "app_debug", debug)
    monkeypatch.setattr(subprocess, "run", _failed_run)
    monkeypatch.setattr(document, "_run_soffice", _failed_run)
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(_ghostscript, "_GS_BINARY", "gs")
    errors = []
    with pytest.raises(_ffmpeg.FFmpegError) as excinfo:
        _ffmpeg.run_ffmpeg(ffmpeg.input("in.mp3").output("out.wav"))
    errors.append(str(excinfo.value))
    with pytest.raises(_ghostscript.GhostscriptError) as excinfo:
        _ghostscript.rerender_to_pdfa(tmp_path / "in.pdf", tmp_path / "out.pdf", icc_bytes=b"icc")
    errors.append(str(excinfo.value))
    with pytest.raises(RuntimeError) as excinfo:
        document._convert_via_libreoffice(tmp_path / "in.docx", tmp_path / "out.pdf", 5)
    errors.append(str(excinfo.value))
    assert all(("SECRET-METADATA" in error) is debug for error in errors), errors
    assert all("exit" in error or "status" in error for error in errors), errors
    # soffice exits 0 but writes no PDF: the same rule for its stderr.
    monkeypatch.setattr(
        document,
        "_run_soffice",
        lambda *a, **k: subprocess.CompletedProcess(a, 0, b"", b"SECRET-METADATA"),
    )
    with pytest.raises(RuntimeError) as excinfo:
        document._convert_via_libreoffice(tmp_path / "in.docx", tmp_path / "out.pdf", 5)
    assert ("SECRET-METADATA" in str(excinfo.value)) is debug


def _weasyprint_works() -> bool:
    try:
        import weasyprint

        weasyprint.HTML(string="<p>probe</p>").write_pdf()
        return True
    except Exception:
        return False


@pytest.mark.skipif(
    not _weasyprint_works(),
    reason="WeasyPrint native deps (libgobject/pango) unavailable on this host",
)
def test_refused_url_from_an_html_upload_is_not_logged(client, tmp_path, caplog):
    from app.converters.document import HtmlToPdfConverter

    src = tmp_path / "in.html"
    src.write_text('<p>x</p><img src="https://marker.invalid/SECRET-URL.png">', encoding="utf-8")
    with caplog.at_level(logging.DEBUG):
        HtmlToPdfConverter().convert(src, tmp_path / "out.pdf")
    assert "SECRET-URL" not in caplog.text
