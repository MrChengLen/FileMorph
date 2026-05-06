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

(Or grab them all via the re-export — see `_components/ui.html`.)

Wrapping macros use Jinja's `{% call %}` / `{% endcall %}` form so the
caller's body is yielded by `{{ caller() }}` inside the macro. Simple
macros are just function-like calls.

## Inventory

### Tier 1 — Chrome (every page uses these)

| Macro | File | Wrap | Notes |
|---|---|---|---|
| `page.page(title, max_w='page', center=False)` | `page.html` | `{% call %}` | Wraps `<main>` with max-width, center, and section-y rhythm |
| `section.section(title=None, eyebrow=None, padded=True)` | `section.html` | `{% call %}` | Semantic `<section>` with optional eyebrow + h2; body via `{{ caller() }}` |
| `card.card(border='default', padded='md')` | `card.html` | `{% call %}` | Surface card with hairline border + radius-card + padding |
| `button.button(label, href=None, variant='primary', size='md', disabled=False, type='button', id=None)` | `button.html` | simple | Variants: primary / secondary / ghost. Sizes: sm / md / lg |
| `eyebrow.eyebrow(text, color='gray')` | `eyebrow.html` | simple | Small all-caps tracking-wide label above headings |
| `text_input.text_input(name, type='text', label=None, placeholder='', autocomplete=None, required=False, value='', id=None)` | `text_input.html` | simple | Form input with optional label. Used in auth + cockpit + index |

### Tier 2 — Repeated patterns (≥3 sites)

| Macro | File | Notes |
|---|---|---|
| `check_list.check_list(items)` | `check_list.html` | items = `[{text, included=True, em=False}]`. ✓ for included, ✗ for not |
| `tier_card.tier_card(name, price, period, blurb, features, cta_label, cta_href, highlighted=False, disabled=False, badge=None)` | `tier_card.html` | The pricing-tier card |

### Tier 3 — Admin family (cockpit + future admin pages)

| Macro | File | Notes |
|---|---|---|
| `metric_card.metric_card(id, label, with_sparkline=False, with_extra=False)` | `admin/metric_card.html` | Single-stat dashboard tile |
| `skeleton_card.skeleton_card(rows=3)` | `admin/skeleton_card.html` | Loading-state placeholder |
| `data_table.data_table(id, columns, with_pagination=True)` | `admin/data_table.html` | Wrapping macro — body via `{{ caller() }}` for `<tbody>` |
| `filter_bar.filter_bar(search_id, selects=[…])` | `admin/filter_bar.html` | Search input + dropdowns row |
| `pagination.pagination(prev_id, next_id, range_id)` | `admin/pagination.html` | Prev / range / next pager |
| `modal.modal(id, title, size='md')` | `admin/modal.html` | Wrapping macro — body via `{{ caller() }}` |

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
- Variant behaviour: `disabled=True` produces `aria-disabled="true"` and
  the `disabled` attribute

The JSON-LD byte-snapshot lives in `tests/test_seo_foundation.py` — do
not duplicate it here.

## Out of scope for this layer

- `app/templates/emails/*.html` — different rendering target (SMTP, must
  use inline `style=""` for Outlook/Gmail compat). Reserve `_components/email/`
  namespace for a future sprint.
