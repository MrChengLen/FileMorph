# SPDX-License-Identifier: AGPL-3.0-or-later
"""PDF compress-to-target (Morph > Convert).

Covers the engine (``app/compressors/pdf.py``) and the dedicated route
(``app/api/routes/pdf_pages.py`` → ``POST /api/v1/pdf/compress``):

* an image-rich PDF shrinks toward the target, stays a valid PDF, and
  preserves page count;
* a text/vector-only PDF (nothing to recompress) comes back a valid PDF,
  unchanged-in-content, reported ``converged=False`` / 0 recompressible
  images — never an error, never a false compression claim;
* invalid / negative / huge / corrupt targets and inputs → graceful 4xx
  (no 500, no pikepdf/Pillow internals in the body);
* the magic-byte guard still rejects a disguised executable;
* a non-PDF source is a 422;
* target above the tier output cap is a 413 before any work.

Windows quirk (identical to ``test_pdfa.py``)
---------------------------------------------
``pikepdf`` bundles libqpdf; importing it after the auth-route's native
stack (cryptography + sqlalchemy + Jinja2) — which the conftest loads
unconditionally via ``app.main`` — segfaults during qpdf DLL init on
Windows. The PDF-compress path runs fine on Linux (CI + production), so
the whole module is skipped on win32 and ``pikepdf`` is imported lazily
(never at module top). Fixtures build PDFs in-process with pikepdf +
Pillow (a real DCTDecode image XObject for the "rich" case) — no binary
fixtures committed.
"""

from __future__ import annotations

import base64
import io
import sys
import zlib
from pathlib import Path

import pytest
from PIL import Image, ImageStat, features

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="pikepdf qpdf DLL conflicts with auth-route native deps on Windows; "
    "Linux CI + production are unaffected.",
)

_PDF_MIME = "application/pdf"


# ── Fixtures (in-process PDF builders) ───────────────────────────────────────


def _entropy_jpeg_bytes(dim: int, quality: int) -> bytes:
    """A high-entropy JPEG so q-floor and q-ceiling differ meaningfully."""
    img = Image.new("RGB", (dim, dim))
    px = img.load()
    for x in range(dim):
        for y in range(dim):
            px[x, y] = (
                (x * 7 + y * 3) % 256,
                (x * 13 + y * 11) % 256,
                (x * 5 + y * 17) % 256,
            )
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _image_pdf_bytes(num_pages: int = 1, dim: int = 1200, quality: int = 98) -> bytes:
    """A PDF with a real DCTDecode image XObject on each page.

    Built directly via pikepdf so the bytes are dominated by the embedded
    photo — i.e. there's something for the compressor to grab. Lazy import
    keeps the Windows-skip contract (pikepdf only loads when a test on a
    supported platform actually runs).
    """
    import pikepdf
    from pikepdf import Name, Pdf

    pdf = Pdf.new()
    jpg = _entropy_jpeg_bytes(dim, quality)
    for _ in range(num_pages):
        page = pdf.add_blank_page(page_size=(dim, dim))
        stream = pdf.make_stream(jpg)
        stream.Type = Name("/XObject")
        stream.Subtype = Name("/Image")
        stream.Width = dim
        stream.Height = dim
        stream.ColorSpace = Name("/DeviceRGB")
        stream.BitsPerComponent = 8
        stream.Filter = Name("/DCTDecode")
        page.Resources = pikepdf.Dictionary(XObject=pikepdf.Dictionary(Im0=stream))
        page.Contents = pdf.make_stream(b"q %d 0 0 %d 0 0 cm /Im0 Do Q" % (dim, dim))
    buf = io.BytesIO()
    pdf.save(buf)
    return buf.getvalue()


def _text_pdf_bytes(num_pages: int = 3) -> bytes:
    """A vector/blank-page-only PDF — nothing the image lever can shrink."""
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(num_pages):
        writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _image_pdf_file(tmp_path: Path, name: str = "rich.pdf", **kw) -> Path:
    path = tmp_path / name
    path.write_bytes(_image_pdf_bytes(**kw))
    return path


# ── Engine: image-rich PDF ───────────────────────────────────────────────────


