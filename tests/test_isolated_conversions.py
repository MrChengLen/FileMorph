# SPDX-License-Identifier: AGPL-3.0-or-later
"""Isolated conversions (``app/converters/_isolated.py``).

The table conversions run in a child process with memory and time limits,
and the child reports its result or error on stdout. PDF compression uses the
same child; its route tests are in ``tests/test_pdf_compress.py`` and, with a
stand-in child, ``tests/test_pdf_error_messages.py``.
"""

from __future__ import annotations

import json
import logging
import signal
import subprocess
import sys
import tracemalloc

import pytest

from app.converters import _isolated
from app.converters.base import (
    EncryptedPdfError,
    InvalidInputError,
    OutputTooLargeError,
    UnsupportedPdfEncryptionError,
)
from app.converters.spreadsheet import (
    CsvToJsonConverter,
    CsvToXlsxConverter,
    JsonToCsvConverter,
)

_TOO_LARGE = "Too large; split it."


def _step_limits(
    monkeypatch, step: str, *, memory: int | None = None, seconds=None, file_bytes=None
):
    module, function, old_memory, old_seconds, old_file_bytes = _isolated._STEPS[step]
    limits = (
        module,
        function,
        memory or old_memory,
        seconds or old_seconds,
        file_bytes or old_file_bytes,
    )
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
    with pytest.raises(_isolated.TooComplexError, match="too large or complex to convert"):
        CsvToJsonConverter().run(src, tmp_path / "out.json")


@pytest.mark.skipif(sys.platform != "linux", reason="the limits apply on Linux")
@pytest.mark.parametrize(
    "converter",
    [CsvToXlsxConverter, CsvToJsonConverter],  # the sheet written by lxml, the JSON by Python
)
def test_a_file_past_its_size_limit_ends_the_child(tmp_path, monkeypatch, caplog, converter):
    if converter is CsvToXlsxConverter:
        from openpyxl.xml import LXML

        assert LXML  # openpyxl writes the sheet through lxml, not Python's files
    _step_limits(monkeypatch, "convert", file_bytes=2 * 1024 * 1024)
    src = tmp_path / "in.csv"
    src.write_text("a,b,c\n" + "1234567890,abcdefghij,klmnopqrst\n" * 100_000, encoding="utf-8")
    with caplog.at_level(logging.INFO, logger="app.converters._isolated"):
        with pytest.raises(_isolated.TooComplexError, match="too large or complex to convert"):
            converter().run(src, tmp_path / "out")
    assert f"(status {-signal.SIGXFSZ})" in caplog.text


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
    limits = [str(256 * 1024 * 1024), "60", str(64 * 1024 * 1024)]
    argv = ["x", "convert", *limits, json.dumps(kwargs)]
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
            "\nimport ctypes, resource, signal"
            "\nprint(*('%d/%d' % resource.getrlimit(limit) for limit in (resource.RLIMIT_AS, "
            "resource.RLIMIT_CPU, resource.RLIMIT_FSIZE, resource.RLIMIT_CORE)), "
            "ctypes.CDLL(None).prctl(3, 0, 0, 0, 0), "  # PR_GET_DUMPABLE
            "signal.getsignal(signal.SIGXFSZ) == signal.SIG_DFL)"
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
        # The limits, soft/hard alike so the child can't raise them again; no
        # core dump; and SIGXFSZ's default action, so a write past the file
        # size limit ends the child.
        memory, _, file_bytes = limits
        caps = [f"{cap}/{cap}" for cap in (memory, "65", file_bytes, "0")]
        assert lines[3].split() == [*caps, "0", "True"]
    assert json.loads(out.read_text(encoding="utf-8")) == [{"a": "1"}]


@pytest.mark.skipif(sys.platform != "linux", reason="the limits apply on Linux")
def test_the_child_keeps_a_lower_hard_limit():
    # A hard limit the host already set lower stays, now as soft and hard limit.
    probe = (
        "import resource; from app.converters._isolated import limit_resources; "
        "resource.setrlimit(resource.RLIMIT_CPU, (80, 80)); "
        "limit_resources(2**30, 95, 2**30); "
        "print('%d/%d' % resource.getrlimit(resource.RLIMIT_CPU))"
    )
    res = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        encoding="utf-8",
        cwd=_isolated._APP_ROOT,
        check=True,
    )
    assert res.stdout.split() == ["80/80"]


@pytest.mark.skipif(sys.platform != "linux", reason="the limits apply on Linux")
def test_a_child_that_ignores_sigxcpu_is_killed_at_its_cpu_limit():
    probe = "\n".join(
        [
            "import signal",
            "from app.converters._isolated import limit_resources",
            "limit_resources(2**30, 1, 2**30)",
            "signal.signal(signal.SIGXCPU, signal.SIG_IGN)",
            "while True:",
            "    pass",
        ]
    )
    res = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        encoding="utf-8",
        cwd=_isolated._APP_ROOT,
        timeout=30,
        check=False,
    )
    assert res.returncode == -signal.SIGKILL, res.stderr


# ── Within the child's memory limit ──────────────────────────────────────────


@pytest.mark.parametrize("converter", [CsvToJsonConverter, CsvToXlsxConverter])
def test_a_csv_is_read_row_by_row(tmp_path, converter):
    """A CSV is converted row by row: the memory taken grows with the longest
    row, not with the file."""
    src, tiny = tmp_path / "in.csv", tmp_path / "tiny.csv"
    # 8 MB in 16,000 cells, every row different
    src.write_bytes(b"a,b\n" + b"".join((b"%07d" % i) * 143 + b",1\n" for i in range(8000)))
    tiny.write_bytes(b"a,b\n1,2\n")
    converter().convert(tiny, tmp_path / "warm-up")  # lazy imports happen here
    tracemalloc.start()
    try:
        converter().convert(src, tmp_path / "out")
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert peak < src.stat().st_size // 4


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
    _, _, memory, seconds, file_bytes = _isolated._STEPS["convert"]
    assert seen["command"][:7] == [
        *(sys.executable, "-m", "app.converters._isolated", "convert"),
        *(str(memory), str(seconds), str(file_bytes)),
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
        ('{"error": "out_of_memory"}', 0, _isolated.TooComplexError, _TOO_LARGE),
        ("", -9, _isolated.TooComplexError, _TOO_LARGE),  # stopped by a limit
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
    assert type(excinfo.value) is error  # e.g. the child's own message is no TooComplexError
    assert message in str(excinfo.value)


@pytest.mark.parametrize(("error_type", "logged"), [("KeyError", "KeyError"), ("a b/c", "-")])
def test_an_unexpected_child_error_is_logged_by_type(
    tmp_path, monkeypatch, caplog, error_type, logged
):
    stdout = json.dumps({"error": "failed", "type": error_type})
    monkeypatch.setattr(subprocess, "run", _fake_child(stdout))
    with caplog.at_level(logging.WARNING, logger="app.converters._isolated"):
        with pytest.raises(RuntimeError):
            _isolated.run_isolated("convert", too_large=_TOO_LARGE, tmp_dir=tmp_path)
    assert f"isolated convert failed (status 0): {logged}" in caplog.messages
