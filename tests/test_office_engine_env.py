# SPDX-License-Identifier: AGPL-3.0-or-later
"""Office-engine env var name regression guard.

The docs, the office compose overlay and the DocxToPdfConverter runtime
error message all tell the operator to set ``FILEMORPH_OFFICE_ENGINE``, but
``Settings.office_engine`` only ever read the unprefixed ``OFFICE_ENGINE`` —
so following the docs silently did nothing. ``FILEMORPH_OFFICE_ENGINE`` must
become the canonical, documented name; the legacy ``OFFICE_ENGINE`` stays
accepted for backward compatibility, and the documented name wins when both
are set.

Every ``Settings`` instance here is constructed fresh with ``_env_file=None``
(or pointed at a throwaway tmp file) so a developer's real ``.env`` can never
leak a value into these assertions.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import Settings


@pytest.fixture(autouse=True)
def _clear_office_engine_env(monkeypatch):
    monkeypatch.delenv("FILEMORPH_OFFICE_ENGINE", raising=False)
    monkeypatch.delenv("OFFICE_ENGINE", raising=False)


def test_default_is_auto():
    assert Settings(_env_file=None).office_engine == "auto"


def test_documented_env_name_is_honoured(monkeypatch):
    monkeypatch.setenv("FILEMORPH_OFFICE_ENGINE", "libreoffice")
    assert Settings(_env_file=None).office_engine == "libreoffice"


def test_legacy_env_name_still_works(monkeypatch):
    monkeypatch.setenv("OFFICE_ENGINE", "mammoth")
    assert Settings(_env_file=None).office_engine == "mammoth"


def test_documented_name_wins_when_both_set(monkeypatch):
    monkeypatch.setenv("FILEMORPH_OFFICE_ENGINE", "libreoffice")
    monkeypatch.setenv("OFFICE_ENGINE", "mammoth")
    assert Settings(_env_file=None).office_engine == "libreoffice"


def test_documented_name_is_read_from_env_file(tmp_path):
    """Self-hosting docs tell people to put it in .env — cover that path,
    not just process env vars."""
    env_file = tmp_path / ".env"
    env_file.write_text("FILEMORPH_OFFICE_ENGINE=mammoth\n", encoding="utf-8", newline="\n")
    assert Settings(_env_file=str(env_file)).office_engine == "mammoth"


def test_office_compose_overlay_does_not_pin_the_engine():
    """Compose ranks a service's ``environment:`` above the base file's
    ``env_file: .env``. A pinned engine in the overlay therefore overrode the
    operator's .env value — and, once the documented name won over the legacy
    one, silently turned a legacy ``OFFICE_ENGINE=mammoth`` into ``auto``."""
    compose_path = Path(__file__).resolve().parent.parent / "docker-compose.office.yml"
    text = compose_path.read_text(encoding="utf-8")
    code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    assert "OFFICE_ENGINE" not in code, (
        "docker-compose.office.yml sets the office engine — that overrides .env"
    )
    assert "FILEMORPH_OFFICE_ENGINE" in text, "the overlay should still document the knob"
