# SPDX-License-Identifier: AGPL-3.0-or-later
"""Translations come straight from the ``.po`` files; no ``.mo`` is committed.

``app/core/i18n.py`` compiles each ``locale/<code>/LC_MESSAGES/messages.po``
in memory. These tests pin what replaced the old "compile and commit the
.mo" step: a catalogue works with no ``.mo`` on disk, and fuzzy entries stay
out, as they did with ``pybabel compile``. The last test keeps Babel's
per-run ``POT-Creation-Date`` header out of the committed catalogues: with it,
any two branches that touched strings conflicted on that one line.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from babel.messages.pofile import read_po

from app.core import i18n

_REPO_ROOT = Path(__file__).resolve().parent.parent

_PO = r"""msgid ""
msgstr ""
"Content-Type: text/plain; charset=utf-8\n"
"Language: de\n"
"Plural-Forms: nplurals=2; plural=(n != 1);\n"

msgid "Compress PDF"
msgstr "PDF verkleinern"

#, fuzzy
msgid "Split PDF"
msgstr "PDF aufteilen"
"""


@pytest.fixture
def locale_dir(monkeypatch, tmp_path: Path) -> Path:
    # The module caches the bundles for the whole process: give each test an
    # empty cache and its own locale directory. monkeypatch restores both.
    monkeypatch.setattr(i18n, "_translations", {})
    monkeypatch.setattr(i18n, "LOCALE_DIR", tmp_path)
    return tmp_path


def _write_german_catalog(root: Path) -> None:
    target = root / "de" / "LC_MESSAGES"
    target.mkdir(parents=True)
    (target / "messages.po").write_text(_PO, encoding="utf-8", newline="\n")


def test_catalog_compiles_from_po_without_mo(locale_dir: Path) -> None:
    _write_german_catalog(locale_dir)
    assert i18n._load_translations()["de"].gettext("Compress PDF") == "PDF verkleinern"
    assert not list(locale_dir.rglob("*.mo"))


def test_fuzzy_entries_stay_untranslated(locale_dir: Path) -> None:
    _write_german_catalog(locale_dir)
    assert i18n._load_translations()["de"].gettext("Split PDF") == "Split PDF"


def test_missing_catalog_falls_back_to_source_strings(locale_dir: Path) -> None:
    assert i18n._load_translations()["de"].gettext("Compress PDF") == "Compress PDF"


def test_broken_catalog_falls_back_and_is_logged(locale_dir: Path, caplog) -> None:
    # A hand-edit gone wrong (here: invalid UTF-8) must not take every page
    # and email down with it: English source strings, and the reason logged.
    target = locale_dir / "de" / "LC_MESSAGES"
    target.mkdir(parents=True)
    (target / "messages.po").write_bytes(
        _PO.encode("utf-8").replace(b"PDF verkleinern", b"\xff\xfe")
    )
    with caplog.at_level("ERROR", logger="app.core.i18n"):
        translations = i18n._load_translations()
    assert translations["de"].gettext("Compress PDF") == "Compress PDF"
    assert "de catalogue failed to load" in caplog.text


@pytest.mark.parametrize("locale", i18n.SUPPORTED_LOCALES)
def test_committed_catalogs_pass_babel_checks(locale: str) -> None:
    # `pybabel compile` ran these checks; the in-memory compile does not. A
    # msgstr whose placeholder differs from its msgid's would raise KeyError
    # when a page or an email renders. abort_invalid also rejects leftover
    # merge-conflict markers, which read_po would otherwise skip with a warning.
    po = _REPO_ROOT / "locale" / locale / "LC_MESSAGES" / "messages.po"
    with po.open("rb") as po_file:
        catalog = read_po(po_file, locale=locale, abort_invalid=True)
    errors = [(message.id, str(error)) for message, errs in catalog.check() for error in errs]
    assert not errors, errors[:5]


@pytest.mark.parametrize(
    "path",
    [
        "locale/messages.pot",
        "locale/de/LC_MESSAGES/messages.po",
        "locale/en/LC_MESSAGES/messages.po",
    ],
)
def test_committed_catalogs_carry_no_creation_date(path: str) -> None:
    text = (_REPO_ROOT / path).read_text(encoding="utf-8")
    assert "POT-Creation-Date" not in text, (
        f"{path} carries a POT-Creation-Date header again. Run `python scripts/i18n.py "
        "extract` and `update`, which drop it, instead of calling pybabel directly."
    )
