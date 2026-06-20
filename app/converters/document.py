# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import logging
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

from app.converters.base import BaseConverter
from app.converters.registry import register

logger = logging.getLogger(__name__)


def _deny_url_fetcher(url: str, **kwargs) -> None:
    """Blocks all external resource loading in WeasyPrint (SSRF prevention)."""
    raise OSError(f"Network access disabled: {url}")


# ---------------------------------------------------------------------------
# DOCX → PDF — two-engine routing
# ---------------------------------------------------------------------------
# Default engine is selected by ``settings.office_engine`` (see
# ``app/core/config.py``):
#
#   - ``auto``: detect DOCX complexity (footnotes / headers / footers /
#     sections / OLE); route complex docs to LibreOffice if ``soffice`` is
#     available, else fall back to mammoth + WeasyPrint and surface a
#     warning header so the caller knows fidelity was reduced.
#   - ``libreoffice``: always invoke ``soffice --headless --convert-to pdf``.
#   - ``mammoth``: always run the pure-Python pipeline; never call
#     LibreOffice. Predictable but limited; documented in
#     ``docs/formats.md``.
#
# The converter stores a list of warnings on ``self.warnings`` after
# convert() returns; the calling route reads it and emits an
# ``X-FileMorph-Warnings`` response header. The route layer cannot inspect
# DOCX internals itself — that's the converter's responsibility.

_COMPLEXITY_FEATURE_TO_LABEL = {
    "footnotes": "footnotes",
    "endnotes": "endnotes",
    "headers": "headers",
    "footers": "footers",
    "ole": "ole_objects",
    "sections": "multi_section_layout",
    "equations": "equations",
    "multilevel_lists": "multilevel_lists",
}


def _detect_docx_complexity(input_path: Path) -> dict[str, bool]:
    """Inspect the DOCX as a ZIP and return a feature-presence map.

    A DOCX is an OPC ZIP container; complex features ship as additional
    XML parts. Probing the namelist + a quick regex over
    ``word/document.xml`` is enough to decide whether the doc carries
    anything mammoth would silently lose. We deliberately don't parse the
    XML — feature detection is a routing hint, not a validator.
    """
    flags = {key: False for key in _COMPLEXITY_FEATURE_TO_LABEL}
    try:
        with zipfile.ZipFile(input_path) as zf:
            names = zf.namelist()
            for name in names:
                if name == "word/footnotes.xml":
                    flags["footnotes"] = True
                elif name == "word/endnotes.xml":
                    flags["endnotes"] = True
                elif name.startswith("word/header"):
                    flags["headers"] = True
                elif name.startswith("word/footer"):
                    flags["footers"] = True
                elif name.startswith("word/embeddings/"):
                    flags["ole"] = True
            try:
                document_xml = zf.read("word/document.xml").decode("utf-8", errors="ignore")
            except KeyError:
                document_xml = ""
    except (zipfile.BadZipFile, OSError):
        # Not a valid DOCX (or unreadable) — let the engine itself raise
        # a clearer error downstream. No complexity flags = mammoth path.
        return flags

    # Multi-section layout — more than one ``<w:sectPr>`` means at least
    # one mid-document section break (landscape pages, two-column inserts,
    # different headers per section).
    if document_xml.count("<w:sectPr") > 1:
        flags["sections"] = True
    # OMML / MathML equations — Word stores them inline as ``<m:oMath>``.
    if "<m:oMath" in document_xml:
        flags["equations"] = True
    # Multi-level numbered lists — ``<w:ilvl w:val="N">`` with N>0.
    # mammoth flattens these to nested <ol> without the original number
    # format strings, breaking § references in legal briefs.
    if re.search(r'<w:ilvl[^>]+w:val="[1-9]', document_xml):
        flags["multilevel_lists"] = True

    return flags


def _docx_is_complex(flags: dict[str, bool]) -> bool:
    """Any complex feature triggers the high-fidelity path."""
    return any(flags.values())


def _soffice_available() -> bool:
    """Check whether LibreOffice's ``soffice`` binary is on PATH.

    Cached at function-level via ``shutil.which`` — Python caches the
    PATH walk poorly across calls, but for a short-lived request the cost
    is negligible (<1 ms on Linux). A long-running worker that wants to
    skip the check can wire a module-level cache; we keep the helper
    side-effect-free for testability.
    """
    return shutil.which("soffice") is not None or shutil.which("libreoffice") is not None


