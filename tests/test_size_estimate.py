# SPDX-License-Identifier: AGPL-3.0-or-later
"""The size estimate under the compress slider (app.js, one JPEG) and the
PNG/TIFF note that replaces the slider, plus the lossless TIFF save they
rely on (app/compressors/image.py).

The browser encodes the picture itself and shows the result's size only
where a probe picture proves its JPEG encoder writes the server's bytes:
ESTIMATE_PROBE_BYTES must be what Pillow writes, and the server must keep
only its 18-byte JFIF header (ESTIMATE_PILLOW_APP_BYTES). The repo has no
JS test runner, so the script is pinned by its source (as in
tests/test_result_preview.py); its pure helpers run under Node, which the
CI runners have.
"""

import json
import os
import re
import shutil
import subprocess
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageCms, ImageDraw

from app.compressors.image import _PIL_FORMAT, _encode_to_bytes, compress_image
from app.converters._metadata import ICC_MAX_BYTES, strip_metadata
from app.core.image_hardening import open_image

APP_JS = (Path(__file__).resolve().parent.parent / "app" / "static" / "js" / "app.js").read_text(
    encoding="utf-8"
)
SECTION = APP_JS.split("// ── Size estimate", 1)[1].split("// ── Submit", 1)[0]
BLOB = re.compile(r'<script id="fm-i18n-strings" type="application/json">(.*?)</script>', re.DOTALL)
NODE = shutil.which("node")


def _function(name: str) -> str:
    """A top-level function of app.js, closing brace included."""
    head = re.search(rf"^(?:async )?function {name}\(", APP_JS, re.MULTILINE)
    assert head, f"function {name} missing from app.js"
    return APP_JS[head.start() :].split("\n}\n", 1)[0] + "\n}\n"


def _js_constant(name: str):
    match = re.search(rf"^const {name} = (\[[^\]]*\]|\d+);", APP_JS, re.MULTILINE)
    assert match, f"const {name} missing from app.js"
    return json.loads(match.group(1).replace("'", '"').replace(",\n]", "\n]"))


def probe_pixels(size: int) -> bytes:
    """The probe picture as RGB, the same pixels as estimateProbePixels."""
    data = bytearray(size * size * 3)
    seed = 12345
    for y in range(size):
        for x in range(size):
            seed = (seed * 1103515245 + 12345) & 0xFFFFFFFF
            grain = (seed >> 16) % 32
            i = (y * size + x) * 3
            data[i] = min(255, ((x * 3 + y) >> 1) + grain)
            data[i + 1] = min(255, ((x * y) >> 8) + grain)
            data[i + 2] = min(255, (((x - 128) ** 2 + (y - 96) ** 2) >> 7) + grain)
    return bytes(data)


def jpeg_info(data: bytes) -> dict | None:
    """What jpegInfo should say: the APPn bytes up to the scan, the frame
    header's fields and the colour profile as Pillow reads it — or None when
    no frame and scan follow, or the frame header comes twice or misshapen."""
    if data[:2] != b"\xff\xd8":
        return None
    info = {
        "appBytes": 0,
        "precision": 0,
        "width": 0,
        "height": 0,
        "components": 0,
        "iccBytes": 0,
        "iccSpace": "",
    }
    icc = []
    frame = False
    pos = 2
    while pos + 4 <= len(data):
        marker = data[pos + 1]
        length = int.from_bytes(data[pos + 2 : pos + 4], "big")
        if 0xE0 <= marker <= 0xEF:
            info["appBytes"] += length + 2
        if marker == 0xE2 and not frame and data[pos + 4 : pos + 16] == b"ICC_PROFILE\x00":
            icc.append((data[pos + 16], data[pos + 17], pos + 18, length - 16))
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            if frame or length != 8 + 3 * data[pos + 9]:
                return None
            frame = True
            info["precision"] = data[pos + 4]
            info["height"] = int.from_bytes(data[pos + 5 : pos + 7], "big")
            info["width"] = int.from_bytes(data[pos + 7 : pos + 9], "big")
            info["components"] = data[pos + 9]
        if marker == 0xDA:
            if not frame:
                return None
            icc.sort(key=lambda part: (part[0], part[1]))
            if icc and icc[0][1] == len(icc):
                info["iccBytes"] = sum(part[3] for part in icc)
                if icc[0][3] >= 20 and icc[0][2] + 20 <= len(data):
                    info["iccSpace"] = data[icc[0][2] + 16 : icc[0][2] + 20].decode("latin-1")
            return info
        pos += length + 2
    return None


