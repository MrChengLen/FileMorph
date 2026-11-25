# Components — Jinja Macro Library

Component layer for FileMorph templates. Every repeated visual primitive
lives here as a Jinja macro; pages compose macros instead of duplicating
markup.

## How to use

At the top of any page template:

```jinja
{% import "_components/page.html" as page %}
{% import "_components/section.html" as section %}
{% import "_components/card.html" as card %}
{% import "_components/button.html" as button %}
{% import "_components/eyebrow.html" as eyebrow %}
```

Wrapping macros use Jinja's `{% call %}` / `{% endcall %}` form so the
caller's body is yielded by `{{ caller() }}` inside the macro. Simple
macros are just function-like calls.

## Inventory

### Tier 1 — Chrome (every page uses these)

| Macro | File | Wrap | Notes |
|---|---|---|---|
| `page.page(title=None, max_w='page', center=False)` | `page.html` | `{% call %}` | The one `<main>` of every page (CI-gated, `tests/test_layout_standards.py`). `<main>` is the page frame — `max-w-page` and the 16 / 24 / 32 px gutters, the same as the header and footer in `base.html` — and fills the screen so the footer sits at the bottom. `max_w` picks the content column inside it: `page` (whole frame), `wide` (56rem), `prose-narrow` (42rem), `form` (28rem). Never centred vertically |
| `section.section(title=None, eyebrow=None, padded=True, divided=False)` | `section.html` | `{% call %}` | Semantic `<section>` with optional eyebrow + h2; body via `{{ caller() }}`. `divided=True`: the reading section under a tool — no box, a hairline above, 18 px heading, 16 px text |
| `card.card(border='default', padded='md', shadow=True, id=None, hidden=False, interactive=False, badge=None)` | `card.html` | `{% call %}` | Surface card with hairline border + radius-card + padding (16 px on a phone). `interactive=True`: the whole card is one link (a stretched `<a>` in its heading). `badge`: a pill label on the top edge (the highlighted plan, with `border='brand'`) |
| `button.button(label=None, href=None, variant='primary', size='md', disabled=False, type='button', id=None, full_width=False, hidden=False, download=False, external=False)` | `button.html` | simple or `{% call %}` | Variants: primary / secondary / ghost / danger / success. Sizes: sm / md / lg. `full_width` stretches it to its container; called with `{% call %}`, the body (icon + label) replaces `label`. `disabled=True` renders the `disabled` attribute and keeps the variant: the muted look comes from the `disabled:` variants, so a script that enables the button later gets its look back. `external` opens a link in a new tab |
| `check_item.check_item()` | `check_item.html` | `{% call %}` | One line of a ✓ list (plan features, "what you can verify"): green tick, the call body as text. The caller owns the `<ul>`, its spacing and text size |
| `data_attrs.data_attrs(attrs)` | `data_attrs.html` | simple | Extra `data-*` attributes from a dict for `dropzone`, `segmented`, `notice`: plain `data-` keys only (autoescape guards values, not names) |
| `page_header.page_header(title, back_href, back_label)` | `page_header.html` | simple or `{% call %}` | Head of a text page: 24 px back link, `text-h-page` heading, the call body as a small meta line (date, legal basis) |
| `notice.notice(tone='info', id=None, tag='p', role=None, hidden=False, hidden_attr=False, attrs=None)` | `notice.html` | simple or `{% call %}` | The one message box: hint, warning, success, error. Tone via `data-tone` (`info` / `ok` / `warn` / `err`), so a script can switch it; the icon is CSS, so a script may replace the text |
| `dropzone.dropzone(id, label, describedby=None, compact=False, attrs=None)` | `dropzone.html` | `{% call %}` | The file drop field; the script sets `data-dragging` while a file is dragged over it |
| `segmented.segmented(options, id=None, label_id=None)` | `segmented.html` | simple | A mode switch; the look follows `aria-pressed` alone. 44 px high on a phone, white focus ring |
| `chip.chip(href, label=None, accent=False, external=False, block=False)` | `chip.html` | simple or `{% call %}` | A 44-px link button for a next step (related tools, quick actions) |
| `eyebrow.eyebrow(text, color='gray')` | `eyebrow.html` | simple | Small all-caps tracking-wide label above headings |
| `text_input.text_input(name, type='text', label=None, placeholder='', autocomplete=None, required=False, value='', id=None, help=None)` | `text_input.html` | simple | Form input with optional label and help text. Used in auth + cockpit + index |
| `textarea.textarea(name, label=None, placeholder='', autocomplete=None, required=False, rows=6, id=None, help=None)` | `textarea.html` | simple | Multi-line sibling of `text_input`, same recipe. Used on /contact and /cancel |
| `icon.icon(name)` | `icon.html` | simple | Quick-action icon; `name` is one of `catalog.ICONS` (app/core/catalog.py) |

### Not built (yet)

Earlier versions of this file listed Tier 2 macros (`check_list`, `tier_card`)
and an admin family (`metric_card`, `data_table`, `modal`, …). None of those
files exist: a plan card on /pricing is `card()` + `eyebrow()` + `check_item()`
+ `button()`, and the cockpit carries its own markup. A shared macro gets
built where it replaces real duplicates.

## The dynamic-class rule (CI-gated)

Tailwind's JIT scanner only sees classes that appear as **literal strings**
in the source. Composing class names from Jinja interpolations breaks the
production bundle silently — the class isn't generated and the styling
disappears.

**WRONG** — JIT cannot extract:

```jinja
<div class="border-{{ color }}-500 bg-{{ tone }}-900">
```

**RIGHT** — both branches present as literals:

```jinja
<div class="{% if highlighted %}border-2 border-brand{% else %}border border-hairline{% endif %}">
```

Macro arguments may select between branches but must never be concatenated
into class names. `scripts/check_template_classes.py` greps for
`class="…{{` patterns where the `{{` is not preceded by `{% if %}` and
fails the build. The hook runs in `.pre-commit-config.yaml` and CI.

## Test discipline

Tests for these macros live in `tests/test_components.py`. **Do not assert
on whole class strings** (any class reorder breaks the test). Assert:

- Structural attributes: `data-component`, `role`, `aria-*`
- Required HTML elements: `<button type="button">`, `<input type="text">`, etc.
- Token classes individually: `assert "text-h-sect" in btn["class"]`
- Variant behaviour: `disabled=True` produces the `disabled` attribute and
  keeps the variant's classes next to the `disabled:` variants

The JSON-LD byte-snapshot lives in `tests/test_seo_foundation.py` — do
not duplicate it here.

## Out of scope for this layer

- `app/templates/emails/*.html` — different rendering target (SMTP, must
  use inline `style=""` for Outlook/Gmail compat). Reserve `_components/email/`
  namespace for a future sprint.
