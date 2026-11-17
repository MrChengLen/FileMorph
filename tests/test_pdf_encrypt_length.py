# SPDX-License-Identifier: AGPL-3.0-or-later
"""A PDF whose ``/Encrypt /Length`` gives a key ``cryptography`` refuses gets the usual 400.

``/Length`` in an RC4 encryption dictionary is the key length in bits. pypdf
takes it as given (6.21.3 dropped its check of the length again), so the length
reaches the cipher: ``cryptography``'s RC4 refuses a key of an unusual size with
a ``ValueError``, which ``_reading_pdf`` and the pdf → txt child answer with
"Could not read the PDF". The first section pins that answer from pypdf up to
the routes: should a pypdf update raise something else, it fails. It assumes
OpenSSL has RC4, as CI and the image do.

Where OpenSSL has no RC4 (as with ``CRYPTOGRAPHY_OPENSSL_NO_LEGACY=1``), pypdf
switches to its own RC4 once OpenSSL has refused RC4 in the process, and that
code divides by the key length: a key of no bytes raises ``ZeroDivisionError``.
The same file gets the same answer there. A stand-in refuses RC4 where and how
such an OpenSSL does, when a cipher context is made (checked against
``CRYPTOGRAPHY_OPENSSL_NO_LEGACY=1`` with cryptography 50).

Fixtures: tiny PDFs from the byte-by-byte builder of
``test_pdf_unsupported_encryption.py``, and the owner-only RC4 PDF of
``test_pdf_error_messages.py``.
"""

from __future__ import annotations

import io
import logging

import pytest
from pypdf import PdfReader

from app.converters import pdf_pages
from app.converters.pdf_insert import insert_pages
from tests.test_pdf_error_messages import _owner_only
from tests.test_pdf_unsupported_encryption import _P_O_U, _encrypted_pdf

_UNREADABLE = "Could not read the PDF. Verify the file is valid."
_PDF_MIME = "application/pdf"


def _rc4_pdf(length: bytes) -> bytes:
    """A one-page PDF encrypted with RC4 (``/V 2 /R 3``) and ``/Length length``."""
    return _encrypted_pdf(b"<< /Filter /Standard /V 2 /R 3 /Length %s %s >>" % (length, _P_O_U))


_NO_KEY = _rc4_pdf(b"0")  # 0 bits: a key of no bytes
_LENGTH_IN_BYTES = _rc4_pdf(b"16")  # 16 meant as bytes: read as a 16-bit key
# Two pages, only an owner password: opens without one. Built here, while RC4
# comes from OpenSSL.
_READABLE_RC4 = _owner_only("RC4-128")

_KEY_LENGTHS = [
    pytest.param(_NO_KEY, id="no-key"),
    pytest.param(_LENGTH_IN_BYTES, id="length-in-bytes"),
]


def _post(client, headers, path, data, pdf):
    return client.post(
        path, headers=headers, files={"file": ("doc.pdf", pdf, _PDF_MIME)}, data=data
    )


# ── as shipped: cryptography's RC4 refuses the key ───────────────────────────


@pytest.mark.parametrize("data", _KEY_LENGTHS)
def test_pypdf_raises_value_error_for_a_key_length_cryptography_refuses(data):
    """Guards the fixtures: pypdf hands the length to the cipher, which raises
    ``ValueError`` on open. Should pypdf check the length itself again, or
    raise something else, this fails and names the cause."""
    with pytest.raises(ValueError, match="key size"):
        PdfReader(io.BytesIO(data))


_ENGINES = [
    pytest.param(lambda src, out: pdf_pages.extract_pages(src, out, "1"), id="extract_pages"),
    pytest.param(lambda src, out: pdf_pages.split_pdf(src, 10**9), id="split_pdf"),
    pytest.param(
        lambda src, out: pdf_pages.PdfPageExtractConverter().convert(src, out), id="pdf-to-pdf"
    ),
]


@pytest.mark.parametrize("data", _KEY_LENGTHS)
@pytest.mark.parametrize("run", _ENGINES)
def test_engine_answers_a_key_length_cryptography_refuses_as_unreadable(tmp_path, run, data):
    src = tmp_path / "in.pdf"
    src.write_bytes(data)
    with pytest.raises(pdf_pages.UnreadablePdfError) as caught:
        run(src, tmp_path / "out.pdf")
    assert str(caught.value) == _UNREADABLE


_ROUTES = [
    pytest.param("/api/v1/pdf/extract", {"pages": "1"}, "invalid_pdf", id="extract"),
    pytest.param("/api/v1/pdf/split", {}, "invalid_pdf", id="split"),
    pytest.param("/api/v1/convert", {"target_format": "pdf"}, "invalid_input", id="convert-pdf"),
    pytest.param("/api/v1/convert", {"target_format": "txt"}, "invalid_input", id="convert-txt"),
]


