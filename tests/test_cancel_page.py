# SPDX-License-Identifier: AGPL-3.0-or-later
"""§ 312k BGB online-cancellation page ("Kündigungsbutton") — the frontend contract.

Guards:
  - Stripe gate: ``/cancel`` (+ ``/de``, ``/en``) 404s unless Stripe is configured, and the
    footer / dashboard entry points render only then (G5 gate parity: a self-host never
    links its own 404).
  - Form contract: the named fields cancel.js reads and posts to
    ``/api/v1/billing/cancellation``; exactly one button, labelled "Cancel now".
  - BGH I ZR 200/25 (16 Jul 2026): the page carries only the form and the button — no
    pricing/upgrade/portal links in <main>, and (minimal chrome) none anywhere on the page:
    header = logo + language switcher, footer = © line + Legal group.
  - Permanent, legible footer link on every page; dashboard billing card entry.
  - Print: navbar, mobile menu, footer and cookie notice are ``print:hidden`` everywhere, so
    the printed receipt stands alone; on /cancel the sheet is white and the receipt prints
    dark-on-white, whether or not the print dialog's "Background graphics" is on.
  - CSP hygiene: no inline handlers/scripts, no HTML-injection sinks in the new JS.

The JS itself is out of pytest's reach (as in the other UI tests) — these tests pin the
server-rendered DOM contract it depends on. The statutory German labels („Verträge hier
kündigen", „jetzt kündigen") and the dunning email's „Abrechnung verwalten" are pinned at the
end of this file.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from bs4 import BeautifulSoup

from app.core.config import settings
from app.core.templates import templates

_ROOT = Path(__file__).resolve().parent.parent
_CANCEL_JS = _ROOT / "app" / "static" / "js" / "cancel.js"
_DASHBOARD_JS = _ROOT / "app" / "static" / "js" / "dashboard.js"
_CANCEL_TEMPLATE = _ROOT / "app" / "templates" / "cancel.html"

_CANCEL_PATHS = ["/cancel", "/en/cancel", "/de/cancel"]


@pytest.fixture
def stripe_on(monkeypatch):
    """Flip Stripe on for BOTH surfaces that read it: ``settings`` (the route-level 404
    gate, read per request) and the Jinja global (template ``{% if stripe_enabled %}``,
    set once at import). Same two-surface flip as test_seo_foundation.py; monkeypatch
    reverts both regardless of test order."""
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_dummy")  # gitleaks:allow
    monkeypatch.setitem(templates.env.globals, "stripe_enabled", True)


@pytest.fixture
def stripe_off(monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "")
    monkeypatch.setitem(templates.env.globals, "stripe_enabled", False)


@pytest.fixture
def pricing_on(monkeypatch):
    """Worst case for the minimal-chrome checks: the commercial offer is switched on as well,
    so every offer/navigation link the full chrome can render is live on the other pages.
    Same two-surface flip as test_footer_nav_structure.py."""
    monkeypatch.setattr(settings, "pricing_page_enabled", True)
    monkeypatch.setitem(templates.env.globals, "pricing_enabled", True)


def _route(href: str) -> str:
    """A link's path without the /de|/en prefix, query and fragment: "/en/tools#x" -> "/tools"."""
    return re.sub(r"^/(de|en)(?=/|$)", "", urlsplit(href).path) or "/"


def _footer(html: str) -> str:
    """Slice from the <footer> tag — a link must not pass just because the same URL
    appears in the page body."""
    return html[html.index("<footer") :]


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


# ── Stripe gate on the route ─────────────────────────────────────────────────


@pytest.mark.parametrize("path", _CANCEL_PATHS)
def test_cancel_page_404_when_stripe_off(client, stripe_off, path):
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("path", _CANCEL_PATHS)
def test_cancel_page_renders_when_stripe_on(client, stripe_on, path):
    assert client.get(path).status_code == 200


def test_cancel_page_is_not_in_the_sitemap(client, stripe_on):
    """A legal entry point, not landing content — it must not be advertised to crawlers."""
    assert "/cancel" not in client.get("/sitemap.xml").text


# ── Form contract (what cancel.js reads and posts) ───────────────────────────


def _form(client) -> BeautifulSoup:
    form = _soup(client.get("/en/cancel").text).find("form", id="cancel-form")
    assert form is not None, "#cancel-form missing"
    return form


