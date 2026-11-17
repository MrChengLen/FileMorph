# SPDX-License-Identifier: AGPL-3.0-or-later
"""/device-check, the local engine's test page (app/api/routes/pages.py).

The page exists only with LOCAL_TOOLS_ENABLED, like the engine mount; it is
strict (CSP profile ``local``, neither auth.js nor app.js), tells search
engines to leave it out, is listed nowhere, and runs on engine modules alone,
all of them preloaded so that the test goes on in airplane mode. Its texts
come from app/core/device_check_content.py in both languages, including
every string its script shows.
"""

from __future__ import annotations

import json
import re

import pytest

from app.core.config import settings
from app.core.device_check_content import DEVICE_CHECK_CONTENT
from app.core.engine import ENGINE_DIR, engine_modules, engine_url
from app.main import _CSP_HEADERS

_PATHS = ["/device-check", "/de/device-check", "/en/device-check"]
_SCRIPT = ENGINE_DIR / "check" / "device-check.js"
_STRINGS = re.compile(r'<script id="fm-check-strings" type="application/json">(.*?)</script>', re.S)


@pytest.fixture
def engine_on(monkeypatch):
    monkeypatch.setattr(settings, "local_tools_enabled", True)


@pytest.mark.parametrize("path", _PATHS)
def test_the_page_is_not_there_without_the_switch(client, monkeypatch, path):
    monkeypatch.setattr(settings, "local_tools_enabled", False)
    r = client.get(path)
    assert r.status_code == 404
    assert r.headers["content-security-policy"] == _CSP_HEADERS["default"]


@pytest.mark.parametrize("path", _PATHS)
def test_the_page_is_strict_and_left_out_of_search(client, engine_on, path):
    r = client.get(path)
    assert r.status_code == 200
    assert r.headers["content-security-policy"] == _CSP_HEADERS["local"]
    assert r.headers["x-robots-tag"] == "noindex, nofollow"
    assert "/static/js/app.js" not in r.text
    assert "/static/js/auth.js" not in r.text


def test_the_page_runs_on_preloaded_engine_modules(client, engine_on):
    r = client.get("/en/device-check")
    base = engine_url()
    assert f'<script type="module" src="{base}/check/device-check.js"></script>' in r.text
    preloaded = re.findall(r'<link rel="modulepreload" href="([^"]+)">', r.text)
    assert preloaded == [f"{base}/{name}" for name in engine_modules()]
    assert f"{base}/ops/worker.js" in preloaded
    for url in preloaded:
        served = client.get(url)
        assert served.status_code == 200, url
        assert served.headers["content-type"] == "text/javascript; charset=utf-8"
        assert served.headers["content-security-policy"] == _CSP_HEADERS["local"]


def test_engine_modules_are_every_engine_file():
    assert list(engine_modules()) == sorted(
        path.relative_to(ENGINE_DIR).as_posix() for path in ENGINE_DIR.rglob("*.js")
    )
    assert "check/device-check.js" in engine_modules()


@pytest.mark.parametrize("locale", ["de", "en"])
def test_the_page_speaks_its_language(client, engine_on, locale):
    content = DEVICE_CHECK_CONTENT[locale]
    other = DEVICE_CHECK_CONTENT["en" if locale == "de" else "de"]
    html = client.get(f"/{locale}/device-check").text
    assert f">{content['h1']}</h1>" in html
    for key in ("intro", "prepare", "start", "copy_result"):
        assert other[key] not in html, f"/{locale}/device-check shows the other language's {key}"
    assert json.loads(_STRINGS.search(html).group(1)) == content["js"]


def test_both_languages_hold_the_same_strings():
    en, de = DEVICE_CHECK_CONTENT["en"], DEVICE_CHECK_CONTENT["de"]
    assert en.keys() == de.keys()
    assert en["js"].keys() == de["js"].keys()
    assert len(en["steps"]) == len(de["steps"])
    for locale, content in DEVICE_CHECK_CONTENT.items():
        for key, value in {**content, **content["js"]}.items():
            assert value, f"{locale}: {key} is empty"
        for key, value in content["js"].items():
            # The placeholders the script fills in, the same in both languages.
            assert set(re.findall(r"\{(\w+)\}", value)) == set(
                re.findall(r"\{(\w+)\}", en["js"][key])
            ), f"{locale}: {key} has other placeholders than in English"


def test_every_string_the_script_shows_is_there():
    source = _SCRIPT.read_text(encoding="utf-8")
    # The keys the script names: every quoted statusX…, lockX…, verdictX…,
    # reasonX… and labelX… string (a bare "status" or "lock" is a field of a
    # record, not a string shown), every numbers… string, and three more.
    used = set(
        re.findall(
            r"""["']((?:status|lock|verdict|reason|label)[A-Z]\w*|numbers(?:[A-Z]\w*)?"""
            r"""|label\d+\w*|notCounted|detected|unsupported)["']""",
            source,
        )
    )
    # Every state a record can get, shown as T[`state_${state}`].
    used |= {
        f"state_{state}"
        for state in re.findall(r'"(passed|slow|wrong|failed|crashed|invalid|measured)"', source)
    }
    used.add("decimalPoint")
    missing = used - DEVICE_CHECK_CONTENT["en"]["js"].keys()
    assert not missing, (
        f"device-check.js shows strings app/core/device_check_content.py lacks: {sorted(missing)}"
    )
    unused = DEVICE_CHECK_CONTENT["en"]["js"].keys() - used
    assert not unused, f"strings no script shows: {sorted(unused)}"


def test_the_page_is_listed_nowhere(client, engine_on):
    for path in ("/sitemap.xml", "/llms.txt", "/tools", "/"):
        assert "device-check" not in client.get(path).text, path
