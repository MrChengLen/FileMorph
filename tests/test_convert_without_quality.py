# SPDX-License-Identifier: AGPL-3.0-or-later
"""Converting in the web UI has no quality slider: a conversion is saved at the
server's default quality, and the result points to Compress for a smaller file.

The default (85) is where the slider started, so the file is the one a user
who left the slider alone got before; the API keeps its ``quality`` field. The
repo has no JS test runner: the script's logic runs under Node (as in
tests/test_size_estimate.py) with a stand-in for the few page elements it
touches, the rest of the script is pinned by its source, and the markup and
texts by the rendered pages.
"""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from app.compressors.image import _SUPPORTED_FORMATS as IMAGE_COMPRESS_FMTS
from app.compressors.video import _SUPPORTED_FORMATS as VIDEO_COMPRESS_FMTS
from app.converters.registry import get_public_conversions

ROOT = Path(__file__).resolve().parents[1]
APP_JS = (ROOT / "app" / "static" / "js" / "app.js").read_text(encoding="utf-8")
BLOB = re.compile(r'<script id="fm-i18n-strings" type="application/json">(.*?)</script>', re.DOTALL)
NODE = shutil.which("node")
# Compress stores these losslessly whatever the quality: no smaller file there.
LOSSLESS = {"png", "tiff", "tif"}


def _function(name: str) -> str:
    """A top-level function of app.js, closing brace included."""
    head = re.search(rf"^(?:async )?function {name}\(", APP_JS, re.MULTILINE)
    assert head, f"function {name} missing from app.js"
    return APP_JS[head.start() :].split("\n}\n", 1)[0] + "\n}\n"


def _constant(name: str) -> str:
    match = re.search(rf"^const {name} = \[[^\]]*\];", APP_JS, re.MULTILINE)
    assert match, f"const {name} missing from app.js"
    return match.group(0) + "\n"


# ── The script, run under Node ───────────────────────────────────────────────

# Every element the functions ask for is a stand-in that starts hidden, as
# the page's do. argv[2]: [mode, file name] pairs; argv[3]: convert targets.
_RUNNER = r"""
let selectedFiles = [];
let currentMode = 'convert';
let compressMode = 'quality';
const supportedConversions = {};
function element() {
  const classes = new Set(['hidden']);
  return {
    classList: {
      add: c => classes.add(c),
      remove: c => classes.delete(c),
      contains: c => classes.has(c),
      toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)),
    },
    setAttribute() {},
    value: '2',
    textContent: '',
  };
}
const elements = {};
const document = { getElementById: id => (elements[id] = elements[id] || element()) };
function formatDecimal(value) { return String(value); }

const shown = {};
for (const [mode, name] of JSON.parse(process.argv[2])) {
  currentMode = mode;
  selectedFiles = [{ name }];
  updateQualityControls();
  shown[mode + ':' + name] = !document.getElementById('quality-section').classList.contains('hidden');
}
const hint = JSON.parse(process.argv[3]).filter(compressMakesSmaller);
process.stdout.write(JSON.stringify({ shown, hint }));
"""


@pytest.mark.skipif(NODE is None and not os.environ.get("CI"), reason="Node is not installed")
def test_only_compress_mode_shows_the_slider_and_the_result_names_compress(tmp_path):
    """Convert mode hides the slider for every source format; compress mode
    still shows it (not for lossless PNG/TIFF). Under a conversion's result,
    Compress is named for exactly the targets it makes smaller by quality."""
    assert NODE, "CI must run the JS helpers; Node is on the runners"
    conversions = get_public_conversions()
    targets = sorted({t for tgts in conversions.values() for t in tgts})
    cases = [["convert", f"file.{src}"] for src in sorted(conversions)]
    cases += [["compress", f"file.{ext}"] for ext in IMAGE_COMPRESS_FMTS + VIDEO_COMPRESS_FMTS]
    script = tmp_path / "run.js"
    script.write_text(
        _constant("TARGET_SIZE_FORMATS")
        + _constant("LOSSLESS_COMPRESS_TYPES")
        + _constant("COMPRESS_VIDEO_TYPES")
        + _function("getExtension")
        + _function("showLosslessNote")
        + _function("syncCompressModeButtons")
        + _function("updateTargetSizeLabel")
        + _function("updateQualityControls")
        + _function("compressMakesSmaller")
        + _RUNNER,
        encoding="utf-8",
        newline="\n",
    )
    run = subprocess.run(
        [NODE, str(script), json.dumps(cases), json.dumps(targets)],
        capture_output=True,
        encoding="utf-8",
        check=True,
        timeout=60,
    )
    result = json.loads(run.stdout)

    assert len(result["shown"]) == len(cases)
    on_convert = {key for key, shown in result["shown"].items() if shown and key[:8] == "convert:"}
    assert not on_convert, f"a quality slider when converting: {sorted(on_convert)}"
    for ext in IMAGE_COMPRESS_FMTS + VIDEO_COMPRESS_FMTS:
        assert result["shown"][f"compress:file.{ext}"] is (ext not in LOSSLESS), ext

    smaller = set(IMAGE_COMPRESS_FMTS + VIDEO_COMPRESS_FMTS) - LOSSLESS
    assert set(result["hint"]) == {t for t in targets if t in smaller}
    assert {"jpg", "webp", "mp4"} <= set(result["hint"]), "the scan found the usual targets"