def test_engine_shrinks_image_pdf_toward_target(tmp_path):
    import pikepdf

    from app.compressors.pdf import compress_pdf_to_target

    src = _image_pdf_file(tmp_path)
    out = tmp_path / "out.pdf"
    target = 200 * 1024

    result = compress_pdf_to_target(src, out, target_bytes=target)

    assert out.read_bytes()[:4] == b"%PDF"
    assert result["recompressible_images"] == 1
    # Output must be well under the source and at/around the target.
    assert out.stat().st_size < src.stat().st_size
    assert out.stat().st_size <= int(target * 1.05) + 1, (
        f"{out.stat().st_size} exceeds target+tolerance"
    )
    with pikepdf.open(str(out)) as pdf:
        assert len(pdf.pages) == 1


def test_engine_preserves_multi_page_count(tmp_path):
    import pikepdf

    from app.compressors.pdf import compress_pdf_to_target

    src = _image_pdf_file(tmp_path, name="multi.pdf", num_pages=3)
    out = tmp_path / "out.pdf"
    compress_pdf_to_target(src, out, target_bytes=300 * 1024)
    with pikepdf.open(str(out)) as pdf:
        assert len(pdf.pages) == 3


def test_engine_generous_target_uses_high_quality_shortcut(tmp_path):
    """A target larger than even a top-quality re-encode → take the
    shortcut at max quality, converged, single iteration."""
    from app.compressors.pdf import compress_pdf_to_target

    src = _image_pdf_file(tmp_path, dim=600, quality=95)
    out = tmp_path / "out.pdf"
    target = src.stat().st_size * 2

    result = compress_pdf_to_target(src, out, target_bytes=target)
    assert result["converged"] is True
    assert result["iterations"] == 1
    assert out.stat().st_size <= target


def test_engine_tiny_target_returns_floor_not_converged(tmp_path):
    """Target smaller than the quality-floor output → still a valid PDF,
    smallest we can honestly produce, converged=False."""
    import pikepdf

    from app.compressors.pdf import compress_pdf_to_target

    src = _image_pdf_file(tmp_path)
    out = tmp_path / "out.pdf"

    result = compress_pdf_to_target(src, out, target_bytes=2 * 1024)
    assert result["converged"] is False
    assert out.read_bytes()[:4] == b"%PDF"
    with pikepdf.open(str(out)) as pdf:
        assert len(pdf.pages) == 1


# ── Engine: honest limit for image-poor PDFs ─────────────────────────────────


def test_engine_text_only_pdf_is_noop_not_error(tmp_path):
    import pikepdf

    from app.compressors.pdf import compress_pdf_to_target

    src = tmp_path / "text.pdf"
    src.write_bytes(_text_pdf_bytes(3))
    out = tmp_path / "out.pdf"

    result = compress_pdf_to_target(src, out, target_bytes=10 * 1024)

    assert result["recompressible_images"] == 0
    assert result["converged"] is False
    assert result["final_quality"] is None
    assert out.read_bytes()[:4] == b"%PDF"
    with pikepdf.open(str(out)) as pdf:
        assert len(pdf.pages) == 3


# ── Engine: working-set DoS guard ────────────────────────────────────────────


def test_engine_oversized_working_set_is_noop(tmp_path, monkeypatch):
    """A document whose recompressible images exceed the decode ceiling is
    NOT decoded — it bails to the honest no-op path (valid PDF, content
    unchanged, converged=False, nothing recompressed) instead of OOM-ing.

    Drives the real image fixture over the pixel ceiling by lowering the
    constant (rather than building a multi-GB PDF), and asserts the decode
    path is never entered.
    """
    import app.compressors.pdf as pdf_mod
    from app.compressors.pdf import compress_pdf_to_target

    # Shrink the ceiling below the fixture's single image so the guard fires.
    monkeypatch.setattr(pdf_mod, "_MAX_TOTAL_DECODE_PIXELS", 1)

    # Fail loudly if the guard let us through and we tried to decode anyway.
    def _boom(_pdf):
        raise AssertionError("_collect_decoded ran despite the working-set ceiling")

    monkeypatch.setattr(pdf_mod, "_collect_decoded", _boom)

    src = _image_pdf_file(tmp_path, dim=600, quality=95)
    out = tmp_path / "out.pdf"

    result = compress_pdf_to_target(src, out, target_bytes=50 * 1024)

    assert result["recompressible_images"] == 0
    assert result["converged"] is False
    assert result["final_quality"] is None
    assert result["iterations"] == 0
    assert out.read_bytes()[:4] == b"%PDF"