def test_cancel_form_has_all_named_fields(client, stripe_on):
    form = _form(client)

    email = form.find("input", attrs={"name": "email"})
    assert email is not None and email["type"] == "email" and email.has_attr("required")
    assert email.get("autocomplete") == "email"

    def radios(name: str) -> dict[str, bool]:
        found = form.find_all("input", attrs={"type": "radio", "name": name})
        return {r["value"]: r.has_attr("checked") for r in found}

    # Values are the API contract; exactly one default per group.
    assert radios("contract") == {"pro": True, "business": False}
    assert radios("kind") == {"ordinary": True, "extraordinary": False}
    assert radios("end") == {"earliest": True, "date": False}

    reason = form.find("textarea", attrs={"name": "reason"})
    assert reason is not None
    end_date = form.find("input", attrs={"name": "end_date"})
    assert end_date is not None and end_date["type"] == "date"
    honeypot = form.find("input", attrs={"name": "website"})
    assert honeypot is not None
    assert honeypot.get("tabindex") == "-1" and honeypot.get("autocomplete") == "off"
    assert honeypot.find_parent(class_="hidden") is not None, "honeypot must not be visible"


def test_form_without_javascript_is_not_a_dead_end_and_never_leaks_into_the_url(client, stripe_on):
    """If cancel.js does not run, a native submit must not be a GET (address and free-text
    reason would land in the URL, history and access logs), and the visitor is told why
    nothing happens — with the email way out."""
    soup = _soup(client.get("/en/cancel").text)
    assert soup.find("form", id="cancel-form")["method"] == "post"
    noscript = soup.find("noscript")
    assert noscript is not None and "JavaScript" in noscript.get_text()
    assert noscript.find(["a", "button", "form"]) is None


def test_conditional_fields_start_hidden(client, stripe_on):
    """Reason and end date only appear once their option is chosen (cancel.js)."""
    form = _form(client)
    assert "hidden" in form.find(id="cancel-reason-wrap")["class"]
    assert "hidden" in form.find(id="cancel-date-wrap")["class"]


def test_cancel_form_has_exactly_one_button_labelled_cancel_now(client, stripe_on):
    """§ 312k BGB: one confirmation button, labelled with nothing else."""
    form = _form(client)
    buttons = form.find_all("button")
    assert len(buttons) == 1
    assert buttons[0]["type"] == "submit"
    assert buttons[0]["id"] == "cancel-submit"
    assert buttons[0].get_text(strip=True) == "Cancel now"
    assert form.find_all("input", attrs={"type": ["submit", "button", "image", "reset"]}) == []


def test_cancel_page_headline_and_title(client, stripe_on):
    soup = _soup(client.get("/en/cancel").text)
    assert soup.find("h1").get_text(strip=True) == "Cancel contracts here"
    assert "Cancel contracts here" in soup.find("title").get_text()


def test_status_region_carries_every_error_text(client, stripe_on):
    status = _soup(client.get("/en/cancel").text).find(id="cancel-status")
    assert status is not None and status["aria-live"] == "polite"
    for key in ("data-err-422", "data-err-429", "data-err-503", "data-err-500"):
        assert status.get(key), f"{key} missing or empty"


def test_errors_never_dead_end_when_an_operator_address_exists(client, stripe_on, monkeypatch):
    monkeypatch.setattr(settings, "contact_form_recipient_email", "cancel-ops@example.test")
    status = _soup(client.get("/en/cancel").text).find(id="cancel-status")
    for key in ("data-err-422", "data-err-429", "data-err-503", "data-err-500"):
        assert status[key].endswith("by email to cancel-ops@example.test."), key


def test_errors_stay_clean_without_an_operator_address(client, stripe_on, monkeypatch):
    for name in ("contact_form_recipient_email", "smtp_reply_to", "smtp_from_email"):
        monkeypatch.setattr(settings, name, "")
    status = _soup(client.get("/en/cancel").text).find(id="cancel-status")
    for key in ("data-err-422", "data-err-429", "data-err-503", "data-err-500"):
        assert "by email to" not in status[key], key


# ── Receipt (the consumer's proof) ───────────────────────────────────────────


