#!/usr/bin/env python
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Cross-platform helper around `pybabel` for FileMorph i18n workflows.

Usage:

    python scripts/i18n.py extract     # Re-scan code → locale/messages.pot
    python scripts/i18n.py init <loc>  # Bootstrap a new language (run once per locale)
    python scripts/i18n.py update      # Merge .pot into all locale .po files
    python scripts/i18n.py compile     # Compile every .po → .mo
    python scripts/i18n.py drift-check # CI gate: re-extract, fail if .pot drifts

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


def _run(cmd: list[str]) -> int:
    """Run a command, stream output, return exit code."""
    print(f"$ {' '.join(cmd)}")
    return subprocess.call(cmd, cwd=ROOT)


def _pybabel(args: list[str]) -> int:
    return _run([sys.executable, "-m", "babel.messages.frontend"] + args)


def cmd_extract() -> int:
    """Scan all sources → locale/messages.pot."""
    LOCALE_DIR.mkdir(parents=True, exist_ok=True)
    return _pybabel(
        [
            "extract",
            "-F",
            str(BABEL_CFG),
            "-o",
            str(POT_FILE),
            "--project=FileMorph",
            "--copyright-holder=FileMorph",
            "--no-location",
            "--sort-output",
            ".",
        ]
    )


def cmd_init(locale: str) -> int:
    if locale not in SUPPORTED:
        print(f"error: unsupported locale {locale!r} (supported: {SUPPORTED})")
        return 1
    if not POT_FILE.exists():
        rc = cmd_extract()
        if rc:
            return rc
    return _pybabel(["init", "-i", str(POT_FILE), "-d", str(LOCALE_DIR), "-l", locale])


def cmd_update() -> int:
    if not POT_FILE.exists():
        rc = cmd_extract()
        if rc:
            return rc
    return _pybabel(["update", "-i", str(POT_FILE), "-d", str(LOCALE_DIR)])


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
    text = re.sub(r'^"POT-Creation-Date:[^"]*"\n', "", text, flags=re.MULTILINE)
    return text


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
    try:
        rc = _pybabel(
            [
                "extract",
                "-F",
                str(BABEL_CFG),
                "-o",
                str(tmp_path),
                "--project=FileMorph",
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
