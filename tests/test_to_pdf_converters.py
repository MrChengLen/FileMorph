# SPDX-License-Identifier: AGPL-3.0-or-later
"""Phase 2 to-PDF converters: image→pdf (Pillow), html→pdf and eml→pdf
(WeasyPrint). Mirrors the WeasyPrint skip pattern in test_convert_document.py
so the WeasyPrint-backed cases run on Linux CI (native libs present) and skip
on Windows dev hosts. image→pdf uses Pillow and runs everywhere."""

from __future__ import annotations

from email.message import EmailMessage
from io import BytesIO
from pathlib import Path

import pytest


def _weasyprint_works() -> bool:
    try:
        import weasyprint

        weasyprint.HTML(string="<p>probe</p>").write_pdf()
        return True
    except Exception:
        return False


_skip_no_weasyprint = pytest.mark.skipif(
    not _weasyprint_works(),
    reason="WeasyPrint native deps (libgobject/pango) unavailable on this host",
)


# ── image → pdf (Pillow native — runs everywhere) ────────────────────────────


def test_image_to_pdf_registered_for_common_formats():
    from app.converters.registry import get_supported_conversions

    conv = get_supported_conversions()
    for src in ("jpg", "png", "webp"):
        assert "pdf" in conv.get(src, []), f"{src}→pdf must be registered"


def test_jpg_to_pdf(client, auth_headers, sample_jpg):
    with sample_jpg.open("rb") as f:
        res = client.post(
            "/api/v1/convert",
            headers=auth_headers,
            files={"file": ("sample.jpg", f, "image/jpeg")},
            data={"target_format": "pdf"},
        )
    assert res.status_code == 200, res.text
    assert res.content[:5] == b"%PDF-"


def test_png_with_alpha_to_pdf(client, auth_headers, tmp_path):
    """RGBA PNG must flatten onto white (PDF has no alpha) instead of crashing."""
    from PIL import Image

    p = tmp_path / "alpha.png"
    Image.new("RGBA", (64, 64), (200, 50, 50, 128)).save(p, "PNG")
    with p.open("rb") as f:
        res = client.post(
            "/api/v1/convert",
            headers=auth_headers,
            files={"file": ("alpha.png", f, "image/png")},
            data={"target_format": "pdf"},
        )
    assert res.status_code == 200, res.text
    assert res.content[:5] == b"%PDF-"


# ── html → pdf (WeasyPrint) ──────────────────────────────────────────────────


@_skip_no_weasyprint
def test_html_to_pdf(client, auth_headers, tmp_path):
    p = tmp_path / "page.html"
    p.write_text(
        "<!DOCTYPE html><html><body><h1>Hello</h1><p>FileMorph</p></body></html>",
        encoding="utf-8",
    )
    with p.open("rb") as f:
        res = client.post(
            "/api/v1/convert",
            headers=auth_headers,
            files={"file": ("page.html", f, "text/html")},
            data={"target_format": "pdf"},
        )
    assert res.status_code == 200, res.text
    assert res.content[:5] == b"%PDF-"
    assert len(res.content) > 512


@_skip_no_weasyprint
def test_html_to_pdf_ssrf_blocked(client, auth_headers, tmp_path, monkeypatch):
    """HTML referencing remote/file resources must NOT trigger an outbound
    fetch — url_fetcher=_deny_url_fetcher is mandatory."""
    import socket

    def _block(self, addr, *args, **kwargs):
        raise AssertionError(f"unexpected outbound network call to {addr!r}")

    monkeypatch.setattr(socket.socket, "connect", _block)

    p = tmp_path / "evil.html"
    p.write_text(
        "<!DOCTYPE html><html><head>"
        "<link rel='stylesheet' href='http://169.254.169.254/x.css'>"
        "</head><body><img src='file:///etc/passwd'><p>hi</p></body></html>",
        encoding="utf-8",
    )
    with p.open("rb") as f:
        res = client.post(
            "/api/v1/convert",
            headers=auth_headers,
            files={"file": ("evil.html", f, "text/html")},
            data={"target_format": "pdf"},
        )
    assert res.status_code == 200, res.text
    assert res.content[:5] == b"%PDF-"


