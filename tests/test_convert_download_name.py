# SPDX-License-Identifier: AGPL-3.0-or-later
"""PDF/A download-name regression guard.

``target_format=pdfa`` used the raw target token as the download's file
extension, so a converted ``Vertrag.pdf`` came back as ``Vertrag.pdfa`` — an
extension no OS associates with a PDF viewer. The fix maps ``pdfa`` to a
``_pdfa.pdf`` suffix (the same ``_<op>`` convention as ``_compressed`` /
``_pages``) via ``app.api.routes.convert._DOWNLOAD_SUFFIX``, mirrored in
``app/static/js/app.js`` for the no-``Content-Disposition`` fallback name.
These tests pin the single-download and batch-ZIP-entry names, that a
regular (non-suffix-mapped) target keeps its plain extension, and that the
JS fallback map doesn't drift from the server-side one.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

import app.converters.registry as registry
from app.api.routes.convert import _DOWNLOAD_SUFFIX
from app.converters.base import BaseConverter


class _CopyConverter(BaseConverter):
    """Stand-in for ``PdfToPdfaConverter`` — a byte-identical copy so these
    tests never have to import pikepdf (segfaults in-process on Windows)."""

    def convert(self, input_path: Path, output_path: Path, **kwargs) -> Path:
        import shutil

        shutil.copyfile(input_path, output_path)
        return output_path


@pytest.fixture
def stub_pdfa_converter(monkeypatch):
    """Route (pdf, pdfa) to the copy stub for the duration of one test —
    ``get_converter`` reads ``_registry`` at call time, so this is enough to
    intercept without touching the real pikepdf-backed converter."""
    monkeypatch.setitem(registry._registry, ("pdf", "pdfa"), _CopyConverter)


def test_pdfa_single_download_is_named_pdf(client, auth_headers, stub_pdfa_converter):
    res = client.post(
        "/api/v1/convert",
        headers=auth_headers,
        files={"file": ("Vertrag.pdf", b"%PDF-1.4\n%stub\n", "application/pdf")},
        data={"target_format": "pdfa"},
    )
    assert res.status_code == 200, res.text
    disposition = res.headers.get("content-disposition", "")
    assert 'filename="Vertrag_pdfa.pdf"' in disposition
    assert ".pdfa" not in disposition


def test_pdfa_batch_zip_entry_is_named_pdf(client, auth_headers, stub_pdfa_converter):
    res = client.post(
        "/api/v1/convert/batch",
        headers=auth_headers,
        files=[("files", ("Vertrag.pdf", b"%PDF-1.4\n%stub\n", "application/pdf"))],
        data={"target_formats": ["pdfa"]},
    )
    assert res.status_code == 200, res.text
    zf = zipfile.ZipFile(io.BytesIO(res.content))
    # All-success batches omit manifest.json (see tests/test_convert_batch.py)
    # — the ZIP holds exactly one entry, the converted file.
    assert zf.namelist() == ["Vertrag_pdfa.pdf"]


def test_regular_target_keeps_plain_extension(client, auth_headers, sample_jpg):
    """Guards the default branch: a target with no ``_DOWNLOAD_SUFFIX`` entry
    must keep using the plain ``<stem>.<tgt_ext>`` name, unchanged."""
    with sample_jpg.open("rb") as f:
        res = client.post(
            "/api/v1/convert",
            headers=auth_headers,
            files={"file": ("sample.jpg", f, "image/jpeg")},
            data={"target_format": "png"},
        )
    assert res.status_code == 200, res.text
    assert 'filename="sample.png"' in res.headers.get("content-disposition", "")


def test_app_js_fallback_mirrors_server_download_suffix():
    assert _DOWNLOAD_SUFFIX.get("pdfa") == "_pdfa.pdf"

    js_path = Path(__file__).resolve().parent.parent / "app" / "static" / "js" / "app.js"
    js_text = js_path.read_text(encoding="utf-8")
    for fmt, suffix in _DOWNLOAD_SUFFIX.items():
        assert f"{fmt}: '{suffix}'" in js_text, (
            f"app.js's DOWNLOAD_SUFFIX fallback map is missing the {fmt!r} "
            f"entry the server-side _DOWNLOAD_SUFFIX carries"
        )
