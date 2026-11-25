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
3. Where applicable, an a11y assertion (the disabled attribute, aria-label, …).
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


def test_page_renders_main_as_the_page_frame(env: Environment) -> None:
    """<main> is the page frame: the width and gutters of the header and footer
    (base.html), growing to fill the screen, never centred vertically."""
    soup = _render(
        env,
        '{% import "_components/page.html" as page %}'
        "{% call page.page(title='Hello') %}<p>body</p>{% endcall %}",
    )
    main = soup.find("main")
    assert main is not None
    assert main["data-component"] == "page"
    classes = main["class"]
    for token in ("max-w-page", "mx-auto", "w-full", "flex-1", "px-4", "sm:px-6", "lg:px-8"):
        assert token in classes, token
    assert "items-center" not in classes and "justify-center" not in classes
    column = main.find("div", recursive=False)
    assert "space-y-section-y" in column["class"]
    h1 = column.find("h1")
    assert h1 is not None
    assert "text-h-page" in h1["class"]
    assert h1.get_text(strip=True) == "Hello"
    assert column.find("p", string="body") is not None


@pytest.mark.parametrize(
    ("max_w", "token"),
    [("wide", "max-w-wide"), ("prose-narrow", "max-w-prose-narrow"), ("form", "max-w-form")],
)
def test_page_column_takes_its_width_inside_the_frame(env: Environment, max_w, token) -> None:
    soup = _render(
        env,
        '{% import "_components/page.html" as page %}'
        "{% call page.page(max_w='" + max_w + "') %}body{% endcall %}",
    )
    main = soup.find("main")
    assert "max-w-page" in main["class"], "the frame stays the same on every page"
    column = main.find("div", recursive=False)
    assert token in column["class"]
    assert "mx-auto" in column["class"]


def test_page_default_column_fills_the_frame(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/page.html" as page %}{% call page.page() %}body{% endcall %}',
    )
    column = soup.find("main").find("div", recursive=False)
    assert not [c for c in column["class"] if c.startswith("max-w-")]


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
    # 16 px on a phone, so nested boxes don't eat a narrow screen; the token from 640 px.
    assert {"p-4", "sm:p-card-pad-md"} <= set(classes)


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
    assert {"p-4", "sm:p-card-pad-lg"} <= set(div["class"])


def test_card_default_has_shadow_token(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/card.html" as card %}{% call card.card() %}body{% endcall %}',
    )
    div = soup.find("div", attrs={"data-component": "card"})
    assert "shadow-card" in div["class"]


def test_card_shadow_false_drops_shadow_token(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/card.html" as card %}'
        "{% call card.card(shadow=False) %}body{% endcall %}",
    )
    div = soup.find("div", attrs={"data-component": "card"})
    assert "shadow-card" not in div["class"]


def test_card_id_attribute_emitted(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/card.html" as card %}'
        "{% call card.card(id='ck-loading') %}body{% endcall %}",
    )
    div = soup.find("div", attrs={"data-component": "card"})
    assert div.get("id") == "ck-loading"


def test_card_hidden_initial_state_renders_hidden_class(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/card.html" as card %}'
        "{% call card.card(hidden=True) %}body{% endcall %}",
    )
    div = soup.find("div", attrs={"data-component": "card"})
    assert "hidden" in div["class"]


def test_card_interactive_positions_for_a_stretched_link(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/card.html" as card %}'
        "{% call card.card(interactive=True) %}body{% endcall %}",
    )
    classes = soup.find("div", attrs={"data-component": "card"})["class"]
    assert "relative" in classes
    assert "hover:border-brand" in classes


def test_card_default_is_not_interactive(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/card.html" as card %}{% call card.card() %}body{% endcall %}',
    )
    classes = soup.find("div", attrs={"data-component": "card"})["class"]
    assert "relative" not in classes
    assert "hover:border-brand" not in classes
    assert not soup.find("span")  # no badge


def test_card_badge_sits_on_the_top_edge(env: Environment) -> None:
    """The highlighted plan: a pill on the card's top edge, positioned against
    the card, which gets no hover look (it is not a link)."""
    soup = _render(
        env,
        '{% import "_components/card.html" as card %}'
        "{% call card.card(border='brand', badge='Most popular') %}body{% endcall %}",
    )
    div = soup.find("div", attrs={"data-component": "card"})
    assert {"relative", "border-brand"} <= set(div["class"])
    assert "hover:border-brand" not in div["class"]
    badge = div.find("span")
    assert badge.get_text() == "Most popular"
    assert {"absolute", "-top-3", "rounded-pill", "bg-brand-dark"} <= set(badge["class"])


