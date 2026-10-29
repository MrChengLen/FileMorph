# SPDX-License-Identifier: AGPL-3.0-or-later
"""Accessibility structure the pages rely on (WCAG 2.2 AA).

Colour contrast is pinned in tests/test_public_claims.py (§ 13); these tests
cover the skip link, the screen-reader announcements of the tools and the
names of their inputs.
"""

import re
from pathlib import Path

TEMPLATES = Path(__file__).resolve().parents[1] / "app" / "templates"


def test_skip_link_is_the_first_tab_stop_and_has_a_target(client):
    html = client.get("/en/").text
    assert html.count('href="#main-content"') == 1
    assert html.count('id="main-content"') == 1
    assert html.index('href="#main-content"') < html.index("<nav")
    assert "Skip to main content" in html


def test_skip_link_is_german_on_german_pages(client):
    assert "Zum Inhalt springen" in client.get("/de/").text


def test_every_page_has_the_polite_live_region_and_its_script(client):
    html = client.get("/en/pdf/insert").text
    region = re.search(r'<div id="fm-live"[^>]*>', html)
    assert region, "live region missing"
    assert 'role="status"' in region.group(0) and 'aria-live="polite"' in region.group(0)
    assert re.search(r'src="/static/js/announce\.js\?v=', html)


def test_tool_error_texts_are_alerts():
    for partial, error_id in (
        ("convert_tool.html", "error-text"),
        ("pdf_tool.html", "pdf-error-text"),
        ("redact_tool.html", "redact-error-text"),
    ):
        source = (TEMPLATES / "partials" / partial).read_text(encoding="utf-8")
        assert re.search(rf'<p id="{error_id}" role="alert"', source), partial


def test_tools_announce_progress_and_results():
    """Each tool announces its progress and result texts, and every error path
    empties the region first, so a pending "Processing…" can't follow the
    error alert."""
    js = Path(__file__).resolve().parents[1] / "app" / "static" / "js"
    clear = "window.FM_announce('')"
    for name, calls in (("app.js", 2), ("pdf-tools.js", 2), ("redact.js", 4)):
        source = (js / name).read_text(encoding="utf-8")
        assert source.count("window.FM_announce(") - source.count(clear) == calls, name
        error_fn = re.search(r"function showError\([^)]*\) \{\n\s*(.*)\n", source)
        assert error_fn and error_fn.group(1).startswith("window.FM_announce && " + clear), name


def test_compress_inputs_are_named_by_their_headings(client):
    html = client.get("/en/compress").text
    for input_id, heading_id in (
        ("quality-slider", "quality-heading"),
        ("target-size-input", "target-size-heading"),
    ):
        tag = re.search(rf'<input id="{input_id}"[^>]*>', html).group(0)
        assert f'aria-labelledby="{heading_id}"' in tag
        assert f'id="{heading_id}"' in html
        assert f'<label for="{input_id}"' in html
