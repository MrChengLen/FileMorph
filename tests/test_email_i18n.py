# SPDX-License-Identifier: AGPL-3.0-or-later
"""PR-i18n-3: outbound-email localisation (``app.core.email.render_email``).

These are pure rendering tests — no DB, no SMTP, no HTTP. They pin that:

* ``render_email`` returns a ``(subject, html, text)`` triple for every
  template we ship, in every supported locale, with no unrendered Jinja
  left in the output;
* the DE bundle actually swaps the strings (subject + body) and stamps
  ``<html lang="de">``;
* an unknown / ``None`` locale degrades to the operator default
  (``LANG_DEFAULT``, ``de`` out of the box) rather than raising;
* the ``{% if next_attempt_date %}`` branch in the dunning template works
  both ways;
* an unknown template stem fails loudly (KeyError naming the registry).
"""

from __future__ import annotations

import pytest

from app.core.email import EMAIL_SUBJECTS, render_email

# Superset of the context keys any of the four templates needs; passing
# extras is harmless (Jinja ignores them).
_CTX = dict(
    user_email="alice@example.de",
    verify_url="http://localhost:8000/verify-email?token=abc",
    reset_url="http://localhost:8000/reset-password?token=abc",
    deleted_at="2026-05-11T10:00:00+00:00",
    support_email="privacy@example.de",
    app_base_url="http://localhost:8000",
    tier_label="Pro",
    next_attempt_date="2026-05-18",
    billing_url="http://localhost:8000/dashboard",
)

_ALL_STEMS = sorted(EMAIL_SUBJECTS)


def _assert_no_unrendered_jinja(*blobs: str) -> None:
    for b in blobs:
        assert "{{" not in b and "}}" not in b, f"unrendered expression: {b[:200]!r}"
        assert "{%" not in b and "%}" not in b, f"unrendered tag/block: {b[:200]!r}"


@pytest.mark.parametrize("stem", _ALL_STEMS)
@pytest.mark.parametrize("locale", ["en", "de"])
def test_render_email_shape(stem: str, locale: str) -> None:
    subject, html, text = render_email(stem, locale=locale, **_CTX)
    assert subject and isinstance(subject, str)
    assert "<html" in html and "</html>" in html
    assert f'lang="{locale}"' in html
    assert text.strip()
    _assert_no_unrendered_jinja(html, text)


def test_subject_localised_per_locale() -> None:
    en_subj, _, _ = render_email("verify_email", locale="en", **_CTX)
    de_subj, _, _ = render_email("verify_email", locale="de", **_CTX)
    assert en_subj == "Confirm your FileMorph email"
    assert de_subj == "Bestätige deine FileMorph-E-Mail-Adresse"
    assert en_subj != de_subj


def test_de_body_is_actually_german() -> None:
    _, html, text = render_email("verify_email", locale="de", **_CTX)
    assert "Willkommen bei FileMorph" in html
    assert "Willkommen bei FileMorph" in text
    # The interpolated, autoescaped recipient address survives into the body.
    assert "alice@example.de" in html and "alice@example.de" in text


def test_en_body_is_english() -> None:
    _, html, _ = render_email("verify_email", locale="en", **_CTX)
    assert "Welcome to FileMorph" in html


@pytest.mark.parametrize("bad_locale", ["zz", "fr", "", None])
def test_unknown_locale_falls_back_to_default(bad_locale) -> None:
    # LANG_DEFAULT is unset in the test env → the effective default is "de".
    subject, html, _ = render_email("verify_email", locale=bad_locale, **_CTX)
    assert subject == "Bestätige deine FileMorph-E-Mail-Adresse"
    assert 'lang="de"' in html


def test_dunning_with_and_without_next_attempt_date() -> None:
    _, html_with, text_with = render_email(
        "dunning", locale="en", **{**_CTX, "next_attempt_date": "2026-05-18"}
    )
    assert "2026-05-18" in html_with and "2026-05-18" in text_with
    assert "retry automatically around" in html_with

    _, html_without, text_without = render_email(
        "dunning", locale="en", **{**_CTX, "next_attempt_date": None}
    )
    assert "2026-05-18" not in html_without and "2026-05-18" not in text_without
    assert "If the next retry still doesn't go through" in html_without
    # The plan label is a proper noun — not translated, not dropped.
    assert "Pro" in html_without
    _assert_no_unrendered_jinja(html_with, text_with, html_without, text_without)


def test_unknown_template_stem_raises_keyerror() -> None:
    with pytest.raises(KeyError) as excinfo:
        render_email("does_not_exist", locale="en", **_CTX)
    assert "EMAIL_SUBJECTS" in str(excinfo.value)


def test_every_subject_has_both_html_and_txt_template(tmp_path) -> None:
    # render_email expects <stem>.html and <stem>.txt to co-exist; if a new
    # subject is registered without both files this surfaces it.
    for stem in _ALL_STEMS:
        subject, html, text = render_email(stem, locale="en", **_CTX)
        assert html and text, stem
