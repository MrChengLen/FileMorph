# SPDX-License-Identifier: AGPL-3.0-or-later
"""i18n infrastructure tests — pin the locale-resolution contract.

Covers the five-step resolution chain in `app/core/i18n.py::resolve_locale`,
the unknown-locale fallback, the cookie persistence rule (only-on-explicit-
signal), the hreflang presence on every page, and the `<html lang>` /
`og:locale` propagation.

These tests do not depend on any DE translations existing — PR-i18n-1
ships infrastructure with empty .po files, so all rendered text stays
EN. The tests assert *behaviour* (URL-prefix wins, cookie persists, etc.),
not translated copy.
"""

from __future__ import annotations

import re

import pytest

from app.core.i18n import (
    DEFAULT_LOCALE,
    SUPPORTED_LOCALES,
    base_path,
    localized_url,
    path_prefix_locale,
)


@pytest.fixture(autouse=True)
def _clear_cookies(client):
    """Reset the session-scoped TestClient's cookie jar before each i18n test.

    The shared ``client`` fixture in ``conftest.py`` is session-scoped, so
    cookies from earlier i18n tests (e.g. a `/de/` visit setting
    ``fm_lang=de``) would leak into later tests and steal priority over
    the resolution chain we're trying to assert. Clearing per-test gives
    each case a clean cookie jar without sacrificing the speed of a
    shared TestClient.
    """
    client.cookies.clear()
    yield
    client.cookies.clear()


# ── Pure functions (no FastAPI client) ────────────────────────────────────────


def test_path_prefix_locale_recognises_de_and_en():
    assert path_prefix_locale("/de/pricing") == "de"
    assert path_prefix_locale("/en/login") == "en"


def test_path_prefix_locale_returns_none_for_unprefixed():
    assert path_prefix_locale("/pricing") is None
    assert path_prefix_locale("/") is None
    assert path_prefix_locale("/login") is None


def test_path_prefix_locale_rejects_unknown_prefix():
    # /fr/... or /api/... should not be treated as locale prefixes.
    assert path_prefix_locale("/fr/pricing") is None
    assert path_prefix_locale("/api/v1/health") is None


def test_base_path_strips_locale_prefix():
    assert base_path("/de/pricing") == "/pricing"
    assert base_path("/en/") == "/"
    assert base_path("/de") == "/"


def test_base_path_passes_through_unprefixed():
    assert base_path("/pricing") == "/pricing"
    assert base_path("/") == "/"


def test_localized_url_builds_prefixed():
    assert localized_url("/pricing", "de") == "/de/pricing"
    assert localized_url("/pricing", "en") == "/en/pricing"
    assert localized_url("/", "de") == "/de/"
    assert localized_url("/", "en") == "/en/"


def test_localized_url_unprefixed_for_x_default():
    assert localized_url("/pricing", None) == "/pricing"
    assert localized_url("/", None) == "/"


# ── End-to-end via TestClient ────────────────────────────────────────────────


def test_unprefixed_path_serves_default_locale(client):
    """`/` (no prefix) defaults to DE per the operator's `LANG_DEFAULT`."""
    r = client.get("/")
    assert r.status_code == 200
    # <html lang="de"> on the unprefixed default route
    m = re.search(r'<html lang="([^"]+)"', r.text)
    assert m, "missing <html lang=...>"
    assert m.group(1) == DEFAULT_LOCALE


def test_de_prefix_serves_de_locale(client):
    r = client.get("/de/")
    assert r.status_code == 200
    m = re.search(r'<html lang="([^"]+)"', r.text)
    assert m and m.group(1) == "de"


def test_en_prefix_serves_en_locale(client):
    r = client.get("/en/")
    assert r.status_code == 200
    m = re.search(r'<html lang="([^"]+)"', r.text)
    assert m and m.group(1) == "en"


def test_query_param_lang_overrides_default(client):
    """`?lang=en` on the unprefixed route resolves to en."""
    r = client.get("/?lang=en")
    assert r.status_code == 200
    m = re.search(r'<html lang="([^"]+)"', r.text)
    assert m and m.group(1) == "en"


def test_cookie_overrides_default(client):
    """A returning visitor with `fm_lang=en` cookie sees EN even on `/`."""
    r = client.get("/", cookies={"fm_lang": "en"})
    assert r.status_code == 200
    m = re.search(r'<html lang="([^"]+)"', r.text)
    assert m and m.group(1) == "en"


def test_accept_language_en_falls_through(client):
    """When no URL prefix / query / cookie, Accept-Language: en* wins over default DE."""
    r = client.get("/", headers={"accept-language": "en-US,en;q=0.9"})
    assert r.status_code == 200
    m = re.search(r'<html lang="([^"]+)"', r.text)
    assert m and m.group(1) == "en"


def test_unknown_locale_query_falls_back_to_default(client):
    """`?lang=fr` is not supported, and with no Accept-Language signal
    the server falls back to step 5 (operator default = DE upstream).

    We send an empty ``accept-language`` so the test pins step 5 in
    isolation; without it httpx's TestClient sometimes inherits a
    locale-shaped default that masks the fallback path.
    """
    r = client.get("/?lang=fr", headers={"accept-language": ""})
    assert r.status_code == 200
    m = re.search(r'<html lang="([^"]+)"', r.text)
    assert m and m.group(1) == DEFAULT_LOCALE


def test_url_prefix_beats_cookie(client):
    """Path-prefix resolution wins over cookie — prevents stale-cookie surprises."""
    r = client.get("/en/", cookies={"fm_lang": "de"})
    assert r.status_code == 200
    m = re.search(r'<html lang="([^"]+)"', r.text)
    assert m and m.group(1) == "en"