def test_engine_image_count_ceiling_is_noop(tmp_path, monkeypatch):
    """The hard image-count cap also routes to the no-op path — a swarm of
    tiny images can't each cost a decode + per-probe re-encode."""
    import pikepdf

    import app.compressors.pdf as pdf_mod
    from app.compressors.pdf import compress_pdf_to_target

    monkeypatch.setattr(pdf_mod, "_MAX_RECOMPRESSIBLE_IMAGES", 1)

    src = _image_pdf_file(tmp_path, name="multi.pdf", num_pages=3, dim=300)
    out = tmp_path / "out.pdf"

    result = compress_pdf_to_target(src, out, target_bytes=50 * 1024)

    assert result["recompressible_images"] == 0
    assert result["converged"] is False
    with pikepdf.open(str(out)) as pdf:
        assert len(pdf.pages) == 3  # content preserved, just not recompressed


# ── Engine: which images are decoded ─────────────────────────────────────────


def _image_bytes(fmt: str) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (300, 300), (200, 30, 30)).save(buf, format=fmt)
    return buf.getvalue()


def _two_image_pdf(path: Path, data: bytes, filters: list[str], **im1) -> None:
    """One page with an ordinary JPEG (/Im0) and a second 300×300 image (/Im1)
    stored as ``data`` under ``filters``; ``im1`` sets more of its keys."""
    import pikepdf
    from pikepdf import Array, Name, Pdf

    pdf = Pdf.new()
    page = pdf.add_blank_page(page_size=(600, 600))
    images = pikepdf.Dictionary()
    for key, raw, chain in (
        ("/Im0", _entropy_jpeg_bytes(300, 98), ["/DCTDecode"]),
        ("/Im1", data, filters),
    ):
        stream = pdf.make_stream(raw)
        stream.Type = Name("/XObject")
        stream.Subtype = Name("/Image")
        stream.Width = 300
        stream.Height = 300
        stream.ColorSpace = Name("/DeviceRGB")
        stream.BitsPerComponent = 8
        stream.Filter = Array([Name(f) for f in chain])
        images[key] = stream
    for name, value in im1.items():
        images["/Im1"][f"/{name}"] = value
    page.Resources = pikepdf.Dictionary(XObject=images)
    page.Contents = pdf.make_stream(
        b"q 300 0 0 300 0 0 cm /Im0 Do Q q 300 0 0 300 300 300 cm /Im1 Do Q"
    )
    # Saved as built: qpdf would otherwise recompress a lossless chain as one filter.
    pdf.save(str(path), compress_streams=False)


_NEEDS_JPEG2000 = pytest.mark.skipif(
    not features.check("jpg_2000"), reason="this Pillow can't write JPEG 2000"
)


@pytest.mark.parametrize(
    ("make_data", "filters"),
    [
        pytest.param(
            lambda: _image_bytes("JPEG2000"), ["/JPXDecode"], id="jpeg2000", marks=_NEEDS_JPEG2000
        ),
        pytest.param(lambda: _image_bytes("PNG"), ["/DCTDecode"], id="unreadable"),
        pytest.param(
            lambda: zlib.compress(_image_bytes("PNG")),
            ["/FlateDecode", "/DCTDecode"],
            id="unreadable-behind-flate",
        ),
        pytest.param(
            lambda: _entropy_jpeg_bytes(600, 90), ["/DCTDecode"], id="other-size-than-declared"
        ),
    ],
)
def test_engine_leaves_images_it_does_not_decode_as_they_are(tmp_path, make_data, filters):
    """Only the ordinary JPEG is re-encoded; the other image stays byte for
    byte."""
    import pikepdf

    from app.compressors.pdf import compress_pdf_to_target

    data = make_data()
    src, out = tmp_path / "in.pdf", tmp_path / "out.pdf"
    _two_image_pdf(src, data, filters)

    result = compress_pdf_to_target(src, out, target_bytes=10 * 1024 * 1024)

    assert result["recompressible_images"] == 1
    with pikepdf.open(str(out)) as pdf:
        im1 = pdf.pages[0].Resources.XObject.Im1
        assert im1.read_raw_bytes() == data
        assert [str(f) for f in im1.Filter] == filters


