# SPDX-License-Identifier: AGPL-3.0-or-later
"""A PDF with certificate or unsupported encryption gets its own 400, never a 500.

pypdf implements only the standard (password) security handler. A PDF encrypted
with a certificate (``/Filter /Adobe.PubSec``), with a DRM plug-in's own handler,
or with an unsupported ``/V``, ``/SubFilter`` or crypt-filter method made the
``PdfReader(...)`` constructor raise ``NotImplementedError``, and nothing caught
it: /pdf/extract, /pdf/split and /convert (PDF -> TXT, PDF -> PDF) answered a
generic 500 plus a logged traceback. qpdf (pikepdf) refuses the same files with a
plain ``PdfError`` ("... (encryption dictionary, offset N): unsupported
encryption filter"): /pdf/compress said "verify the file is valid" (a 400
``invalid_pdf`` plus a logged traceback), and PDF -> PDF/A answered a 500 or,
where Ghostscript is installed, passed the file on to it.

Now every path raises ``UnsupportedPdfEncryptionError``, an ``EncryptedPdfError``
with its own ``error_code``: the routes answer ``400`` with
``X-FileMorph-Error-Code: pdf_encryption_unsupported`` and a fixed message that
says no password helps, the batch route puts that message in the per-file
``error_message``, and both UIs map the code to the localized text.

Fixtures are tiny PDFs assembled byte by byte: a one-page document whose
``/Encrypt`` entry points at the encryption dictionary under test, no binary
files. Three variants are refused by pypdf *and* qpdf and go through every path.
Two more are refused only by pypdf (a ``/SubFilter``, an unknown crypt-filter
method): qpdf doesn't call either unsupported, it takes both for password-protected
files and reports a bad password, so only the pypdf engines get those. Compress
and PDF/A run pikepdf, which crashes the Windows test session (see
``test_pdf_compress.py``): those cases run on Linux CI only.
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
from pypdf import PdfReader

from app.converters import pdf_pages
from app.converters.base import (
    EncryptedPdfError,
    InvalidInputError,
    UnsupportedPdfEncryptionError,
    open_pikepdf,
)
from app.converters.document import PdfToTxtConverter

_UNSUPPORTED = (
    "This PDF is protected with a certificate or an unsupported encryption. "
    "Remove the protection (e.g. ask the sender for an unprotected copy) and try again."
)
_UNSUPPORTED_DE = (
    "Dieses PDF ist mit einem Zertifikat oder einer nicht unterstützten Verschlüsselung "
    "geschützt. Entferne den Schutz (z. B. beim Absender eine ungeschützte Kopie anfordern) "
    "und versuche es erneut."
)
_CODE = "pdf_encryption_unsupported"
_PDF_MIME = "application/pdf"
_STATIC_JS = Path(__file__).resolve().parents[1] / "app" / "static" / "js"
_PIKEPDF = pytest.mark.skipif(
    sys.platform == "win32",
    reason="pikepdf qpdf DLL conflicts with auth-route native deps on Windows; "
    "Linux CI + production are unaffected.",
)

_CATALOG = b"<< /Type /Catalog /Pages 2 0 R >>"
_ONE_PAGE = b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"
_PAGE = b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>"
_FILE_ID = b"<00112233445566778899aabbccddeeff>"  # 16 bytes, as in a real /ID
# /P, /O and /U of the /Standard dictionaries below. Filler: the files are
# refused (or fail on the password) before any of it is used.
_P_O_U = b"/P -4 /O <" + b"00" * 32 + b"> /U <" + b"00" * 32 + b">"


def _encrypted_pdf(encryption: bytes) -> bytes:
    """A one-page PDF whose ``/Encrypt`` is ``encryption`` (object 4).

    Numbers the objects from 1 and adds a correct xref table and trailer, like
    ``_pdf`` in ``test_pdf_unreadable.py``; the trailer also carries the file
    ``/ID`` an encrypted PDF has.
    """
    objects = (_CATALOG, _ONE_PAGE, _PAGE, encryption)
    out = bytearray(b"%PDF-1.7\n")
    offsets = []
    for num, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (num, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R /Encrypt 4 0 R /ID [%s %s] >>\n" % (
        len(objects) + 1,
        _FILE_ID,
        _FILE_ID,
    )
    out += b"startxref\n%d\n%%%%EOF\n" % xref
    return bytes(out)


# Refused by pypdf and qpdf alike: every path must answer the new code.
_CERTIFICATE = _encrypted_pdf(
    b"<< /Filter /Adobe.PubSec /SubFilter /adbe.pkcs7.s5 /V 4 /R 4 /Length 128"
    b" /CF << /DefaultCryptFilter << /CFM /AESV2 /Recipients [<3082>] /Length 16 >> >>"
    b" /StmF /DefaultCryptFilter /StrF /DefaultCryptFilter >>"
)
_DRM_HANDLER = _encrypted_pdf(b"<< /Filter /Example.DRM /V 2 /R 3 /Length 128 >>")
_UNKNOWN_VERSION = _encrypted_pdf(b"<< /Filter /Standard /V 0 /R 2 " + _P_O_U + b" >>")

# Refused by pypdf only: qpdf takes both for password-protected files.
_SUBFILTER = _encrypted_pdf(
    b"<< /Filter /Standard /SubFilter /Foo /V 2 /R 3 /Length 128 " + _P_O_U + b" >>"
)
_CRYPT_METHOD = _encrypted_pdf(
    b"<< /Filter /Standard /V 4 /R 4 /Length 128 " + _P_O_U + b" /CF << /StdCF"
    b" << /CFM /FooCrypt /Length 16 >> >> /StmF /StdCF /StrF /StdCF >>"
)

_SHARED = [
    pytest.param(_CERTIFICATE, id="certificate"),
    pytest.param(_DRM_HANDLER, id="drm-handler"),
    pytest.param(_UNKNOWN_VERSION, id="unknown-version"),
]
_PYPDF_ONLY = [
    pytest.param(_SUBFILTER, id="subfilter"),
    pytest.param(_CRYPT_METHOD, id="crypt-method"),
]


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


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("data", _SHARED + _PYPDF_ONLY)
def test_pypdf_refuses_every_fixture_in_its_constructor(data):
    """Guards the fixtures: should pypdf change, this names the cause instead
    of the engine and route tests failing on a 500 or a 200."""
    with pytest.raises(NotImplementedError):
        PdfReader(io.BytesIO(data))


@_PIKEPDF
@pytest.mark.parametrize("data", _SHARED)
def test_qpdf_refuses_the_shared_fixtures_naming_the_encryption_dictionary(data):
    """open_pikepdf tells these from a damaged file by that phrase alone."""
    import pikepdf

    with pytest.raises(pikepdf.PdfError, match="encryption dictionary") as caught:
        pikepdf.open(io.BytesIO(data))
    assert not isinstance(caught.value, pikepdf.PasswordError)


# ── engine ───────────────────────────────────────────────────────────────────

_ENGINES = [
    pytest.param(lambda src, out: pdf_pages.extract_pages(src, out, "1"), id="extract_pages"),
    pytest.param(lambda src, out: pdf_pages.split_pdf(src), id="split_pdf"),
    pytest.param(
        lambda src, out: pdf_pages.PdfPageExtractConverter().convert(src, out), id="pdf-to-pdf"
    ),
    pytest.param(lambda src, out: PdfToTxtConverter().convert(src, out), id="pdf-to-txt"),
]


@pytest.mark.parametrize("data", _SHARED + _PYPDF_ONLY)
@pytest.mark.parametrize("run", _ENGINES)
def test_engine_raises_unsupported_pdf_encryption(tmp_path, run, data):
    src = tmp_path / "in.pdf"
    src.write_bytes(data)
    with pytest.raises(UnsupportedPdfEncryptionError) as caught:
        run(src, tmp_path / "out")
    assert str(caught.value) == _UNSUPPORTED


def _xref_stream_pdf(filter_name: bytes) -> bytes:
    """An unencrypted PDF whose only xref is a stream compressed with ``filter_name``."""
    out = bytearray(b"%PDF-1.7\n")
    for num, body in enumerate((_CATALOG, _ONE_PAGE, _PAGE), start=1):
        out += b"%d 0 obj\n%s\nendobj\n" % (num, body)
    xref = len(out)
    out += (
        b"4 0 obj\n<< /Type /XRef /Size 5 /W [1 2 1] /Root 1 0 R /Filter %s /Length 4 >>\n"
        b"stream\nabcd\nendstream\nendobj\nstartxref\n%d\n%%%%EOF\n" % (filter_name, xref)
    )
    return bytes(out)


@pytest.mark.parametrize("run", _ENGINES)
def test_unsupported_filter_outside_encryption_is_not_blamed_on_encryption(tmp_path, run):
    """open_pypdf guards only the constructor, where (pypdf 6.19) only the
    encryption dictionary raises NotImplementedError. Should pypdf let an
    unknown filter's NotImplementedError escape it, this unencrypted PDF would
    be called certificate-protected."""
    src = tmp_path / "in.pdf"
    src.write_bytes(_xref_stream_pdf(b"/FooDecode"))
    with pytest.raises(InvalidInputError) as caught:
        run(src, tmp_path / "out")
    assert not isinstance(caught.value, EncryptedPdfError)


def test_unsupported_encryption_is_an_encrypted_pdf_error_with_its_own_code():
    """The routes' ``except EncryptedPdfError`` clauses rely on the subclass."""
    assert issubclass(UnsupportedPdfEncryptionError, EncryptedPdfError)
    assert EncryptedPdfError().error_code == "pdf_encrypted"
    assert UnsupportedPdfEncryptionError().error_code == _CODE
    assert str(UnsupportedPdfEncryptionError()) == _UNSUPPORTED