def pillow_icc_bytes(icc_len: int) -> int:
    """APP2 bytes the server writes for a profile: 18 per piece of 65 519 —
    none for one over ICC_MAX_BYTES, which strip_metadata drops."""
    if not icc_len or icc_len > ICC_MAX_BYTES:
        return 0
    return icc_len + 18 * -(-icc_len // 65519)


def _profile(space: bytes = b"RGB ", size: int = 0) -> bytes:
    """A real sRGB profile, or a stand-in of ``size`` bytes for another
    colour space (only the header's colour space matters here)."""
    if space == b"RGB " and not size:
        return ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    raw = bytearray((bytes(range(256)) * (size // 256 + 1))[:size])
    raw[16:20] = space
    return bytes(raw)


def _photo(width: int = 160, height: int = 120) -> Image.Image:
    """A deterministic picture with grain — compresses roughly like a photo."""
    return Image.frombytes("RGB", (64, 64), probe_pixels(64)).resize(
        (width, height), Image.Resampling.BICUBIC
    )


# ── The page ─────────────────────────────────────────────────────────────────


def test_the_estimate_line_sits_under_the_slider_and_starts_hidden(client):
    html = client.get("/de/compress").text
    slider = re.search(r'<input id="quality-slider"[^>]*>', html)
    assert slider and 'aria-describedby="size-estimate"' in slider.group(0)
    order = [
        html.index('id="quality-section"'),
        slider.start(),
        html.index('id="size-estimate"'),
        html.index('id="lossless-note"'),
        html.index('id="target-size-section"'),
    ]
    assert order == sorted(order)
    box = re.search(r'<div id="size-estimate" class="([^"]*)"([^>]*)>', html)
    assert box and "hidden" in box.group(1).split()
    assert 'aria-live="polite"' in box.group(2)
    for slot in ('id="size-estimate-text"', 'id="size-estimate-note"'):
        assert slot in html


def test_the_lossless_note_starts_hidden_with_its_webp_switch(client):
    html = client.get("/de/compress").text
    note = re.search(r'<div id="lossless-note"\s+class="([^"]*)"', html)
    assert note and "hidden" in note.group(1).split()
    button = re.search(r'<button id="lossless-to-webp" type="button"\s+class="([^"]*)"', html)
    assert button and "hidden" in button.group(1).split()
    assert "PNG und TIFF sind verlustfrei" in html
    assert "Stattdessen in WebP umwandeln →" in html
    english = client.get("/en/compress").text
    assert "PNG and TIFF are lossless" in english
    assert "PNG und TIFF" not in english


def test_the_estimate_texts_are_german_on_de(client):
    de = json.loads(BLOB.search(client.get("/de/compress").text).group(1))
    en = json.loads(BLOB.search(client.get("/en/compress").text).group(1))
    assert de["sizeEstimate"] == "Geschätzte Größe: ca. {size}"
    assert de["sizeEstimateNote"] == "{change} · im Browser berechnet, ohne Hochladen"
    assert de["sizeEstimateLarger"] == "{change} – wähle eine niedrigere Qualität"
    assert de["sizeEstimatePending"] == "Größe wird berechnet…"
    assert de["sizeEstimateNone"] == (
        "Für diese Datei gibt es keine Größenvorschau. Mit „Nach Zielgröße“ legst du "
        "die Größe selbst fest."
    )
    assert de["sizeEstimateBrowser"] == (
        "Dein Browser kann die Größe hier nicht genau vorausberechnen. Mit „Nach "
        "Zielgröße“ legst du sie selbst fest."
    )
    assert de["sizeEstimateVideo"] == (
        "Bei Videos steht die Größe erst nach dem Komprimieren fest."
    )
    assert en["sizeEstimate"] == "Estimated size: about {size}"


# ── The script ───────────────────────────────────────────────────────────────


def test_the_estimate_uploads_nothing():
    """Worked out in the browser: no request of any kind in the section."""
    for call in ("fetch(", "FormData", "XMLHttpRequest", "sendBeacon", "UPLOAD_BASE", "WebSocket"):
        assert call not in SECTION, call


def test_every_wait_is_followed_by_a_check_for_a_newer_run():
    """A slider move, another file or another mode while the browser decodes
    or encodes starts a new run; the older one must stop at once, never show
    its number (product-ux.md #1) or keep a picture of another file."""
    body = _function("runSizeEstimate")
    lines = [line.strip() for line in body.splitlines()]
    waits = [i for i, line in enumerate(lines) if "await " in line]
    assert len(waits) >= 5, lines
    for i in waits:
        assert lines[i + 1].startswith("if (run !== estimateRun"), lines[i]
    # The one exception: after a mere slider move the picture is kept.
    assert (
        "if (run !== estimateRun && !(canvas && selectedFiles[0] === file "
        "&& sizeEstimateKind() === 'jpeg')) {"
    ) in body
    assert "if (canvas) { canvas.width = 0; canvas.height = 0; }" in body


def test_the_picture_is_read_before_it_is_decoded():
    """Bit depth, components, pixels and bytes come first: a large picture is
    never decoded (4 bytes a pixel), greyscale and CMYK (which the server
    writes with 1 and 4 components) get no estimate."""
    body = _function("runSizeEstimate")
    decode = body.index("decodeForEstimate(file, info)")
    for check in (
        "info.precision !== 8",
        "info.components !== 3",
        "pixels > ESTIMATE_MAX_PIXELS",
        "file.size > ESTIMATE_MAX_BYTES",
    ):
        assert body.index(check) < decode, check
    assert (
        "ESTIMATE_MAX_PIXELS = (navigator.deviceMemory || 0) >= 8 ? 25e6 : PREVIEW_MAX_PIXELS"
        in (SECTION)
    )


def test_the_decode_is_the_servers_or_none():
    """Turned upright and with the stored colour values, like the server; not
    waited on longer than ESTIMATE_DECODE_MS (a late picture is released), and
    measured only at the size its header says — Chromium decodes smaller when
    memory is short, which would give a wrong number."""
    decode = _function("decodeForEstimate")
    assert (
        "createImageBitmap(file, { imageOrientation: 'from-image', colorSpaceConversion: 'none' })"
        in decode
    )
    assert "Promise.race([" in decode and "ESTIMATE_DECODE_MS" in decode
    assert "decoding.then(late => late.close(), () => {});" in decode
    assert "bitmap.width === info.width && bitmap.height === info.height" in decode
    assert "bitmap.width === info.height && bitmap.height === info.width" in decode
    assert decode.count("bitmap.close();") == 2, "on a wrong size and after drawing"
    # A failed decode is not tried again for the same file on every slider move.
    body = _function("runSizeEstimate")
    retry = body.index("if (estimateFailed === file) { showSizeEstimate('none'); return; }")
    assert retry < body.index("decodeForEstimate(file, info)")
    assert body.count("estimateFailed = file") == 2, "a late and a current failure"


def test_only_a_proven_encoder_gets_a_number():
    body = _function("runSizeEstimate")
    assert body.index("estimateProbeMatches(quality)") < body.index("decodeForEstimate(")
    assert "if (!matches) { showSizeEstimate('browser'); return; }" in body
    assert "blob.type === 'image/jpeg'" in body
    assert (
        "const after = blob.size - out.appBytes + ESTIMATE_PILLOW_APP_BYTES + "
        "estimateSource.iccBytes;"
    ) in body
    assert "estimateSource = { file, canvas, iccBytes: pillowIccBytes(info) };" in body
    probe = _function("estimateProbeMatches")
    assert "blob.type !== 'image/jpeg'" in probe, "Safari answers an unknown type with a PNG"
    assert "blob.size - info.appBytes === ESTIMATE_PROBE_BYTES[quality - 1]" in probe
    assert ".catch(() => false)" in probe


def test_every_change_schedules_a_new_estimate():
    assert re.search(
        r"function updateQualityVisibility\(\) \{\n  updateQualityControls\(\);\n"
        r"(?:  //[^\n]*\n)*  scheduleSizeEstimate\(\);\n\}",
        APP_JS,
    ), "the estimate goes by the controls, so it runs after them"
    slider = APP_JS.split("qualitySlider.addEventListener('input'", 1)[1].split("});", 1)[0]
    assert "scheduleSizeEstimate();" in slider
    schedule = _function("scheduleSizeEstimate")
    assert schedule.index("showSizeEstimate('pending')") < schedule.index("setTimeout(")
    assert "releaseEstimateSource()" in schedule


def test_the_estimate_reads_like_the_result_card():
    show = _function("showSizeEstimate")
    assert "resultChangeText(sizes.before, sizes.after)" in show
    assert "formatBytes(sizes.after)" in show
    assert "sizes.after >= sizes.before * 0.99" in show, "no smaller file: ask for a lower quality"
    assert "box.setAttribute('aria-busy', state === 'pending' ? 'true' : 'false');" in show


def test_the_formats_match_the_server():
    """JPEG gets an estimate; PNG and TIFF, saved losslessly whatever the
    quality, get the note instead of the slider."""
    assert _js_constant("ESTIMATE_TYPES") == [e for e, f in _PIL_FORMAT.items() if f == "JPEG"]
    lossless = [e for e, f in _PIL_FORMAT.items() if f in ("PNG", "TIFF")]
    assert _js_constant("LOSSLESS_COMPRESS_TYPES") == lossless
    controls = _function("updateQualityControls")
    assert "section.classList.toggle('hidden', showTarget || lossless);" in controls
    assert controls.count("showLosslessNote(") == 3, "shown, and hidden on both other paths"


# ── Parity with the server's encoder ─────────────────────────────────────────


def test_the_probe_table_is_what_the_server_writes():
    """ESTIMATE_PROBE_BYTES: Pillow's JPEG of the probe picture at each
    quality, without its 18-byte JFIF header. A Pillow or libjpeg-turbo
    update that changes these makes every browser fail the probe — no number
    rather than a wrong one — and this test says what to pin instead."""
    img = Image.frombytes("RGB", (64, 64), probe_pixels(64))
    expected = [len(_encode_to_bytes(img, "JPEG", q)) - 18 for q in range(1, 101)]
    assert _js_constant("ESTIMATE_PROBE_BYTES") == expected, f"pin {expected}"
    assert _js_constant("ESTIMATE_PROBE_SIZE") == 64


def test_compress_image_writes_the_probes_bytes(tmp_path):
    """The table comes from _encode_to_bytes; compress_image must encode a
    JPEG with exactly those settings."""
    src = tmp_path / "src.jpg"
    _photo().save(src, format="JPEG", quality=95)
    for quality in (30, 85):
        out = tmp_path / f"out{quality}.jpg"
        compress_image(src, out, quality=quality)
        expected = _encode_to_bytes(strip_metadata(open_image(src)), "JPEG", quality)
        assert out.read_bytes() == expected


@pytest.mark.parametrize(
    "icc",
    [None, _profile(), _profile(b"RGB ", 70_144), _profile(b"GRAY", 600)],
    ids=["none", "srgb", "two-pieces", "grey-profile"],
)
def test_the_server_keeps_its_jfif_header_and_the_colour_profile(tmp_path, icc):
    """ESTIMATE_PILLOW_APP_BYTES + pillowIccBytes: of the original's APPn
    segments — EXIF, a colour profile — the compressed JPEG keeps the 18-byte
    JFIF header and an RGB colour profile in pieces of 65 519 bytes. A profile
    for other pixels (here greyscale on RGB) goes (strip_metadata)."""
    exif = Image.Exif()
    exif[0x0112] = 6  # orientation: turned
    src = tmp_path / "src.jpg"
    options = {"icc_profile": icc} if icc else {}
    _photo().save(src, format="JPEG", quality=90, exif=exif, **options)
    out = tmp_path / "out.jpg"
    compress_image(src, out, quality=70)
    kept = icc if icc and icc[16:20] == b"RGB " else None
    expected = _js_constant("ESTIMATE_PILLOW_APP_BYTES") + pillow_icc_bytes(len(kept or b""))
    assert jpeg_info(out.read_bytes())["appBytes"] == expected
    with Image.open(out) as result:
        assert result.info.get("icc_profile") == kept


def _sample_jpegs(tmp_path: Path) -> dict[str, Path]:
    icc = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    exif = Image.Exif()
    exif[0x0112] = 6
    photo = _photo(150, 100)
    samples = {
        "plain": (photo, {}),
        "icc": (photo, {"icc_profile": icc}),
        "icc_two_chunks": (photo, {"icc_profile": _profile(b"RGB ", 70_144)}),
        "icc_grey_profile": (photo, {"icc_profile": _profile(b"GRAY", 600)}),
        "exif": (photo, {"exif": exif}),
        "progressive": (photo, {"progressive": True}),
        "grey": (photo.convert("L"), {}),
        "cmyk": (photo.convert("CMYK"), {}),
    }
    paths = {}
    for name, (img, options) in samples.items():
        path = tmp_path / f"{name}.jpg"
        img.save(path, format="JPEG", quality=85, **options)
        paths[name] = path
    whole = paths["plain"].read_bytes()
    broken = {"cut": whole[: whole.index(b"\xff\xda")]}
    # A frame header for 65535 x 65535 before the real one, and a frame header
    # whose length doesn't fit its components: the pixel check would read the
    # wrong size, so both count as unreadable.
    sof = _segment_offset(whole, 0xC0)
    huge = b"\xff\xc0\x00\x11\x08\xff\xff\xff\xff\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    broken["two_frames"] = whole[:sof] + huge + whole[sof:]
    broken["short_frame"] = whole[: sof + 2] + b"\x00\x02" + whole[sof + 4 :]
    buf = BytesIO()
    photo.save(buf, format="PNG")
    broken["png"] = buf.getvalue()
    for name, data in broken.items():
        (tmp_path / f"{name}.jpg").write_bytes(data)
        paths[name] = tmp_path / f"{name}.jpg"
    # The colour profile's segment moved behind the frame header: Pillow puts
    # the profile together at the frame header, so this one doesn't count.
    with_icc = paths["icc"].read_bytes()
    app2 = _segment_offset(with_icc, 0xE2)
    segment = with_icc[app2 : app2 + 2 + int.from_bytes(with_icc[app2 + 2 : app2 + 4], "big")]
    sof_end = sof + 2 + int.from_bytes(whole[sof + 2 : sof + 4], "big")
    (tmp_path / "icc_after_sof.jpg").write_bytes(whole[:sof_end] + segment + whole[sof_end:])
    paths["icc_after_sof"] = tmp_path / "icc_after_sof.jpg"
    return paths


BROKEN = ("cut", "two_frames", "short_frame", "png")


def _segment_offset(data: bytes, wanted: int) -> int:
    """Where the first segment with this marker starts."""
    pos = 2
    while data[pos + 1] != wanted:
        pos += 2 + int.from_bytes(data[pos + 2 : pos + 4], "big")
    return pos


_RUNNER = """
const files = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const out = { probe: Buffer.from(estimateProbePixels(64)).toString('hex') };
for (const [name, path] of Object.entries(files)) {
  const info = jpegInfo(new Uint8Array(fs.readFileSync(path)));
  out[name] = { info, icc: info ? pillowIccBytes(info) : null };
}
process.stdout.write(JSON.stringify(out));
"""


@pytest.mark.skipif(NODE is None and not os.environ.get("CI"), reason="Node is not installed")
def test_the_js_helpers_match_python(tmp_path):
    """estimateProbePixels makes the probe's pixels, and jpegInfo reads the
    segments: run under Node on JPEGs with a colour profile (one and two
    chunks), EXIF, progressive, greyscale and CMYK, plus a cut-off file, a
    doubled and a misshapen frame header, and a PNG."""
    assert NODE, "CI must run the JS helpers; Node is on the runners"
    paths = _sample_jpegs(tmp_path)
    script = tmp_path / "run.js"
    icc_mark = re.search(r"^const ICC_MARK = \[[^\]]*\];", APP_JS, re.MULTILINE)
    assert icc_mark, "const ICC_MARK missing from app.js"
    icc_max = re.search(r"^const ICC_MAX_BYTES = 1 << (\d+);", APP_JS, re.MULTILINE)
    assert icc_max and 1 << int(icc_max.group(1)) == ICC_MAX_BYTES, "mirror ICC_MAX_BYTES"
    script.write_text(
        "const fs = require('fs');\n"
        + icc_mark.group(0)
        + "\n"
        + icc_max.group(0)
        + "\n"
        + _function("estimateProbePixels")
        + _function("jpegInfo")
        + _function("pillowIccBytes")
        + _RUNNER,
        encoding="utf-8",
        newline="\n",
    )
    listing = tmp_path / "files.json"
    listing.write_text(
        json.dumps({name: str(path) for name, path in paths.items()}), encoding="utf-8"
    )
    run = subprocess.run(
        [NODE, str(script), str(listing)],
        capture_output=True,
        encoding="utf-8",
        check=True,
        timeout=60,
    )
    result = json.loads(run.stdout)

    rgba = bytes.fromhex(result.pop("probe"))
    rgb = bytes(b for i, b in enumerate(rgba) if i % 4 != 3)
    assert rgb == probe_pixels(64)
    assert set(rgba[3::4]) == {255}

    for name in BROKEN:
        assert result[name]["info"] is None, name
        assert jpeg_info(paths[name].read_bytes()) is None, name
    components = {"RGB": 3, "L": 1, "CMYK": 4}
    for name, path in paths.items():
        if name in BROKEN:
            continue
        info = result[name]["info"]
        assert info == jpeg_info(path.read_bytes()), name
        with Image.open(path) as img:
            assert (info["width"], info["height"]) == img.size, name
            assert info["components"] == components[img.mode], name
            assert info["precision"] == 8, name
            assert info["iccBytes"] == len(img.info.get("icc_profile") or b""), name
        if info["components"] == 3:
            # The profile bytes the estimate adds are the ones the server writes.
            out = tmp_path / f"server-{name}.jpg"
            compress_image(path, out, quality=70)
            server_app = jpeg_info(out.read_bytes())["appBytes"]
            assert result[name]["icc"] == server_app - 18, name
    assert result["icc_after_sof"]["icc"] == 0
    assert result["icc_two_chunks"]["icc"] == 70_144 + 2 * 18
    assert result["icc_grey_profile"]["icc"] == 0
    assert result["icc"]["icc"] > 0


# ── Lossless formats ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("fmt", ["PNG", "TIFF"])
def test_png_and_tiff_come_out_the_same_whatever_the_quality(tmp_path, fmt):
    """What the hidden slider promises: the quality changes nothing."""
    src = tmp_path / f"src.{fmt.lower()}"
    _photo().save(src, format=fmt)
    outputs = set()
    for quality in (5, 50, 95):
        out = tmp_path / f"out{quality}.{fmt.lower()}"
        compress_image(src, out, quality=quality)
        outputs.add(out.read_bytes())
    assert len(outputs) == 1


@pytest.mark.parametrize(
    "original,predictor",
    [
        (None, False),
        ("tiff_lzw", False),
        ("tiff_adobe_deflate", False),
        ("tiff_lzw", True),
        ("tiff_adobe_deflate", True),
    ],
    ids=["raw", "lzw", "deflate", "lzw-predictor", "deflate-predictor"],
)
def test_tiff_is_packed_losslessly_instead_of_growing(tmp_path, original, predictor):
    """Saved without a compression, a compressed TIFF came out as raw pixels —
    larger than an LZW or Deflate original. Photo TIFFs from Photoshop, GIMP
    or libvips use the horizontal predictor, so the result does too."""
    photo = _photo(320, 240)
    src = tmp_path / "src.tiff"
    options = {"tiffinfo": {317: 2}} if predictor else {}
    photo.save(src, format="TIFF", compression=original, **options)
    out = tmp_path / "out.tiff"
    compress_image(src, out, quality=80)
    assert out.stat().st_size <= src.stat().st_size
    if original is None:
        assert out.stat().st_size < src.stat().st_size * 0.9
    with Image.open(out) as result:
        assert result.info["compression"] == "tiff_adobe_deflate"
        assert result.tag_v2.get(317) == 2, "horizontal predictor"
        assert result.tobytes() == photo.tobytes(), "lossless"


def test_a_palette_tiff_keeps_plain_deflate(tmp_path):
    """The predictor makes palette images larger."""
    picture = _photo(320, 240).convert("P")
    src = tmp_path / "src.tiff"
    picture.save(src, format="TIFF", compression="tiff_lzw")
    out = tmp_path / "out.tiff"
    compress_image(src, out, quality=80)
    with Image.open(out) as result:
        assert result.info["compression"] == "tiff_adobe_deflate"
        assert result.tag_v2.get(317, 1) == 1
        assert result.mode == "P"
        assert result.tobytes() == picture.tobytes()


def _scanned_page() -> Image.Image:
    """Black and white like a scanned letter: lines of words, scanned at a
    slight angle. (Clean drawn text repeats exactly and packs better with
    Deflate; a scan doesn't.)"""
    words = "the of and to in is was for on that with as by at from his her an were which".split()
    seed = 7
    page = Image.new("L", (800, 600), 255)
    draw = ImageDraw.Draw(page)
    for row in range(10, 580, 16):
        line = []
        for _ in range(30):
            seed = (seed * 1103515245 + 12345) & 0xFFFFFFFF
            line.append(words[(seed >> 16) % len(words)])
        draw.text((12 + row % 7, row), " ".join(line), fill=0)
    scan = page.resize((1600, 1200), Image.Resampling.BICUBIC).rotate(
        0.4, fillcolor=255, resample=Image.Resampling.BICUBIC
    )
    return scan.point(lambda v: 255 if v > 150 else 0).convert("1", dither=Image.Dither.NONE)


@pytest.mark.parametrize("kind", ["scanned text", "dithered"])
def test_black_and_white_tiff_gets_the_smaller_packing(tmp_path, kind):
    """Group 4 packs a scanned letter best, Deflate a dithered picture."""
    if kind == "scanned text":
        page = _scanned_page()
    else:
        page = _photo(320, 240).convert("1")  # Floyd-Steinberg dithering
    src = tmp_path / "scan.tiff"
    page.save(src, format="TIFF")
    out = tmp_path / "out.tiff"
    compress_image(src, out, quality=80)
    clean = strip_metadata(open_image(src))
    sizes = {}
    for compression in ("group4", "tiff_adobe_deflate"):
        buf = BytesIO()
        clean.save(buf, format="TIFF", compression=compression)
        sizes[compression] = len(buf.getvalue())
    best = min(sizes, key=sizes.get)
    assert best == ("group4" if kind == "scanned text" else "tiff_adobe_deflate"), sizes
    assert out.stat().st_size == sizes[best]
    with Image.open(out) as result:
        assert result.info["compression"] == best
        assert result.tobytes() == page.tobytes()
