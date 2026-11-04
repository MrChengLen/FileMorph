# SPDX-License-Identifier: AGPL-3.0-or-later
"""The converter's result card: how the result's size compares to the
original's, and a small picture of an image result (app.js, single files).

The repo has no JS runner, so the script is pinned by its source (as in
tests/test_converter_i18n.py) and the markup and texts by the rendered pages.
The CSP that lets the picture load is pinned in tests/test_csp_profiles.py.
"""

import json
import re
from pathlib import Path

from app.compressors.image import _SUPPORTED_FORMATS as IMAGE_COMPRESS_FMTS
from app.converters.registry import get_supported_conversions

APP_JS = (Path(__file__).resolve().parent.parent / "app" / "static" / "js" / "app.js").read_text(
    encoding="utf-8"
)
BLOB = re.compile(r'<script id="fm-i18n-strings" type="application/json">(.*?)</script>', re.DOTALL)


def _function(name: str) -> str:
    """The body of a top-level function in app.js."""
    head = re.search(rf"^(?:async )?function {name}\(", APP_JS, re.MULTILINE)
    assert head, f"function {name} missing from app.js"
    return APP_JS[head.start() :].split("\n}\n", 1)[0]


def test_the_result_card_has_the_preview_above_the_download_button(client):
    html = client.get("/de/").text
    section = html.index('id="result-section"')
    preview = html.index('id="result-preview"')
    link = html.index('id="download-link"')
    assert section < preview < link
    tag = re.search(r'<div id="result-preview" class="([^"]*)"', html)
    assert tag and "hidden" in tag.group(1).split(), "the preview starts hidden"
    image = re.search(r"<img id=\"result-preview-image\"[^>]*>", html)
    assert image, "no picture slot"
    assert 'alt=""' in image.group(0)
    assert "hidden" in re.search(r'class="([^"]*)"', image.group(0)).group(1).split()
    for slot in ('id="result-change"', 'id="result-sizes"'):
        assert slot in html


def test_the_texts_are_german_on_de(client):
    de = json.loads(BLOB.search(client.get("/de/").text).group(1))
    en = json.loads(BLOB.search(client.get("/en/").text).group(1))
    assert de["resultSizeSmaller"] == "{percent} kleiner als das Original"
    assert de["resultSizeLarger"] == "{percent} größer als das Original"
    assert de["resultSizeTimes"] == "{factor}-mal so groß wie das Original"
    assert de["resultSizeSame"] == "Etwa so groß wie das Original"
    assert de["resultSizes"] == "Vorher {before}, jetzt {after}"
    assert de["resultPreviewAlt"] == "Vorschau von {name}"
    assert en["resultSizeSmaller"] == "{percent} smaller than the original"


def test_only_a_single_file_gets_a_preview():
    """A batch ZIP is compressed (ZIP_DEFLATED), so its size is not the
    files': no size line, no picture."""
    submit = _function("submitForm")
    assert re.search(
        r"if \(!isBatch\) \{\s*await showResultPreview\(blob, filename, beforeBytes, "
        r"\{ sizes: !useTargetSize, picture: !videoToGif \}\);",
        submit,
    )
    # The card shows once the preview is in place (the picture decoded).
    assert submit.index("await showResultPreview(") < submit.rindex("showResult();")


def test_the_original_size_is_read_before_the_upload():
    """The selection may change while the server works."""
    submit = _function("submitForm")
    assert submit.index("const beforeBytes = selectedFiles[0].size;") < submit.index(
        "await fetch(endpoint"
    )


def test_what_arrives_for_a_reset_run_is_dropped():
    """Another file or mode mid-run resets the card; the old response, or its
    picture still decoding, must not bring back a stale result or a card whose
    download link the reset already released (product-ux: no dead end)."""
    submit = _function("submitForm")
    assert submit.index("const run = ++currentRun;") < submit.index("showProgress(")
    # After the fetch, the error body, the result body and the picture.
    assert submit.count("if (run !== currentRun) return;") == 4
    assert "if (run === currentRun) showError(" in submit
    assert "currentRun++;" in _function("resetResultState")


