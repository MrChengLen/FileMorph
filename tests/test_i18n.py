# SPDX-License-Identifier: AGPL-3.0-or-later
"""i18n infrastructure tests — pin the locale-resolution contract.

Covers the four-step resolution chain in
``app/core/i18n.py::resolve_locale`` (URL-prefix → query-param →
Accept-Language → operator default), the unknown-locale fallback, the
hreflang presence on every page, the ``<html lang>`` / ``og:locale``
propagation, and the **no-cookie** regression-guard.

The app sets no cookies at all — the published privacy policy
(``app/templates/privacy.html`` §6) commits to "no cookies on its own
domain"; auth uses ``localStorage`` + bearer/``X-API-Key`` headers and
locale is in the URL path, so there is nothing a cookie would carry.
``test_no_cookie_set_on_any_route`` is the programmatic guard against
accidental reintroduction of *any* ``Set-Cookie``.

These tests do not depend on any DE translations existing — PR-i18n-1
ships infrastructure with empty .po files, so all rendered text stays
EN. The tests assert *behaviour*, not translated copy.
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
    """Defensive: reset the session-scoped TestClient's cookie jar per test.

    The app no longer sets any locale cookie, but the session-scoped
    ``client`` from ``conftest.py`` accumulates whatever any other test
    in the suite happens to set. Clearing here pins each i18n test to a
    clean jar so unrelated suite ordering can't leak state into the
    resolution-chain assertions.
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


def test_accept_language_en_falls_through(client):
    """When no URL prefix / query is present, Accept-Language: en* wins over default DE."""
    r = client.get("/", headers={"accept-language": "en-US,en;q=0.9"})
    assert r.status_code == 200
    m = re.search(r'<html lang="([^"]+)"', r.text)
    assert m and m.group(1) == "en"


def test_unknown_locale_query_falls_back_to_default(client):
    """`?lang=fr` is not supported, and with no Accept-Language signal
    the server falls back to the operator default (DE upstream).

    We send an empty ``accept-language`` so the test pins the default in
    isolation; without it httpx's TestClient sometimes inherits a
    locale-shaped default that masks the fallback path.
    """
    r = client.get("/?lang=fr", headers={"accept-language": ""})
    assert r.status_code == 200
    m = re.search(r'<html lang="([^"]+)"', r.text)
    assert m and m.group(1) == DEFAULT_LOCALE


def test_url_prefix_beats_query_param(client):
    """Path-prefix wins over `?lang=` so deep-linked URLs stay deterministic."""
    r = client.get("/de/?lang=en")
    assert r.status_code == 200
    m = re.search(r'<html lang="([^"]+)"', r.text)
    assert m and m.group(1) == "de"


# ── No-cookie regression-guard ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "url",
    [
        "/",
        "/de/",
        "/en/",
        "/?lang=de",
        "/?lang=en",
        "/login",
        "/de/login",
        "/en/login",
        "/contact",
        "/de/contact",
        "/en/contact",
    ],
)
def test_no_cookie_set_on_any_route(client, url):
    """The app commits to "no cookies on its own domain" (privacy.html §6).

    Programmatic gate against *any* accidental ``Set-Cookie`` — not just the
    ``fm_lang`` locale cookie that PR-i18n-1 once wired up and PR-i18n-1b
    removed. FileMorph is wholly cookie-free: JWT/API-key live in
    ``localStorage`` + ``Authorization``/``X-API-Key`` headers, locale is in
    the URL path, there is no server-side session. So *no* response from any
    route may carry a ``Set-Cookie`` header. Hits root, locale-prefixed,
    query-param, and a non-trivial page.
    """
    r = client.get(url, headers={"accept-language": ""})
    assert r.status_code == 200
    assert "set-cookie" not in r.headers, (
        f"FileMorph set a cookie on {url!r} — Set-Cookie was: "
        f"{r.headers.get('set-cookie')!r}. The app commits to 'no cookies' "
        f"(privacy.html §6); auth uses localStorage + bearer headers, locale "
        f"uses the URL path. If a strictly-necessary cookie is ever genuinely "
        f"required, that's a deliberate decision — update privacy.html and "
        f"this guard together."
    )


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


def test_switcher_uses_aria_label_not_visible_sr_text(client):
    """Switcher must show plain "DE" / "EN" with the screen-reader text on
    ``aria-label`` — never inside a child ``<span class="sr-only">``.

    Earlier markup wrapped the SR text in ``<span class="sr-only">Switch
    to German</span>DE`` which renders correctly *only* when Tailwind's
    ``sr-only`` utility makes it into the bundle. Our committed
    ``app/static/css/tailwind.*.css`` does not contain that utility,
    which let the SR string leak as visible text in production
    (``"SWITCH TO GERMANDE"``). This guard pins the markup to the
    a11y-equivalent ``aria-label`` form so a future Tailwind purge can't
    break the visible label again.
    """
    r = client.get("/")
    text = r.text

    # Negative: the broken pattern must never reappear.
    assert "Switch to GermanDE" not in text, (
        "screen-reader text leaked into visible DE label — re-introducing sr-only span?"
    )
    assert "Switch to EnglishEN" not in text, (
        "screen-reader text leaked into visible EN label — re-introducing sr-only span?"
    )

    # Positive: both switcher links carry aria-label so screen readers still
    # announce the action even though the visible text is just "DE" / "EN".
    assert re.search(r'<a[^>]*hreflang="de"[^>]*aria-label="[^"]+"', text), (
        "DE switcher link missing aria-label"
    )
    assert re.search(r'<a[^>]*hreflang="en"[^>]*aria-label="[^"]+"', text), (
        "EN switcher link missing aria-label"
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
        "/contact",
        "/verify-email",
    ]
    for page in pages:
        r = client.get(f"/{locale}{page}" if page != "/" else f"/{locale}/")
        assert r.status_code == 200, f"/{locale}{page} returned {r.status_code}"


