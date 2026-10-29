# SPDX-License-Identifier: AGPL-3.0-or-later
"""/formats: each conversion once, and the format search (2026-10-29).

docs-internal/navigation-suche-konzept-2026-10.md. The page lists every
conversion once, under the formats' first names: the registry also knows
JPEG, TIF and HTM, which used to add 40 chips, three of them no conversion at
all (JPG to JPEG, TIF to TIFF, TIFF to TIF). Above the list, format-filter.js
filters it in place by format, another name, kind of file or pair. The field
is invisible until the script runs, so without it the full list shows (G6),
and keeps its space, so the list doesn't jump when it appears. The query
lives in the fragment (#q=), never in a query string. There is no JS
runner in the repo, so the script's guards are pinned on its source, like
tests/test_formats_links.py.
"""

from __future__ import annotations

import json
import re
from html import unescape
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from app.api.routes.pages import _tool_formats
from app.api.routes.pdf_pages import INSERT_FORMATS
from app.compressors.image import _SUPPORTED_FORMATS as IMAGE_COMPRESS
from app.compressors.video import _SUPPORTED_FORMATS as VIDEO_COMPRESS
from app.converters.registry import get_public_conversions
from app.core import catalog
from app.core.convert_pairs import SEARCH_WORDS, SPELLINGS

_JS = Path(__file__).resolve().parent.parent / "app" / "static" / "js" / "format-filter.js"

# Written out here on purpose, not imported from convert_pairs.SPELLINGS, so a
# change there has to agree with this independent count.
_SAME = {"jpeg": "jpg", "tif": "tiff", "htm": "html"}


def _expected_pairs() -> set[tuple[str, str]]:
    pairs = set()
    for src, targets in get_public_conversions().items():
        for tgt in targets:
            pair = (_SAME.get(src, src), _SAME.get(tgt, tgt))
            if pair[0] != pair[1]:
                pairs.add(pair)
    return pairs


def _page(client, prefix: str = "/en") -> BeautifulSoup:
    html = client.get(f"{prefix}/formats").text
    return BeautifulSoup(html[html.index("<main") : html.index("</main>")], "html.parser")


def _filter(main: BeautifulSoup):
    return main.find(id="format-filter")


# ── each conversion once ──────────────────────────────────────────────────────


@pytest.mark.parametrize("prefix", ["/en", "/de"])
def test_each_conversion_is_listed_once(client, prefix):
    chips = _page(client, prefix).select("[data-pair]")
    listed = [tuple(chip["data-pair"].split()) for chip in chips]
    expected = _expected_pairs()
    assert len(listed) == len(set(listed)) == len(expected)
    assert set(listed) == expected


def test_every_listed_pair_is_one_the_format_list_has(client):
    """app.js applies a "#convert=" link only for a pair /api/v1/formats has,
    so each folded pair must exist there under the first names, or its chip
    would do nothing."""
    public = client.get("/api/v1/formats").json()["conversions"]
    for chip in _page(client).select("[data-pair]"):
        src, tgt = chip["data-pair"].split()
        assert tgt in public.get(src, []), (src, tgt)


def test_no_format_is_converted_into_another_spelling_of_itself(client):
    main = _page(client)
    for src, tgt in (tuple(c["data-pair"].split()) for c in main.select("[data-pair]")):
        assert src not in _SAME and tgt not in _SAME, (src, tgt)
    labels = {c.get_text(strip=True) for c in main.select("[data-pair]")}
    assert not labels & {"JPEG", "TIF", "HTM", "PDFA"}
    assert {"PDF/A", "WebP"} <= labels


def test_a_chip_names_its_conversion_and_carries_it(client):
    main = _page(client)
    for chip in main.select("[data-pair]"):
        src, tgt = chip["data-pair"].split()
        assert chip.get_text(strip=True), chip
        assert chip["aria-label"].startswith("Convert "), chip
        href = chip["href"]
        if "#convert=" in href:
            assert href.endswith(f"#convert={src}-to-{tgt}")


def test_compression_lists_each_format_once(client):
    main = _page(client)
    formats = [span["data-formats"] for span in main.select("span[data-formats]")]
    expected = {_SAME.get(f, f) for f in [*IMAGE_COMPRESS, *VIDEO_COMPRESS]}
    assert len(formats) == len(set(formats)) and set(formats) == expected


# ── the search field ──────────────────────────────────────────────────────────


@pytest.mark.parametrize("prefix", ["/en", "/de"])
def test_full_list_is_in_the_raw_html(client, prefix):
    """Only the search UI is hidden until the script runs; the list is not."""
    main = _page(client, prefix)
    box = _filter(main)
    # invisible, not hidden: the field keeps its space until the script runs.
    assert box is not None and "invisible" in box["class"] and not box.has_attr("hidden")
    for el in main.select("[data-pair], [data-formats], [data-filter-group]"):
        assert not el.has_attr("hidden") and "hidden" not in el.get("class", []), el.name
    # Before the matrix: tests/test_formats_links.py slices from its comment.
    html = client.get(f"{prefix}/formats").text
    assert html.index('id="format-filter"') < html.index("<!-- Conversion matrix")


