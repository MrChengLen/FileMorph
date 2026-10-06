# SPDX-License-Identifier: AGPL-3.0-or-later
"""Changelog entries live in changelog.d/, one file each.

Every pull request used to insert its entry directly under ``## [Unreleased]``
in CHANGELOG.md, the same line every time, so each merge left every other open
pull request in conflict. New files never conflict; ``scripts/changelog.py``
folds them into CHANGELOG.md in the release-prep pull request.
"""

from __future__ import annotations

import datetime
import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIRST_LINE = re.compile(r"### (Added|Changed|Deprecated|Removed|Fixed|Security) — \S")

_spec = importlib.util.spec_from_file_location(
    "changelog_script", ROOT / "scripts" / "changelog.py"
)
changelog = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(changelog)

FRAGMENTS = sorted(p for p in (ROOT / "changelog.d").iterdir() if p.name != "README.md")
DAY = datetime.date(2026, 3, 1)


@pytest.mark.parametrize("path", FRAGMENTS, ids=lambda p: p.name)
def test_fragment_is_one_house_style_entry(path: Path) -> None:
    assert path.is_file() and not path.is_symlink(), f"{path.name}: must be a regular file"
    assert changelog.NAME.fullmatch(path.name), (
        f"{path.name}: name it YYYY-MM-DD-<topic>.md (lower case, digits and '-', ending in .md)"
    )
    datetime.date.fromisoformat(path.name[:10])  # a real date, not 2026-13-45
    text = path.read_text(encoding="utf-8-sig")
    assert FIRST_LINE.match(text), (
        f"{path.name}: the first line must be '### Fixed — <headline>' (or Added/Changed/"
        "Deprecated/Removed/Security), with an em dash (—) between type and headline"
    )
    assert not re.search(r"^##? ", text, re.M), (
        f"{path.name}: no '#' or '##' headings inside an entry"
    )


def test_unreleased_takes_no_direct_entries() -> None:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8-sig")
    assert changelog.UNRELEASED + changelog.POINTER in text, (
        "Something was added at the top of CHANGELOG.md's [Unreleased] section. Move it into "
        "changelog.d/<YYYY-MM-DD>-<topic>.md (see changelog.d/README.md), keep the two pointer "
        "lines directly under ## [Unreleased], and don't run scripts/changelog.py in a feature PR."
    )


def _tree(tmp_path: Path) -> tuple[Path, Path]:
    log = tmp_path / "CHANGELOG.md"
    log.write_bytes(
        (
            "# Changelog\n\n---\n\n"
            + changelog.UNRELEASED
            + changelog.POINTER
            + "### Fixed — already folded\n\nOld.\n\n---\n\n## [1.0.0] — 2026-01-01\n\n"
            + "### Added — first\n"
        ).encode()
    )
    frags = tmp_path / "changelog.d"
    frags.mkdir()
    (frags / "README.md").write_bytes(b"rules\n")
    (frags / "2026-02-01-older.md").write_bytes("### Fixed — older\n\nA.\n".encode())
    (frags / "2026-02-03-newer.md").write_bytes("### Added — newer\n\nB.\n".encode())
    return log, frags


def _below_pointer(log: Path) -> str:
    return log.read_text(encoding="utf-8").split(changelog.POINTER, 1)[1]


def test_fold_puts_newest_first_below_the_pointer_and_removes_fragments(tmp_path: Path) -> None:
    log, frags = _tree(tmp_path)
    assert changelog.fold(log, frags, None, DAY) == 2
    assert _below_pointer(log).startswith(
        "### Added — newer\n\nB.\n\n### Fixed — older\n\nA.\n\n### Fixed — already folded"
    )
    assert [p.name for p in frags.iterdir()] == ["README.md"]


def test_fold_normalises_crlf_bom_and_a_missing_final_newline(tmp_path: Path) -> None:
    log, frags = _tree(tmp_path)
    (frags / "2026-02-04-windows.md").write_bytes(
        b"\xef\xbb\xbf### Added \xe2\x80\x94 windows\r\n\r\nW."
    )
    changelog.fold(log, frags, None, DAY)
    raw = log.read_bytes()
    assert b"\r" not in raw and b"\xef\xbb\xbf" not in raw
    assert _below_pointer(log).startswith("### Added — windows\n\nW.\n\n### Added — newer")