@pytest.mark.parametrize("data", _KEY_LENGTHS)
@pytest.mark.parametrize(("path", "form", "code"), _ROUTES)
def test_route_answers_a_key_length_cryptography_refuses_with_400(
    client, auth_headers, caplog, path, form, code, data
):
    with caplog.at_level(logging.INFO):
        r = _post(client, auth_headers, path, form, data)
    assert r.status_code == 400, r.text
    assert r.headers.get("X-FileMorph-Error-Code") == code
    assert r.json()["detail"] == _UNREADABLE
    assert [rec.getMessage() for rec in caplog.records if rec.exc_info] == []


@pytest.mark.parametrize("field", ["file", "insert_file"])
def test_insert_route_names_the_file_whose_key_length_cryptography_refuses(
    client, auth_headers, field
):
    files = {"file": _READABLE_RC4, "insert_file": _READABLE_RC4}
    files[field] = _NO_KEY
    r = client.post(
        "/api/v1/pdf/insert",
        headers=auth_headers,
        files={
            "file": ("report.pdf", files["file"], _PDF_MIME),
            "insert_file": ("insert.pdf", files["insert_file"], "application/octet-stream"),
        },
    )
    assert r.status_code == 400, r.text
    assert r.headers.get("X-FileMorph-Error-Code") == "invalid_pdf"
    assert r.headers.get("X-FileMorph-Error-Field") == field


# ── OpenSSL without RC4: pypdf's own RC4 ─────────────────────────────────────


@pytest.fixture
def openssl_without_rc4(monkeypatch):
    """``cryptography`` refuses RC4 when a cipher context is made, as it does
    with ``CRYPTOGRAPHY_OPENSSL_NO_LEGACY=1``. pypdf notes the refusal for the
    whole process; monkeypatch restores that note afterwards."""
    from cryptography.exceptions import UnsupportedAlgorithm
    from cryptography.hazmat.primitives.ciphers import Cipher
    from pypdf._crypt_providers import _cryptography

    def refusing_rc4(make_context):
        def context(self):
            if self.algorithm.name == "RC4":
                raise UnsupportedAlgorithm("cipher RC4 in None mode is not supported")
            return make_context(self)

        return context

    monkeypatch.setattr(Cipher, "encryptor", refusing_rc4(Cipher.encryptor))
    monkeypatch.setattr(Cipher, "decryptor", refusing_rc4(Cipher.decryptor))
    monkeypatch.setattr(_cryptography.CryptRC4, "_is_rc4_supported", True)


def test_pypdf_without_openssl_rc4_divides_by_a_key_of_no_bytes(openssl_without_rc4):
    """Guards the stand-in: the first RC4 PDF makes pypdf switch to its own
    RC4, which still reads it; on a key of no bytes that RC4 raises
    ``ZeroDivisionError``. Should pypdf change either, this names the cause."""
    assert len(PdfReader(io.BytesIO(_READABLE_RC4)).pages) == 2
    with pytest.raises(ZeroDivisionError):
        PdfReader(io.BytesIO(_NO_KEY))


@pytest.mark.parametrize("run", _ENGINES)
def test_engine_without_openssl_rc4_answers_a_key_of_no_bytes_as_unreadable(
    tmp_path, openssl_without_rc4, run
):
    readable, src = tmp_path / "readable.pdf", tmp_path / "in.pdf"
    readable.write_bytes(_READABLE_RC4)
    src.write_bytes(_NO_KEY)
    run(readable, tmp_path / "readable.out.pdf")
    with pytest.raises(pdf_pages.UnreadablePdfError) as caught:
        run(src, tmp_path / "out.pdf")
    assert str(caught.value) == _UNREADABLE


def test_insert_without_openssl_rc4_names_the_file_with_a_key_of_no_bytes(
    tmp_path, openssl_without_rc4
):
    """``insert_pages`` reads both PDFs, so the first one's switch applies to the second."""
    base, insert = tmp_path / "base.pdf", tmp_path / "insert.pdf"
    base.write_bytes(_READABLE_RC4)
    insert.write_bytes(_NO_KEY)
    refused = insert_pages(base, insert, tmp_path / "out.pdf", None, "pdf", 10**9)["refused"]
    assert (refused["code"], refused["field"]) == ("invalid_pdf", "insert_file")


# pdf → txt reads one PDF per child process, so the switch never carries over
# from an earlier file there; the stand-in doesn't reach the child either.
_IN_PROCESS_ROUTES = [route for route in _ROUTES if route.id != "convert-txt"]


@pytest.mark.parametrize(("path", "form", "code"), _IN_PROCESS_ROUTES)
def test_route_without_openssl_rc4_answers_a_key_of_no_bytes_with_the_same_400(
    client, auth_headers, caplog, openssl_without_rc4, path, form, code
):
    first = _post(client, auth_headers, path, form, _READABLE_RC4)
    assert first.status_code == 200, first.text
    with caplog.at_level(logging.INFO):
        r = _post(client, auth_headers, path, form, _NO_KEY)
    assert r.status_code == 400, r.text
    assert r.headers.get("X-FileMorph-Error-Code") == code
    assert r.json()["detail"] == _UNREADABLE
    assert [rec.getMessage() for rec in caplog.records if rec.exc_info] == []
