# SPDX-License-Identifier: AGPL-3.0-or-later
"""/convert/video-to-mp3 — one page for Video → audio, for every video format.

Guards, as for /convert/video-to-gif (tests/test_video_to_gif_page.py): the
page renders in all three locale mounts (the fixed route wins over
/convert/{pair_slug}); the converter on it is pre-set to MP3; what it says
is the converter's and the upload cap's own facts, so the page can't promise
more than a visitor gets; and the tool is findable — on /tools, in the
footer, from the Video to GIF page and from every video → MP3 chip on
/formats (the sitemap and llms.txt follow from the page catalogue, see
tests/test_catalog.py).
"""

from __future__ import annotations

import re

import pytest

from app.api.routes.pages import _tool_formats
from app.converters.audio import _AUDIO_FORMATS
from app.converters.video import _AUDIO_TARGETS, _VIDEO_FORMATS
from app.core.config import settings
from app.core.quotas import QUOTAS
from app.core.video_audio_content import VIDEO_AUDIO_CONTENT

_PATH = "/convert/video-to-mp3"


def _main(html: str) -> str:
    return html[html.index("<main") : html.index("</main>")]


@pytest.mark.parametrize("prefix", ["", "/de", "/en"])
def test_page_renders_on_every_mount(client, prefix):
    r = client.get(f"{prefix}{_PATH}")
    assert r.status_code == 200, f"{prefix}{_PATH} returned {r.status_code}"
    locale = prefix.strip("/") or settings.lang_default
    assert VIDEO_AUDIO_CONTENT[locale]["h1"] in r.text


def test_converter_is_preset_to_mp3(client):
    assert 'data-preset-target="mp3"' in _main(client.get(f"/en{_PATH}").text)


@pytest.mark.parametrize("locale", ["en", "de"])
def test_the_formats_named_are_the_converters(locale):
    # The video formats it takes and the audio formats it offers, as the
    # first step names them: exactly the registered ones, no more.
    step = VIDEO_AUDIO_CONTENT[locale]["how_it_works"][0][1]
    named = {word.lower() for word in re.findall(r"\b[A-Z][A-Za-z0-9]+\b", step)}
    assert named & set(_VIDEO_FORMATS) == set(_VIDEO_FORMATS)
    assert named & set(_AUDIO_FORMATS) == set(_AUDIO_TARGETS)


@pytest.mark.parametrize("locale", ["en", "de"])
def test_limits_name_the_first_track_and_the_anonymous_upload_cap(locale):
    limits = VIDEO_AUDIO_CONTENT[locale]["limits"]
    anonymous_mb = QUOTAS["anonymous"].max_file_size_bytes // 2**20
    assert f"{anonymous_mb} MB" in limits
    first = {"en": "first audio track", "de": "erste Tonspur"}[locale]
    assert first in limits


@pytest.mark.parametrize("prefix", ["/en", "/de"])
def test_findable_on_tools_in_the_footer_and_from_video_to_gif(client, prefix):
    tools = _main(client.get(f"{prefix}/tools").text)
    assert f'href="{prefix}{_PATH}"' in tools
    home = client.get(f"{prefix}/").text
    footer = home[home.index("<footer") :]
    assert f'href="{prefix}{_PATH}"' in footer
    gif_page = _main(client.get(f"{prefix}/convert/video-to-gif").text)
    assert f'href="{prefix}{_PATH}"' in gif_page


def test_video_to_mp3_chips_on_formats_link_the_page(client):
    html = client.get("/en/formats").text
    matrix = html[html.index("<!-- Conversion matrix") : html.index("<!-- Compression")]
    assert matrix.count(f'href="/en{_PATH}"') == len(_VIDEO_FORMATS)
    assert "#convert=mp4-to-mp3" not in matrix
    # The other audio targets have no page of their own: the preset converter.
    assert 'href="/en/#convert=mp4-to-m4a"' in matrix


def test_the_format_search_finds_the_page_by_its_formats():
    # The tool chip on /formats: every video format it takes, and MP3.
    assert set(_tool_formats()[_PATH]) == {*_VIDEO_FORMATS, "mp3"}
