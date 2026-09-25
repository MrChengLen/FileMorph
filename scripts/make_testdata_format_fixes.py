# SPDX-License-Identifier: AGPL-3.0-or-later
"""Deterministic QA fixtures for the format-consistency manual test round.

Generates the files the manual checklist refers to:

* ``vertrag.pdf``         — small text PDF; convert it to PDF/A and check the
  download is named ``vertrag_pdfa.pdf`` and opens as a PDF
* ``webseite-word.htm``   — windows-1252 HTML with a ``<meta charset>``, the
  way Word's "Save as Web Page" writes it; umlauts must survive → PDF
* ``webseite-utf8.html``  — the same page as UTF-8 (control case)

Same call => byte-identical output on every run (the PDF is written in
reportlab's invariant mode). Output directory defaults to
``docs-internal/testdata/format-fixes/`` next to this repo checkout (the
folder is gitignored — commit this script, never the data) and can be
overridden as the first CLI argument.

Run:
    python scripts/make_testdata_format_fixes.py [output_dir]
"""

from __future__ import annotations

import sys
from pathlib import Path

from reportlab.pdfgen import canvas

TEXT = "Straße, Übergröße, Ärger – 5 €"

HTML = (
    "<!DOCTYPE html>\n<html><head>{meta}<title>Testseite</title></head>\n"
    "<body><h1>Umlaut-Test</h1><p>{text}</p></body></html>\n"
)


def main() -> None:
    out = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else (
            Path(__file__).resolve().parent.parent / "docs-internal" / "testdata" / "format-fixes"
        )
    )
    out.mkdir(parents=True, exist_ok=True)

    pdf = canvas.Canvas(str(out / "vertrag.pdf"), invariant=1)
    pdf.setFont("Helvetica", 14)
    pdf.drawString(72, 720, "Vertrag - Testdokument fuer die PDF/A-Umwandlung")
    pdf.showPage()
    pdf.save()

    word_meta = '<meta http-equiv="Content-Type" content="text/html; charset=windows-1252">'
    (out / "webseite-word.htm").write_bytes(HTML.format(meta=word_meta, text=TEXT).encode("cp1252"))
    (out / "webseite-utf8.html").write_bytes(
        HTML.format(meta='<meta charset="utf-8">', text=TEXT).encode("utf-8")
    )

    for f in sorted(out.iterdir()):
        if f.is_file():
            print(f"{f.name:22} {f.stat().st_size:8} bytes")


if __name__ == "__main__":
    main()
