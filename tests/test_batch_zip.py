# SPDX-License-Identifier: AGPL-3.0-or-later
"""``build_batch_zip`` gives every ZIP entry a unique name.

Duplicate output names get a numeric suffix (``a.png``, ``a_1.png``,
``a_2.png``). A suffixed candidate can already be taken — by an input
that carries that name itself, or by ``manifest.json`` — and is then
skipped. A duplicate entry would make unzipping silently overwrite one
of the files.
"""

from __future__ import annotations

import io
import json
import zipfile

import pytest

from app.core.batch import BatchFileResult, build_batch_zip


def _ok(name: str) -> BatchFileResult:
    # The content is the input's name, so each entry shows which input it holds.
    return BatchFileResult(name=name, status="ok", size_in=1, size_out=1, content=name.encode())


def _failed(name: str) -> BatchFileResult:
    return BatchFileResult(name=name, status="error", size_in=1, error_message="boom")


def _zip(results: list[BatchFileResult]) -> zipfile.ZipFile:
    zip_bytes, _summary = build_batch_zip(results, operation="convert", duration_ms=0)
    return zipfile.ZipFile(io.BytesIO(zip_bytes))


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        # Plain duplicates count up: the second copy gets _1, the third _2.
        (["a.png", "a.png", "a.png"], ["a.png", "a_1.png", "a_2.png"]),
        # A later input already carries the suffixed name: it moves on instead of clashing.
        (["a.png", "a.png", "a_1.png"], ["a.png", "a_1.png", "a_1_1.png"]),
        # An earlier input holds the next suffix: that one is skipped.
        (["a_1.png", "a.png", "a.png"], ["a_1.png", "a.png", "a_2.png"]),
        (["README", "README"], ["README", "README_1"]),
    ],
    ids=["plain-duplicates", "suffix-taken-later", "suffix-taken-earlier", "no-extension"],
)
def test_entry_names_are_unique(names, expected):
    zf = _zip([_ok(n) for n in names])
    assert zf.namelist() == expected
    # Every input's bytes are in the ZIP, in input order — none was overwritten.
    assert [zf.read(entry) for entry in expected] == [n.encode() for n in names]


def test_failed_files_do_not_take_a_name():
    zf = _zip([_failed("a.png"), _ok("a.png"), _ok("a.png")])
    assert zf.namelist() == ["manifest.json", "a.png", "a_1.png"]


def test_output_named_manifest_json_does_not_replace_the_report():
    zf = _zip([_failed("x.png"), _ok("manifest.json")])
    assert zf.namelist() == ["manifest.json", "manifest_1.json"]
    assert json.loads(zf.read("manifest.json"))["summary"]["failed"] == 1
    assert zf.read("manifest_1.json") == b"manifest.json"


def test_output_named_manifest_json_keeps_its_name_when_nothing_failed():
    # No file failed, so there is no report to make room for.
    assert _zip([_ok("manifest.json")]).namelist() == ["manifest.json"]
