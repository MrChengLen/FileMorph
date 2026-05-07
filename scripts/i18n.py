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

import subprocess
import sys
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
    return _pybabel(["update", "-i", str(POT_FILE), "-d", str(LOCALE_DIR), "--no-location"])


def cmd_compile() -> int:
    return _pybabel(["compile", "-d", str(LOCALE_DIR), "--statistics"])


def cmd_drift_check() -> int:
    """CI gate: re-extract the .pot, then `git diff --exit-code` it.

    A non-zero diff means a developer added a new ``_('...')`` call but
    didn't run ``python scripts/i18n.py extract`` before pushing. Failing
    here keeps translations in sync with code.
    """
    rc = cmd_extract()
    if rc:
        return rc
    diff = subprocess.call(
        ["git", "diff", "--exit-code", "--", str(POT_FILE.relative_to(ROOT))],
        cwd=ROOT,
    )
    if diff:
        print(
            "\n::error::messages.pot is stale. Run `python scripts/i18n.py extract` "
            "and commit the result."
        )
    return diff


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