def test_receipt_section_structure(client, stripe_on):
    soup = _soup(client.get("/en/cancel").text)
    receipt = soup.find(id="cancel-receipt")
    assert receipt is not None and "hidden" in receipt["class"]
    # Focus target after submit.
    heading = receipt.find("h2")
    assert heading["tabindex"] == "-1" and heading.get_text(strip=True) == "Cancellation received"
    # Timestamp sentence: cancel.js fills {datetime} from the server's receipt time.
    time_line = receipt.find(id="cancel-receipt-time")
    assert "{datetime}" in time_line["data-template"]
    assert "“Cancel now”" in time_line["data-template"]
    # Email-sent / not-sent sentences.
    mail = receipt.find(id="cancel-receipt-email")
    assert "{email}" in mail["data-sent"] and mail["data-not-sent"]
    # Summary rows cancel.js fills; the reason row is hidden until there is a reason.
    fields = {dd["data-field"] for dd in receipt.find_all("dd")}
    assert fields == {"email", "contract", "kind", "reason", "end"}
    assert "hidden" in receipt.find(id="cancel-receipt-reason-row")["class"]
    assert receipt.find("dd", attrs={"data-field": "end"})["data-end-earliest"]
    # Print / save as PDF — a real button, outside the cancellation form.
    printer = receipt.find("button", id="cancel-print")
    assert printer is not None and printer["type"] == "button"
    assert soup.find("form", id="cancel-form").find(id="cancel-print") is None


# ── BGH I ZR 200/25: nothing but the form and the button ─────────────────────


def test_cancel_page_body_has_no_pricing_upgrade_or_portal_links(client, stripe_on):
    main = _soup(client.get("/en/cancel").text).find("main")
    hrefs = [a.get("href", "") for a in main.find_all("a")]
    for forbidden in ("/pricing", "/enterprise", "/dashboard", "/api/v1/billing/portal"):
        assert not any(forbidden in href for href in hrefs), f"{forbidden} linked on /cancel"
        assert forbidden not in str(main), f"{forbidden} mentioned inside <main> of /cancel"
    # The privacy-policy link is the only link the page may carry.
    assert hrefs == ["/en/privacy"]


# ── Minimal chrome: the confirmation page carries no offer/navigation links at all ──
# Decision (legally safest reading of BGH I ZR 200/25): not just <main> but the WHOLE page
# — header, footer, cookie notice, <head> — must lead nowhere but the home page, the
# language switcher and the legal pages (Impressum/Privacy stay reachable, DDG § 5).

_OFFER_AND_NAV_ROUTES = (
    "/pricing",
    "/enterprise",
    "/tools",
    "/formats",
    "/dashboard",
    "/login",
    "/register",
    "/api/v1/billing/portal",
)


def _imprint(locale: str) -> str:
    return "/en/imprint" if locale == "en" else "/de/impressum"  # EN URL alias of /impressum


@pytest.mark.parametrize("locale", ["en", "de"])
def test_cancel_page_has_no_offer_or_navigation_links_anywhere(
    client, stripe_on, pricing_on, locale
):
    html = client.get(f"/{locale}/cancel").text
    soup = _soup(html)
    routes = [_route(el["href"]) for el in soup.find_all(["a", "link", "area"], href=True)]
    for forbidden in _OFFER_AND_NAV_ROUTES:
        hits = [r for r in routes if r == forbidden or r.startswith(forbidden + "/")]
        assert not hits, f"/{locale}/cancel links {forbidden}: {hits}"
    # Nor into the product: tool/pair pages, API docs, GitHub, the self-hosted anchor.
    hrefs = [el["href"] for el in soup.find_all(["a", "link", "area"], href=True)]
    for product in ("/convert/", "/pdf/", "/compress", "/docs", "github.com", "#self-hosted"):
        assert not [h for h in hrefs if product in h], f"/{locale}/cancel links {product}"
    assert "Popular conversions" not in html
    # What remains, exactly: home, language switcher, and the legal pages + the cancel link.
    assert {a["href"] for a in soup.find_all("a", href=True)} == {
        f"/{locale}/",  # logo
        "/de/cancel",  # language switcher
        "/en/cancel",  # language switcher, footer
        f"/{locale}/privacy",  # form note, footer
        f"/{locale}/privacy#cookies",  # cookie notice
        f"/{locale}/terms",
        _imprint(locale),
        f"/{locale}/contact",
    }