def test_fold_without_fragments_changes_nothing(tmp_path: Path) -> None:
    log, frags = _tree(tmp_path)
    changelog.fold(log, frags, None, DAY)
    before = log.read_bytes()
    assert changelog.fold(log, frags, None, DAY) == 0
    assert log.read_bytes() == before


def test_release_turns_everything_unreleased_into_the_version(tmp_path: Path) -> None:
    log, frags = _tree(tmp_path)
    changelog.fold(log, frags, "1.1.0", DAY)
    below = _below_pointer(log)
    assert below.startswith("---\n\n## [1.1.0] — 2026-03-01\n\n### Added — newer")
    assert below.index("already folded") < below.index("## [1.0.0]")


def test_a_late_entry_joins_the_release_already_cut(tmp_path: Path) -> None:
    log, frags = _tree(tmp_path)
    changelog.fold(log, frags, "1.1.0", DAY)
    (frags / "2026-02-05-late.md").write_bytes("### Fixed — late\n\nL.\n".encode())
    changelog.fold(log, frags, "1.1.0", datetime.date(2026, 3, 9))
    below = _below_pointer(log)
    assert below.startswith("---\n\n## [1.1.0] — 2026-03-01\n\n### Fixed — late\n\nL.\n\n")
    assert below.count("## [1.1.0]") == 1
    before = log.read_bytes()
    changelog.fold(log, frags, "1.1.0", datetime.date(2026, 3, 9))
    assert log.read_bytes() == before


def test_a_new_release_nests_above_the_last_one(tmp_path: Path) -> None:
    log, frags = _tree(tmp_path)
    changelog.fold(log, frags, "1.1.0", DAY)
    (frags / "2026-03-02-next.md").write_bytes("### Fixed — next\n\nN.\n".encode())
    changelog.fold(log, frags, None, DAY)
    changelog.fold(log, frags, "1.2.0", datetime.date(2026, 4, 1))
    below = _below_pointer(log)
    assert below.startswith("---\n\n## [1.2.0] — 2026-04-01\n\n### Fixed — next\n\nN.\n\n---\n\n")
    assert below.index("## [1.2.0]") < below.index("## [1.1.0]") < below.index("## [1.0.0]")


@pytest.mark.parametrize(
    ("release", "reason"), [("1.0.0", "already released"), ("1.1.0", "nothing to release")]
)
def test_release_refuses_an_old_or_empty_version(tmp_path: Path, release: str, reason: str) -> None:
    log, frags = _tree(tmp_path)
    changelog.fold(log, frags, "1.0.1", DAY)
    before = log.read_bytes()
    with pytest.raises(SystemExit, match=reason):
        changelog.fold(log, frags, release, DAY)
    assert log.read_bytes() == before


def test_fold_refuses_a_changelog_without_the_pointer(tmp_path: Path) -> None:
    log, frags = _tree(tmp_path)
    log.write_bytes("# Changelog\n\n## [Unreleased]\n\n### Fixed — direct\n".encode())
    with pytest.raises(SystemExit):
        changelog.fold(log, frags, None, DAY)
    assert len(list(frags.iterdir())) == 3


@pytest.mark.parametrize("name", ["2026-02-04-notes.txt", "2026-02-04-Upper.md", "notes.md"])
def test_fold_refuses_files_that_are_not_fragments(tmp_path: Path, name: str) -> None:
    log, frags = _tree(tmp_path)
    (frags / name).write_bytes("### Fixed — x\n\nX.\n".encode())
    before = log.read_bytes()
    with pytest.raises(SystemExit):
        changelog.fold(log, frags, None, DAY)
    assert log.read_bytes() == before


def test_fold_refuses_links(tmp_path: Path) -> None:
    log, frags = _tree(tmp_path)
    secret = tmp_path / "secret.txt"
    secret.write_bytes(b"### Fixed - not a fragment\n")
    try:
        (frags / "2026-02-04-link.md").symlink_to(secret)
    except OSError:
        pytest.skip("this system cannot create symlinks")
    with pytest.raises(SystemExit):
        changelog.fold(log, frags, None, DAY)
