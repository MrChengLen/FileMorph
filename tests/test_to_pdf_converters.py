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


def _spy_on_deny_fetcher(monkeypatch) -> list[str]:
    """Record every URL a converter's fetcher is asked for; it still refuses it."""
    import app.converters.document as document

    guarded: list[str] = []
    deny = document._deny_url_fetcher

    def _spy():
        fetcher = deny()
        refuse = fetcher.fetch

        def fetch(url, headers=None):
            guarded.append(url)
            return refuse(url, headers)

        fetcher.fetch = fetch
        return fetcher

    monkeypatch.setattr(document, "_deny_url_fetcher", _spy)
    return guarded


def _record_connects(monkeypatch) -> list:
    """Refuse every outbound connection and record it: WeasyPrint catches what
    a fetch raises and renders on, so an exception alone fails no test."""
    import socket

    connects: list = []

    def _connect(self, addr, *args, **kwargs):
        connects.append(addr)
        raise OSError(f"outbound connection to {addr!r} blocked by the test")

    monkeypatch.setattr(socket.socket, "connect", _connect)
    return connects


@_skip_no_weasyprint
@pytest.mark.parametrize("encoding", ["utf-8", "cp1252"], ids=["str-path", "bytes-path"])
def test_html_to_pdf_ssrf_blocked(client, auth_headers, tmp_path, monkeypatch, encoding):
    """HTML referencing remote/file resources must NOT trigger an outbound
    fetch — url_fetcher=_deny_url_fetcher() is mandatory. Runs for both input
    paths: UTF-8 is decoded to str, anything else reaches WeasyPrint as bytes
    (see _html_source); every resource URL must go through the guard."""
    connects = _record_connects(monkeypatch)
    guarded = _spy_on_deny_fetcher(monkeypatch)

    p = tmp_path / "evil.html"
    p.write_bytes(
        (
            "<!DOCTYPE html><html><head>"
            "<link rel='stylesheet' href='http://169.254.169.254/x.css'>"
            "</head><body><img src='file:///etc/passwd'><p>Grüße</p></body></html>"
        ).encode(encoding)
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
    assert not connects, connects
    assert any("169.254.169.254" in u for u in guarded), guarded
    assert any(u.startswith("file:") for u in guarded), guarded


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
    connects = _record_connects(monkeypatch)

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
    assert not connects, connects


# ── SSRF guard (WeasyPrint 70 takes a fetcher object) ────────────────────────


def test_every_weasyprint_render_passes_the_deny_fetcher():
    """Every ``weasyprint.HTML(...)`` in app/ passes ``url_fetcher=_deny_url_fetcher()``.

    Runs everywhere, unlike the render tests. Without ``url_fetcher=``,
    WeasyPrint fetches with its own fetcher (SSRF, local file read); the
    factory passed uncalled is a function, which breaks the render at the
    first resource on WeasyPrint 70. ``write_pdf()`` options that take a URL
    or file name (stylesheets, attachments, XMP metadata) read a plain file
    name without asking the fetcher, so app/ passes none of them, and it
    calls ``weasyprint.HTML`` by that name so that this test sees every call.
    """
    import ast

    root = Path(__file__).resolve().parents[1]
    options = {"stylesheets", "attachments", "attachment_relationships", "xmp_metadata"}
    calls, wrong = [], []
    for path in sorted((root / "app").rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            site = f"{path.relative_to(root).as_posix()}:{getattr(node, 'lineno', '?')}"
            if isinstance(node, ast.ImportFrom) and node.module == "weasyprint":
                wrong.append(f"{site} from weasyprint import")
            elif isinstance(node, ast.Import) and any(
                a.name == "weasyprint" and a.asname for a in node.names
            ):
                wrong.append(f"{site} import weasyprint as")
            elif isinstance(node, ast.Call) and ast.unparse(node.func) == "weasyprint.HTML":
                fetcher = next((kw.value for kw in node.keywords if kw.arg == "url_fetcher"), None)
                calls.append(site)
                if fetcher is None or ast.unparse(fetcher) != "_deny_url_fetcher()":
                    wrong.append(f"{site} without url_fetcher=_deny_url_fetcher()")
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "write_pdf" and options & {kw.arg for kw in node.keywords}:
                    wrong.append(f"{site} write_pdf() with a URL/file option")
    assert calls, "no weasyprint.HTML(...) call found in app/: update this test"
    assert not wrong, wrong


@_skip_no_weasyprint
def test_deny_url_fetcher_refuses_every_url():
    """WeasyPrint's ``fetch()``, which every resource goes through, gets an
    error it skips for each URL: no response, no AttributeError."""
    from weasyprint.urls import URLFetchingError, fetch

    from app.converters.document import _deny_url_fetcher

    for url in ("http://169.254.169.254/", "file:///etc/passwd", "data:text/plain,hi"):
        with pytest.raises(URLFetchingError), fetch(_deny_url_fetcher(), url):
            pass


# One page that asks for a resource of each kind: stylesheets (<link>,
# @import), a font, images (<img>, a CSS background, an SVG <image>) and an
# attachment, over http, file: and data:. WeasyPrint 70 loads every resource
# through the fetcher (its urls.fetch). Whatever loads leaves a trace: a
# stylesheet makes the page A6, an image or the attachment ends up in the PDF
# (the background is no-repeat, so it is drawn as an image, not a pattern),
# and a remote fetch opens a socket.
_A6_WIDTH_PT = 105 / 25.4 * 72


def _png_data_url(color: str) -> str:
    import base64

    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (4, 4), color).save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _hostile_fragment(tmp_path: Path) -> tuple[str, list[str]]:
    """Return the page body and every URL in it."""
    from PIL import Image

    css = tmp_path / "local.css"
    css.write_text("@page{size:A6}", encoding="utf-8")
    png = tmp_path / "local.png"
    Image.new("RGB", (4, 4), "black").save(png, "PNG")
    remote = "http://169.254.169.254/latest"
    link, link_file, link_data = f"{remote}/style.css", css.as_uri(), "data:text/css,@page{size:A6}"
    imported = "data:text/css,/*import*/@page{size:A6}"
    font, attachment = f"{remote}/font.woff", "data:text/plain,attached"
    img, img_file, img_data = f"{remote}/pixel.png", png.as_uri(), _png_data_url("red")
    background, svg_image = _png_data_url("green"), _png_data_url("blue")
    fragment = (
        "<div>"
        f'<style>@import url("{imported}");'
        f'@font-face{{font-family:Remote;src:url("{font}")}}</style>'
        f'<link rel="stylesheet" href="{link}"><link rel="stylesheet" href="{link_file}">'
        f'<link rel="stylesheet" href="{link_data}"><link rel="attachment" href="{attachment}">'
        f'<img src="{img}"><img src="{img_file}"><img src="{img_data}">'
        f"<p style=\"background:url('{background}') no-repeat\">background</p>"
        f'<svg width="10" height="10"><image href="{svg_image}" width="10" height="10"/></svg>'
        "</div>"
    )
    urls = [imported, font, link, link_file, link_data, attachment]
    urls += [img, img_file, img_data, background, svg_image]
    return fragment, urls


@_skip_no_weasyprint
@pytest.mark.parametrize("fmt", ["html", "md", "eml", "docx"])
def test_no_fetch_slips_past_the_guard(fmt, tmp_path, monkeypatch):
    """Each WeasyPrint call site asks the guard for every resource on every
    channel, and nothing loads: no socket, page still A4, no image, no
    attachment. docx is the mammoth path, with mammoth's HTML replaced."""
    from types import SimpleNamespace

    import mammoth
    from pypdf import PdfReader

    from app.converters import document

    connects = _record_connects(monkeypatch)
    guarded = _spy_on_deny_fetcher(monkeypatch)
    fragment, urls = _hostile_fragment(tmp_path)
    page = f"<!DOCTYPE html><html><body>{fragment}</body></html>"
    src, out = tmp_path / f"in.{fmt}", tmp_path / "out.pdf"
    if fmt == "html":
        src.write_text(page, encoding="utf-8")
        document.HtmlToPdfConverter().convert(src, out)
    elif fmt == "md":
        src.write_text(fragment, encoding="utf-8")
        document.MarkdownToPdfConverter().convert(src, out)
    elif fmt == "eml":
        msg = EmailMessage()
        msg["Subject"] = "resources"
        msg.set_content("plain")
        msg.add_alternative(page, subtype="html")
        src.write_bytes(msg.as_bytes())
        document.EmlToPdfConverter().convert(src, out)
    else:
        src.write_bytes(b"")
        result = SimpleNamespace(value=fragment, messages=[])
        monkeypatch.setattr(mammoth, "convert_to_html", lambda f: result)
        document._convert_via_mammoth(src, out)

    assert not connects, connects
    assert set(urls) <= set(guarded), set(urls) - set(guarded)
    reader = PdfReader(out)
    a6 = [p for p in reader.pages if abs(float(p.mediabox.width) - _A6_WIDTH_PT) < 1]
    assert not a6, "a stylesheet was loaded"
    assert not any(p.images for p in reader.pages), "an image was loaded"
    assert not reader.attachments, "the attachment was loaded"


@_skip_no_weasyprint
def test_hostile_fragment_loads_without_the_guard(tmp_path, monkeypatch):
    """Self-test: with WeasyPrint's own fetcher the same page loads its
    stylesheets, images and attachment and tries the network, so each check
    in the test above can fail."""
    import weasyprint
    from pypdf import PdfReader
    from weasyprint.urls import URLFetcher

    connects = _record_connects(monkeypatch)
    fragment, _ = _hostile_fragment(tmp_path)
    out = tmp_path / "out.pdf"
    page = f"<!DOCTYPE html><html><body>{fragment}</body></html>"
    weasyprint.HTML(string=page, url_fetcher=URLFetcher()).write_pdf(out)

    reader = PdfReader(out)
    assert connects
    assert abs(float(reader.pages[0].mediabox.width) - _A6_WIDTH_PT) < 1
    assert any(p.images for p in reader.pages)
    assert reader.attachments


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


# ── .htm must be a registered alias of html → pdf (runs everywhere) ────────
#
# The /convert/html-to-pdf file picker's accept attribute offers `.htm`
# (app/core/convert_pairs.py _ACCEPT["html"]), but only `("html", "pdf")` was
# registered — picking a `.htm` file was a dead end. `.htm` must resolve to
# the same HtmlToPdfConverter class (same SSRF-guarded url_fetcher).


def test_htm_is_registered_as_html_alias(client):
    from app.converters.document import HtmlToPdfConverter
    from app.converters.registry import get_converter

    assert isinstance(get_converter("htm", "pdf"), HtmlToPdfConverter)

    r = client.get("/api/v1/formats")
    assert r.status_code == 200
    assert "pdf" in r.json()["conversions"].get("htm", [])


@_skip_no_weasyprint
def test_htm_to_pdf(client, auth_headers, tmp_path):
    p = tmp_path / "page.htm"
    p.write_text(
        "<!DOCTYPE html><html><body><h1>Hello</h1><p>FileMorph</p></body></html>",
        encoding="utf-8",
    )
    with p.open("rb") as f:
        res = client.post(
            "/api/v1/convert",
            headers=auth_headers,
            files={"file": ("page.htm", f, "text/html")},
            data={"target_format": "pdf"},
        )
    assert res.status_code == 200, res.text
    assert res.content[:5] == b"%PDF-"
    assert 'filename="page.pdf"' in res.headers.get("content-disposition", "")


# ── non-UTF-8 HTML keeps its characters ─────────────────────────────────────
#
# Word's "Save as Web Page" writes windows-1252 `.htm`. Decoding every upload
# as UTF-8 with errors="replace" turned each umlaut into U+FFFD while the
# conversion still reported success. _html_source() hands non-UTF-8 input to
# WeasyPrint as bytes so its parser honours the BOM / <meta charset>.

_WORD_HTM = (
    '<html><head><meta http-equiv=Content-Type content="text/html; charset=windows-1252">'
    "</head><body><p>Straße Ärger</p></body></html>"
)


def test_html_source_decodes_utf8():
    from app.converters.document import _html_source

    assert _html_source("<p>Straße</p>".encode("utf-8")) == "<p>Straße</p>"


def test_html_source_keeps_non_utf8_as_bytes():
    from app.converters.document import _html_source

    raw = _WORD_HTM.encode("cp1252")
    assert _html_source(raw) == raw


@_skip_no_weasyprint
def test_windows_1252_htm_keeps_umlauts(client, auth_headers):
    res = client.post(
        "/api/v1/convert",
        headers=auth_headers,
        files={"file": ("brief.htm", _WORD_HTM.encode("cp1252"), "text/html")},
        data={"target_format": "pdf"},
    )
    assert res.status_code == 200, res.text

    from pypdf import PdfReader

    reader = PdfReader(BytesIO(res.content))
    extracted = "\n".join((pg.extract_text() or "") for pg in reader.pages)
    assert "Straße" in extracted and "Ärger" in extracted
    assert "�" not in extracted
