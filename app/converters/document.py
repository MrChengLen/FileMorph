# SPDX-License-Identifier: AGPL-3.0-or-later
from pathlib import Path

from app.converters.base import BaseConverter
from app.converters.registry import register


def _deny_url_fetcher(url: str, **kwargs) -> None:
    """Blocks all external resource loading in WeasyPrint (SSRF prevention)."""
    raise OSError(f"Network access disabled: {url}")


# ---------------------------------------------------------------------------
# DOCX → PDF (mammoth → HTML → WeasyPrint → PDF)
# ---------------------------------------------------------------------------
# Pure-Python pipeline: mammoth extracts the DOCX body as HTML with images
# inlined as data: URIs, WeasyPrint renders it to PDF. SSRF-safe — the same
# _deny_url_fetcher used by md→pdf blocks any external URL the converted
# HTML might reference. Best-effort: footnotes, headers/footers and embedded
# OLE objects get simplified by mammoth; tables, images, hyperlinks and
# basic paragraph styles survive intact.
@register(("docx", "pdf"))
class DocxToPdfConverter(BaseConverter):
    def convert(self, input_path: Path, output_path: Path, **kwargs) -> Path:
        import mammoth
        import weasyprint

        with open(input_path, "rb") as f:
            result = mammoth.convert_to_html(f)
        html_body = result.value
        had_warnings = any(m.type == "warning" for m in result.messages)

        notice = (
            (
                '<div style="background:#fff3cd;border:1px solid #ffe39a;'
                'padding:8px;font-size:10pt;margin-bottom:1em">'
                "Some elements were simplified during conversion "
                "(footnotes, headers/footers, or embedded objects)."
                "</div>"
            )
            if had_warnings
            else ""
        )

        full_html = (
            "<!DOCTYPE html><html><head>"
            "<style>body{font-family:sans-serif;margin:2cm;line-height:1.6}"
            "table{border-collapse:collapse}"
            "td,th{border:1px solid #999;padding:4pt}</style>"
            f"</head><body>{notice}{html_body}</body></html>"
        )
        weasyprint.HTML(string=full_html, url_fetcher=_deny_url_fetcher).write_pdf(str(output_path))
        return output_path


# ---------------------------------------------------------------------------
# DOCX → TXT
# ---------------------------------------------------------------------------
@register(("docx", "txt"))
class DocxToTxtConverter(BaseConverter):
    def convert(self, input_path: Path, output_path: Path, **kwargs) -> Path:
        from docx import Document  # python-docx

        doc = Document(str(input_path))
        text = "\n".join(p.text for p in doc.paragraphs)
        output_path.write_text(text, encoding="utf-8")
        return output_path


# ---------------------------------------------------------------------------
# TXT → PDF
# ---------------------------------------------------------------------------
@register(("txt", "pdf"))
class TxtToPdfConverter(BaseConverter):
    def convert(self, input_path: Path, output_path: Path, **kwargs) -> Path:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas

        text = input_path.read_text(encoding="utf-8", errors="replace")
        c = canvas.Canvas(str(output_path), pagesize=A4)
        width, height = A4
        margin = 50
        y = height - margin
        line_height = 14

        c.setFont("Helvetica", 11)
        for line in text.splitlines():
            if y < margin:
                c.showPage()
                c.setFont("Helvetica", 11)
                y = height - margin
            c.drawString(margin, y, line[:120])  # truncate very long lines
            y -= line_height

        c.save()
        return output_path


# ---------------------------------------------------------------------------
# PDF → TXT
# ---------------------------------------------------------------------------
@register(("pdf", "txt"))
class PdfToTxtConverter(BaseConverter):
    def convert(self, input_path: Path, output_path: Path, **kwargs) -> Path:
        from pypdf import PdfReader

        reader = PdfReader(str(input_path))
        parts = [page.extract_text() or "" for page in reader.pages]
        output_path.write_text("\n\n".join(parts), encoding="utf-8")
        return output_path


# ---------------------------------------------------------------------------
# Markdown → HTML
# ---------------------------------------------------------------------------
@register(("md", "html"))
class MarkdownToHtmlConverter(BaseConverter):
    def convert(self, input_path: Path, output_path: Path, **kwargs) -> Path:
        import markdown

        src = input_path.read_text(encoding="utf-8")
        html = markdown.markdown(src, extensions=["tables", "fenced_code"])
        output_path.write_text(f"<!DOCTYPE html><html><body>{html}</body></html>", encoding="utf-8")
        return output_path


# ---------------------------------------------------------------------------
# Markdown → PDF  (via HTML → WeasyPrint)
# ---------------------------------------------------------------------------
@register(("md", "pdf"))
class MarkdownToPdfConverter(BaseConverter):
    def convert(self, input_path: Path, output_path: Path, **kwargs) -> Path:
        import markdown
        import weasyprint

        src = input_path.read_text(encoding="utf-8")
        html = markdown.markdown(src, extensions=["tables", "fenced_code"])
        full_html = (
            "<!DOCTYPE html><html><head>"
            "<style>body{font-family:sans-serif;margin:2cm;line-height:1.6}</style>"
            f"</head><body>{html}</body></html>"
        )
        weasyprint.HTML(string=full_html, url_fetcher=_deny_url_fetcher).write_pdf(str(output_path))
        return output_path