@pytest.mark.parametrize(
    ("make_data", "filters"),
    [
        pytest.param(
            lambda: zlib.compress(Image.new("RGB", (300, 300), (10, 120, 200)).tobytes()),
            ["/FlateDecode"],
            id="lossless",
        ),
        pytest.param(
            lambda: base64.a85encode(_entropy_jpeg_bytes(300, 98)) + b"~>",
            ["/ASCII85Decode", "/DCTDecode"],
            id="jpeg-behind-ascii85",  # how ReportLab stores a JPEG
        ),
        pytest.param(
            lambda: zlib.compress(_entropy_jpeg_bytes(300, 98)),
            ["/FlateDecode", "/DCTDecode"],
            id="jpeg-behind-flate",
        ),
    ],
)
def test_engine_re_encodes_lossless_images_and_jpegs_behind_a_filter(tmp_path, make_data, filters):
    import pikepdf

    from app.compressors.pdf import compress_pdf_to_target

    src, out = tmp_path / "in.pdf", tmp_path / "out.pdf"
    _two_image_pdf(src, make_data(), filters)

    result = compress_pdf_to_target(src, out, target_bytes=10 * 1024 * 1024)

    assert result["recompressible_images"] == 2
    with pikepdf.open(str(out)) as pdf:
        assert pdf.pages[0].Resources.XObject.Im1.Filter == "/DCTDecode"


def test_engine_survives_a_jpeg_cut_short(tmp_path):
    """A damaged JPEG doesn't fail the request. (Whether its rest decodes as
    gray depends on the platform's JPEG library, so only that is checked.)"""
    from app.compressors.pdf import compress_pdf_to_target

    src, out = tmp_path / "in.pdf", tmp_path / "out.pdf"
    _two_image_pdf(src, _entropy_jpeg_bytes(300, 90)[:2000], ["/DCTDecode"])

    result = compress_pdf_to_target(src, out, target_bytes=10 * 1024 * 1024)

    assert result["recompressible_images"] >= 1
    assert out.read_bytes()[:4] == b"%PDF"


def test_engine_leaves_a_doubly_compressed_image_as_it_is(tmp_path):
    """Two filters that can expand data are one too many: the image isn't
    decoded. (The re-save may store the same samples under one filter.)"""
    import pikepdf

    from app.compressors.pdf import compress_pdf_to_target

    samples = Image.new("RGB", (300, 300), (5, 6, 7)).tobytes()
    src, out = tmp_path / "in.pdf", tmp_path / "out.pdf"
    _two_image_pdf(src, zlib.compress(zlib.compress(samples)), ["/FlateDecode", "/FlateDecode"])

    result = compress_pdf_to_target(src, out, target_bytes=10 * 1024 * 1024)

    assert result["recompressible_images"] == 1
    with pikepdf.open(str(out)) as pdf:
        assert pdf.pages[0].Resources.XObject.Im1.read_bytes() == samples


def test_engine_leaves_an_image_with_a_malformed_filter_as_it_is(tmp_path):
    import pikepdf

    from app.compressors.pdf import compress_pdf_to_target

    data = _entropy_jpeg_bytes(300, 90)
    src, out = tmp_path / "in.pdf", tmp_path / "out.pdf"
    _two_image_pdf(src, data, ["/DCTDecode"], Filter=pikepdf.String("/DCTDecode"))

    result = compress_pdf_to_target(src, out, target_bytes=10 * 1024 * 1024)

    assert result["recompressible_images"] == 1
    with pikepdf.open(str(out)) as pdf:
        assert pdf.pages[0].Resources.XObject.Im1.read_raw_bytes() == data


