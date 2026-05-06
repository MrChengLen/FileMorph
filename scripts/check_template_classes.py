#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""CI gate: forbid dynamic class-name *concatenation* in Jinja templates.

Tailwind's JIT scanner picks up classes by reading the source file with a
liberal identifier regex. It sees literal strings inside ``class="…"``
attributes and inside ``{% set var = '…literal…' %}`` assignments. So
both of these are FINE:

    class="bg-brand text-white"
    {% set size_cls = 'px-4 py-2 text-sm' %}
    class="{{ base }} {{ size_cls }}"

What is NOT fine is concatenating a Jinja expression *inside* a class
word — the concatenation produces fragments at scan time that aren't
real classes, and the actual class never reaches the production bundle:

    class="border-{{ color }}-500"
    class="text-{{ tone }}"
    class="bg-{{ shade }}-900"

The rule this script enforces:
    Inside any class="…" attribute, every whitespace-separated token
    that contains ``{{`` must be exactly ``{{ … }}`` — never adjacent
    to literal characters that would form a class fragment.

Use ``{% if cond %}foo{% else %}bar{% endif %}`` whenever you need to
choose between literal class strings on a condition.

Usage:
    python scripts/check_template_classes.py

Runs in:
- ``.pre-commit-config.yaml`` (local guard)
- CI workflow ``.github/workflows/ci.yml`` (server-side guard,
  cannot be bypassed via ``--no-verify``)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Match a class="..." attribute (single-line; multiline class strings are
# rare and always look the same after splitting on whitespace).
_CLASS_ATTR = re.compile(r'class="([^"]*)"', re.DOTALL)

# Match a complete Jinja {{ … }} interpolation, including whitespace-
# control variants. The body cannot contain another '{{' or '}}'.
_INTERP_PAT = re.compile(r"\{\{-?\s*[^{}]*?\s*-?\}\}")
# Sentinel that survives whitespace-tokenisation as a single word.
_INTERP_TOKEN = "\x01INTERP\x01"


def _scan_file(path: Path) -> list[str]:
    """Return human-readable error strings for offenses in *path*."""
    errors: list[str] = []
    text = path.read_text(encoding="utf-8")
    for match in _CLASS_ATTR.finditer(text):
        attr_value = match.group(1)
        if "{{" not in attr_value:
            continue
        # If the author has wrapped the dynamic part in {% if %} … {% endif %},
        # accept — every branch is responsible for emitting clean literal
        # class strings.
        if re.search(r"\{%\s*if\b", attr_value):
            continue
        # Replace every complete {{ … }} interpolation with a single
        # whitespace-free sentinel so naive whitespace-split doesn't
        # fragment them into "{{", "var", "}}". A class-word token that
        # is exactly the sentinel is fine; a token that contains the
        # sentinel mixed with other characters is concatenation.
        masked = _INTERP_PAT.sub(_INTERP_TOKEN, attr_value)
        for token in masked.split():
            if _INTERP_TOKEN in token and token != _INTERP_TOKEN:
                line = text.count("\n", 0, match.start()) + 1
                errors.append(
                    f"{path}:{line}: dynamic class concatenation\n"
                    f"    offending token: {token.replace(_INTERP_TOKEN, '{{ … }}')}\n"
                    f"    rule: a class-attribute token containing '{{{{' must be exactly\n"
                    f"          '{{{{ var }}}}'. Use {{% if cond %}}foo{{% else %}}bar{{% endif %}} for\n"
                    f"          conditional class names so Tailwind sees both literals."
                )
    return errors


def main() -> int:
    repo = Path(__file__).resolve().parent.parent
    template_root = repo / "app" / "templates"
    if not template_root.exists():
        print(f"check_template_classes: {template_root} not found", file=sys.stderr)
        return 2

    all_errors: list[str] = []
    scanned = 0
    for path in template_root.rglob("*.html"):
        # Email templates are SMTP-served, not subject to Tailwind/CSP.
        if "emails" in path.parts:
            continue
        scanned += 1
        all_errors.extend(_scan_file(path))

    if all_errors:
        print("check_template_classes: forbidden dynamic class concatenation found.")
        print()
        for err in all_errors:
            print(err)
            print()
        print(f"Total offenses: {len(all_errors)}")
        return 1

    print(f"check_template_classes: OK (scanned {scanned} files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
