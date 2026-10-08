# SPDX-License-Identifier: AGPL-3.0-or-later
"""A password-protected or page-less PDF gets an error that names the fix.

A PDF that needs a user password fell into the catch-all of every PDF path:
pypdf's ``FileNotDecryptedError`` (pikepdf's ``PasswordError`` on compress and
PDF/A) became a generic "verify the file is valid" error (a 500 plus a logged
traceback on PDF/A), and the user, whose file is fine, was told to check it. Now
each path raises ``EncryptedPdfError``: the routes answer ``400`` with
``X-FileMorph-Error-Code: pdf_encrypted`` and a fixed message, the batch route
puts that message in the per-file ``error_message``. A PDF with only an *owner*
password (restrictions, no user password) opens without one and must keep
working; those tests catch a future "reject every encrypted PDF" shortcut.

Three neighbouring fixes are pinned here too:

* a PDF without pages sent ``invalid_page_selection`` from /pdf/extract, so the
  web page blamed the user's selection; it is ``invalid_pdf`` now;
* PDF -> PDF keeps every page when nothing is selected and is held to the
  selection cap, so over it the message may not talk about a selection;
* the server code is useless unless both UIs map it to the localized text: the
  catalog needs the German string (a *fuzzy* entry silently serves English while
  the CI drift check stays green) and both scripts must handle the code.

Fixtures are built in-process with pypdf (``PdfWriter.encrypt``), no binary
files. Compress and PDF/A run pikepdf, which crashes the Windows test session
(see ``test_pdf_compress.py``): those cases run on Linux CI only.
"""

from __future__ import annotations

import copy
import io
import json
import logging
import pickle
import re
import sys
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter
from pypdf.constants import UserAccessPermissions as Perm
from pypdf.errors import FileNotDecryptedError

from app.converters import pdf_pages
from app.converters.base import EncryptedPdfError
from app.converters.document import PdfToTxtConverter

_ENCRYPTED = (
    "This PDF is password-protected. Remove the password "
    "(e.g. open the file and print it to a new PDF) and try again."
)
_ENCRYPTED_DE = (
    "Dieses PDF ist passwortgeschützt. Entferne das Passwort "
    "(z. B. die Datei öffnen und als neues PDF drucken) und versuche es erneut."
)
_PDF_MIME = "application/pdf"
_ALGORITHMS = ["RC4-128", "AES-128", "AES-256"]
# What an owner password typically forbids: printing and copying text out.
_RESTRICTED = Perm.all() & ~(Perm.PRINT | Perm.PRINT_TO_REPRESENTATION | Perm.EXTRACT)
_PAGE_CAP = pdf_pages._MAX_SELECTION_PAGES  # read at import, before any test patches it
_STATIC_JS = Path(__file__).resolve().parents[1] / "app" / "static" / "js"
_PIKEPDF = pytest.mark.skipif(
    sys.platform == "win32",
    reason="pikepdf qpdf DLL conflicts with auth-route native deps on Windows; "
    "Linux CI + production are unaffected.",
)


def _pdf(pages: int = 2, *, algorithm: str | None = None, user_password: str = "secret") -> bytes:
    """Blank pages (none: a PDF without pages), encrypted when ``algorithm`` is given.

    ``user_password=""`` leaves an owner-only PDF: it carries restrictions but
    opens without a password.
    """
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    if algorithm:
        writer.encrypt(
            user_password=user_password,
            owner_password="owner",
            algorithm=algorithm,
            permissions_flag=_RESTRICTED,
        )
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _locked(algorithm: str) -> bytes:
    return _pdf(algorithm=algorithm)


def _owner_only(algorithm: str) -> bytes:
    return _pdf(algorithm=algorithm, user_password="")


def _post(client, headers, path, data, pdf):
    return client.post(
        path, headers=headers, files={"file": ("doc.pdf", pdf, _PDF_MIME)}, data=data
    )


# (path, form data) of every route that opens a PDF; pikepdf's two run on Linux only.
_ROUTES = [
    pytest.param("/api/v1/pdf/extract", {"pages": "1"}, id="extract"),
    pytest.param("/api/v1/pdf/split", {}, id="split"),
    pytest.param("/api/v1/convert", {"target_format": "txt"}, id="convert-txt"),
    pytest.param("/api/v1/convert", {"target_format": "pdf"}, id="convert-pdf"),
    pytest.param("/api/v1/pdf/compress", {"target_kb": "50"}, id="compress", marks=_PIKEPDF),
    pytest.param("/api/v1/convert", {"target_format": "pdfa"}, id="convert-pdfa", marks=_PIKEPDF),
]


