# SPDX-License-Identifier: AGPL-3.0-or-later
"""Layout standards of the templates (UI frame, 2026-11).

One page frame: the header, every <main> (the page() macro) and the footer
share max-w-page and the 16 / 24 / 32 px gutters, so their edges line up on
every screen, and the body is a flex column that keeps the footer at the
bottom of a short page. These checks keep the pages from drifting back:

1. Every <main> comes from _components/page.html; no page builds its own.
2. No page is sized to, or centred in, the screen height (min-h-screen,
   min-h-full): a centred page jumps when its content grows, and the footer
   ends up in the middle of a tall screen.
3. Templates already moved onto the design tokens stay on them: no raw
   gray-* colours, no rounded-sm/md/lg/xl/2xl/3xl, no arbitrary text sizes.
   TOKEN_FILES grows as templates move onto the tokens, until it covers
   every template.
4. Footer links stay big enough to tap: 44-px rows on a phone, 24 px from
   640 px (WCAG 2.2 SC 2.5.8).

Each pattern has a self-test, so a broken regex cannot pass silently.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

TEMPLATES = Path(__file__).resolve().parent.parent / "app" / "templates"
PAGE_MACRO = TEMPLATES / "_components" / "page.html"

_COMMENTS = re.compile(r"\{#.*?#\}|<!--.*?-->", re.DOTALL)
_MAIN_TAG = re.compile(r"<main[\s>]")
# min-h-screen / -full / -dvh / -svh / -lvh / -[…vh], h-screen / -dvh …; h-full and
# max-h-screen stay allowed (equal-height cards, scroll boxes).
_SCREEN_HEIGHT = re.compile(
    r"(?<![\w-])(?:[^\s:\"']+:)*"
    r"(?:min-h-(?:screen|full|[sld]vh|\[[^\]]*vh[^\]]*\])|h-(?:screen|[sld]vh))(?![\w-])"
)
_RAW_GRAY = re.compile(
    r"(?<![\w-])(?:[^\s:\"']+:)*"
    r"(?:text|bg|border(?:-[trblxyse])?|ring(?:-offset)?|outline|divide|placeholder|from|via|to"
    r"|fill|stroke|shadow|accent|caret|decoration)"
    r"-(?:gray|slate|zinc|neutral|stone)-\d{2,3}(?:/\d+)?(?![\w-])"
)
# Any rounded-* that is not one of the three tokens (card, control, pill),
# bare `rounded` and `rounded-full` included.
_RAW_RADIUS = re.compile(
    r"(?<![\w-])(?:[^\s:\"']+:)*rounded(?:-[trblse]{1,2})?"
    r"(?:-(?:none|sm|md|lg|xl|2xl|3xl|full)|-\[[^\]]+\])?(?![\w-])"
)
_ARBITRARY_TEXT = re.compile(r"(?<![\w-])(?:[a-z0-9]+:)*text-\[[^\]]+\]")

# Templates on the design tokens: the page shell, the component macros, the
# cookie bar and the tool pages (the shared tool layout, the three tool cards
# and what they include). Add a template here once it is moved onto the tokens.
TOKEN_FILES = [
    "base.html",
    "partials/cookie_notice.html",
    "layouts/tool_page.html",
    "compress.html",
    "convert_pair.html",
    "pdf_tool.html",
    "video_to_gif.html",
    "video_to_mp3.html",
    "redact.html",
    "device_check.html",
    "partials/convert_tool.html",
    "partials/pdf_tool.html",
    "partials/redact_tool.html",
    "partials/quick_actions.html",
    "partials/breadcrumb.html",
    "partials/location_hint.html",
    # The text pages (UI frame package 3a).
    "security.html",
    "privacy.html",
    "terms.html",
    "impressum.html",
    "contact.html",
    # Pricing and the Compliance Edition page (package 3b).
    "pricing.html",
    "enterprise.html",
    "partials/hosting_note.html",
    *sorted(
        p.relative_to(TEMPLATES).as_posix() for p in (TEMPLATES / "_components").glob("*.html")
    ),
]

# The scripts that build or restyle markup on those pages follow the same
# rules for the classes they set (app.js: file rows, batch summary; the PDF and
# redact scripts: drag state, findings rows; contact.js: the status box;
# pricing-segment.js: the audience panels).
SCRIPTS = TEMPLATES.parent / "static" / "js"
TOKEN_SCRIPTS = ["app.js", "pdf-tools.js", "redact.js", "contact.js", "pricing-segment.js"]
_JS_COMMENTS = re.compile(r"/\*.*?\*/|//[^\n]*", re.DOTALL)


def _code(path: Path) -> str:
    """The template without its Jinja and HTML comments (they may mention <main>)."""
    return _COMMENTS.sub("", path.read_text(encoding="utf-8"))


def _token_violations(code: str) -> dict[str, list[str]]:
    found = {
        "raw gray (use ink-*, surface-*, hairline-*)": _RAW_GRAY.findall(code),
        "raw radius (use rounded-card / rounded-control / rounded-pill)": _RAW_RADIUS.findall(code),
        "arbitrary text size (use the type scale)": _ARBITRARY_TEXT.findall(code),
    }
    return {rule: hits for rule, hits in found.items() if hits}


def _pages() -> list[Path]:
    # Email templates render for mail clients (inline styles), not for the site.
    return sorted(p for p in TEMPLATES.rglob("*.html") if "emails" not in p.parts)


def test_every_main_comes_from_the_page_macro():
    offenders = [
        p.relative_to(TEMPLATES).as_posix()
        for p in _pages()
        if p != PAGE_MACRO and _MAIN_TAG.search(_code(p))
    ]
    assert not offenders, f"hand-built <main>, use _components/page.html: {offenders}"


_BODY_HEIGHT = {"min-h-screen", "supports-[min-height:100dvh]:min-h-dvh"}


def test_no_page_is_sized_to_the_screen_height():
    # The one exception: base.html's <body>, the screen-high flex column.
    offenders = {}
    for p in _pages():
        hits = {m.group(0) for m in _SCREEN_HEIGHT.finditer(_code(p))}
        if p == TEMPLATES / "base.html":
            hits -= _BODY_HEIGHT
        if hits:
            offenders[p.relative_to(TEMPLATES).as_posix()] = sorted(hits)
    assert not offenders, (
        f"screen-height layout (the body's flex column places the footer): {offenders}"
    )


@pytest.mark.parametrize("name", TOKEN_FILES)
def test_token_files_use_only_design_tokens(name):
    found = _token_violations(_code(TEMPLATES / name))
    assert not found, f"{name}: {found}"


@pytest.mark.parametrize("name", TOKEN_SCRIPTS)
def test_tool_scripts_set_only_design_tokens(name):
    found = _token_violations(_JS_COMMENTS.sub("", (SCRIPTS / name).read_text(encoding="utf-8")))
    assert not found, f"{name}: {found}"


@pytest.mark.parametrize("name", TOKEN_SCRIPTS)
def test_tool_scripts_never_open_a_browser_dialog(name):
    """Missing input is said in the tool's own error box (role="alert"), not in
    alert()/confirm(): one place for every message, the way the PDF tools did."""
    code = _JS_COMMENTS.sub("", (SCRIPTS / name).read_text(encoding="utf-8"))
    assert not re.search(r"(?<![\w.])(?:window\.)?(?:alert|confirm)\(", code), name


def test_every_tone_a_script_sets_exists_in_the_notice():
    """app.js sets data-tone on the batch summary; each value needs its styles
    in _components/notice.html, or the box would lose its tint."""
    js = _JS_COMMENTS.sub("", (SCRIPTS / "app.js").read_text(encoding="utf-8"))
    tones = set()
    for line in re.findall(r"dataset\.tone\s*=([^;]*);", js):
        tones |= set(re.findall(r"'(\w+)'", line))
    assert tones, "app.js no longer sets a notice tone"
    notice = (TEMPLATES / "_components" / "notice.html").read_text(encoding="utf-8")
    missing = [t for t in sorted(tones) if f"data-[tone={t}]:bg-tone-{t}-tint" not in notice]
    assert not missing, f"tones without notice styles: {missing}"


def test_js_comments_are_not_mistaken_for_classes():
    code = "/* was bg-gray-800 */ el.className = 'bg-surface-sunken'; // not rounded-lg\n"
    assert not _token_violations(_JS_COMMENTS.sub("", code))
    assert _token_violations(_JS_COMMENTS.sub("", "el.className = 'rounded text-gray-200';"))


@pytest.mark.parametrize(
    ("pattern", "bad", "good"),
    [
        (_MAIN_TAG, '<main class="max-w-2xl">', "{% call up.page(max_w='prose-narrow') %}"),
        (_SCREEN_HEIGHT, 'class="min-h-screen flex"', 'class="min-h-11 h-full"'),
        (_SCREEN_HEIGHT, 'class="sm:min-h-full"', 'class="max-h-screen overflow-y-auto"'),
        (_SCREEN_HEIGHT, 'class="min-h-dvh items-center"', 'class="min-h-0"'),
        (_SCREEN_HEIGHT, 'class="h-screen"', 'class="h-10"'),
        (_SCREEN_HEIGHT, 'class="min-h-[100vh]"', 'class="min-h-[2rem]"'),
        (_RAW_GRAY, 'class="hover:text-gray-300"', 'class="hover:text-ink-soft"'),
        (_RAW_GRAY, 'class="border-gray-800/60"', 'class="border-hairline/60"'),
        (_RAW_GRAY, 'class="border-t-gray-800"', 'class="border-t border-hairline"'),
        (_RAW_GRAY, 'class="ring-offset-slate-900"', 'class="ring-brand"'),
        (_RAW_RADIUS, 'class="rounded-xl"', 'class="rounded-card"'),
        (_RAW_RADIUS, 'class="rounded-t-lg"', 'class="rounded-control rounded-pill"'),
        (_RAW_RADIUS, 'class="focus:rounded"', 'class="focus:rounded-control"'),
        (_RAW_RADIUS, 'class="rounded-full"', 'class="after:rounded-card"'),
        (_ARBITRARY_TEXT, 'class="text-[10px]"', 'class="text-xs text-ink-faint"'),
    ],
)
def test_patterns_catch_what_they_guard(pattern, bad, good):
    assert pattern.search(bad), f"{pattern.pattern} misses {bad!r}"
    assert not pattern.search(good), f"{pattern.pattern} flags {good!r}"


def test_comments_are_not_mistaken_for_markup(tmp_path):
    sample = tmp_path / "sample.html"
    sample.write_text("{# right before each page's <main> #}<!-- <main> -->", encoding="utf-8")
    assert not _MAIN_TAG.search(_code(sample))


_FRAME = {"mx-auto", "w-full", "max-w-page", "px-4", "sm:px-6", "lg:px-8"}


@pytest.mark.parametrize(
    "path", ["/en/", "/en/compress", "/en/privacy", "/en/tools", "/en/no-such-page"]
)
def test_header_main_and_footer_share_the_page_frame(client, path):
    soup = BeautifulSoup(client.get(path).text, "html.parser")
    body = set(soup.find("body")["class"])
    # min-h-dvh behind @supports: a plain min-h-dvh sorts before min-h-screen in
    # Tailwind's output and would never win, so phones would keep 100vh.
    assert {"flex", "flex-col"} | _BODY_HEIGHT <= body
    header_row = soup.find("nav").find("div", recursive=False)
    footer = soup.find("footer")
    assert "mt-auto" in footer["class"], "the footer sits at the bottom of a short page"
    for name, element in (
        ("header", header_row),
        ("main", soup.find("main")),
        ("cookie bar", soup.find(id="cookie-notice").find("div", recursive=False)),
        ("footer", footer.find("div", recursive=False)),
    ):
        assert _FRAME <= set(element["class"]), f"{path}: {name} is off the page frame"


def test_footer_links_are_big_enough_to_tap(client):
    footer = BeautifulSoup(client.get("/en/").text, "html.parser").find("footer")
    links = footer.find_all("a")
    assert len(links) > 20
    small = [a.get_text(strip=True) for a in links if not {"py-3", "sm:py-0.5"} <= set(a["class"])]
    assert not small, f"footer links without 44-px rows on a phone: {small}"


def test_cookie_bar_stays_in_the_flow_and_never_covers_the_footer(client):
    """Sticky, not fixed: at the end of the page the bar sits in its own place
    above the footer, so it cannot cover the legal links (it did on 320 and
    390 px phones). Right before the footer, "Got it" comes before the footer
    links in the tab order."""
    html = client.get("/en/").text
    assert html.index('id="cookie-notice"') < html.index("<footer")
    bar = BeautifulSoup(html, "html.parser").find(id="cookie-notice")
    assert "sticky" in bar["class"] and "fixed" not in bar["class"]
    button = bar.find(id="cookie-notice-dismiss")
    assert button["data-component"] == "button" and button["type"] == "button"
