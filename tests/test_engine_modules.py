# SPDX-License-Identifier: AGPL-3.0-or-later
"""The engine's pure modules (app/static/engine/core/, check/sample.js),
run under Node and checked against Pillow.

core/sniff.js reads an image's format, size and orientation from its first
bytes, before anything decodes it; core/plan.js keeps every canvas within
the size Safari on the iPhone still draws and searches for a JPEG quality;
check/sample.js writes the device check's test photos. None of them touches
a browser API, so Node runs them as the browser would. The repo has no JS
test runner; Node is on the CI runners (as for tests/test_size_estimate.py).
The browser-side modules (raster/, ops/) run in tests/browser/.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image, ImageOps

from app.core.engine import ENGINE_DIR

NODE = shutil.which("node")
needs_node = pytest.mark.skipif(
    NODE is None and not os.environ.get("CI"), reason="Node is not installed"
)


def _node(tmp_path: Path, script: str) -> object:
    """Runs ``script`` (an ES module) next to a copy of the engine; returns
    what it prints as JSON."""
    assert NODE, "CI must run the engine's modules; Node is on the runners"
    engine = tmp_path / "engine"
    shutil.copytree(ENGINE_DIR, engine, dirs_exist_ok=True)
    # Plain ES modules, as the browser loads them: Node needs to be told.
    (engine / "package.json").write_text('{"type": "module"}\n', encoding="utf-8")
    (engine / "run.js").write_text(script, encoding="utf-8", newline="\n")
    done = subprocess.run(
        [NODE, str(engine / "run.js")],
        capture_output=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _exif_orientation(value: int) -> bytes:
    exif = Image.Exif()
    exif[0x0112] = value
    return exif.tobytes()


def _fixtures(folder: Path) -> dict[str, dict]:
    """Image files and what their headers say."""
    cases: dict[str, tuple[bytes, dict]] = {}

    def save(image: Image.Image, fmt: str, **options) -> bytes:
        out = BytesIO()
        image.save(out, fmt, **options)
        return out.getvalue()

    photo = Image.new("RGB", (640, 480), (120, 90, 60))
    cases["rotated.jpg"] = (
        save(photo, "JPEG", exif=_exif_orientation(6), icc_profile=b"\0" * 300),
        {"format": "jpeg", "width": 640, "height": 480, "orientation": 6, "icc": True},
    )
    cases["plain.jpg"] = (
        save(photo, "JPEG", quality=80),
        {"format": "jpeg", "width": 640, "height": 480, "orientation": 1, "icc": False},
    )
    cases["progressive.jpg"] = (
        save(photo, "JPEG", progressive=True, exif=_exif_orientation(8)),
        {"format": "jpeg", "width": 640, "height": 480, "orientation": 8, "progressive": True},
    )
    cases["grey.jpg"] = (
        save(photo.convert("L"), "JPEG"),
        {"format": "jpeg", "width": 640, "height": 480, "components": 1},
    )
    cases["image.png"] = (save(photo, "PNG"), {"format": "png", "width": 640, "height": 480})
    cases["image.webp"] = (save(photo, "WEBP"), {"format": "webp", "width": None})
    cases["image.gif"] = (save(photo.convert("P"), "GIF"), {"format": "gif", "width": None})
    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
        cases["image.heic"] = (
            save(photo, "HEIF"),
            {"format": "heic", "width": 640, "height": 480},
        )
    except ImportError:  # pillow-heif is in requirements.lock; locally it may be missing
        pass
    cut = save(photo, "JPEG")
    cases["cut.jpg"] = (cut[:120], {"format": "jpeg", "width": None})
    cases["noise.bin"] = (bytes(range(256)) * 4, {"format": None, "width": None})
    expected = {}
    for name, (data, wanted) in cases.items():
        (folder / name).write_bytes(data)
        expected[name] = wanted
    return expected


@needs_node
def test_sniff_reads_format_size_and_orientation(tmp_path):
    expected = _fixtures(tmp_path)
    found = _node(
        tmp_path,
        "import { readFileSync } from 'node:fs';\n"
        "import { imageInfo } from './core/sniff.js';\n"
        f"const names = {json.dumps(sorted(expected))};\n"
        f"const folder = {json.dumps(str(tmp_path))};\n"
        "const out = {};\n"
        "for (const name of names) out[name] = imageInfo(new Uint8Array(readFileSync(folder + '/' + name)));\n"
        "console.log(JSON.stringify(out));\n",
    )
    for name, wanted in expected.items():
        for key, value in wanted.items():
            assert found[name][key] == value, (
                f"{name}: {key} is {found[name][key]!r}, not {value!r}"
            )


@needs_node
def test_plan_keeps_every_canvas_within_safaris_limit(tmp_path):
    found = _node(
        tmp_path,
        "import { MAX_CANVAS_PIXELS, fitPixels, displaySize } from './core/plan.js';\n"
        "const sizes = [[6000, 4000], [8000, 6000], [4000, 3000], [4096, 4096], [4097, 4096],"
        " [12000, 3], [1, 50000000]];\n"
        "console.log(JSON.stringify({ max: MAX_CANVAS_PIXELS,"
        " fits: sizes.map(([w, h]) => fitPixels(w, h)),"
        " turned: displaySize(6000, 4000, 6), upright: displaySize(6000, 4000, 1) }));\n",
    )
    assert found["max"] == 16_777_216
    for fit, (width, height) in zip(
        found["fits"],
        [
            (6000, 4000),
            (8000, 6000),
            (4000, 3000),
            (4096, 4096),
            (4097, 4096),
            (12000, 3),
            (1, 50000000),
        ],
        strict=True,
    ):
        assert fit["width"] * fit["height"] <= 16_777_216
        if width * height <= 16_777_216:
            assert (fit["width"], fit["height"], fit["scale"]) == (width, height, 1)
        elif min(fit["width"], fit["height"]) > 1:
            # Nearly the whole budget, in the photo's proportions.
            assert fit["width"] * fit["height"] >= 0.99 * 16_777_216
            ratio = width / height
            assert abs(fit["width"] / fit["height"] - ratio) / ratio < 0.01
        else:
            # A side of one pixel: the other takes the rest of the budget.
            assert max(fit["width"], fit["height"]) == 16_777_216
    assert found["turned"] == {"width": 4000, "height": 6000}
    assert found["upright"] == {"width": 6000, "height": 4000}


@needs_node
def test_the_quality_search_keeps_within_its_passes(tmp_path):
    # A fake encoder: the size falls as the quality falls.
    found = _node(
        tmp_path,
        "import { searchQuality, MAX_PASSES } from './core/plan.js';\n"
        "const runs = [];\n"
        "for (const target of [10_000_000, 2_000_000, 600_000, 1]) {\n"
        "  const tried = [];\n"
        "  const result = await searchQuality(async (q) => { tried.push(q); return Math.round(q * q * 4_000_000); }, target);\n"
        "  runs.push({ target, tried, result });\n"
        "}\n"
        "console.log(JSON.stringify({ max: MAX_PASSES, runs }));\n",
    )
    for run in found["runs"]:
        result, tried, target = run["result"], run["tried"], run["target"]
        assert 1 <= result["passes"] == len(tried) <= found["max"]
        if result["met"]:
            assert result["bytes"] <= target
            # No quality tried that also fits is higher than the one chosen.
            assert all(round(q * q * 4_000_000) > target or q <= result["quality"] for q in tried)
        else:
            assert result["bytes"] == min(round(q * q * 4_000_000) for q in tried)
    assert found["runs"][0]["tried"] == [0.95]  # fits at the top: one pass
    assert found["runs"][-1]["result"]["met"] is False


def _red(pixel: tuple[int, int, int]) -> bool:
    red, green, blue = pixel
    return red > 170 and green < 60 and blue < 80


@needs_node
def test_the_test_photo_is_a_camera_like_jpeg(tmp_path):
    found = _node(
        tmp_path,
        "import { writeFileSync } from 'node:fs';\n"
        "import { testPhoto } from './check/sample.js';\n"
        f"const folder = {json.dumps(str(tmp_path))};\n"
        "const sizes = [[333, 217], [1600, 1200]];\n"
        "for (const [width, height] of sizes) {\n"
        "  const chunks = await testPhoto({ width, height });\n"
        "  writeFileSync(`${folder}/photo-${width}.jpg`, Buffer.concat(chunks.map((c) => Buffer.from(c))));\n"
        "}\n"
        "console.log(JSON.stringify(sizes));\n",
    )
    for width, height in found:
        data = (tmp_path / f"photo-{width}.jpg").read_bytes()
        with Image.open(BytesIO(data)) as image:
            image.load()
            assert image.format == "JPEG"
            assert image.size == (width, height)
            assert image.mode == "RGB"
            assert image.getexif().get(0x0112) == 6  # turned, as a portrait photo is
            assert image.layer[0][1:3] == (2, 2)  # 4:2:0, like a camera's
            # The red corner: top left as stored, top right once turned, where
            # check/device-check.js looks for it (with the same thresholds).
            assert _red(image.getpixel((2, 2)))
            turned = ImageOps.exif_transpose(image)
            assert _red(turned.getpixel((turned.width - 3, 2)))
            assert not _red(turned.getpixel((2, 2)))
        # About as heavy as a camera photo: 2–5 bits per pixel.
        assert 2 <= len(data) * 8 / (width * height) <= 5
    # The same photo every time: the device check compares phones.
    again = _node(
        tmp_path,
        "import { testPhoto } from './check/sample.js';\n"
        "const chunks = await testPhoto({ width: 333, height: 217 });\n"
        "console.log(JSON.stringify(Array.from(Buffer.concat(chunks.map((c) => Buffer.from(c))))));\n",
    )
    assert bytes(again) == (tmp_path / "photo-333.jpg").read_bytes()