@pytest.mark.parametrize(
    "clone",
    [
        pytest.param(copy.copy, id="copy"),
        pytest.param(lambda e: pickle.loads(pickle.dumps(e)), id="pickle"),
    ],
)
def test_unsupported_encryption_error_survives_copy_and_pickle(clone):
    """Both rebuild the exception from its args; a process pool pickles it."""
    cloned = clone(UnsupportedPdfEncryptionError())
    assert type(cloned) is UnsupportedPdfEncryptionError
    assert str(cloned) == _UNSUPPORTED
    assert cloned.error_code == _CODE


# ── routes ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("data", _SHARED)
@pytest.mark.parametrize(("path", "form"), _ROUTES)
def test_route_answers_pdf_encryption_unsupported_without_a_logged_traceback(
    client, auth_headers, caplog, path, form, data
):
    with caplog.at_level(logging.INFO):
        r = _post(client, auth_headers, path, form, data)
    assert r.status_code == 400, r.text
    assert r.headers.get("X-FileMorph-Error-Code") == _CODE
    assert r.json()["detail"] == _UNSUPPORTED
    assert [rec.getMessage() for rec in caplog.records if rec.exc_info] == []


@pytest.mark.parametrize("data", _SHARED)
@pytest.mark.parametrize("target", ["txt", "pdf", pytest.param("pdfa", marks=_PIKEPDF)])
def test_convert_batch_names_the_unsupported_encryption(client, auth_headers, target, data):
    r = client.post(
        "/api/v1/convert/batch",
        headers=auth_headers,
        data={"target_formats": [target]},
        files=[("files", ("doc.pdf", data, _PDF_MIME))],
    )
    assert r.status_code == 422, r.text
    assert r.json()["files"][0]["error_message"] == _UNSUPPORTED


