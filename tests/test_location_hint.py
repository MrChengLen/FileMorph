# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every tool's start button says where the work runs, as text, not only as an icon.

All tools run on the server, so each tool card carries the server hint
directly below its start button — exactly once per page.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.core.convert_pairs import PAIR_CONTENT
from app.core.pdf_tools_content import PDF_TOOL_CONTENT

ROOT = Path(__file__).resolve().parent.parent

HINT_EN = "Runs via our server — files are uploaded and deleted right after processing."
HINT_DE = "Läuft über unseren Server – Dateien werden hochgeladen und nach der Verarbeitung sofort gelöscht."

_PAIR = next(iter(PAIR_CONTENT))
_PAGES = [
    ("/", "convert-btn"),
    ("/compress", "convert-btn"),
    (f"/convert/{_PAIR[0]}-to-{_PAIR[1]}", "convert-btn"),
    *((f"/pdf/{tool}", "pdf-submit") for tool in PDF_TOOL_CONTENT),
]


def _hint_after(html: str, button_id: str) -> str:
    """The location hint directly after the given button, as rendered."""
    button = html.index(f'id="{button_id}"')
    end = html.index("</button>", button) + len("</button>")
    hint = re.match(r'\s*<p [^>]*data-component="location-hint".*?</p>', html[end:], re.S)
    assert hint, f"the location hint is not directly below #{button_id}"
    return hint.group(0)


@pytest.mark.parametrize("locale, text", [("en", HINT_EN), ("de", HINT_DE)])
@pytest.mark.parametrize("path, button_id", _PAGES)
def test_start_button_says_it_runs_on_the_server(client, path, button_id, locale, text):
    res = client.get(f"/{locale}{path}" if path != "/" else f"/{locale}/")
    assert res.status_code == 200
    hint = _hint_after(res.text, button_id)
    assert 'data-location="server"' in hint
    assert text in hint
    assert res.text.count('data-component="location-hint"') == 1


@pytest.mark.parametrize("locale, text", [("en", HINT_EN), ("de", HINT_DE)])
def test_redact_scan_button_says_it_runs_on_the_server(client, redact_enabled, locale, text):
    html = client.get(f"/{locale}/redact").text
    assert text in _hint_after(html, "redact-scan-btn")
    assert html.count('data-component="location-hint"') == 1


def test_redact_scan_step_stays_on_screen_for_the_apply_step():
    """The apply step re-uploads the file and shows no hint of its own: it
    relies on the scan step (and its hint) staying visible. redact.js only
    ever shows that step again (restart), never hides it."""
    js = (ROOT / "app" / "static" / "js" / "redact.js").read_text(encoding="utf-8")
    assert js.count("redact-step-upload") == 1
    assert "show($('redact-step-upload'))" in js


@pytest.mark.parametrize("path", ["/en/", f"/en/convert/{_PAIR[0]}-to-{_PAIR[1]}"])
def test_old_page_note_is_gone(client, path):
    """The hint under the button replaces the note that sat below the tool."""
    html = client.get(path).text
    assert "Files are processed server-side and deleted immediately after conversion." not in html
