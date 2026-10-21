# SPDX-License-Identifier: AGPL-3.0-or-later
"""Isolated conversions (``app/converters/_isolated.py``).

The table conversions run in a child process with memory and time limits,
and the child reports its result or error on stdout. PDF compression uses the
same child; its route tests are in ``tests/test_pdf_compress.py``.
"""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from app.converters import _isolated
from app.converters.base import (
    EncryptedPdfError,
    InvalidInputError,
    OutputTooLargeError,
    UnsupportedPdfEncryptionError,
)
from app.converters.spreadsheet import CsvToJsonConverter, JsonToCsvConverter

_TOO_LARGE = "Too large; split it."


def _step_limits(monkeypatch, step: str, *, memory: int | None = None, seconds=None):
    module, function, old_memory, old_seconds = _isolated._STEPS[step]
    limits = (module, function, memory or old_memory, seconds or old_seconds)
    monkeypatch.setitem(_isolated._STEPS, step, limits)


# ── A real child ─────────────────────────────────────────────────────────────


def test_an_isolated_converter_converts_in_a_child(tmp_path):
    src, out = tmp_path / "in.csv", tmp_path / "out.json"
    src.write_text("a,b\n1,2\n", encoding="utf-8")
    assert CsvToJsonConverter().run(src, out) == out
    assert json.loads(out.read_text(encoding="utf-8")) == [{"a": "1", "b": "2"}]


def test_the_childs_errors_come_back(tmp_path):
    src = tmp_path / "in.csv"
    src.write_text("a\n" + "x\n" * 1000, encoding="utf-8")
    with pytest.raises(OutputTooLargeError):
        CsvToJsonConverter().run(src, tmp_path / "out.json", max_output_bytes=100)
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    with pytest.raises(InvalidInputError, match="non-empty array of objects"):
        JsonToCsvConverter().run(bad, tmp_path / "out.csv")


def test_a_child_over_its_time_is_stopped(tmp_path, monkeypatch):
    _step_limits(monkeypatch, "convert", seconds=0.01)
    src = tmp_path / "in.csv"
    src.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(InvalidInputError, match="too large or complex to convert"):
        CsvToJsonConverter().run(src, tmp_path / "out.json")


def test_the_convert_route_names_the_next_step_past_the_limits(client, auth_headers, monkeypatch):
    _step_limits(monkeypatch, "convert", seconds=0.01)
    res = client.post(
        "/api/v1/convert",
        headers=auth_headers,
        files={"file": ("t.csv", b"a,b\n1,2\n", "text/csv")},
        data={"target_format": "json"},
    )
    assert res.status_code == 400
    assert res.headers["X-FileMorph-Error-Code"] == "invalid_input"
    assert "Split it into smaller files" in res.json()["detail"]


def test_only_isolated_converters_run_in_the_child(tmp_path):
    with pytest.raises(ValueError, match="doesn't run isolated"):
        _isolated._convert(
            "app.converters.document:MarkdownToHtmlConverter",
            tmp_path / "in.md",
            tmp_path / "out.html",
        )


def test_the_child_hardens_pillow_and_caps_itself(tmp_path):
    src, out = tmp_path / "in.csv", tmp_path / "out.json"
    src.write_text("a\n1\n", encoding="utf-8")
    kwargs = {
        "converter": "app.converters.spreadsheet:CsvToJsonConverter",
        "input_path": str(src),
        "output_path": str(out),
    }
    argv = ["x", "convert", str(256 * 1024 * 1024), "60", json.dumps(kwargs)]
    probe = "\n".join(
        [
            "import runpy, sys, warnings",
            f"sys.argv = {argv!r}",
            "runpy.run_module('app.converters._isolated', run_name='__main__')",
            "from PIL import EpsImagePlugin, Image",
            "try:",
            "    warnings.warn('probe', Image.DecompressionBombWarning)",
            "    print('not raised')",
            "except Image.DecompressionBombWarning:",
            "    print('raised')",
            "print(EpsImagePlugin.gs_binary)",
        ]
    )
    if sys.platform == "linux":
        probe += (
            "\nimport ctypes, resource"
            "\nprint(*(resource.getrlimit(limit)[0] for limit in "
            "(resource.RLIMIT_AS, resource.RLIMIT_CPU, resource.RLIMIT_CORE)), "
            "ctypes.CDLL(None).prctl(3, 0, 0, 0, 0))"  # PR_GET_DUMPABLE
        )
    res = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        encoding="utf-8",
        cwd=_isolated._APP_ROOT,
        check=True,
    )
    lines = res.stdout.splitlines()
    assert json.loads(lines[0]) == {"result": None}
    assert lines[1:3] == ["raised", "False"]  # bomb warnings raise; no Ghostscript
    if sys.platform == "linux":
        assert lines[3].split() == [str(256 * 1024 * 1024), "65", "0", "0"]
    assert json.loads(out.read_text(encoding="utf-8")) == [{"a": "1"}]


# ── The parent's side, with a stand-in child ─────────────────────────────────


def _fake_child(stdout: str, returncode: int = 0, seen: dict | None = None):
    def run(command, **kwargs):
        if seen is not None:
            seen.update(kwargs, command=command)
        return subprocess.CompletedProcess(command, returncode, stdout, None)

    return run


def test_the_child_gets_no_secrets_and_the_request_temp_folder(tmp_path, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "not-for-the-child")
    seen: dict = {}
    monkeypatch.setattr(subprocess, "run", _fake_child('{"result": 7}', seen=seen))
    assert _isolated.run_isolated("convert", too_large=_TOO_LARGE, tmp_dir=tmp_path) == 7
    _, _, memory, seconds = _isolated._STEPS["convert"]
    assert seen["command"][:6] == [
        *(sys.executable, "-m", "app.converters._isolated", "convert"),
        *(str(memory), str(seconds)),
    ]
    assert "JWT_SECRET" not in seen["env"]
    assert seen["env"]["TMPDIR"] == seen["env"]["TEMP"] == str(tmp_path)
    assert seen["env"]["MALLOC_ARENA_MAX"] == "2"
    assert seen["stdin"] is subprocess.DEVNULL
    assert seen["stderr"] is subprocess.DEVNULL
    assert seen["timeout"] == seconds


@pytest.mark.parametrize(
    ("stdout", "returncode", "error", "message"),
    [
        ('{"error": "output_too_large"}', 0, OutputTooLargeError, ""),
        ('{"error": "encrypted"}', 0, EncryptedPdfError, "password"),
        ('{"error": "unsupported_encryption"}', 0, UnsupportedPdfEncryptionError, "certificate"),
        ('{"error": "invalid", "message": "Fix it."}', 0, InvalidInputError, "Fix it."),
        ('{"error": "out_of_memory"}', 0, InvalidInputError, _TOO_LARGE),
        ("", -9, InvalidInputError, _TOO_LARGE),  # stopped by a limit
        ('{"error": "failed", "type": "KeyError"}', 0, RuntimeError, "KeyError"),
        ("not json", 1, RuntimeError, "status 1"),
    ],
)
def test_child_outcomes_map_to_the_usual_errors(
    tmp_path, monkeypatch, stdout, returncode, error, message
):
    monkeypatch.setattr(subprocess, "run", _fake_child(stdout, returncode))
    with pytest.raises(error) as excinfo:
        _isolated.run_isolated("convert", too_large=_TOO_LARGE, tmp_dir=tmp_path)
    assert message in str(excinfo.value)
