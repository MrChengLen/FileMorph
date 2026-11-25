# SPDX-License-Identifier: AGPL-3.0-or-later
"""/pricing is built from the shared components (UI frame, package 3b).

The plans variant (Stripe on) is latent on filemorph.io, so nothing renders it
there; these checks keep its structure from drifting back to hand-made markup:
the audience switch is the segmented component (a labelled group, its look
driven by aria-pressed alone), and the plan cards are card() + button().
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from app.core.config import settings
from app.core.templates import templates

SEGMENT_JS = Path(__file__).resolve().parent.parent / "app" / "static" / "js" / "pricing-segment.js"
STRIPE_TEST_KEY = "sk_test_dummy"  # gitleaks:allow — a placeholder, never a real key


def _commercial_pages_on(monkeypatch, *, stripe: bool) -> None:
    """/pricing and /enterprise on; with ``stripe`` the plans variant renders
    (the route reads ``settings``, the template the Jinja global)."""
    monkeypatch.setattr(settings, "pricing_page_enabled", True)
    monkeypatch.setattr(settings, "stripe_secret_key", STRIPE_TEST_KEY if stripe else "")
    monkeypatch.setitem(templates.env.globals, "stripe_enabled", stripe)


@pytest.fixture
def plans_page(client, monkeypatch) -> BeautifulSoup:
    _commercial_pages_on(monkeypatch, stripe=True)
    return BeautifulSoup(client.get("/en/pricing").text, "html.parser")


def test_audience_switch_is_a_labelled_segmented_group(plans_page):
    switch = plans_page.find(attrs={"data-component": "segmented"})
    assert switch["role"] == "group" and switch["aria-labelledby"] == "seg-label"
    label = plans_page.find(id="seg-label")
    assert label.get_text() == "Choose audience" and "sr-only" in label["class"]
    assert plans_page.find(id="seg-dev")["aria-pressed"] == "true"
    assert plans_page.find(id="seg-gov")["aria-pressed"] == "false"
    assert not plans_page.find(attrs={"role": "tablist"})


def test_audience_script_switches_aria_pressed_and_panels_only():
    """The segmented look follows aria-pressed: the script never restyles. Its
    only class changes are the two panels' `hidden`, whatever the quotes."""
    code = SEGMENT_JS.read_text(encoding="utf-8")
    assert re.findall(r"classList\.(\w+)\(\s*['\"]([^'\"]+)['\"]", code) == [
        ("toggle", "hidden"),
        ("toggle", "hidden"),
    ]
    assert code.count("classList.") == 2 and "className" not in code
    assert code.count('setAttribute("aria-pressed"') == 2


@pytest.mark.parametrize(
    "path,stripe",
    [
        ("/en/pricing", False),
        ("/en/pricing", True),
        ("/de/pricing", True),
        ("/en/enterprise", False),
    ],
    ids=["pricing-free", "pricing-plans", "pricing-plans-de", "enterprise"],
)
def test_commercial_pages_carry_no_inline_code(client, monkeypatch, path, stripe):
    """CSP: nothing inline in the content these pages build — no event-handler
    attribute, no style attribute, no <script> (pricing loads its two scripts
    by src after </main>)."""
    _commercial_pages_on(monkeypatch, stripe=stripe)
    main = BeautifulSoup(client.get(path).text, "html.parser").find("main")
    handlers = [
        f"{el.name}[{attr}]"
        for el in main.find_all(True)
        for attr in el.attrs
        if attr.startswith("on")
    ]
    assert not handlers, handlers
    assert not main.find_all(style=True)
    assert not main.find_all("script")


def test_plan_cards_are_cards_with_shared_buttons(plans_page):
    cards = plans_page.select('#panel-dev [data-component="card"]')
    assert len(cards) == 3
    pro = cards[1]
    assert "border-brand" in pro["class"]
    assert pro.find("span", string="Most popular")
    for button_id, variant in (("pro-btn", "primary"), ("business-btn", "secondary")):
        button = plans_page.find(id=button_id)
        assert button["data-component"] == "button" and button["data-variant"] == variant
        assert button.has_attr("disabled")
    waivers = plans_page.select("input.withdrawal-waiver")
    assert [w["data-target"] for w in waivers] == ["pro-btn", "business-btn"]
