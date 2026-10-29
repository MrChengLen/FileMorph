# SPDX-License-Identifier: AGPL-3.0-or-later
"""The converter script (app.js) writes no English on German pages: every text
it shows comes from the FM_I18N catalogue (``_js_i18n_strings``).

The repo has no JS runner, so the script is pinned by its source (the same
approach as tests/test_formats_links.py), and the catalogue by the rendered
/de/ and /en/ pages.
"""

import json
import re
from pathlib import Path

from app.core.i18n import _js_i18n_strings

APP_JS = (Path(__file__).resolve().parent.parent / "app" / "static" / "js" / "app.js").read_text(
    encoding="utf-8"
)
# Without line comments: a comment such as "see app/core/i18n.py" is not a key.
APP_JS_CODE = re.sub(r"(?m)^\s*//.*$", "", APP_JS)
BLOB = re.compile(r'<script id="fm-i18n-strings" type="application/json">(.*?)</script>', re.DOTALL)

# Every way app.js reads the catalogue: i18nText('key', …), FM_I18N.key,
# (window.FM_I18N || {}).key, i18n.key / I18N.key, the preset keys handed to
# showPresetNotice (one of them through a ternary), and the keys of
# WARNING_FEATURE_LABELS, read as i18n[i18nKey].
_KEY_PATTERNS = (
    r"i18nText\(\s*'(\w+)'",
    r"FM_I18N\.(\w+)",
    r"FM_I18N \|\| \{\}\)\.(\w+)",
    r"\bi18n\.(\w+)",
    r"\bI18N\.(\w+)",
    r"'(preset[A-Z]\w*)'",
    r":\s*'(warningSimplified\w+)'",
)
# i18nText('key', 'English fallback', { token: value, … })
_CALL = re.compile(r"i18nText\(\s*'(\w+)',\s*'([^']*)'(?:,\s*\{([^}]*)\})?")


def _keys_used_by_app_js() -> set[str]:
    return {key for pattern in _KEY_PATTERNS for key in re.findall(pattern, APP_JS_CODE)}


def _i18n_text_keys() -> set[str]:
    return {key for key, _fallback, _vars in _CALL.findall(APP_JS_CODE)}


def _blob(client, path: str) -> dict[str, str]:
    match = BLOB.search(client.get(path).text)
    assert match, f"FM_I18N script tag missing on {path}"
    return json.loads(match.group(1))


def test_every_key_app_js_reads_is_in_the_catalogue():
    """A key the catalogue lacks shows its English fallback on every page, and
    a preset notice shows nothing at all."""
    catalogue = set(_js_i18n_strings(lambda s: s))
    used = _keys_used_by_app_js()
    assert {"presetMismatch", "presetMismatchTarget", "presetReady"} <= used
    assert len(used) > 40, f"key scan looks broken: {sorted(used)}"
    assert used <= catalogue, f"app.js reads keys the catalogue lacks: {sorted(used - catalogue)}"


def test_i18n_text_calls_match_the_catalogue():
    """Each fallback is the English msgid, so English pages read as before;
    the tokens passed are the ones the text has, so no raw "{size}" shows."""
    catalogue = _js_i18n_strings(lambda s: s)
    calls = _CALL.findall(APP_JS_CODE)
    assert len(calls) >= 20, f"i18nText scan looks broken: {calls}"
    for key, fallback, passed in calls:
        names = {part.split(":")[0].strip() for part in passed.split(",") if part.strip()}
        assert fallback == catalogue[key], key
        assert set(re.findall(r"\{(\w+)\}", fallback)) == names, key


def test_converter_texts_are_german_on_de(client):
    de = _blob(client, "/de/")
    en = _blob(client, "/en/")
    keys = _i18n_text_keys()
    untranslated = sorted(key for key in keys if de.get(key) in (None, "", en.get(key)))
    assert not untranslated, f"English on /de/ for: {untranslated}"
    # The texts every conversion shows.
    assert de["progressSingle"] == "Deine Datei wird verarbeitet…"
    assert de["fileCountOne"] == "1 Datei · {size}"
    assert de["fileCountMany"] == "{count} Dateien · {size} insgesamt"
    assert de["downloadResult"] == "Ergebnis herunterladen"
    assert de["downloadResultSize"] == "Ergebnis herunterladen ({size} MB)"
    assert de["downloadZip"] == "ZIP herunterladen ({count} Dateien)"
    assert en["progressSingle"] == "Processing your file…"


def test_tokens_survive_translation(client):
    """app.js fills {tokens} by name; a translation that drops or renames one
    would show a raw "{size}" or lose the number."""
    de = _blob(client, "/de/")
    en = _blob(client, "/en/")
    for key in _i18n_text_keys():
        tokens_en = set(re.findall(r"\{(\w+)\}", en[key]))
        tokens_de = set(re.findall(r"\{(\w+)\}", de[key]))
        assert tokens_de == tokens_en, f"{key}: {tokens_de} != {tokens_en}"


def test_app_js_writes_no_english_literals():
    for literal in (
        "`1 file · ${",
        "files · ${formatBytes",
        "`Download Result (${",
        "`Download ZIP (${",
        "`Batch failed: ${",
        "`Conversion failed (status ${",
        "'Network error: ' +",
        "`Heads up: ${",
        "`Use ${match.suggest",
        "`Simplified: ${",
        "`Target format for ${",
        "`Remove ${",
        "`Processing ${",
        "× larger'",
    ):
        assert literal not in APP_JS, f"English literal back in app.js: {literal}"


def test_numbers_follow_the_page_language():
    """Sizes read "1,5 KB" on German pages: no toFixed (always a point)."""
    assert ".toFixed(" not in APP_JS_CODE
    body = APP_JS.split("function formatDecimal(", 1)[1].split("\n}\n", 1)[0]
    assert "toLocaleString(document.documentElement.lang" in body
    assert "useGrouping: false" in body


def test_i18n_text_fills_tokens_once_as_plain_text():
    """One pass over the template: a value that contains "{x}" (a file name,
    a server message) is never filled in again."""
    body = APP_JS.split("function i18nText(", 1)[1].split("\n}\n", 1)[0]
    assert "template.replace(/\\{(\\w+)\\}/g" in body
    assert "hasOwnProperty.call(vars, name)" in body
    assert "innerHTML" not in body
