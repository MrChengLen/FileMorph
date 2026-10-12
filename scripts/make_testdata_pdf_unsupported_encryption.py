# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deterministic QA fixtures for the unsupported-PDF-encryption manual test round.

Generates the files the manual checklist refers to:

* ``gueltig-3-seiten.pdf`` — a valid three-page PDF with a line of text per
  page (the control file: every PDF tool and conversion works)
* ``zertifikat-verschluesselt.pdf`` — the control file declaring certificate
  encryption (``/Adobe.PubSec``, the handler Acrobat's "certificate security"
  writes) for a recipient that doesn't exist, so no reader can open it
* ``drm-geschuetzt.pdf`` — the control file declaring a DRM plug-in's own
  security handler instead of the standard (password) one
* ``passwort-aes256.pdf`` — the control file locked with the password
  ``filemorph`` (AES-256): it must keep getting the password message

Only the encryption dictionary of the certificate and DRM files is real; their
content isn't actually encrypted. FileMorph refuses them on reading that dictionary, as it
does a genuinely encrypted file. Same call => byte-identical output on every
run (the password copy is built by ``make_testdata_pdf_error_messages.py``,
which seeds its randomness). Output directory defaults to
``docs-internal/testdata/pdf-unsupported-encryption/`` next to this repo
checkout (the folder is gitignored — commit this script, never the data) and
can be overridden as the first CLI argument.

Run:
    python scripts/make_testdata_pdf_unsupported_encryption.py [output_dir]
"""

from __future__ import annotations

import sys
from pathlib import Path

from make_testdata_pdf_error_messages import PASSWORD, _locked, _three_pages

# The file identifier both encryption dictionaries are bound to (trailer /ID).
_ID = b"/ID [<46696c654d6f727068205141> <46696c654d6f727068205141>]"
CERTIFICATE = (
    b"<< /Filter /Adobe.PubSec /SubFilter /adbe.pkcs7.s5 /V 4 /R 4 /Length 128"
    b" /CF << /DefaultCryptFilter << /CFM /AESV2 /Length 16 /Recipients [<3082>] >> >>"
    b" /StmF /DefaultCryptFilter /StrF /DefaultCryptFilter >>"
)
DRM_HANDLER = b"<< /Filter /Example.DRM /V 2 /R 3 /Length 128 >>"


def _with_encryption(pdf: bytes, encrypt: bytes) -> bytes:
    """Append ``encrypt`` as a new object and point the trailer at it.

    ``pdf`` must come from ``_three_pages()``: one classic xref table
    (``0 <size>``, the free entry, one line per object) and a trailer with
    ``/Root 1 0 R``.
    """
    head, _, table = pdf.partition(b"xref\n")
    lines = table.splitlines()
    size = int(lines[0].split()[1])
    offsets = [int(line[:10]) for line in lines[2 : 1 + size]]
    out = bytearray(head)
    offsets.append(len(out))
    out += b"%d 0 obj\n%s\nendobj\n" % (size, encrypt)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (size + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R /Encrypt %d 0 R %s >>\nstartxref\n%d\n%%%%EOF\n" % (
        size + 1,
        size,
        _ID,
        xref,
    )
    return bytes(out)


def main() -> None:
    out = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else (
            Path(__file__).resolve().parent.parent
            / "docs-internal"
            / "testdata"
            / "pdf-unsupported-encryption"
        )
    )
    out.mkdir(parents=True, exist_ok=True)
    valid = _three_pages()
    files = {
        "gueltig-3-seiten.pdf": valid,
        "zertifikat-verschluesselt.pdf": _with_encryption(valid, CERTIFICATE),
        "drm-geschuetzt.pdf": _with_encryption(valid, DRM_HANDLER),
        "passwort-aes256.pdf": _locked(valid, "AES-256", PASSWORD),
    }
    for name, data in files.items():
        (out / name).write_bytes(data)
        print(f"{name:32} {len(data):7} B")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
