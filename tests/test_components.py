# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the Jinja macro component library at app/templates/_components/.

Discipline: assert structural invariants (data-component, role, aria-*),
required HTML elements (correct tag, type), and **individual token
classes** — not whole class strings, which break on any class reorder.
See app/templates/_components/README.md § "Test discipline".

Each Tier-1 macro gets at least:
1. A "happy-path" rendering that confirms shape + tokens.
2. A variant test (e.g., disabled, brand border) that confirms
   conditional class branches make it into the output.
3. Where applicable, an a11y assertion (aria-disabled, aria-label, …).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader, select_autoescape

_TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "templates"


@pytest.fixture(scope="module")
def env() -> Environment:
    """Module-level Jinja environment rooted at app/templates so macros
    can resolve their imports (``{% import "_components/..." %}``)."""
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES)),
        autoescape=select_autoescape(["html"]),
    )


def _render(env: Environment, source: str) -> BeautifulSoup:
    """Render *source* against *env* and parse with html.parser."""
    return BeautifulSoup(env.from_string(source).render(), "html.parser")


# ── page ───────────────────────────────────────────────────────────────────────


def test_page_renders_main_with_max_w_and_section_y(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/page.html" as page %}'
        "{% call page.page(title='Hello') %}<p>body</p>{% endcall %}",
    )
    main = soup.find("main")
    assert main is not None
    assert main["data-component"] == "page"
    classes = main["class"]
    assert "max-w-page" in classes
    assert "space-y-section-y" in classes
    h1 = soup.find("h1")
    assert h1 is not None
    assert "text-h-page" in h1["class"]
    assert h1.get_text(strip=True) == "Hello"
    assert soup.find("p", string="body") is not None


def test_page_prose_narrow_uses_narrow_max_width(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/page.html" as page %}'
        "{% call page.page(max_w='prose-narrow') %}body{% endcall %}",
    )
    main = soup.find("main")
    assert "max-w-prose-narrow" in main["class"]
    assert "max-w-page" not in main["class"]


# ── section ────────────────────────────────────────────────────────────────────


def test_section_padded_renders_card_surface_classes(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/section.html" as section %}'
        "{% call section.section(title='Why') %}<p>body</p>{% endcall %}",
    )
    s = soup.find("section")
    assert s is not None
    assert s["data-component"] == "section"
    classes = s["class"]
    assert "bg-surface-raised" in classes
    assert "border" in classes
    assert "border-hairline" in classes
    assert "rounded-card" in classes
    h2 = soup.find("h2")
    assert "text-h-sect" in h2["class"]
    assert h2.get_text(strip=True) == "Why"


def test_section_unpadded_drops_card_surface(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/section.html" as section %}'
        "{% call section.section(padded=False) %}body{% endcall %}",
    )
    s = soup.find("section")
    assert "bg-surface-raised" not in s["class"]
    assert "border-hairline" not in s["class"]


def test_section_eyebrow_renders_when_set(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/section.html" as section %}'
        "{% call section.section(eyebrow='Step 1') %}body{% endcall %}",
    )
    eyebrow = soup.find("p")
    assert eyebrow is not None
    assert "text-eyebrow" in eyebrow["class"]
    assert "uppercase" in eyebrow["class"]


# ── card ───────────────────────────────────────────────────────────────────────


def test_card_default_uses_hairline_border(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/card.html" as card %}'
        "{% call card.card() %}<p>body</p>{% endcall %}",
    )
    div = soup.find("div", attrs={"data-component": "card"})
    assert div is not None
    classes = div["class"]
    assert "rounded-card" in classes
    assert "border-hairline" in classes
    assert "p-card-pad-md" in classes


def test_card_brand_border_uses_brand_color(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/card.html" as card %}'
        "{% call card.card(border='brand') %}body{% endcall %}",
    )
    div = soup.find("div", attrs={"data-component": "card"})
    assert "border-brand" in div["class"]
    assert "border-2" in div["class"]
    assert "border-hairline" not in div["class"]


def test_card_padded_lg_uses_large_padding(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/card.html" as card %}'
        "{% call card.card(padded='lg') %}body{% endcall %}",
    )
    div = soup.find("div", attrs={"data-component": "card"})
    assert "p-card-pad-lg" in div["class"]


