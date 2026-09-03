#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""CI gate: one Python version across image, CI, and lockfile.

The Python version used to live in five places that drifted apart without
anyone noticing. On 2026-05-26 a Dependabot PR (``2b26b49``) bumped the base
image from ``python:3.12-slim`` to ``python:3.14-slim`` — two minor versions
in one "deps" commit. Nothing carried the change into the workflows, so for
three months CI tested 3.12 while production ran 3.14, and
``requirements.lock`` still carried the 3.11 it was compiled with. The
mismatch was invisible because no gate compared them.

This script is that gate. The **Dockerfile is the single source of truth** —
it is what actually ships — and everything else must agree with it:

* every ``python-version:`` in ``.github/workflows/*.yml``
* the ``--python-version X.Y`` recorded in ``requirements.lock``'s uv header
* ``requires-python`` in ``pyproject.toml`` must *permit* the shipped version

The lockfile is compiled by ``uv pip compile``, which resolves *for* a target
Python version without needing that version installed. That is deliberate: the
previous pip-compile setup could only lock on whatever interpreter happened to
be running, which is why the committed lockfile carried 3.11 while the image
shipped 3.14 — and why nobody could regenerate it without matching the image
locally first.

``requires-python`` is deliberately only checked for compatibility, not
equality: it declares the floor for self-hosters (``>=3.11``) while the image
ships a specific version. Note that the floor itself is not exercised by CI —
only the shipped version is. Raising the floor or adding a matrix build is a
product decision, not something this gate should force.

Run: ``python scripts/check_python_version.py``
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# ``FROM python:3.14-slim@sha256:...`` — the tag carries the version; the
# digest is the enforcement. Both stages must agree, so we collect all hits.
DOCKERFILE_RE = re.compile(r"^FROM\s+python:(\d+\.\d+)-slim@sha256:", re.MULTILINE)

# ``python-version: "3.14"`` in setup-python steps. Quotes optional in YAML.
WORKFLOW_RE = re.compile(r'^\s*python-version:\s*["\']?(\d+\.\d+)["\']?\s*$', re.MULTILINE)

# uv records the *target* version it resolved for in its header command line:
# ``#    uv pip compile --generate-hashes --python-version 3.14 ...``
LOCK_RE = re.compile(r"--python-version[= ](\d+\.\d+)")

# ``requires-python = ">=3.11"``
REQUIRES_RE = re.compile(r'^requires-python\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)


def shipped_version() -> str:
    """The version in the Dockerfile — the source of truth."""
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    found = DOCKERFILE_RE.findall(text)
    if not found:
        sys.exit("FAIL: no digest-pinned `FROM python:X.Y-slim@sha256:` in Dockerfile")
    if len(set(found)) > 1:
        sys.exit(f"FAIL: Dockerfile stages disagree on the Python version: {sorted(set(found))}")
    return found[0]


def main() -> int:
    shipped = shipped_version()
    problems: list[str] = []

    # --- workflows -------------------------------------------------------
    for wf in sorted((ROOT / ".github/workflows").glob("*.yml")):
        for version in WORKFLOW_RE.findall(wf.read_text(encoding="utf-8")):
            if version != shipped:
                problems.append(
                    f"{wf.relative_to(ROOT).as_posix()}: python-version {version} "
                    f"!= shipped {shipped}"
                )

    # --- lockfile --------------------------------------------------------
    lock = ROOT / "requirements.lock"
    if lock.exists():
        m = LOCK_RE.search(lock.read_text(encoding="utf-8"))
        if not m:
            problems.append(
                "requirements.lock: no `--python-version X.Y` in the uv header — "
                "regenerate it with `uv pip compile --generate-hashes "
                "--python-version <shipped>`"
            )
        elif m.group(1) != shipped:
            problems.append(
                f"requirements.lock: resolved for Python {m.group(1)} != shipped {shipped} "
                f"(regenerate it, or run the deps-lock workflow)"
            )

    # --- pyproject floor must permit the shipped version -----------------
    m = REQUIRES_RE.search((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    if m:
        try:
            from packaging.specifiers import SpecifierSet
            from packaging.version import Version

            if not SpecifierSet(m.group(1)).contains(Version(shipped)):
                problems.append(
                    f"pyproject.toml: requires-python {m.group(1)!r} excludes the shipped {shipped}"
                )
        except ImportError:  # packaging is a pip dependency; skip if absent
            pass

    if problems:
        print(f"Python-version drift (Dockerfile ships {shipped}):", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print(
            "\nThe Dockerfile is the source of truth. Align the others, or change "
            "the Dockerfile deliberately and align everything in the same PR.",
            file=sys.stderr,
        )
        return 1

    print(f"Python version consistent everywhere: {shipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