def test_engine_leaves_images_over_the_pixel_limit(tmp_path, monkeypatch):
    """An image over Pillow's per-image limit is left as it is, JPEG or not."""
    from app.compressors.pdf import compress_pdf_to_target

    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 300 * 300 - 1)
    src, out = tmp_path / "in.pdf", tmp_path / "out.pdf"
    _two_image_pdf(src, zlib.compress(bytes(300 * 300 * 3)), ["/FlateDecode"])

    result = compress_pdf_to_target(src, out, target_bytes=10 * 1024 * 1024)

    assert result["recompressible_images"] == 0


def test_engine_keeps_the_decode_array_of_a_lossless_image(tmp_path):
    """An inverted grayscale image keeps its stored samples and its /Decode,
    so a viewer still inverts it exactly once."""
    import pikepdf
    from pikepdf import Array, Name, PdfImage

    from app.compressors.pdf import compress_pdf_to_target

    src, out = tmp_path / "in.pdf", tmp_path / "out.pdf"
    samples = bytes([40]) * (300 * 300)  # dark samples, shown light
    _two_image_pdf(
        src,
        zlib.compress(samples),
        ["/FlateDecode"],
        ColorSpace=Name("/DeviceGray"),
        Decode=Array([1, 0]),
    )

    result = compress_pdf_to_target(src, out, target_bytes=10 * 1024 * 1024)

    assert result["recompressible_images"] == 2
    with pikepdf.open(str(out)) as pdf:
        im1 = pdf.pages[0].Resources.XObject.Im1
        assert list(im1.Decode) == [1, 0]
        stored = PdfImage(im1).as_pil_image(apply_decode_array=False).convert("L")
        assert abs(ImageStat.Stat(stored).mean[0] - 40) < 5


# ── Engine: input validation ─────────────────────────────────────────────────


@pytest.mark.parametrize("bad", [0, -1, -1000])
def test_engine_rejects_non_positive_target(tmp_path, bad):
    from app.compressors.pdf import compress_pdf_to_target

    src = _image_pdf_file(tmp_path)
    with pytest.raises(ValueError, match="positive"):
        compress_pdf_to_target(src, tmp_path / "o.pdf", target_bytes=bad)


# ── Route: happy path ────────────────────────────────────────────────────────


def test_route_compress_image_pdf(client, auth_headers):
    import pikepdf

    res = client.post(
        "/api/v1/pdf/compress",
        headers=auth_headers,
        files={"file": ("doc.pdf", _image_pdf_bytes(), _PDF_MIME)},
        data={"target_kb": "200"},
    )
    assert res.status_code == 200, res.text
    assert res.content[:4] == b"%PDF"
    with pikepdf.open(io.BytesIO(res.content)) as pdf:
        assert len(pdf.pages) == 1
    achieved = int(res.headers["X-FileMorph-Achieved-Bytes"])
    assert achieved == len(res.content)
    assert res.headers["X-FileMorph-Recompressible-Images"] == "1"
    # Download name carries the original stem, sanitised, never a disk path.
    assert "doc_compressed.pdf" in res.headers.get("content-disposition", "")


def test_route_compress_past_the_limits_names_the_next_step(client, auth_headers, monkeypatch):
    """The engine runs in a child process with memory and time limits; past
    them the route answers 400 and points to extracting fewer pages."""
    from app.converters import _isolated

    module, function, memory, _, file_bytes = _isolated._STEPS["pdf-compress"]
    limits = (module, function, memory, 0.01, file_bytes)
    monkeypatch.setitem(_isolated._STEPS, "pdf-compress", limits)
    res = client.post(
        "/api/v1/pdf/compress",
        headers=auth_headers,
        files={"file": ("doc.pdf", _image_pdf_bytes(), _PDF_MIME)},
        data={"target_kb": "200"},
    )
    assert res.status_code == 400
    assert res.headers["X-FileMorph-Error-Code"] == "pdf_too_complex"
    assert "/api/v1/pdf/extract" in res.json()["detail"]


def test_route_compress_long_name_keeps_suffix(client, auth_headers):
    # An over-long stem is shortened; "_compressed.pdf" survives intact.
    res = client.post(
        "/api/v1/pdf/compress",
        headers=auth_headers,
        files={"file": ("d" * 250 + ".pdf", _image_pdf_bytes(), _PDF_MIME)},
        data={"target_kb": "200"},
    )
    assert res.status_code == 200, res.text
    expected = "d" * 185 + "_compressed.pdf"
    assert f'filename="{expected}"' in res.headers.get("content-disposition", "")