# ── check_item ─────────────────────────────────────────────────────────────────


def test_check_item_is_a_tick_and_the_call_body(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/check_item.html" as ci %}'
        "<ul>{% call ci.check_item() %}Signed <strong>releases</strong>{% endcall %}</ul>",
    )
    li = soup.find("li", attrs={"data-component": "check-item"})
    tick, text = li.find_all("span", recursive=False)
    assert tick.get_text() == "✓" and tick["aria-hidden"] == "true"
    assert {"shrink-0", "text-tone-ok"} <= set(tick["class"])
    assert "leading-6" not in tick["class"]  # the tick takes the text's line
    assert text.get_text() == "Signed releases" and text.find("strong")


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
    assert "bg-brand-dark" in classes  # white on it: 6.3 : 1 (AA)
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


def test_button_disabled_keeps_its_variant_for_a_script_to_unlock(env: Environment) -> None:
    """A disabled button looks disabled through the disabled: variants alone, so
    a script that sets el.disabled = false (the pricing upgrade buttons, once
    their waiver box is ticked) gets the variant's look back. The native
    attribute is the whole state: no aria-disabled that a script would leave
    behind."""
    soup = _render(
        env,
        '{% import "_components/button.html" as btn %}'
        "{{ btn.button('Upgrade', id='up', disabled=True) }}"
        "{{ btn.button('Go', href='/x', variant='secondary', disabled=True) }}",
    )
    primary, link = soup.find_all("button")
    for b in (primary, link):
        assert b.has_attr("disabled") and not b.has_attr("aria-disabled")
        assert {
            "disabled:cursor-not-allowed",
            "disabled:bg-surface-sunken",
            "disabled:text-ink-muted",
            "disabled:border-hairline",
        } <= set(b["class"])
    assert "bg-brand-dark" in primary["class"]  # the variant stays
    assert not link.has_attr("href")  # a disabled link is a button


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
    assert "bg-brand-dark" not in b["class"]


def test_button_size_lg_uses_large_padding(env: Environment) -> None:
    soup = _render(
        env,
        "{% import \"_components/button.html\" as btn %}{{ btn.button('Big', size='lg') }}",
    )
    b = soup.find("button")
    assert b["data-size"] == "lg"
    assert "px-7" in b["class"]
    assert "py-3.5" in b["class"]


def test_button_full_width_adds_w_full_class(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/button.html" as btn %}'
        "{{ btn.button('Submit', full_width=True) }}",
    )
    b = soup.find("button")
    assert "w-full" in b["class"]


def test_button_default_is_not_full_width(env: Environment) -> None:
    soup = _render(
        env,
        "{% import \"_components/button.html\" as btn %}{{ btn.button('Save') }}",
    )
    b = soup.find("button")
    assert "w-full" not in b["class"]


def test_button_external_link_opens_a_new_tab(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/button.html" as btn %}'
        "{{ btn.button('Guide', href='https://example.org/', external=True) }}"
        "{{ btn.button('Home', href='/') }}",
    )
    external, internal = soup.find_all("a")
    assert external["target"] == "_blank" and external["rel"] == ["noopener"]
    assert not internal.has_attr("target") and not internal.has_attr("rel")


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
    assert "text-brand-light" in p["class"]
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


# ── tool-card components (UI frame package 2) ──────────────────────────────────


def test_notice_carries_its_tone_and_every_tone_style(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/notice.html" as n %}'
        "{% call n.notice(tone='warn', id='w') %}Careful{% endcall %}",
    )
    p = soup.find("p", attrs={"data-component": "notice"})
    assert p["id"] == "w" and p["data-tone"] == "warn"
    assert p.get_text(strip=True) == "Careful"
    classes = set(p["class"])
    # Every tone's tint is present, so a script can switch data-tone later.
    for tone in ("info", "ok", "warn", "err"):
        assert f"data-[tone={tone}]:bg-tone-{tone}-tint" in classes
    assert {"rounded-control", "text-sm", "text-ink"} <= classes


