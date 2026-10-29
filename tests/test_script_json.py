# SPDX-License-Identifier: AGPL-3.0-or-later
"""Text on the page stays text.

Every page carries two JSON blocks inside <script> elements: the FM_I18N text
catalogue (translations) and the JSON-LD structured data (the configured base
URL among it). Both are written with Jinja's htmlsafe_json_dumps (the escaping
behind |tojson), so neither a translation nor a setting can end the block or
open a comment, and a JSON parser reads the same data.

In the front-end scripts, no quoted markup string is joined with a value and
assigned to innerHTML; the account menu (auth.js) and the API-key list
(dashboard.js) escape the values they put into markup.
"""

import json
import re
from pathlib import Path

import pytest

import app.core.i18n as i18n_module
from app.core.jsonld import build_site_jsonld

HOSTILE = '</script><img src=x onerror="alert(1)"><!-- & -->'
BLOB = re.compile(r'<script id="fm-i18n-strings" type="application/json">(.*?)</script>', re.DOTALL)
JS = Path(__file__).resolve().parent.parent / "app" / "static" / "js"
# innerHTML = '<…' + value, or "<…" + value (also +=).
JOINED = re.compile(r"""innerHTML\s*\+?=\s*(?:'<[^']*'|"<[^"]*")\s*\+""")


def test_a_translation_cannot_end_the_catalogue_block(client, monkeypatch):
    original = i18n_module._js_i18n_strings

    def hostile_catalogue(gettext):
        return {**original(gettext), "convert": HOSTILE}

    monkeypatch.setattr(i18n_module, "_js_i18n_strings", hostile_catalogue)
    html = client.get("/de/").text
    # The plain JSON encoder would leave this markup in the page.
    assert "<img src=x" not in html
    block = BLOB.search(html)
    assert block, "FM_I18N script tag missing"
    assert json.loads(block.group(1))["convert"] == HOSTILE


def test_a_base_url_cannot_end_the_jsonld_block():
    text, csp_source = build_site_jsonld("https://example.com/</script><b>&")
    assert not set("<>&") & set(text)
    assert json.loads(text)[0]["url"] == "https://example.com/</script><b>&"
    assert csp_source.startswith("'sha256-")


def test_the_join_guard_catches_what_it_names():
    # The three lines this guard was written for, as they read before.
    assert JOINED.search("""select.innerHTML = '<option value="">' + noConvLabel + '</option>';""")
    assert JOINED.search(
        """list.innerHTML = '<p class="text-sm text-gray-500">' + _t('noApiKeys', 'x') + '</p>';"""
    )
    assert JOINED.search(
        """$('metrics-pairs').innerHTML = '<li class="text-xs text-gray-500">' + label + '</li>';"""
    )
    assert JOINED.search("""s.innerHTML += "<p class='x'>" + label;""")
    assert not JOINED.search("""select.innerHTML = '';""")
    assert not JOINED.search("""tbody.innerHTML = '<tr><td>static</td></tr>';""")


@pytest.mark.parametrize("script", sorted(p.name for p in JS.glob("*.js")))
def test_no_script_joins_markup_with_a_value(script):
    source = (JS / script).read_text(encoding="utf-8")
    lines = [source[: m.start()].count("\n") + 1 for m in JOINED.finditer(source)]
    assert not lines, f"{script} lines {lines}: build the element and set textContent instead"


def test_the_account_menu_and_the_key_list_escape_their_values():
    auth = (JS / "auth.js").read_text(encoding="utf-8")
    for value in ("initial", "user.email", "user.tier", "lDashboard", "lSignOut", "lSignIn"):
        assert "${" + value + "}" not in auth, value
        assert "${escapeHtml(" + value + ")}" in auth, value
    keys = (JS / "dashboard.js").read_text(encoding="utf-8")
    for value in (
        "k.label",
        "k.id",
        "labelCreated",
        "labelLastUsed",
        "labelNeverUsed",
        "labelRevoke",
    ):
        assert f"+ {value} +" not in keys and f"+ {value})" not in keys, value
        assert f"escapeHtml({value})" in keys, value