def test_route_compress_shrinks_below_source(client, auth_headers):
    source = _image_pdf_bytes(dim=1400, quality=98)
    res = client.post(
        "/api/v1/pdf/compress",
        headers=auth_headers,
        files={"file": ("big.pdf", source, _PDF_MIME)},
        data={"target_kb": "150"},
    )
    assert res.status_code == 200, res.text
    assert len(res.content) < len(source)


def test_route_compress_text_pdf_reports_not_converged(client, auth_headers):
    """Image-poor PDF: 200 OK, valid PDF, headers flag nothing to shrink."""
    import pikepdf

    res = client.post(
        "/api/v1/pdf/compress",
        headers=auth_headers,
        files={"file": ("text.pdf", _text_pdf_bytes(2), _PDF_MIME)},
        data={"target_kb": "10"},
    )
    assert res.status_code == 200, res.text
    assert res.content[:4] == b"%PDF"
    assert res.headers["X-FileMorph-Converged"] == "false"
    assert res.headers["X-FileMorph-Recompressible-Images"] == "0"
    with pikepdf.open(io.BytesIO(res.content)) as pdf:
        assert len(pdf.pages) == 2


# ── Route: validation + hardening ────────────────────────────────────────────


@pytest.mark.parametrize("bad", ["0", "-1", "abc", ""])
def test_route_compress_bad_target_is_4xx_no_stacktrace(client, auth_headers, bad):
    res = client.post(
        "/api/v1/pdf/compress",
        headers=auth_headers,
        files={"file": ("doc.pdf", _image_pdf_bytes(dim=400), _PDF_MIME)},
        data={"target_kb": bad},
    )
    assert res.status_code in (400, 422), res.text
    assert res.status_code != 500
    body = res.text.lower()
    assert "traceback" not in body
    assert "pikepdf" not in body


def test_route_compress_huge_target_is_413(client, auth_headers):
    """A target above the anonymous output cap is rejected before any work."""
    res = client.post(
        "/api/v1/pdf/compress",
        headers=auth_headers,
        files={"file": ("doc.pdf", _image_pdf_bytes(dim=400), _PDF_MIME)},
        data={"target_kb": "999999"},  # ~977 MB > anonymous 90 MB cap
    )
    assert res.status_code == 413, res.text
    assert "output cap" in res.json()["detail"].lower()


def test_route_compress_target_over_form_ceiling_is_422(client, auth_headers):
    """Beyond the form-level sanity ceiling (2 GB in KB) → 422 validation."""
    res = client.post(
        "/api/v1/pdf/compress",
        headers=auth_headers,
        files={"file": ("doc.pdf", _image_pdf_bytes(dim=400), _PDF_MIME)},
        data={"target_kb": str(3 * 1024 * 1024)},
    )
    assert res.status_code == 422, res.text


def test_route_compress_non_pdf_is_422(client, auth_headers):
    res = client.post(
        "/api/v1/pdf/compress",
        headers=auth_headers,
        files={"file": ("photo.jpg", b"\xff\xd8\xff\xe0fake", "image/jpeg")},
        data={"target_kb": "100"},
    )
    assert res.status_code == 422, res.text


def test_route_compress_corrupt_pdf_is_400_no_stacktrace(client, auth_headers):
    res = client.post(
        "/api/v1/pdf/compress",
        headers=auth_headers,
        files={"file": ("doc.pdf", b"%PDF-1.4 not a real pdf body", _PDF_MIME)},
        data={"target_kb": "100"},
    )
    assert res.status_code == 400, res.text
    assert res.status_code != 500
    body = res.text.lower()
    assert "traceback" not in body
    assert "pikepdf" not in body


def test_route_compress_blocks_disguised_executable(client, auth_headers):
    res = client.post(
        "/api/v1/pdf/compress",
        headers=auth_headers,
        files={"file": ("malware.pdf", b"MZ\x90\x00 this is a PE", _PDF_MIME)},
        data={"target_kb": "100"},
    )
    assert res.status_code == 400, res.text
    assert "not permitted" in res.text.lower()
