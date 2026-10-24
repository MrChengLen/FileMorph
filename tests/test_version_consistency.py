# SPDX-License-Identifier: AGPL-3.0-or-later
"""The version strings agree with each other and with the newest changelog release.

The 1.2.1 release-prep pull request folded the changelog but left the version at
1.2.0, so the app and the OpenAPI schema reported the wrong version.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from app.core.config import Settings

ROOT = Path(__file__).resolve().parent.parent


def test_version_strings_agree() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    version = pyproject["project"]["version"]
    assert Settings.model_fields["app_version"].default == version
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    newest = re.search(r"^## \[(\d+\.\d+\.\d+)\]", changelog, re.M)
    assert newest is not None and newest.group(1) == version