def test_search_field_is_labelled_and_mobile_safe(client):
    box = _filter(_page(client))
    field = box.find("input")
    assert field["id"] == "format-q" and field["type"] == "search"
    assert box.find("label", attrs={"for": "format-q"}).get_text(strip=True) == "Find a format"
    assert not field.has_attr("autofocus")
    assert field["maxlength"] == "64", "the script cuts longer queries anyway"
    assert "text-base" in field["class"], "under 16px, iOS zooms into the page"
    assert box["role"] == "search"
    assert box.find(id="format-live")["role"] == "status"
    assert "sr-only" in box.find(id="format-live")["class"]
    assert box.find(id="format-empty").has_attr("hidden")


@pytest.mark.parametrize(
    ("prefix", "texts"),
    [
        ("/en", ("Find a format", "{n} of {total} conversions", "Show all formats")),
        ("/de", ("Format suchen", "{n} von {total} Umwandlungen", "Alle Formate zeigen")),
    ],
)
def test_search_texts_are_in_the_page_language(client, prefix, texts):
    html = unescape(str(_filter(_page(client, prefix))))
    for text in texts:
        assert text in html, text


def test_search_words_point_at_listed_formats(client):
    box = _filter(_page(client))
    words = json.loads(box["data-words"])
    labels = json.loads(box["data-labels"])
    listed = {f for pair in _expected_pairs() for f in pair}
    assert set(labels) >= listed
    for word, formats in words.items():
        assert formats and set(formats) <= set(labels), word
    assert words["jpeg"] == ["jpg"] and words["tif"] == ["tiff"]
    assert words["word"] == ["docx"] and words["excel"] == ["xlsx"]
    assert words["iphone"] == ["heic", "heif", "mov"]
    assert words["pdf/a"] == ["pdfa"] and labels["pdfa"] == "PDF/A"
    assert {"jpg", "png", "heic"} <= set(words["foto"])
    assert "mp3" in words["musik"] and "mp4" in words["video"]
    # Every word of the lists finds something: a misspelt category or format
    # would otherwise drop out without a word.
    assert set(words) == set(SPELLINGS) | set(SEARCH_WORDS)


# ── tools ─────────────────────────────────────────────────────────────────────


def _tools(main: BeautifulSoup) -> dict[str, set[str]]:
    return {a["href"]: set(a["data-formats"].split()) for a in main.select("[data-tool]")}


def test_every_tool_page_is_a_chip_with_its_formats(client, redact_enabled):
    tools = _tools(_page(client))
    pages = [page.path for page in catalog.pages(kind="tool")]
    assert sorted(tools) == sorted(f"/en{path}" for path in pages)
    for href, formats in tools.items():
        assert formats, f"{href} has no formats, the search can't find it"
    assert tools["/en/redact"] >= {"txt", "docx", "xlsx"}


def test_tool_formats_name_exactly_the_tool_pages():
    """A renamed or new tool page must get its formats, or the search can't
    find it; a stale path must go."""
    tool_pages = {page.path for page in catalog.PAGES if page.kind == "tool"}
    assert set(_tool_formats()) == tool_pages


def test_tools_carry_the_formats_they_take(client):
    tools = _tools(_page(client))
    for path in ("/pdf/compress", "/pdf/split", "/pdf/extract"):
        assert tools[f"/en{path}"] == {"pdf"}
    assert tools["/en/pdf/insert"] == {_SAME.get(f, f) for f in INSERT_FORMATS}
    assert tools["/en/compress"] == {_SAME.get(f, f) for f in [*IMAGE_COMPRESS, *VIDEO_COMPRESS]}
    assert {"mp4", "mov", "gif"} <= tools["/en/convert/video-to-gif"]


# ── format-filter.js ──────────────────────────────────────────────────────────


def test_format_filter_js_writes_plain_text_and_fetches_nothing():
    source = _JS.read_text(encoding="utf-8")
    assert "innerHTML" not in source and "insertAdjacentHTML" not in source
    assert "fetch(" not in source and "XMLHttpRequest" not in source
    # What the list shows at once, for screen readers once typing settles.
    assert "status.textContent = text;" in source and "live.textContent = text;" in source
    # The query goes into the fragment, never into the query string.
    assert "'#q=' + encodeURIComponent(" in source
    assert "history.replaceState(" in source and "location.search +" not in source
    # Own keys only: a typed "constructor" is no search word.
    assert "Object.prototype.hasOwnProperty.call(" in source
    # The list shows until the script has wired the field.
    assert source.rstrip().endswith("})();")
    assert "root.classList.remove('invisible');" in source
    # A long crafted "#q=" link must not make the pair pattern backtrack for
    # seconds: every query, typed or from the fragment, is cut first.
    assert "const MAX_QUERY = 64;" in source
    assert "q = q.trim().slice(0, MAX_QUERY);" in source


def test_format_filter_js_hides_chips_by_class():
    """A chip's inline-block beats the hidden attribute; the class wins."""
    source = _JS.read_text(encoding="utf-8")
    assert "el.classList.toggle('hidden', !visible)" in source
    assert re.search(r"group\.hidden = !visible", source)