def _resolve_office_engine(
    configured: str, *, docx_is_complex: bool, soffice_available: bool
) -> tuple[str, list[str]]:
    """Pick the engine for one conversion + collect any routing warnings.

    Returns ``(engine, warnings)`` where ``engine`` is one of
    ``libreoffice`` / ``mammoth``. The warnings list goes back to the
    route handler for inclusion in the ``X-FileMorph-Warnings`` header.
    """
    cfg = configured.lower()
    if cfg == "libreoffice":
        if not soffice_available:
            # Fail loud — the operator explicitly asked for the
            # high-fidelity path. Surface the misconfiguration instead
            # of silently degrading.
            raise RuntimeError(
                "FILEMORPH_OFFICE_ENGINE=libreoffice but neither `soffice` nor `libreoffice` "
                "is on PATH. Use the filemorph:office image variant or set the engine to "
                "`auto` / `mammoth`."
            )
        return "libreoffice", []
    if cfg == "mammoth":
        return "mammoth", []
    # auto
    if docx_is_complex and soffice_available:
        return "libreoffice", []
    if docx_is_complex and not soffice_available:
        return "mammoth", ["engine=mammoth_fallback", "reason=soffice_unavailable"]
    return "mammoth", []


def _convert_via_libreoffice(input_path: Path, output_path: Path, timeout_s: int) -> None:
    """Render DOCX → PDF using LibreOffice headless.

    ``soffice --headless --convert-to pdf:writer_pdf_Export --outdir <tmp>
    <input>`` writes the result as ``<tmp>/<input-stem>.pdf``. We then
    move it to the caller's ``output_path``.

    soffice insists on writing relative to ``--outdir`` and cannot be
    pointed at an exact output filename, hence the staging directory.
    """
    binary = shutil.which("soffice") or shutil.which("libreoffice")
    if binary is None:
        raise RuntimeError("LibreOffice binary not found on PATH")
    work_dir = output_path.parent / f".soffice_{output_path.stem}"
    work_dir.mkdir(exist_ok=True)
    try:
        # ``--norestore`` disables document recovery, ``--nofirststartwizard``
        # skips the per-profile setup prompt, ``--nolockcheck`` allows
        # parallel instances. The user-profile directory is per-call so two
        # concurrent conversions don't clobber each other's lockfiles.
        profile_uri = (work_dir / "userprofile").resolve().as_uri()
        result = subprocess.run(  # noqa: S603 — binary resolved via shutil.which, no shell
            [
                binary,
                "--headless",
                "--norestore",
                "--nofirststartwizard",
                "--nolockcheck",
                f"-env:UserInstallation={profile_uri}",
                "--convert-to",
                "pdf:writer_pdf_Export",
                "--outdir",
                str(work_dir),
                str(input_path),
            ],
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")[:500]
            raise RuntimeError(
                f"soffice exited with status {result.returncode}: {stderr.strip() or '(no stderr)'}"
            )
        produced = work_dir / f"{input_path.stem}.pdf"
        if not produced.exists():
            raise RuntimeError(
                f"soffice reported success but produced no PDF at {produced}. "
                f"stderr: {result.stderr.decode('utf-8', errors='replace')[:200]!r}"
            )
        shutil.move(str(produced), str(output_path))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def _convert_via_mammoth(input_path: Path, output_path: Path) -> bool:
    """Pure-Python fallback: mammoth → HTML → WeasyPrint.

    Returns True iff mammoth raised conversion warnings (i.e. structural
    fidelity loss the caller should know about).
    """
    import mammoth  # local import — keeps startup fast for self-hosters who only convert images
    import weasyprint

    with open(input_path, "rb") as f:
        result = mammoth.convert_to_html(f)
    html_body = result.value
    had_warnings = any(m.type == "warning" for m in result.messages)

    full_html = (
        "<!DOCTYPE html><html><head>"
        "<style>body{font-family:sans-serif;margin:2cm;line-height:1.6}"
        "table{border-collapse:collapse}"
        "td,th{border:1px solid #999;padding:4pt}</style>"
        f"</head><body>{html_body}</body></html>"
    )
    weasyprint.HTML(string=full_html, url_fetcher=_deny_url_fetcher).write_pdf(str(output_path))
    return had_warnings


@register(("docx", "pdf"))
class DocxToPdfConverter(BaseConverter):
    """DOCX → PDF with engine selection by configuration + DOCX complexity.

    The caller (route handler) inspects ``self.warnings`` after
    ``convert()`` returns. Empty list means a clean high-fidelity
    conversion; otherwise the warnings name the fidelity-affecting
    decisions (e.g. ``engine=mammoth_fallback`` when LibreOffice was
    requested but absent and the converter degraded gracefully).
    """

    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.engine_used: str | None = None

    def convert(self, input_path: Path, output_path: Path, **kwargs) -> Path:
        # Local import so test code can monkeypatch settings without
        # picking up a stale module-level reference.
        from app.core.config import settings

        flags = _detect_docx_complexity(input_path)
        is_complex = _docx_is_complex(flags)
        soffice = _soffice_available()
        engine, route_warnings = _resolve_office_engine(
            settings.office_engine,
            docx_is_complex=is_complex,
            soffice_available=soffice,
        )
        self.warnings.extend(route_warnings)

        if engine == "libreoffice":
            try:
                _convert_via_libreoffice(
                    input_path,
                    output_path,
                    timeout_s=settings.office_subprocess_timeout_seconds,
                )
                self.engine_used = "libreoffice"
            except (subprocess.TimeoutExpired, RuntimeError) as exc:
                # If the operator explicitly required LibreOffice, propagate
                # the failure so the caller learns about the misconfiguration
                # or a sick worker. In `auto`, treat a runtime failure as a
                # graceful fallback to mammoth — the caller still gets a PDF.
                if settings.office_engine.lower() == "libreoffice":
                    raise
                logger.warning(
                    "LibreOffice convert failed (%s) — falling back to mammoth pipeline",
                    exc,
                )
                self.warnings.append("engine=mammoth_fallback")
                self.warnings.append("reason=soffice_runtime_error")
                had = _convert_via_mammoth(input_path, output_path)
                self.engine_used = "mammoth"
                if had:
                    # mammoth flagged structural simplifications. Surface the
                    # generic label here; the per-feature breakdown lives in
                    # _detect_docx_complexity above and is already on
                    # self.warnings via the route-warning path.
                    self.warnings.append("fidelity=reduced")
            return output_path

        # engine == "mammoth"
        had = _convert_via_mammoth(input_path, output_path)
        self.engine_used = "mammoth"
        if is_complex:
            for feat, present in flags.items():
                if present:
                    self.warnings.append(f"simplified={_COMPLEXITY_FEATURE_TO_LABEL[feat]}")
        elif had:
            self.warnings.append("fidelity=reduced")
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


# ---------------------------------------------------------------------------
# HTML → PDF  (via WeasyPrint)
# ---------------------------------------------------------------------------
# url_fetcher=_deny_url_fetcher is MANDATORY (CLAUDE.md / security.md): a
# crafted HTML could otherwise pull internal URLs or file:// (SSRF / local
# file read). WeasyPrint logs and skips each denied resource, so the render
# still succeeds — it just never fetches anything external.
@register(("html", "pdf"))
class HtmlToPdfConverter(BaseConverter):
    def convert(self, input_path: Path, output_path: Path, **kwargs) -> Path:
        import weasyprint

        html = input_path.read_text(encoding="utf-8", errors="replace")
        weasyprint.HTML(string=html, url_fetcher=_deny_url_fetcher).write_pdf(str(output_path))
        return output_path


# ---------------------------------------------------------------------------
# EML (email) → PDF  (stdlib email parse → HTML → WeasyPrint)
# ---------------------------------------------------------------------------
# Renders the common headers + the message body (prefers the text/html part,
# else the escaped text/plain part). Same mandatory SSRF guard — an email's
# HTML part routinely references remote tracking pixels / images, which must
# never be fetched server-side.
def _eml_to_html(raw: bytes) -> str:
    """Parse an ``.eml`` (RFC 5322 / MIME) into a self-contained HTML document.

    Pure stdlib (no WeasyPrint) so the escaping / body-selection logic is
    unit-testable on every host, not just CI. Header values are HTML-escaped;
    the body prefers the ``text/html`` part (left un-escaped — it *is* HTML,
    and it's rendered with no JS execution + the SSRF guard downstream) and
    falls back to the escaped ``text/plain`` part, or a placeholder if empty.
    """
    import email
    import html as html_lib
    from email import policy

    msg = email.message_from_bytes(raw, policy=policy.default)

    rows = []
    for key in ("From", "To", "Cc", "Date", "Subject"):
        val = msg.get(key)
        if val:
            rows.append(
                f"<tr><td class='k'>{html_lib.escape(key)}</td>"
                f"<td>{html_lib.escape(str(val))}</td></tr>"
            )
    header_html = "<table class='hdr'>" + "".join(rows) + "</table>"

    body_part = msg.get_body(preferencelist=("html", "plain"))
    if body_part is not None and body_part.get_content_type() == "text/html":
        body_html = body_part.get_content()
    else:
        text = body_part.get_content() if body_part is not None else ""
        body_html = (
            "<pre>" + html_lib.escape(text) + "</pre>"
            if text.strip()
            else "<p>(no readable body)</p>"
        )

    return (
        "<!DOCTYPE html><html><head><meta charset='utf-8'>"
        "<style>body{font-family:sans-serif;margin:2cm;line-height:1.5}"
        ".hdr{border-collapse:collapse;margin-bottom:1em;font-size:0.9em}"
        ".hdr td{padding:2px 8px;vertical-align:top}"
        ".hdr .k{font-weight:bold;color:#444}"
        "hr{border:none;border-top:1px solid #ccc}"
        "pre{white-space:pre-wrap;word-wrap:break-word;font-family:inherit}</style>"
        f"</head><body>{header_html}<hr>{body_html}</body></html>"
    )


@register(("eml", "pdf"))
class EmlToPdfConverter(BaseConverter):
    def convert(self, input_path: Path, output_path: Path, **kwargs) -> Path:
        import weasyprint

        full_html = _eml_to_html(input_path.read_bytes())
        weasyprint.HTML(string=full_html, url_fetcher=_deny_url_fetcher).write_pdf(str(output_path))
        return output_path