# ── M9 — DE-content smoke (catalog-loaded asserter) ─────────────────────────
#
# The 200-status smoke above passes even when the .mo catalog is missing,
# corrupt, or out of sync — Babel falls back to the msgid (EN) silently.
# These tests pin a stable DE-only string per page, so a missing catalog
# (or a future PR that drops a translation) surfaces as a hard failure
# rather than a silent regression to English.
#
# Strings chosen for stability:
#   - ``Datenschutz``: navbar / privacy heading; would never appear in EN.
#   - ``Nutzungsbedingungen``: terms-of-use heading; would render as
#     "Terms" or "Terms of Use" in EN.
#   - ``Impressum``: legal-imprint header; same word in both locales but
#     the page also carries DE-only ``Verantwortlich`` which we pin as
#     the second anchor for the DE branch.
#   - ``Widerrufsrecht``: BGB §356 right-of-withdrawal language; appears
#     on /de/privacy as part of the consumer-protection clause and is
#     untranslatable in an EN render.


@pytest.mark.parametrize(
    "path,de_marker",
    [
        ("/de/privacy", "Datenschutz"),
        ("/de/terms", "Nutzungsbedingungen"),
        ("/de/impressum", "Verantwortlich"),
        ("/de/security", "Sicherheit"),
        ("/de/contact", "Nachricht senden"),
    ],
)
def test_de_page_renders_german_content(client, path, de_marker):
    """A DE-marker string must appear in the rendered output. If the .mo
    catalog is missing or corrupt, gettext falls back to the EN msgid and
    this assertion fails — without it the 200-status test passes silently.
    """
    r = client.get(path)
    assert r.status_code == 200, f"{path} returned {r.status_code}"
    text = r.text
    # Locale-resolution sanity (catches routing drift independently of
    # the catalog status).
    assert '<html lang="de"' in text, f"{path} served without lang=de — i18n routing drift"
    # Catalog-loaded assertion — the actual M9 guard.
    assert de_marker in text, (
        f"{path} resolved to lang=de but DE marker '{de_marker}' missing — "
        f"messages.mo loaded? gettext fallback to EN? Catalog out of sync?"
    )


# ── FM_I18N JS strings — the server-rendered JSON blob in base.html ───────────


def test_fm_i18n_json_blob_present_on_every_page(client):
    """Every rendered page must inline the FM_I18N JSON catalogue so the
    front-end JS layer has translated strings available. Missing this blob
    means every alert/button label silently falls back to its English
    hardcoded fallback, defeating the JS-i18n design."""
    for path in ("/", "/de/", "/en/", "/de/login", "/en/login"):
        r = client.get(path)
        assert r.status_code == 200, f"{path} -> {r.status_code}"
        assert 'id="fm-i18n-strings"' in r.text, f"{path} missing FM_I18N script tag"
        assert "window.FM_I18N = JSON.parse" in r.text, f"{path} missing FM_I18N bootstrap"


def test_fm_i18n_json_blob_localises_per_request(client):
    """The JSON blob carries strings for the active locale — pin a known
    DE translation against the /de/ render and a known EN string against
    /en/. If gettext silently drops back to the msgid, the assertions
    fail and we know the JS-side i18n is broken at the source."""
    import json
    import re

    de = client.get("/de/")
    en = client.get("/en/")
    assert de.status_code == 200 and en.status_code == 200

    # Extract the JSON content out of the script tag, parse, compare.
    pattern = re.compile(
        r'<script id="fm-i18n-strings" type="application/json">(.*?)</script>',
        re.DOTALL,
    )
    de_match = pattern.search(de.text)
    en_match = pattern.search(en.text)
    assert de_match and en_match, "FM_I18N script tag missing"

    de_strings = json.loads(de_match.group(1))
    en_strings = json.loads(en_match.group(1))

    # German render: 'Convert' button label translated.
    assert de_strings.get("convert") == "Konvertieren", (
        f"FM_I18N.convert on /de/ should be 'Konvertieren', got {de_strings.get('convert')!r}"
    )
    assert de_strings.get("compress") == "Komprimieren"
    # English render: msgid is already English so the value stays English.
    assert en_strings.get("convert") == "Convert"
    assert en_strings.get("compress") == "Compress"
