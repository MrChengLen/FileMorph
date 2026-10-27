#!/usr/bin/env python
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Cross-platform helper around `pybabel` for FileMorph i18n workflows.

Usage:

    python scripts/i18n.py extract     # Re-scan code → locale/messages.pot
    python scripts/i18n.py init <loc>  # Bootstrap a new language (run once per locale)
    python scripts/i18n.py update      # Merge .pot into all locale .po files
    python scripts/i18n.py compile     # Optional: compile .po → .mo, print statistics and placeholder errors
    python scripts/i18n.py drift-check # CI gate: re-extract, fail if .pot drifts

The app compiles the .po files in memory at startup (app/core/i18n.py), so
.mo files are neither committed nor needed; `compile` only reports how
complete each catalogue is (tests/test_i18n_catalogs.py runs its placeholder
checks in CI). `extract`, `update` and `init` drop the
POT-Creation-Date header, which Babel rewrites on every run: otherwise two
branches that both touched strings conflicted on that one line.

Cross-platform: works on Windows (`pybabel.exe` + venv) and Linux (CI).
"""

from __future__ import annotations

import difflib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCALE_DIR = ROOT / "locale"
POT_FILE = LOCALE_DIR / "messages.pot"
BABEL_CFG = ROOT / "babel.cfg"
SUPPORTED = ("de", "en")

# Babel stamps the wall-clock time into this header on every extract/update.
_CREATION_DATE_RE = re.compile(r'^"POT-Creation-Date:[^"]*"\n', re.MULTILINE)


def _run(cmd: list[str]) -> int:
    """Run a command, stream output, return exit code."""
    print(f"$ {' '.join(cmd)}")
    return subprocess.call(cmd, cwd=ROOT)


def _pybabel(args: list[str]) -> int:
    return _run([sys.executable, "-m", "babel.messages.frontend"] + args)


def _drop_creation_date(*paths: Path) -> None:
    """Remove the POT-Creation-Date header so a re-run leaves the file unchanged."""
    for path in paths:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        stripped = _CREATION_DATE_RE.sub("", text)
        if stripped != text:
            path.write_text(stripped, encoding="utf-8", newline="\n")


def _po_files() -> list[Path]:
    return [LOCALE_DIR / loc / "LC_MESSAGES" / "messages.po" for loc in SUPPORTED]


def _project_version() -> str:
    """Read project version from pyproject.toml (single source of truth).

    Falling back to "0.0.0" if pyproject is unparseable lets the extract
    succeed in degenerate environments rather than blocking the whole
    i18n pipeline on a header field.
    """
    pyproject = ROOT / "pyproject.toml"
    if not pyproject.exists():
        return "0.0.0"
    try:
        for line in pyproject.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("version") and "=" in stripped:
                return stripped.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return "0.0.0"


def cmd_extract() -> int:
    """Scan all sources → locale/messages.pot."""
    LOCALE_DIR.mkdir(parents=True, exist_ok=True)
    version = _project_version()
    rc = _pybabel(
        [
            "extract",
            "-F",
            str(BABEL_CFG),
            "-o",
            str(POT_FILE),
            "--project=FileMorph",
            f"--version={version}",
            "--copyright-holder=FileMorph",
            "--no-location",
            "--sort-output",
            ".",
        ]
    )
    if not rc:
        _drop_creation_date(POT_FILE)
    return rc


def cmd_init(locale: str) -> int:
    if locale not in SUPPORTED:
        print(f"error: unsupported locale {locale!r} (supported: {SUPPORTED})")
        return 1
    if not POT_FILE.exists():
        rc = cmd_extract()
        if rc:
            return rc
    rc = _pybabel(["init", "-i", str(POT_FILE), "-d", str(LOCALE_DIR), "-l", locale])
    if not rc:
        _drop_creation_date(*_po_files())
    return rc


def cmd_update() -> int:
    if not POT_FILE.exists():
        rc = cmd_extract()
        if rc:
            return rc
    # --ignore-obsolete: removed msgids are dropped instead of kept as "#~"
    # blocks (the catalogs carry none since c8fc734; they only add noise).
    rc = _pybabel(["update", "--ignore-obsolete", "-i", str(POT_FILE), "-d", str(LOCALE_DIR)])
    if not rc:
        _drop_creation_date(*_po_files())
    return rc


def cmd_compile() -> int:
    return _pybabel(["compile", "-d", str(LOCALE_DIR), "--statistics"])


def _normalize_pot(path: Path) -> str:
    """Read a .pot file and strip the parts that change every extraction.

    Babel writes a fresh ``POT-Creation-Date`` header on each ``extract``
    and Python's text-mode write may emit CRLF on Windows vs LF on Linux.
    Both are noise — what matters for the drift check is the *body* of
    the catalogue (msgid/msgstr/comments). Normalising both files the
    same way lets us assert "did the set of translatable strings actually
    change" without false positives from wall-clock or platform.
    """
    text = path.read_text(encoding="utf-8")
    text = text.replace("\r\n", "\n")
    return _CREATION_DATE_RE.sub("", text)


def cmd_drift_check() -> int:
    """CI gate: re-extract to a tmp file, normalise, compare to committed.

    A non-zero diff means a developer added a new ``_('...')`` call but
    didn't run ``python scripts/i18n.py extract`` before pushing. The
    POT-Creation-Date header and CRLF/LF differences are filtered out of
    both sides so the gate only fires on real translation-key drift.
    """
    if not POT_FILE.exists():
        print("::error::locale/messages.pot is missing — run `extract` first.")
        return 1

    fd, tmp_name = tempfile.mkstemp(prefix="messages_drift_", suffix=".pot")
    os.close(fd)
    tmp_path = Path(tmp_name)
    version = _project_version()
    try:
        rc = _pybabel(
            [
                "extract",
                "-F",
                str(BABEL_CFG),
                "-o",
                str(tmp_path),
                "--project=FileMorph",
                f"--version={version}",
                "--copyright-holder=FileMorph",
                "--no-location",
                "--sort-output",
                ".",
            ]
        )
        if rc:
            return rc

        committed = _normalize_pot(POT_FILE)
        fresh = _normalize_pot(tmp_path)

        if committed == fresh:
            return 0

        print(
            "\n::error::messages.pot is stale. New `_('...')` keys were added or "
            "removed without re-extracting. Run `python scripts/i18n.py extract` "
            "locally and commit the result.\n"
        )
        for line in difflib.unified_diff(
            committed.splitlines(keepends=True),
            fresh.splitlines(keepends=True),
            fromfile="committed messages.pot (normalised)",
            tofile="fresh extract (normalised)",
            n=2,
        ):
            print(line, end="")
        return 1
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    cmd = sys.argv[1]
    if cmd == "extract":
        return cmd_extract()
    if cmd == "init":
        if len(sys.argv) < 3:
            print("error: init requires a locale argument (e.g. `init de`)")
            return 2
        return cmd_init(sys.argv[2])
    if cmd == "update":
        return cmd_update()
    if cmd == "compile":
        return cmd_compile()
    if cmd == "drift-check":
        return cmd_drift_check()
    print(f"error: unknown command {cmd!r}")
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