def test_url_prefix_beats_query_param(client):
    """Path-prefix wins over `?lang=` so deep-linked URLs stay deterministic."""
    r = client.get("/de/?lang=en")
    assert r.status_code == 200
    m = re.search(r'<html lang="([^"]+)"', r.text)
    assert m and m.group(1) == "de"


# ── Cookie persistence ────────────────────────────────────────────────────────


def test_explicit_url_prefix_sets_cookie(client):
    """Visiting `/en/` should set `fm_lang=en` cookie for sticky preference."""
    r = client.get("/en/")
    assert r.status_code == 200
    set_cookie = r.headers.get("set-cookie", "")
    assert "fm_lang=en" in set_cookie


def test_explicit_query_lang_sets_cookie(client):
    """`?lang=en` is also explicit — cookie persists the choice."""
    r = client.get("/?lang=en")
    assert r.status_code == 200
    set_cookie = r.headers.get("set-cookie", "")
    assert "fm_lang=en" in set_cookie


def test_unprefixed_path_does_not_set_cookie(client):
    """`/` with no explicit locale signal must NOT set fm_lang.

    Otherwise a default-DE visitor's first hit would write `fm_lang=de`,
    locking them out of any future Accept-Language detection.
    """
    r = client.get("/")
    assert r.status_code == 200
    set_cookie = r.headers.get("set-cookie", "")
    assert "fm_lang" not in set_cookie


# ── hreflang + canonical ──────────────────────────────────────────────────────


def test_hreflang_alternates_present_on_homepage(client):
    """Three hreflang links: de, en, x-default — required on every page."""
    r = client.get("/")
    text = r.text
    assert 'hreflang="de"' in text, "missing hreflang=de"
    assert 'hreflang="en"' in text, "missing hreflang=en"
    assert 'hreflang="x-default"' in text, "missing hreflang=x-default"


def test_hreflang_targets_match_locale_prefix(client):
    """hreflang=de should point at /de/<base>, hreflang=en at /en/<base>."""
    r = client.get("/")
    text = r.text
    de_link = re.search(r'hreflang="de"\s+href="([^"]+)"', text)
    en_link = re.search(r'hreflang="en"\s+href="([^"]+)"', text)
    assert de_link and de_link.group(1).endswith("/de/")
    assert en_link and en_link.group(1).endswith("/en/")


def test_hreflang_present_on_de_prefix_route(client):
    """The /de/... route must also emit the hreflang triple."""
    r = client.get("/de/")
    text = r.text
    assert 'hreflang="de"' in text
    assert 'hreflang="en"' in text
    assert 'hreflang="x-default"' in text


def test_canonical_self_canonical_on_each_locale(client):
    """Each locale variant is self-canonical (never canonical across languages)."""
    r_de = client.get("/de/")
    canonical_de = re.search(r'<link rel="canonical" href="([^"]+)"', r_de.text)
    assert canonical_de and "/de/" in canonical_de.group(1)

    r_en = client.get("/en/")
    canonical_en = re.search(r'<link rel="canonical" href="([^"]+)"', r_en.text)
    assert canonical_en and "/en/" in canonical_en.group(1)


def test_og_locale_matches_active_locale(client):
    """og:locale and og:locale:alternate flip per render so social cards
    advertise the right language to Facebook / LinkedIn / Slack."""
    r_de = client.get("/de/")
    assert 'property="og:locale" content="de_DE"' in r_de.text
    assert 'property="og:locale:alternate" content="en_US"' in r_de.text

    r_en = client.get("/en/")
    assert 'property="og:locale" content="en_US"' in r_en.text
    assert 'property="og:locale:alternate" content="de_DE"' in r_en.text


# ── Switcher visibility in nav ────────────────────────────────────────────────


def test_navbar_includes_language_switcher(client):
    r = client.get("/")
    # Switcher group is wrapped in role="group" aria-label (English by default for x-default DE)
    assert 'role="group"' in r.text
    # Both DE and EN links present
    assert 'hreflang="de"' in r.text
    assert 'hreflang="en"' in r.text


def test_active_locale_marked_aria_current(client):
    """The link for the active locale carries aria-current=true so SR users
    know which language they're currently reading."""
    r_de = client.get("/de/")
    # Active de: aria-current on the de link
    assert re.search(r'href="[^"]*/de/"[^>]*aria-current="true"', r_de.text), (
        "DE link missing aria-current on /de/"
    )

    r_en = client.get("/en/")
    assert re.search(r'href="[^"]*/en/"[^>]*aria-current="true"', r_en.text), (
        "EN link missing aria-current on /en/"
    )


# ── Sub-router prefix isolation ───────────────────────────────────────────────


def test_de_prefix_routes_do_not_collide_with_unprefixed(client):
    """`/de/login` resolves the login page; `/login` likewise — both work."""
    r_de = client.get("/de/login")
    r_root = client.get("/login")
    assert r_de.status_code == 200
    assert r_root.status_code == 200


@pytest.mark.parametrize("locale", SUPPORTED_LOCALES)
def test_supported_locale_renders_each_page(client, locale):
    """Smoke: every page renders 200 in both supported locales (excluding
    pricing-gated which 404s without PRICING_PAGE_ENABLED)."""
    pages = [
        "/",
        "/login",
        "/register",
        "/forgot-password",
        "/security",
        "/privacy",
        "/terms",
        "/impressum",
        "/verify-email",
    ]
    for page in pages:
        r = client.get(f"/{locale}{page}" if page != "/" else f"/{locale}/")
        assert r.status_code == 200, f"/{locale}{page} returned {r.status_code}"
