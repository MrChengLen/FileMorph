# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deterministic QA fixtures for the unreadable-PDF manual test round.

Generates the files the manual checklist refers to:

* ``gueltig-3-seiten.pdf`` — a valid three-page PDF with a line of text per
  page (the control file: extracts, splits and converts normally)
* ``kaputtes-seitenobjekt.pdf`` — its page object lacks ``/Type``: pypdf opens
  the file but refuses to copy the page (extract, split, PDF → PDF)
* ``zu-grosser-stream.pdf`` — a tiny file whose page stream declares 80 MB,
  over pypdf's 75 MB limit (extract, split, PDF → PDF)
* ``seitenbaum-zu-tief.pdf`` — pages nested 120 levels deep, over pypdf's
  limit of 100 (extract, split, PDF → PDF, PDF → TXT; compress reads it
  with pikepdf and succeeds)
* ``riesige-schriftbreiten.pdf`` — a font whose width table spans 100 000
  characters, over pypdf's 65 536 (PDF → TXT)
* ``kaputte-zeichentabelle.pdf`` — a font map pointing a letter at half of a
  surrogate pair; converts to TXT with a ``?`` in its place
* ``passwort-geschuetzt.pdf`` — the control file locked with the password
  ``filemorph``

Same call => byte-identical output on every run: the PDFs are assembled
here object by object, and the locked copy uses RC4-128, whose key comes
from the passwords and pypdf's content-derived document ID (no random salt).
Output directory defaults to ``docs-internal/testdata/pdf-unreadable/`` next
to this repo checkout (the folder is gitignored — commit this script, never
the data) and can be overridden as the first CLI argument.

Run:
    python scripts/make_testdata_pdf_unreadable.py [output_dir]
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

from pypdf import PdfReader, PdfWriter

CATALOG = b"<< /Type /Catalog /Pages 2 0 R >>"
ONE_PAGE = b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"
PAGE_WITH_FONT = (
    b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842]"
    b" /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>"
)
HELVETICA = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"


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


def _untyped_page() -> bytes:
    return _pdf(CATALOG, ONE_PAGE, b"<< /Parent 2 0 R /MediaBox [0 0 595 842] >>")


def _oversized_stream() -> bytes:
    return _pdf(
        CATALOG,
        ONE_PAGE,
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R >>",
        b"<< /Length 80000000 >>\nstream\nBT ET\nendstream",
    )


def _deep_page_tree() -> bytes:
    nodes = [b"<< /Type /Pages /Kids [%d 0 R] /Count 1 >>" % (num + 1) for num in range(2, 122)]
    return _pdf(CATALOG, *nodes, b"<< /Type /Page /MediaBox [0 0 595 842] >>")


def _huge_font_width_range() -> bytes:
    return _pdf(
        CATALOG,
        ONE_PAGE,
        PAGE_WITH_FONT,
        _stream(b"BT /F1 24 Tf 72 760 Td <0041> Tj ET"),
        b"<< /Type /Font /Subtype /Type0 /BaseFont /X /Encoding /Identity-H"
        b" /DescendantFonts [6 0 R] >>",
        b"<< /Type /Font /Subtype /CIDFontType2 /BaseFont /X"
        b" /CIDSystemInfo << /Registry (Adobe) /Ordering (Identity) /Supplement 0 >>"
        b" /W [0 99999 500] >>",
    )


def _surrogate_font_map() -> bytes:
    cmap = (
        b"/CIDInit /ProcSet findresource begin 12 dict begin begincmap\n"
        b"/CMapName /X def /CMapType 2 def\n"
        b"1 begincodespacerange\n<00> <FF>\nendcodespacerange\n"
        b"1 beginbfchar\n<41> <D800>\nendbfchar\nendcmap\nend end\n"
    )
    return _pdf(
        CATALOG,
        ONE_PAGE,
        PAGE_WITH_FONT,
        _stream(b"BT /F1 24 Tf 72 760 Td (A) Tj ET"),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /ToUnicode 6 0 R >>",
        _stream(cmap),
    )


def _locked(data: bytes) -> bytes:
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(data)))
    writer.encrypt(user_password="filemorph", algorithm="RC4-128")
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def main() -> None:
    out = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else (
            Path(__file__).resolve().parent.parent / "docs-internal" / "testdata" / "pdf-unreadable"
        )
    )
    out.mkdir(parents=True, exist_ok=True)
    valid = _three_pages()
    files = {
        "gueltig-3-seiten.pdf": valid,
        "kaputtes-seitenobjekt.pdf": _untyped_page(),
        "zu-grosser-stream.pdf": _oversized_stream(),
        "seitenbaum-zu-tief.pdf": _deep_page_tree(),
        "riesige-schriftbreiten.pdf": _huge_font_width_range(),
        "kaputte-zeichentabelle.pdf": _surrogate_font_map(),
        "passwort-geschuetzt.pdf": _locked(valid),
    }
    for name, data in files.items():
        (out / name).write_bytes(data)
        print(f"{name:30} {len(data):6} B")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