@pytest.mark.parametrize("locale", ["en", "de"])
def test_cancel_page_chrome_is_logo_language_switcher_and_legal_group_only(
    client, stripe_on, pricing_on, locale
):
    soup = _soup(client.get(f"/{locale}/cancel").text)
    # Header: logo + language switcher, in that order — the switcher still targets the
    # other language's /cancel.
    header = soup.find("nav")
    assert [a["href"] for a in header.find_all("a")] == [f"/{locale}/", "/de/cancel", "/en/cancel"]
    # No hamburger and no mobile menu, so the switcher must be visible at every width.
    menu_classes = header.find(id="nav-menu")["class"]
    assert "flex" in menu_classes and not {"hidden", "md:flex"} & set(menu_classes)
    for gone in ("nav-toggle", "nav-mobile-menu", "nav-auth-desktop", "nav-auth-mobile"):
        assert soup.find(id=gone) is None, f"#{gone} must not render on /cancel"
    # Footer: the © line and the Legal group (Privacy, Terms, Impressum, Contact, Cancel).
    footer = soup.find("footer")
    assert "© 2026 FileMorph" in footer.get_text()
    assert len(footer.find_all("nav")) == 1, "only the Legal group may remain in the footer"
    assert [a["href"] for a in footer.find_all("a")] == [
        f"/{locale}/privacy",
        f"/{locale}/terms",
        _imprint(locale),
        f"/{locale}/contact",
        f"/{locale}/cancel",
    ]
    # The cookie notice is privacy information and stays.
    assert soup.find(id="cookie-notice") is not None


def test_homepage_chrome_is_unchanged_with_pricing_on(client, stripe_on, pricing_on):
    """minimal_chrome is a /cancel-only flag: every other page keeps the full chrome."""
    soup = _soup(client.get("/en/").text)
    header = soup.find("nav")
    header_links = {a["href"] for a in header.find_all("a")}
    assert {
        "/en/tools",
        "/en/pricing",
        "/en/enterprise",
        "/en/login",
        "/en/register",
        "/de/",
    } <= header_links
    for present in ("nav-toggle", "nav-mobile-menu", "nav-auth-desktop", "nav-auth-mobile"):
        assert soup.find(id=present) is not None, f"#{present} missing on the homepage"
    assert "md:flex" in header.find(id="nav-menu")["class"]
    footer = soup.find("footer")
    footer_links = {a["href"] for a in footer.find_all("a")}
    assert {
        "/en/tools",
        "/en/formats",
        "/en/pdf/split",
        "/en/pricing",
        "/en/enterprise",
        "/en/privacy",
        "/en/cancel",
    } <= footer_links
    grid = footer.find("nav", attrs={"aria-label": "Popular conversions"})
    assert grid is not None and grid.find_all("a", href=re.compile(r"^/en/convert/"))


@pytest.mark.parametrize("path", ["/en/", "/en/login", "/en/cancel"])
def test_site_chrome_is_hidden_when_printing(client, stripe_on, path):
    """A printed page shows only <main> — on /cancel that is the receipt, the consumer's
    saved proof — not the navbar, footer or cookie notice."""
    soup = _soup(client.get(path).text)
    assert "print:hidden" in soup.find("nav")["class"]
    assert "print:hidden" in soup.find("footer")["class"]
    assert "print:hidden" in soup.find(id="cookie-notice")["class"]
    menu = soup.find(id="nav-mobile-menu")
    body = soup.find("body")["class"]
    if path == "/en/cancel":
        assert menu is None, "minimal chrome renders no mobile menu"
        # White sheet: with "Background graphics" on, the dark body would print dark and
        # swallow the receipt's black heading.
        assert "print:bg-white" in body
    else:
        assert menu is not None and "print:hidden" in menu["class"]
        # Deliberately NOT white: on every other page the dark body is what keeps their light
        # text legible when graphics are on (white sheet = white text on white).
        assert "print:bg-white" not in body


def test_receipt_prints_dark_on_white(client, stripe_on):
    """Every element the printed receipt shows must read dark on a white sheet with the print
    dialog's "Background graphics" on AND off (measured in headless Edge, both modes): white
    body and card, black heading and text, dark-gray labels, and no button on paper."""
    soup = _soup(client.get("/en/cancel").text)
    assert "print:bg-white" in soup.find("body")["class"]
    main = soup.find("main")
    assert "print:text-black" in main["class"]
    assert "print:text-black" in main.find("h1")["class"]
    receipt = main.find(id="cancel-receipt")
    assert "print:bg-white" in receipt["class"], "dark card would print dark with graphics on"
    assert "print:text-black" in receipt.find(id="cancel-receipt-title")["class"]
    labels = receipt.find_all("dt")
    assert labels and all("print:text-gray-700" in dt["class"] for dt in labels)
    # The paragraphs and values set no colour of their own, so they inherit main's black.
    for el in receipt.find_all(["p", "dd"]):
        colours = [
            c
            for c in el.get("class", [])
            if c.startswith("text-") and not re.fullmatch(r"text-(xs|sm|base|lg|[1-9]?xl)", c)
        ]
        assert not colours, f"<{el.name}> sets its own text colour {colours}: not black in print"
    assert "print:hidden" in receipt.find(id="cancel-print").parent["class"]