# ── eml → pdf (stdlib email + WeasyPrint) ────────────────────────────────────


def _make_eml(path: Path, *, html: bool) -> Path:
    msg = EmailMessage()
    msg["From"] = "alice@example.com"
    msg["To"] = "bob@example.com"
    msg["Subject"] = "Quarterly report"
    msg["Date"] = "Mon, 08 Jun 2026 10:00:00 +0000"
    if html:
        msg.set_content("plain fallback")
        msg.add_alternative("<html><body><p>HTML <b>body</b></p></body></html>", subtype="html")
    else:
        msg.set_content("This is the plain body.")
    path.write_bytes(msg.as_bytes())
    return path


@_skip_no_weasyprint
def test_eml_to_pdf_plain(client, auth_headers, tmp_path):
    p = _make_eml(tmp_path / "mail.eml", html=False)
    with p.open("rb") as f:
        res = client.post(
            "/api/v1/convert",
            headers=auth_headers,
            files={"file": ("mail.eml", f, "message/rfc822")},
            data={"target_format": "pdf"},
        )
    assert res.status_code == 200, res.text
    assert res.content[:5] == b"%PDF-"


@_skip_no_weasyprint
def test_eml_to_pdf_renders_subject(client, auth_headers, tmp_path):
    p = _make_eml(tmp_path / "mail.eml", html=True)
    with p.open("rb") as f:
        res = client.post(
            "/api/v1/convert",
            headers=auth_headers,
            files={"file": ("mail.eml", f, "message/rfc822")},
            data={"target_format": "pdf"},
        )
    assert res.status_code == 200, res.text
    assert res.content[:5] == b"%PDF-"

    from pypdf import PdfReader

    reader = PdfReader(BytesIO(res.content))
    extracted = "\n".join((pg.extract_text() or "") for pg in reader.pages)
    assert "Quarterly report" in extracted, "email subject missing from PDF"


@_skip_no_weasyprint
def test_eml_to_pdf_ssrf_blocked(client, auth_headers, tmp_path, monkeypatch):
    """An email HTML part with a remote tracking pixel must not be fetched."""
    import socket

    def _block(self, addr, *args, **kwargs):
        raise AssertionError(f"unexpected outbound network call to {addr!r}")

    monkeypatch.setattr(socket.socket, "connect", _block)

    msg = EmailMessage()
    msg["From"] = "a@example.com"
    msg["To"] = "b@example.com"
    msg["Subject"] = "tracked"
    msg.set_content("plain")
    msg.add_alternative(
        "<html><body><img src='http://169.254.169.254/pixel.gif'>hi</body></html>",
        subtype="html",
    )
    p = tmp_path / "tracked.eml"
    p.write_bytes(msg.as_bytes())
    with p.open("rb") as f:
        res = client.post(
            "/api/v1/convert",
            headers=auth_headers,
            files={"file": ("tracked.eml", f, "message/rfc822")},
            data={"target_format": "pdf"},
        )
    assert res.status_code == 200, res.text
    assert res.content[:5] == b"%PDF-"


# ── SSRF guard unit test (runs everywhere) ───────────────────────────────────


def test_deny_url_fetcher_raises():
    from app.converters.document import _deny_url_fetcher

    with pytest.raises(OSError):
        _deny_url_fetcher("http://169.254.169.254/")
    with pytest.raises(OSError):
        _deny_url_fetcher("file:///etc/passwd")