def test_every_new_run_error_and_reset_releases_the_result():
    """No picture or numbers of an earlier result, and its blob: URLs are
    freed: before, every result stayed in memory until the page closed."""
    for name in ("showProgress", "showError", "resetResultState"):
        assert "releaseResult();" in _function(name), name
    release = _function("releaseResult")
    assert "URL.revokeObjectURL(resultPreviewUrl);" in release
    assert "URL.revokeObjectURL(link.href);" in release
    assert "image.removeAttribute('src');" in release


def test_the_picture_shows_only_once_decoded():
    """No broken-image icon for a format the browser can't show, no jump."""
    preview = _function("showResultPreview")
    assert preview.index("await image.decode();") < preview.index(
        "image.classList.remove('hidden');"
    )
    # A plain object lookup: an extension like "__proto__" finds no type.
    assert "Object.prototype.hasOwnProperty.call(PREVIEW_IMAGE_TYPES, ext)" in preview


def test_a_picture_too_costly_to_decode_is_left_out():
    """Decoding costs ~4 bytes per pixel whatever the file size; a phone tab
    that dies takes the result with it. The numbers still show."""
    preview = _function("showResultPreview")
    assert "blob.size > PREVIEW_MAX_BYTES" in preview
    assert preview.index(
        "image.naturalWidth * image.naturalHeight > PREVIEW_MAX_PIXELS"
    ) < preview.index("await image.decode();")
    # Load and decode together never hold the card back longer than this,
    # and a picture given up on stops loading.
    assert "setTimeout(reject, PREVIEW_DECODE_MS)" in preview
    catch = preview.split("} catch (_) {", 1)[1]
    assert "if (resultPreviewUrl === url) image.removeAttribute('src');" in catch
    assert "const PREVIEW_MAX_BYTES = 10 * 1024 * 1024;" in APP_JS
    assert "const PREVIEW_MAX_PIXELS = 16e6;" in APP_JS
    assert "const PREVIEW_DECODE_MS = 1500;" in APP_JS


def test_picture_types_are_image_formats_filemorph_writes():
    block = APP_JS.split("const PREVIEW_IMAGE_TYPES = {", 1)[1].split("};", 1)[0]
    types = dict(re.findall(r"(\w+): '([^']+)'", block))
    assert types, "type scan looks broken"
    written = {t for targets in get_supported_conversions().values() for t in targets}
    written |= set(IMAGE_COMPRESS_FMTS)
    assert set(types) <= written, sorted(set(types) - written)
    assert all(mime.startswith("image/") for mime in types.values())
    # Formats most browsers can't show stay out: no broken picture slot.
    assert not {"tif", "tiff", "heic", "heif", "svg"} & set(types)


def test_the_change_reads_100_percent_smaller_only_for_an_empty_result():
    """Rounded, 99.6 % smaller would read "100 %" — as if nothing were left.
    An empty result (PDF → TXT of a scan without text) does read 100 %."""
    assert "Math.min(after > 0 ? 99 : 100, Math.round((1 - ratio) * 100))" in _function(
        "resultChangeText"
    )


def test_every_download_link_releases_its_previous_result():
    """A download link holds its result in memory until its blob: URL is
    revoked; the PDF tools and the redaction tool revoke it on the next one."""
    js = Path(__file__).resolve().parent.parent / "app" / "static" / "js"
    for name in ("pdf-tools.js", "redact.js"):
        source = (js / name).read_text(encoding="utf-8")
        revoke = "if (link.href && link.href.startsWith('blob:')) URL.revokeObjectURL(link.href);"
        assert source.index(revoke) < source.index("link.href = URL.createObjectURL(blob);"), name