@pytest.fixture
def two_page_cap(monkeypatch):
    monkeypatch.setattr(pdf_pages, "_MAX_SELECTION_PAGES", 2)


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("algorithm", _ALGORITHMS)
def test_fixtures_are_encrypted_the_way_the_tests_assume(algorithm):
    """Guards the fixtures: should pypdf change, this names the cause instead
    of the route tests failing on a 200 or the owner-only ones passing for a
    file that isn't encrypted at all."""
    with pytest.raises(FileNotDecryptedError):
        len(PdfReader(io.BytesIO(_locked(algorithm))).pages)
    restricted = PdfReader(io.BytesIO(_owner_only(algorithm)))
    assert restricted.is_encrypted
    assert len(restricted.pages) == 2
    assert not restricted.user_access_permissions & (Perm.PRINT | Perm.EXTRACT)


def test_pageless_fixture_has_no_pages():
    assert len(PdfReader(io.BytesIO(_pdf(0))).pages) == 0


# ── password-protected: engine ───────────────────────────────────────────────

_ENGINES = [
    pytest.param(lambda src, out: pdf_pages.extract_pages(src, out, "1"), id="extract_pages"),
    pytest.param(lambda src, out: pdf_pages.split_pdf(src), id="split_pdf"),
    pytest.param(
        lambda src, out: pdf_pages.PdfPageExtractConverter().convert(src, out), id="pdf-to-pdf"
    ),
    pytest.param(lambda src, out: PdfToTxtConverter().convert(src, out), id="pdf-to-txt"),
]


@pytest.mark.parametrize("algorithm", _ALGORITHMS)
@pytest.mark.parametrize("run", _ENGINES)
def test_engine_raises_encrypted_pdf_error(tmp_path, run, algorithm):
    src = tmp_path / "in.pdf"
    src.write_bytes(_locked(algorithm))
    with pytest.raises(EncryptedPdfError) as caught:
        run(src, tmp_path / "out")
    assert str(caught.value) == _ENCRYPTED


@pytest.mark.parametrize("clone", [copy.copy, lambda e: pickle.loads(pickle.dumps(e))])
def test_encrypted_pdf_error_survives_copy_and_pickle(clone):
    """Both rebuild the exception from its args; a process pool pickles it."""
    assert str(clone(EncryptedPdfError())) == _ENCRYPTED


# ── password-protected: routes ───────────────────────────────────────────────


@pytest.mark.parametrize("algorithm", _ALGORITHMS)
@pytest.mark.parametrize(("path", "data"), _ROUTES)
def test_route_answers_pdf_encrypted_without_a_logged_traceback(
    client, auth_headers, caplog, path, data, algorithm
):
    with caplog.at_level(logging.INFO):
        r = _post(client, auth_headers, path, data, _locked(algorithm))
    assert r.status_code == 400, r.text
    assert r.headers.get("X-FileMorph-Error-Code") == "pdf_encrypted"
    assert r.json()["detail"] == _ENCRYPTED
    assert [rec.getMessage() for rec in caplog.records if rec.exc_info] == []


@pytest.mark.parametrize("algorithm", _ALGORITHMS)
@pytest.mark.parametrize("target", ["txt", "pdf", pytest.param("pdfa", marks=_PIKEPDF)])
def test_convert_batch_names_the_password(client, auth_headers, target, algorithm):
    r = client.post(
        "/api/v1/convert/batch",
        headers=auth_headers,
        data={"target_formats": [target]},
        files=[("files", ("doc.pdf", _locked(algorithm), _PDF_MIME))],
    )
    assert r.status_code == 422, r.text
    assert r.json()["files"][0]["error_message"] == _ENCRYPTED


@pytest.mark.parametrize("algorithm", _ALGORITHMS)
@pytest.mark.parametrize(("path", "data"), _ROUTES)
def test_owner_only_pdf_is_still_processed(client, auth_headers, path, data, algorithm):
    """Readers open it without asking, so must we."""
    r = _post(client, auth_headers, path, data, _owner_only(algorithm))
    assert r.status_code == 200, r.text


# ── PDF/A: the password check runs before ghostscript ────────────────────────
#
# Ghostscript doesn't fail on a locked PDF: it renders it without the password
# and exits 0 (seen in CI with 10.02.1), so a check after it never fires.
# Ghostscript is faked here, so these hold whether or not it is installed.


@_PIKEPDF
def test_pdfa_refuses_a_locked_pdf_before_ghostscript(tmp_path, monkeypatch):
    from app.converters import _ghostscript as gs
    from app.converters.pdfa import PdfToPdfaConverter

    def _must_not_run(*_args, **_kwargs):
        raise AssertionError("ghostscript ran on a password-protected PDF")

    monkeypatch.setattr(gs, "is_available", lambda: True)
    monkeypatch.setattr(gs, "rerender_to_pdfa", _must_not_run)
    src = tmp_path / "in.pdf"
    src.write_bytes(_locked("AES-256"))
    with pytest.raises(EncryptedPdfError):
        PdfToPdfaConverter().convert(src, tmp_path / "out.pdf")