def test_the_videos_compress_takes_match_the_server():
    match = re.search(r"^const COMPRESS_VIDEO_TYPES = \[([^\]]*)\];", APP_JS, re.MULTILINE)
    assert match, "const COMPRESS_VIDEO_TYPES missing from app.js"
    assert re.findall(r"'([a-z0-9]+)'", match.group(1)) == VIDEO_COMPRESS_FMTS


def test_no_slider_logic_is_left_for_convert_mode():
    """The pair rules that showed the slider when converting are gone, and the
    heading is no longer switched: the slider is compress mode's alone."""
    for gone in ("pairUsesQuality", "QUALITY_TYPES", "AUDIO_TYPES", "quality-heading"):
        assert gone not in APP_JS, gone
    controls = _function("updateQualityControls")
    assert "if (selectedFiles.length === 0 || currentMode !== 'compress') {" in controls
    # A hidden slider sends nothing: the server's default applies.
    send = "} else if (!document.getElementById('quality-section').classList.contains('hidden')) {"
    assert f"{send}\n" in APP_JS and APP_JS.count("formData.append('quality'") == 1


# ── The server's default ─────────────────────────────────────────────────────


def _convert(client, headers, path: Path, target: str, form: dict[str, str]) -> bytes:
    with path.open("rb") as f:
        res = client.post(
            "/api/v1/convert",
            headers=headers,
            files={"file": (path.name, f, "image/png")},
            data={"target_format": target, **form},
        )
    assert res.status_code == 200, res.text
    return res.content


@pytest.mark.parametrize("target", ["jpg", "webp"])
def test_a_conversion_without_quality_is_the_one_at_85(client, auth_headers, tmp_path, target):
    """What the web UI now sends (no quality) gives the file the untouched
    slider gave (85). A lower quality does change it, so the comparison
    means something."""
    picture = tmp_path / "picture.png"
    Image.radial_gradient("L").convert("RGB").resize((192, 160)).save(picture)
    without = _convert(client, auth_headers, picture, target, {})
    assert without == _convert(client, auth_headers, picture, target, {"quality": "85"})
    assert without != _convert(client, auth_headers, picture, target, {"quality": "40"})


# ── The page ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("path", "text", "link", "href"),
    [
        (
            "/de/",
            "Zu groß? Lade die Datei herunter und mach sie dann unter „Komprimieren“ kleiner.",
            "Zum Komprimieren →",
            "/de/compress",
        ),
        (
            "/en/",
            "Too large? Download the file, then make it smaller under Compress.",
            "Go to Compress →",
            "/en/compress",
        ),
        (
            "/de/convert/jpg-to-webp",
            "Zu groß? Lade die Datei herunter und mach sie dann unter „Komprimieren“ kleiner.",
            "Zum Komprimieren →",
            "/de/compress",
        ),
    ],
    ids=["de-home", "en-home", "de-pair-page"],
)
def test_the_result_card_names_compress_after_the_download(client, path, text, link, href):
    html = client.get(path).text
    hint = re.search(r'<p id="compress-hint"\s+class="([^"]*)"[^>]*>(.*?)</p>', html, re.DOTALL)
    assert hint, f"no pointer to Compress on {path}"
    assert "hidden" in hint.group(1).split(), "it starts hidden"
    assert 'data-component="notice"' in hint.group(0), "the one message box"
    assert html.index('id="download-link"') < hint.start() < html.index('id="error-section"')
    body = " ".join(re.sub(r"<[^>]+>", " ", hint.group(2)).split())
    assert body == f"{text} {link}"
    assert f'href="{href}"' in hint.group(2)


def test_the_pointer_shows_only_for_a_converted_file_and_goes_on_every_reset():
    submit = _function("submitForm")
    # Read before the upload, like the other facts about the selection.
    decided = submit.index("const compressHint = !isBatch && currentMode === 'convert'")
    assert decided < submit.index("await fetch(endpoint")
    assert "&& compressMakesSmaller(document.getElementById('target-format').value);" in submit
    # Set before showResult, which reads the card out.
    shown = submit.index("hint.classList.toggle('hidden', !compressHint);")
    assert submit.index("await showResultPreview(") < shown < submit.rindex("showResult();")
    release = _function("releaseResult")
    assert "document.getElementById('compress-hint')" in release
    assert "hint.classList.add('hidden');" in release


# ── Over the output limit ────────────────────────────────────────────────────


@pytest.mark.parametrize(("locale", "word"), [("en", "quality"), ("de", "qualität")])
def test_a_conversion_over_the_limit_suggests_no_lower_quality(client, accounts, locale, word):
    """Converting has no quality to lower; Compress, with its slider, keeps the
    word. What every limit text must say (FileMorph named, the free account
    only where accounts exist) is tests/test_limit_messages_free_paths.py."""
    strings = json.loads(BLOB.search(client.get(f"/{locale}/").text).group(1))
    assert word not in strings["errorOutputCapConvert"].lower()
    assert word in strings["errorOutputCapExceeded"].lower()


def test_the_script_picks_the_text_by_mode():
    submit = _function("submitForm")
    gif = submit.index("if (videoToGif) msg = i18n.errorOutputCapGif;")
    convert = submit.index("else if (currentMode === 'convert') msg = i18n.errorOutputCapConvert;")
    rest = submit.index("else msg = i18n.errorOutputCapExceeded;")
    assert gif < convert < rest
