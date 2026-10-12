# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deterministic fixtures for manually testing the PDF/A header gate (PR #206).

Run: ``python scripts/make_testdata_pdfa_header_gate.py``

Writes four small files to ``docs-internal/testdata/pdfa-header-gate/`` (that
folder is gitignored and must never be committed — only this script ships).
Same call => identical files. Names are referenced by CHECKLISTE.md.

The files cover the gate's decisions:
- ``kein-echtes-pdf.pdf``       — bytes that are not a PDF, under a .pdf name.
- ``als-pdf-getarnt.pdf``       — presents as PostScript (``%!`` first), yet
                                  carries a ``%PDF-`` string further down.
- ``echtes-pdf.pdf``            — a normal one-page PDF.
- ``beschaedigt-mit-kopf.pdf``  — starts with the PDF header but is otherwise
                                  broken (covered by automated tests; included
                                  for completeness).
"""

from __future__ import annotations

from pathlib import Path


def _out_dir() -> Path:
    root = Path(__file__).resolve().parents[1]
    out = root / "docs-internal" / "testdata" / "pdfa-header-gate"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _real_pdf() -> bytes:
    from pypdf import PdfWriter

    import io

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def main() -> None:
    out = _out_dir()
    (out / "kein-echtes-pdf.pdf").write_bytes(
        b"This file is not a PDF. It just has a .pdf name so it reaches the converter.\n"
    )
    (out / "als-pdf-getarnt.pdf").write_bytes(
        b"%!PS-Adobe-3.0\n% the string %PDF-1.4 appears only inside this comment\nshowpage\n"
    )
    (out / "echtes-pdf.pdf").write_bytes(_real_pdf())
    (out / "beschaedigt-mit-kopf.pdf").write_bytes(
        b"%PDF-1.4 this starts like a PDF but the rest is not valid PDF structure"
    )
    print(f"Wrote 4 fixtures to {out}")


if __name__ == "__main__":
    main()
