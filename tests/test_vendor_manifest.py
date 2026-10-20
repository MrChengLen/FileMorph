# SPDX-License-Identifier: AGPL-3.0-or-later
"""Vendored browser code stays exactly what app/static/vendor/manifest.json says.

Third-party code shipped to the browser is vendored unmodified, each file listed
with version, source, licence and SHA-256, under a permissive licence only, and
nothing is vendored without an entry. A changed byte, an unlisted file or a
licence outside the allow-list fails here. The allow-list lives in this test,
not in the manifest, so editing the manifest alone cannot widen it.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest

_VENDOR = Path(__file__).resolve().parents[1] / "app" / "static" / "vendor"
_ALLOWED_LICENSES = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause", "ISC"}
_ENTRIES = json.loads((_VENDOR / "manifest.json").read_text(encoding="utf-8"))["files"]
_IDS = [entry["path"] for entry in _ENTRIES]


@pytest.mark.parametrize("entry", _ENTRIES, ids=_IDS)
def test_vendored_file_matches_its_sha256(entry):
    data = (_VENDOR / entry["path"]).read_bytes()
    assert hashlib.sha256(data).hexdigest() == entry["sha256"]


@pytest.mark.parametrize("entry", _ENTRIES, ids=_IDS)
def test_vendored_file_licence_is_allowed(entry):
    assert entry["license"] in _ALLOWED_LICENSES


@pytest.mark.parametrize("entry", _ENTRIES, ids=_IDS)
def test_vendored_file_version_matches_its_source(entry):
    # scripts/check_vendor_advisories.py asks OSV about this version; a label
    # that drifted from the source would check the wrong release.
    assert entry["version"] in entry["source"]


@pytest.mark.parametrize("entry", _ENTRIES, ids=_IDS)
def test_vendored_file_notice_names_the_same_sha256(entry):
    # Notice files are exempt from the listing check below, so only a
    # LICENSE-<name>.md may be named here — never a file the browser runs.
    assert re.fullmatch(r"LICENSE-[a-z0-9-]+\.md", entry["notices"])
    notices = _VENDOR / entry["notices"]
    assert notices.is_file()
    assert entry["sha256"] in notices.read_text(encoding="utf-8")


def test_every_vendored_file_is_in_the_manifest():
    # Everything under vendor/ is served at /static/vendor/, subfolders included;
    # only the manifest itself and the notice files it names are exempt.
    exempt = {"manifest.json"} | {entry["notices"] for entry in _ENTRIES}
    shipped = {
        path.relative_to(_VENDOR).as_posix() for path in _VENDOR.rglob("*") if path.is_file()
    }
    assert shipped - exempt == set(_IDS)