# ── Footer link: permanent, legible, no login needed ─────────────────────────


def test_footer_links_cancel_page_last_in_legal_group_when_stripe_on(client, stripe_on):
    footer = _soup(_footer(client.get("/en/").text))
    legal = footer.find("nav", attrs={"aria-label": "Legal"})
    last = legal.find_all("a")[-1]
    assert last["href"] == "/en/cancel"
    assert last.get_text(strip=True) == "Cancel contracts here"
    # A notch brighter than its text-gray-500 neighbours — the law requires legibility.
    assert "text-gray-400" in last["class"] and "text-gray-500" not in last["class"]


@pytest.mark.parametrize(
    "path",
    ["/en/", "/en/login", "/en/contact", "/en/privacy", "/en/terms", "/en/imprint", "/en/cancel"],
)
def test_footer_link_is_on_every_page_when_stripe_on(client, stripe_on, path):
    r = client.get(path)
    assert r.status_code == 200
    assert 'href="/en/cancel"' in _footer(r.text)


def test_footer_link_is_localized_on_de(client, stripe_on):
    assert 'href="/de/cancel"' in _footer(client.get("/de/").text)


def test_footer_has_no_cancel_link_when_stripe_off(client, stripe_off):
    for path in ("/en/", "/de/"):
        assert "/cancel" not in _footer(client.get(path).text)


# ── Dashboard billing card ───────────────────────────────────────────────────


def test_dashboard_billing_card_renders_when_stripe_on(client, stripe_on):
    soup = _soup(client.get("/en/dashboard").text)
    main = soup.find("main")
    # The whole card (box included) is hidden until dashboard.js sees a subscription.
    card = main.find(id="billing-card")
    assert card is not None and "hidden" in card["class"]
    assert card.find("h2").get_text(strip=True) == "Subscription"
    # The dunning email names this button — the label is fixed.
    manage = card.find("button", id="manage-billing-btn")
    assert manage is not None and manage.get_text(strip=True) == "Manage billing"
    link = card.find("a", id="cancel-contract-link")
    assert link["href"] == "/en/cancel"
    assert link.get_text(strip=True) == "Cancel contracts here"
    assert "hidden" in link["class"], "shown by dashboard.js for live contracts only"
    # Status texts and portal errors travel as data-* (CSP: no strings in JS).
    line = card.find(id="billing-status")
    for key in ("active", "trialing", "past-due", "ended"):
        assert line.get(f"data-status-{key}"), f"data-status-{key} missing"
    action = card.find(id="billing-action-status")
    assert action["aria-live"] == "polite"
    for key in ("data-err-400", "data-err-429", "data-err-503", "data-err"):
        assert action.get(key), f"{key} missing"


def test_dashboard_has_no_billing_card_when_stripe_off(client, stripe_off):
    html = client.get("/en/dashboard").text
    assert 'id="manage-billing-btn"' not in html
    assert 'id="billing-card"' not in html
    assert "/en/cancel" not in html


# ── JS contract + CSP hygiene ────────────────────────────────────────────────


def test_dashboard_js_opens_the_billing_portal():
    js = _DASHBOARD_JS.read_text(encoding="utf-8")
    assert "/api/v1/billing/portal" in js
    assert "manage-billing-btn" in js
    assert "subscription_status" in js


def test_cancel_js_posts_anonymously_to_the_cancellation_endpoint():
    js = _CANCEL_JS.read_text(encoding="utf-8")
    assert "/api/v1/billing/cancellation" in js
    assert "?lang=" in js
    assert "'Content-Type': 'application/json'" in js
    # Public endpoint: no bearer token, no authFetch.
    assert "authFetch" not in js and "Authorization" not in js