# ── button ─────────────────────────────────────────────────────────────────────


def test_button_primary_renders_button_element(env: Environment) -> None:
    soup = _render(
        env,
        "{% import \"_components/button.html\" as btn %}{{ btn.button('Save') }}",
    )
    b = soup.find("button")
    assert b is not None
    assert b["type"] == "button"
    assert b["data-component"] == "button"
    assert b["data-variant"] == "primary"
    assert b.get_text(strip=True) == "Save"
    classes = b["class"]
    assert "bg-brand" in classes
    assert "text-white" in classes


def test_button_with_href_renders_anchor(env: Environment) -> None:
    soup = _render(
        env,
        "{% import \"_components/button.html\" as btn %}{{ btn.button('Go', href='/somewhere') }}",
    )
    a = soup.find("a")
    assert a is not None
    assert a["href"] == "/somewhere"
    assert a["data-component"] == "button"


def test_button_disabled_renders_aria_and_attribute(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/button.html" as btn %}'
        "{{ btn.button('Coming soon', disabled=True) }}",
    )
    b = soup.find("button")
    assert b.has_attr("disabled")
    assert b["aria-disabled"] == "true"
    assert "cursor-not-allowed" in b["class"]
    assert "bg-brand" not in b["class"]  # primary tone replaced


def test_button_secondary_uses_outline(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/button.html" as btn %}'
        "{{ btn.button('Cancel', variant='secondary') }}",
    )
    b = soup.find("button")
    assert b["data-variant"] == "secondary"
    assert "border" in b["class"]
    assert "border-hairline" in b["class"]
    assert "bg-brand" not in b["class"]


def test_button_size_lg_uses_large_padding(env: Environment) -> None:
    soup = _render(
        env,
        "{% import \"_components/button.html\" as btn %}{{ btn.button('Big', size='lg') }}",
    )
    b = soup.find("button")
    assert b["data-size"] == "lg"
    assert "px-7" in b["class"]
    assert "py-3.5" in b["class"]


# ── eyebrow ────────────────────────────────────────────────────────────────────


def test_eyebrow_default_uses_ink_faint(env: Environment) -> None:
    soup = _render(
        env,
        "{% import \"_components/eyebrow.html\" as eyebrow %}{{ eyebrow.eyebrow('Section A') }}",
    )
    p = soup.find("p", attrs={"data-component": "eyebrow"})
    assert p is not None
    assert "text-eyebrow" in p["class"]
    assert "uppercase" in p["class"]
    assert "text-ink-faint" in p["class"]
    assert p.get_text(strip=True) == "Section A"


def test_eyebrow_brand_color(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/eyebrow.html" as eyebrow %}'
        "{{ eyebrow.eyebrow('Featured', color='brand') }}",
    )
    p = soup.find("p", attrs={"data-component": "eyebrow"})
    assert "text-brand" in p["class"]
    assert "text-ink-faint" not in p["class"]


# ── text_input ─────────────────────────────────────────────────────────────────


def test_text_input_renders_input_with_token_classes(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/text_input.html" as ti %}'
        "{{ ti.text_input('email', type='email', label='Email') }}",
    )
    wrapper = soup.find("div", attrs={"data-component": "text_input"})
    assert wrapper is not None
    label = wrapper.find("label")
    assert label is not None
    assert label["for"] == "email"
    inp = wrapper.find("input")
    assert inp["name"] == "email"
    assert inp["type"] == "email"
    assert inp["id"] == "email"
    classes = inp["class"]
    assert "bg-surface-sunken" in classes
    assert "border-hairline" in classes
    assert "rounded-control" in classes


def test_text_input_required_renders_required_attribute(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/text_input.html" as ti %}'
        "{{ ti.text_input('pw', type='password', required=True) }}",
    )
    inp = soup.find("input")
    assert inp.has_attr("required")


def test_text_input_help_text_rendered(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/text_input.html" as ti %}'
        "{{ ti.text_input('email', help='We never share this.') }}",
    )
    helper = soup.find_all("p")
    assert any("never share" in p.get_text() for p in helper)


def test_text_input_value_pre_filled(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/text_input.html" as ti %}'
        "{{ ti.text_input('email', value='alice@example.com') }}",
    )
    inp = soup.find("input")
    assert inp["value"] == "alice@example.com"