def test_notice_hides_by_class_or_by_attribute(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/notice.html" as n %}'
        "{{ n.notice(id='a', hidden=True) }}"
        "{{ n.notice(id='b', role='status', hidden_attr=True) }}",
    )
    a, b = soup.find(id="a"), soup.find(id="b")
    assert "hidden" in a["class"] and not a.has_attr("hidden")
    assert b.has_attr("hidden") and "hidden" not in b["class"] and b["role"] == "status"


def test_notice_as_div_wraps_an_alert(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/notice.html" as n %}'
        "{% call n.notice(tone='err', tag='div') %}<p id='t' role='alert'></p>{% endcall %}",
    )
    box = soup.find("div", attrs={"data-component": "notice"})
    assert box["data-tone"] == "err" and box.find(id="t")["role"] == "alert"


def test_dropzone_is_one_keyboard_button_with_a_drag_state(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/dropzone.html" as d %}'
        "{% call d.dropzone('dz', 'Drop here', attrs={'data-preset-source': 'jpg'}) %}"
        '<input type="file" class="hidden">{% endcall %}',
    )
    dz = soup.find(id="dz")
    assert dz["data-component"] == "dropzone" and dz["role"] == "button"
    assert dz["tabindex"] == "0" and dz["aria-label"] == "Drop here"
    assert dz["data-preset-source"] == "jpg"
    # The script only sets data-dragging; the field styles itself from it.
    assert {"data-[dragging]:border-brand", "rounded-control", "border-dashed"} <= set(dz["class"])


def test_segmented_state_lives_in_aria_pressed(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/segmented.html" as s %}'
        "{{ s.segmented([{'id': 'a', 'label': 'A', 'pressed': True},"
        " {'id': 'b', 'label': 'B', 'pressed': False, 'data': {'data-mode': 'b'}}], label_id='lbl') }}",
    )
    group = soup.find(attrs={"data-component": "segmented"})
    assert group["role"] == "group" and group["aria-labelledby"] == "lbl"
    a, b = soup.find(id="a"), soup.find(id="b")
    assert a["type"] == "button" and a["aria-pressed"] == "true"
    assert b["aria-pressed"] == "false" and b["data-mode"] == "b"
    # The pressed look comes from the attribute alone: one class list for both.
    assert a["class"] == b["class"]
    assert {"aria-pressed:bg-brand-dark", "min-h-11"} <= set(a["class"])
    # White focus ring: a brand ring vanished on the brand-filled pressed button.
    assert "focus-visible:ring-ink-strong" in a["class"]


def test_page_header_back_link_heading_and_meta(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/page_header.html" as h %}'
        "{% call h.page_header('Terms', '/en/', '← Back') %}Last updated: today{% endcall %}",
    )
    head = soup.find(attrs={"data-component": "page-header"})
    link, title = head.find("a"), head.find("h1")
    assert link["href"] == "/en/" and link.get_text() == "← Back"
    assert "min-h-6" in link["class"]  # a 24 px target
    assert title.get_text() == "Terms" and "text-h-page" in title["class"]
    assert head.find("p").get_text() == "Last updated: today"


def test_page_header_without_meta_has_no_meta_line(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/page_header.html" as h %}'
        "{{ h.page_header('Contact', '/de/', '← Zurück') }}",
    )
    assert soup.find("h1").get_text() == "Contact" and soup.find("p") is None


def test_notice_carries_data_attributes_only(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/notice.html" as n %}'
        "{{ n.notice(id='s', attrs={'data-ok': 'Sent', 'onclick': 'x()'}) }}",
    )
    box = soup.find(id="s")
    assert box["data-ok"] == "Sent" and not box.has_attr("onclick")


@pytest.mark.parametrize(
    ("macro", "call"),
    [
        ("notice", "{{ m.notice(id='t', attrs={KEY: 'v'}) }}"),
        ("dropzone", "{% call m.dropzone('t', 'T', attrs={KEY: 'v'}) %}{% endcall %}"),
        (
            "segmented",
            "{{ m.segmented([{'id': 't', 'label': 'T', 'pressed': True, 'data': {KEY: 'v'}}]) }}",
        ),
    ],
)
def test_extra_attribute_names_cannot_smuggle_attributes(env: Environment, macro, call) -> None:
    # Autoescape guards attribute values, not names: a key with spaces or "="
    # would otherwise add attributes of its own.
    key = "'data-x onfocus=alert(1) autofocus'"
    soup = _render(
        env, f'{{% import "_components/{macro}.html" as m %}}' + call.replace("KEY", key)
    )
    element = soup.find(id="t")
    assert element is not None
    assert not {"onfocus", "autofocus", "data-x"} & set(element.attrs)