def test_image_to_pdf_heic_registration_tracks_pillow_heif():
    """heic/heif → pdf must be registered iff pillow-heif is available, exactly
    like the image↔image loop — guards the conditional registration."""
    from app.converters import image as image_mod
    from app.converters.registry import get_supported_conversions

    conv = get_supported_conversions()
    for src in ("heic", "heif"):
        if image_mod._heif_available:
            assert "pdf" in conv.get(src, []), f"{src}→pdf missing though pillow-heif is present"
        else:
            assert src not in conv, f"{src} should not be registered without pillow-heif"


def test_la_mode_image_to_pdf(client, auth_headers, tmp_path):
    """Greyscale+alpha (LA) is the mode most likely to regress the flatten path."""
    from PIL import Image

    p = tmp_path / "la.png"
    Image.new("LA", (48, 48), (120, 128)).save(p, "PNG")
    with p.open("rb") as f:
        res = client.post(
            "/api/v1/convert",
            headers=auth_headers,
            files={"file": ("la.png", f, "image/png")},
            data={"target_format": "pdf"},
        )
    assert res.status_code == 200, res.text
    assert res.content[:5] == b"%PDF-"


def test_unsupported_source_to_pdf_rejected(client, auth_headers, tmp_path):
    """pdf is not a universal target — a non-image/doc source must 422, proving
    the image→pdf loop didn't over-claim pdf for unrelated formats."""
    p = tmp_path / "a.mp3"
    p.write_bytes(b"ID3\x04\x00\x00\x00\x00\x00\x00fake mp3 body")
    with p.open("rb") as f:
        res = client.post(
            "/api/v1/convert",
            headers=auth_headers,
            files={"file": ("a.mp3", f, "audio/mpeg")},
            data={"target_format": "pdf"},
        )
    assert res.status_code == 422, res.text


def test_magic_byte_blocks_pe_disguised_as_image_to_pdf(client, auth_headers):
    """A PE payload renamed to .png with target pdf must be rejected at the
    magic-byte gate before any converter runs (BLOCKED_MAGIC)."""
    res = client.post(
        "/api/v1/convert",
        headers=auth_headers,
        files={"file": ("evil.png", b"MZ\x90\x00fake-pe-payload", "image/png")},
        data={"target_format": "pdf"},
    )
    assert res.status_code == 400, res.text


# ── _eml_to_html assembly (pure stdlib — runs everywhere, guards untrusted HTML) ──


def _eml_bytes(*, subject: str, html: str | None = None, plain: str | None = None) -> bytes:
    msg = EmailMessage()
    msg["From"] = "alice@example.com"
    msg["Subject"] = subject
    if plain is not None:
        msg.set_content(plain)
    if html is not None:
        if plain is None:
            msg.set_content("fallback")
        msg.add_alternative(html, subtype="html")
    return msg.as_bytes()


def test_eml_to_html_escapes_header_values():
    from app.converters.document import _eml_to_html

    out = _eml_to_html(_eml_bytes(subject="<script>alert(1)</script> & co", plain="hi"))
    assert "<script>alert(1)</script>" not in out, "subject must be HTML-escaped"
    assert "&lt;script&gt;" in out
    assert "&amp; co" in out


def test_eml_to_html_prefers_html_part():
    from app.converters.document import _eml_to_html

    out = _eml_to_html(_eml_bytes(subject="s", html="<p>RICH <b>body</b></p>", plain="plain text"))
    assert "<b>body</b>" in out, "html alternative must be used verbatim"
    assert "<pre>" not in out, "html part must not be wrapped in <pre>"


def test_eml_to_html_plain_wrapped_and_escaped():
    from app.converters.document import _eml_to_html

    out = _eml_to_html(_eml_bytes(subject="s", plain="line1\n<tag> & stuff"))
    assert "<pre>" in out
    assert "&lt;tag&gt; &amp; stuff" in out, "plain body must be escaped inside <pre>"


def test_eml_to_html_no_body_fallback():
    from app.converters.document import _eml_to_html

    out = _eml_to_html(_eml_bytes(subject="s", plain="   "))
    assert "(no readable body)" in out