@_PIKEPDF
def test_pdfa_still_lets_ghostscript_repair_a_pdf_pikepdf_cannot_open(tmp_path, monkeypatch):
    """The password check passes every other open error on to ghostscript."""
    from app.converters import _ghostscript as gs
    from app.converters.pdfa import PdfToPdfaConverter

    def _repair(_src, dst, **_kwargs):
        dst.write_bytes(_pdf(1))
        return dst

    monkeypatch.setattr(gs, "is_available", lambda: True)
    monkeypatch.setattr(gs, "rerender_to_pdfa", _repair)
    src = tmp_path / "in.pdf"
    src.write_bytes(b"%PDF-1.4 damaged beyond what pikepdf can recover")
    out = PdfToPdfaConverter().convert(src, tmp_path / "out.pdf")
    assert len(PdfReader(out).pages) == 1


# ── a PDF without pages ──────────────────────────────────────────────────────


def test_parse_page_ranges_blames_the_file_for_a_pdf_without_pages():
    with pytest.raises(pdf_pages.UnreadablePdfError, match="no pages to extract"):
        pdf_pages.parse_page_ranges("1", 0)


@pytest.mark.parametrize(
    ("path", "data", "detail"),
    [
        pytest.param(
            "/api/v1/pdf/extract", {"pages": "1"}, "The PDF has no pages to extract.", id="extract"
        ),
        pytest.param("/api/v1/pdf/split", {}, "The PDF has no pages to split.", id="split"),
    ],
)
def test_pdf_without_pages_is_invalid_pdf_not_a_bad_selection(
    client, auth_headers, path, data, detail
):
    r = _post(client, auth_headers, path, data, _pdf(0))
    assert r.status_code == 400, r.text
    assert r.headers.get("X-FileMorph-Error-Code") == "invalid_pdf"
    assert r.json()["detail"] == detail


# ── PDF -> PDF over the page cap ─────────────────────────────────────────────


def test_pdf_to_pdf_over_the_page_cap_does_not_blame_a_selection(
    client, auth_headers, two_page_cap
):
    r = _post(client, auth_headers, "/api/v1/convert", {"target_format": "pdf"}, _pdf(3))
    assert r.status_code == 400, r.text
    assert r.headers.get("X-FileMorph-Error-Code") == "invalid_input"
    detail = r.json()["detail"]
    assert "selected" not in detail
    assert detail == pdf_pages._TOO_MANY_PAGES_TO_CONVERT
    assert f"{_PAGE_CAP:,}" in detail  # names the real limit (the constant is built at import)


def test_pdf_to_pdf_exactly_at_the_page_cap_keeps_every_page(client, auth_headers, two_page_cap):
    r = _post(client, auth_headers, "/api/v1/convert", {"target_format": "pdf"}, _pdf(2))
    assert r.status_code == 200, r.text
    assert len(PdfReader(io.BytesIO(r.content)).pages) == 2


def test_extract_over_the_page_cap_still_blames_the_selection(client, auth_headers, two_page_cap):
    """Regression guard: here the user did select the pages."""
    r = _post(client, auth_headers, "/api/v1/pdf/extract", {"pages": "1-3"}, _pdf(3))
    assert r.status_code == 400, r.text
    assert r.headers.get("X-FileMorph-Error-Code") == "invalid_page_selection"
    assert r.json()["detail"] == "Too many pages selected."


# ── the UIs ──────────────────────────────────────────────────────────────────

_I18N_BLOB = re.compile(
    r'<script id="fm-i18n-strings" type="application/json">(.*?)</script>', re.DOTALL
)


@pytest.mark.parametrize(
    ("lang", "expected"),
    [pytest.param("en", _ENCRYPTED, id="en"), pytest.param("de", _ENCRYPTED_DE, id="de")],
)
def test_js_strings_carry_the_encrypted_message_in_each_language(client, lang, expected):
    page = client.get(f"/{lang}/")
    assert page.status_code == 200, page.text
    blob = _I18N_BLOB.search(page.text)
    assert blob, f"/{lang}/ has no FM_I18N script tag"
    assert json.loads(blob.group(1)).get("pdfEncrypted") == expected


@pytest.mark.parametrize("script", ["pdf-tools.js", "app.js"])
def test_ui_script_maps_the_encrypted_code_to_the_localized_text(script):
    js = (_STATIC_JS / script).read_text(encoding="utf-8")
    assert "'pdf_encrypted'" in js, f"{script} ignores the pdf_encrypted error code"
    assert "pdfEncrypted" in js, f"{script} never shows the localized pdfEncrypted text"