def test_notice_element_is_only_p_or_div(env: Environment) -> None:
    # The element name is not autoescaped, so the macro allows only p and div.
    soup = _render(
        env,
        '{% import "_components/notice.html" as n %}'
        "{{ n.notice(id='x', tag='img src=x onerror=alert(1)') }}",
    )
    assert soup.find("img") is None and soup.find(id="x").name == "p"


def test_extra_attributes_are_data_attributes_only(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/dropzone.html" as d %}'
        '{% import "_components/segmented.html" as s %}'
        "{% call d.dropzone('z', 'Z', attrs={'data-ok': '1', 'onclick': 'x()'}) %}{% endcall %}"
        "{{ s.segmented([{'id': 'b', 'label': 'B', 'pressed': False,"
        " 'data': {'data-mode': 'm', 'onfocus': 'x()'}}]) }}",
    )
    zone, button = soup.find(id="z"), soup.find(id="b")
    assert zone["data-ok"] == "1" and not zone.has_attr("onclick")
    assert button["data-mode"] == "m" and not button.has_attr("onfocus")


def test_segmented_without_a_label_is_no_group(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/segmented.html" as s %}'
        "{{ s.segmented([{'id': 'a', 'label': 'A', 'pressed': True}], id='m') }}",
    )
    group = soup.find(id="m")
    assert group["data-component"] == "segmented" and not group.has_attr("role")


def test_dropzone_compact_names_its_step(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/dropzone.html" as d %}'
        "{% call d.dropzone('z2', 'Second', describedby='step-2', compact=True) %}x{% endcall %}",
    )
    zone = soup.find(id="z2")
    assert zone["aria-describedby"] == "step-2"
    assert "p-4" in zone["class"] and "sm:p-card-pad-md" not in zone["class"]


def test_chip_with_its_own_body(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/chip.html" as c %}'
        "{% call c.chip('/t', block=True) %}<svg></svg>Tool{% endcall %}",
    )
    a = soup.find("a", attrs={"data-component": "chip"})
    assert a.find("svg") is not None and a.get_text() == "Tool"
    assert {"flex", "h-full"} <= set(a["class"]) and "text-ink" in a["class"]


def test_chip_is_a_44px_link(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/chip.html" as c %}'
        "{{ c.chip('/x', 'X', accent=True, external=True) }}",
    )
    a = soup.find("a", attrs={"data-component": "chip"})
    assert a["href"] == "/x" and a.get_text() == "X"
    assert {"min-h-11", "rounded-control", "text-brand-light"} <= set(a["class"])
    assert a["target"] == "_blank" and a["rel"] == ["noopener"]


def test_button_success_download_link_with_its_own_body(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/button.html" as b %}'
        "{% call b.button(href='#', variant='success', id='dl', download=True) %}"
        "<span id='lbl'>Get</span>{% endcall %}",
    )
    a = soup.find(id="dl")
    assert a.name == "a" and a.has_attr("download")
    assert {"bg-emerald-700", "hover:bg-emerald-800"} <= set(a["class"])
    assert a.find(id="lbl").get_text() == "Get"


def test_button_hidden_and_the_look_of_a_script_disabled_button(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/button.html" as b %}{{ b.button("Go", id="go", hidden=True) }}',
    )
    btn = soup.find(id="go")
    assert "hidden" in btn["class"]
    # A script that sets el.disabled gets the muted look without a class change.
    assert {"disabled:bg-surface-sunken", "disabled:cursor-not-allowed"} <= set(btn["class"])


def test_section_divided_has_a_rule_instead_of_a_box(env: Environment) -> None:
    soup = _render(
        env,
        '{% import "_components/section.html" as s %}'
        "{% call s.section(title='T', divided=True) %}<p>x</p>{% endcall %}",
    )
    sec = soup.find("section", attrs={"data-component": "section"})
    classes = set(sec["class"])
    assert {"border-t", "border-hairline", "text-base"} <= classes
    assert not classes & {"rounded-card", "bg-surface-raised"}
    assert sec.find("h2").get_text() == "T"