def _dataset_keys(html: str) -> set[str]:
    """What ``element.dataset`` exposes for a page's data-* attributes (HTML spec): a dash
    before an ASCII lowercase letter is dropped and the letter upper-cased, every other dash
    stays. So ``data-err-422`` is ``dataset['err-422']`` and ``dataset.err422`` is undefined
    — a message read that way silently comes out empty."""
    keys: set[str] = set()
    for tag in _soup(html).find_all(True):
        for attr in tag.attrs:
            if attr.startswith("data-"):
                keys.add(re.sub(r"-([a-z])", lambda m: m.group(1).upper(), attr[len("data-") :]))
    return keys


def test_cancel_js_reads_only_dataset_keys_the_page_provides(client, stripe_on):
    js = _CANCEL_JS.read_text(encoding="utf-8")
    read = set(re.findall(r"\.dataset\.(\w+)", js))
    assert read, "cancel.js reads no dataset keys — regex drift?"
    missing = read - _dataset_keys(client.get("/en/cancel").text)
    assert not missing, f"cancel.js reads dataset keys no data-* attribute produces: {missing}"


def test_cancel_js_writes_text_never_html():
    js = _CANCEL_JS.read_text(encoding="utf-8")
    assert not re.search(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write", js)


def test_cancel_template_has_no_inline_event_handlers():
    source = _CANCEL_TEMPLATE.read_text(encoding="utf-8")
    assert not re.search(r"\son[a-z]+\s*=", source, re.IGNORECASE)


def test_cancel_page_ships_no_inline_executable_script(client, stripe_on):
    """The page's logic lives in /static/js/cancel.js; base.html's inline scripts are
    data blocks only (application/json, ld+json), which the CSP does not govern."""
    html = client.get("/en/cancel").text
    assert '<script src="/static/js/cancel.js"></script>' in html
    for attrs, body in re.findall(r"<script\b([^>]*)>(.*?)</script>", html, re.S | re.I):
        if re.search(r"\bsrc\s*=", attrs):
            continue
        assert re.search(r"application/(ld\+)?json", attrs), (
            f"inline executable script on /cancel: {body.strip()[:60]!r}"
        )


# ── German wording: the statutory labels and the dunning email's button name ──


def test_de_cancel_page_uses_the_statutory_labels(client, stripe_on):
    """§ 312k (2) BGB: „Verträge hier kündigen" and „jetzt kündigen", nothing else."""
    soup = _soup(client.get("/de/cancel").text)
    assert soup.find("h1").get_text(strip=True) == "Verträge hier kündigen"
    assert "Verträge hier kündigen" in soup.find("title").get_text()
    buttons = soup.find("form", id="cancel-form").find_all("button")
    assert [b.get_text(strip=True) for b in buttons] == ["jetzt kündigen"]


def test_de_footer_link_uses_the_statutory_label(client, stripe_on):
    legal = _soup(_footer(client.get("/de/").text)).find("nav", attrs={"aria-label": "Rechtliches"})
    last = legal.find_all("a")[-1]
    assert last["href"] == "/de/cancel"
    assert last.get_text(strip=True) == "Verträge hier kündigen"


@pytest.mark.parametrize(
    ("path", "foreign"),
    [
        ("/de/cancel", ("Cancel now", "Cancel contracts here", "Type of cancellation")),
        ("/en/cancel", ("jetzt kündigen", "Verträge hier kündigen", "Art der Kündigung")),
    ],
)
def test_cancel_page_has_no_text_in_the_other_language(client, stripe_on, path, foreign):
    html = client.get(path).text
    for text in foreign:
        assert text not in html, f"{text!r} leaked into {path}"


@pytest.mark.parametrize(
    ("locale", "label"), [("de", "Abrechnung verwalten"), ("en", "Manage billing")]
)
def test_dunning_email_names_the_dashboard_button(client, stripe_on, locale, label):
    """The dunning email tells users to click the dashboard button by name — both must
    carry the same label in each language."""
    from app.core import email as email_mod

    button = _soup(client.get(f"/{locale}/dashboard").text).find("button", id="manage-billing-btn")
    assert button.get_text(strip=True) == label
    _subject, html, text = email_mod.render_email(
        "dunning",
        locale=locale,
        user_email="someone@example.test",
        tier_label="Pro",
        next_attempt_date=None,
        billing_url="https://files.example.test/dashboard",
        app_base_url="https://files.example.test",
    )
    assert label in text
    assert label in html
