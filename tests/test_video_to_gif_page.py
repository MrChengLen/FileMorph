# SPDX-License-Identifier: AGPL-3.0-or-later
"""/convert/video-to-gif — one page for Video → GIF (#266), for every video format.

Guards: the page renders in all three locale mounts (the fixed route wins
over /convert/{pair_slug}); the converter on it is pre-set to GIF, for every
file of a batch too; the limits it states are the converter's and the upload
cap's own numbers, so the page can't promise more than a visitor gets; and the
tool is findable — on /tools, in the footer's "Tools" group and from
/compress (the sitemap and llms.txt follow from the page catalogue, see
tests/test_catalog.py).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.converters._ffmpeg import GIF_FPS, GIF_MAX_SECONDS, GIF_MAX_SIDE, GIF_MAX_SOURCE_PIXELS
from app.core import catalog
from app.core.config import settings
from app.core.quotas import QUOTAS
from app.core.video_gif_content import VIDEO_GIF_CONTENT

_PATH = "/convert/video-to-gif"
_APP_JS = Path(__file__).resolve().parent.parent / "app" / "static" / "js" / "app.js"


def _main(html: str) -> str:
    return html[html.index("<main") : html.index("</main>")]


@pytest.mark.parametrize("prefix", ["", "/de", "/en"])
def test_page_renders_on_every_mount(client, prefix):
    r = client.get(f"{prefix}{_PATH}")
    assert r.status_code == 200, f"{prefix}{_PATH} returned {r.status_code}"
    locale = prefix.strip("/") or settings.lang_default
    assert VIDEO_GIF_CONTENT[locale]["h1"] in r.text


def test_converter_is_preset_to_gif(client):
    assert 'data-preset-target="gif"' in _main(client.get(f"/en{_PATH}").text)


def test_batch_rows_keep_the_preset_target():
    # Every file of a batch gets its own target select; on a pre-set page it
    # must start at the page's target too, not at the first format in the list.
    source = _APP_JS.read_text(encoding="utf-8")
    assert "perRowSelect.value = presetTarget" in source


@pytest.mark.parametrize("locale", ["en", "de"])
def test_stated_limits_are_the_converters(locale):
    limits = VIDEO_GIF_CONTENT[locale]["limits"]
    assert f"{GIF_MAX_SIDE} × {GIF_MAX_SIDE}" in limits
    fps = {"en": "frames per second", "de": "Bildern pro Sekunde"}[locale]
    assert f"{GIF_FPS} {fps}" in limits
    assert GIF_MAX_SOURCE_PIXELS == 4096 * 2160 and "4096 × 2160" in limits


@pytest.mark.parametrize("locale", ["en", "de"])
def test_every_stated_duration_is_the_converters(locale):
    # The maximum length appears in the meta, the limits, the steps, the FAQ,
    # the /tools card and llms.txt: each of them must name the converter's own
    # number ("30 seconds", "30-second clip", "30-Sekunden-Clip" all count).
    content = VIDEO_GIF_CONTENT[locale]
    page = catalog.get(_PATH)
    stem = {"en": "second", "de": "Sekunde"}[locale]
    texts = [
        content["meta"],
        content["limits"],
        *(text for pair in content["how_it_works"] + content["faq"] for text in pair),
        page.blurb[locale],
        *([page.llms[1]] if locale == "en" else []),
    ]
    stated = {int(n) for text in texts for n in re.findall(rf"(\d+)[ -]{stem}", text)}
    assert stated == {GIF_MAX_SECONDS}


@pytest.mark.parametrize("locale", ["en", "de"])
def test_limits_name_the_anonymous_upload_cap(locale):
    # A video hits the upload cap long before the GIF limits: say so up front.
    anonymous_mb = QUOTAS["anonymous"].max_file_size_bytes // 2**20
    assert f"{anonymous_mb} MB" in VIDEO_GIF_CONTENT[locale]["limits"]


@pytest.mark.parametrize("prefix", ["/en", "/de"])
def test_findable_on_tools_in_the_footer_and_from_compress(client, prefix):
    tools = _main(client.get(f"{prefix}/tools").text)
    assert f'href="{prefix}{_PATH}"' in tools
    home = client.get(f"{prefix}/").text
    footer = home[home.index("<footer") :]
    assert f'href="{prefix}{_PATH}"' in footer
    assert f'href="{prefix}{_PATH}"' in _main(client.get(f"{prefix}/compress").text)
