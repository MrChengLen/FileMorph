# SPDX-License-Identifier: AGPL-3.0-or-later
"""The menu button of the navigation bar (2026-10-29).

docs-internal/navigation-suche-konzept-2026-10.md, item 3. Below 1024 px the
links sit behind a button that says "Menu" in words, is 44 px high and tells
screen readers whether the menu is open (aria-expanded, aria-controls). The
full bar starts at 1024 px (lg:), because at 768 px its items wrapped onto two
lines. nav.js keeps aria-expanded in step and closes the menu on Escape. There
is no JS runner in the repo, so its guards are pinned on its source.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

_NAV_JS = Path(__file__).resolve().parent.parent / "app" / "static" / "js" / "nav.js"


@pytest.mark.parametrize(("prefix", "label"), [("/en", "Menu"), ("/de", "Menü")])
def test_menu_button_says_menu_and_is_big_enough(client, prefix, label):
    soup = BeautifulSoup(client.get(f"{prefix}/").text, "html.parser")
    button = soup.find(id="nav-toggle")
    assert button.name == "button" and button["type"] == "button"
    assert button.get_text(strip=True) == label
    assert not button.has_attr("aria-label"), "the visible word is its name"
    assert button["aria-expanded"] == "false"
    assert button["aria-controls"] == "nav-mobile-menu"
    assert soup.find(id=button["aria-controls"]) is not None
    assert "min-h-11" in button["class"], "44 px, for a thumb"


def test_full_bar_starts_at_1024_px(client):
    soup = BeautifulSoup(client.get("/en/").text, "html.parser")
    assert "lg:hidden" in soup.find(id="nav-toggle")["class"]
    assert {"hidden", "lg:flex"} <= set(soup.find(id="nav-menu")["class"])
    assert {"hidden", "lg:hidden"} <= set(soup.find(id="nav-mobile-menu")["class"])
    header = str(soup.find("nav")) + str(soup.find(id="nav-mobile-menu"))
    assert "md:" not in header, "one breakpoint for the bar, or it wraps at 768 px"


def test_nav_js_keeps_aria_expanded_in_step_and_closes_on_escape():
    source = _NAV_JS.read_text(encoding="utf-8")
    assert "toggle.setAttribute('aria-expanded', String(open))" in source
    assert "menu.classList.toggle('hidden', !open)" in source
    assert "e.key === 'Escape'" in source and "toggle.focus()" in source
    # Only an Escape from the nav: the /formats search clears its field with it.
    assert "menu.contains(e.target)" in source
