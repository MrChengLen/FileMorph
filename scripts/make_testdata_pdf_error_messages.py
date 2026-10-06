# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deterministic QA fixtures for the PDF error-message manual test round.

Generates the files the manual checklist refers to:

* ``gueltig-3-seiten.pdf`` — a valid three-page PDF with a line of text per
  page (the control file: every PDF tool and conversion works)
* ``passwort-rc4.pdf`` — the control file locked with the password
  ``filemorph`` (RC4-128)
* ``passwort-aes256.pdf`` — the same, locked with AES-256, as Acrobat and
  most current tools do
* ``nur-besitzerpasswort.pdf`` — AES-256 without an open password (only an
  owner password is set), so it opens without one and must not get the
  password message
* ``null-seiten.pdf`` — a PDF whose page tree holds no pages
* ``10001-seiten.pdf`` — 10 001 blank pages, one more than a PDF → PDF
  conversion (``/api/v1/convert`` with ``target_format=pdf``) takes

Same call => byte-identical output on every run: the PDFs are assembled
here object by object, and the locked copies are written while
``secrets.token_bytes`` (where pypdf draws AES keys, salts and IVs) is a
seeded generator. Test data only — never encrypt a real document that way.
Output directory defaults to ``docs-internal/testdata/pdf-error-messages/``
next to this repo checkout (the folder is gitignored — commit this script,
never the data) and can be overridden as the first CLI argument.

Run:
    python scripts/make_testdata_pdf_error_messages.py [output_dir]
"""

from __future__ import annotations

import io
import random
import secrets
import sys
from pathlib import Path
from unittest import mock

from pypdf import PdfReader, PdfWriter
from pypdf.constants import UserAccessPermissions

CATALOG = b"<< /Type /Catalog /Pages 2 0 R >>"
HELVETICA = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
PASSWORD = "filemorph"
OWNER_PASSWORD = "filemorph-owner"


def _pdf(*objects: bytes) -> bytes:
    """Number ``objects`` from 1 and add a correct xref table and trailer."""
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for num, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (num, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def _stream(data: bytes) -> bytes:
    return b"<< /Length %d >>\nstream\n%s\nendstream" % (len(data), data)


def _three_pages() -> bytes:
    # 1 catalog, 2 page tree, 3 font, then a page and its text per page.
    kids = b" ".join(b"%d 0 R" % (4 + 2 * i) for i in range(3))
    objects = [CATALOG, b"<< /Type /Pages /Kids [%s] /Count 3 >>" % kids, HELVETICA]
    for i in range(3):
        objects.append(
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842]"
            b" /Resources << /Font << /F1 3 0 R >> >> /Contents %d 0 R >>" % (5 + 2 * i)
        )
        objects.append(_stream(b"BT /F1 24 Tf 72 760 Td (FileMorph Testseite %d) Tj ET" % (i + 1)))
    return _pdf(*objects)


def _blank_pages(count: int) -> bytes:
    # 1 catalog, 2 page tree, then one empty page per object from 3 on.
    kids = b" ".join(b"%d 0 R" % (3 + i) for i in range(count))
    page = b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] >>"
    return _pdf(
        CATALOG, b"<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, count), *[page] * count
    )


def _locked(data: bytes, algorithm: str, user_password: str, **kwargs) -> bytes:
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(data)))
    rng = random.Random(f"{algorithm}/{user_password}")
    # Seeded "randomness" is insecure on purpose: byte-stable test fixtures only.
    with mock.patch.object(secrets, "token_bytes", lambda n=32: rng.randbytes(n)):
        writer.encrypt(
            user_password=user_password,
            owner_password=OWNER_PASSWORD,
            algorithm=algorithm,
            **kwargs,
        )
        buf = io.BytesIO()
        writer.write(buf)
    return buf.getvalue()


def main() -> None:
    out = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else (
            Path(__file__).resolve().parent.parent
            / "docs-internal"
            / "testdata"
            / "pdf-error-messages"
        )
    )
    out.mkdir(parents=True, exist_ok=True)
    valid = _three_pages()
    no_print_or_copy = UserAccessPermissions.all() & ~(
        UserAccessPermissions.PRINT
        | UserAccessPermissions.PRINT_TO_REPRESENTATION
        | UserAccessPermissions.EXTRACT
    )
    files = {
        "gueltig-3-seiten.pdf": valid,
        "passwort-rc4.pdf": _locked(valid, "RC4-128", PASSWORD),
        "passwort-aes256.pdf": _locked(valid, "AES-256", PASSWORD),
        "nur-besitzerpasswort.pdf": _locked(
            valid, "AES-256", "", permissions_flag=no_print_or_copy
        ),
        "null-seiten.pdf": _pdf(CATALOG, b"<< /Type /Pages /Kids [] /Count 0 >>"),
        "10001-seiten.pdf": _blank_pages(10_001),
    }
    for name, data in files.items():
        (out / name).write_bytes(data)
        print(f"{name:28} {len(data):9} B")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