# ── PDF/A: the encryption check runs before ghostscript ──────────────────────
#
# The converter's probe has to refuse before stage 1: a PDF qpdf can't open used
# to be passed on to ghostscript (test_pdf_error_messages.py has the same check
# for a password). Ghostscript is faked here, so this holds whether or not it is
# installed.


@_PIKEPDF
@pytest.mark.parametrize("data", _SHARED)
def test_pdfa_refuses_unsupported_encryption_before_ghostscript(tmp_path, monkeypatch, data):
    from app.converters import _ghostscript as gs
    from app.converters.pdfa import PdfToPdfaConverter

    def _must_not_run(*_args, **_kwargs):
        raise AssertionError("ghostscript ran on a PDF with unsupported encryption")

    monkeypatch.setattr(gs, "is_available", lambda: True)
    monkeypatch.setattr(gs, "rerender_to_pdfa", _must_not_run)
    src = tmp_path / "in.pdf"
    src.write_bytes(data)
    with pytest.raises(UnsupportedPdfEncryptionError):
        PdfToPdfaConverter().convert(src, tmp_path / "out.pdf")


@_PIKEPDF
def test_open_pikepdf_lets_a_damaged_pdf_error_propagate(tmp_path):
    """Only the encryption errors are mapped: the PDF/A path leaves every other
    open error to ghostscript, which repairs some files pikepdf can't open."""
    import pikepdf

    src = tmp_path / "in.pdf"
    src.write_bytes(b"%PDF-1.4 damaged beyond what pikepdf can recover")
    with pytest.raises(pikepdf.PdfError):
        open_pikepdf(src)


# ── the UIs ──────────────────────────────────────────────────────────────────

_I18N_BLOB = re.compile(
    r'<script id="fm-i18n-strings" type="application/json">(.*?)</script>', re.DOTALL
)


@pytest.mark.parametrize(
    ("lang", "expected"),
    [pytest.param("en", _UNSUPPORTED, id="en"), pytest.param("de", _UNSUPPORTED_DE, id="de")],
)
def test_js_strings_carry_the_unsupported_encryption_message_in_each_language(
    client, lang, expected
):
    page = client.get(f"/{lang}/")
    assert page.status_code == 200, page.text
    blob = _I18N_BLOB.search(page.text)
    assert blob, f"/{lang}/ has no FM_I18N script tag"
    assert json.loads(blob.group(1)).get("pdfEncryptionUnsupported") == expected


@pytest.mark.parametrize("script", ["pdf-tools.js", "app.js"])
def test_ui_script_maps_the_unsupported_encryption_code_to_the_localized_text(script):
    js = (_STATIC_JS / script).read_text(encoding="utf-8")
    assert f"'{_CODE}'" in js, f"{script} ignores the {_CODE} error code"
    assert "pdfEncryptionUnsupported" in js, f"{script} never shows pdfEncryptionUnsupported"
