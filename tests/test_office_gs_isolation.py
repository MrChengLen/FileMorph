# SPDX-License-Identifier: AGPL-3.0-or-later
"""The office-image DOCX→PDF path runs LibreOffice without reaching Ghostscript.

On the ``filemorph:office`` image, a complex DOCX is rendered by a LibreOffice
(``soffice``) subprocess. That subprocess is run with a reduced environment as
defense-in-depth: application secrets are dropped from it, and a Ghostscript
stub is prepended to its ``PATH`` so it cannot start the real ``gs``.
FileMorph's own PDF/A path resolves Ghostscript in the app process and must
keep working; the pure-Python (mammoth) path is unaffected.

These tests fake ``shutil.which``/``subprocess.run`` so the wiring is asserted
on any platform, with no real ``soffice`` or ``gs`` installed. The real office
image is exercised end-to-end in ``.github/workflows/docker-pr.yml``.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

from app.converters import _ghostscript, document


def test_gs_binary_names_are_a_single_source_of_truth():
    # document.py neutralises exactly the names _ghostscript.py would find —
    # the same object, so the two cannot drift apart.
    assert document._GS_BINARY_NAMES is _ghostscript._GS_BINARY_NAMES
    assert "gs" in document._GS_BINARY_NAMES


def test_is_secret_env_name_flags_app_secrets_not_libreoffice_vars():
    for name in (
        "JWT_SECRET",
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "SMTP_PASSWORD",
        "SMTP_USERNAME",
        "DATABASE_URL",
        "ANTHROPIC_API_KEY",  # a future AI-provider key — caught by the KEY substring
        "jwt_secret",  # case-insensitive
    ):
        assert document._is_secret_env_name(name), name
    # None of LibreOffice's / fontconfig's own vars contain a secret fragment.
    for name in (
        "HOME",
        "LANG",
        "LC_ALL",
        "PATH",
        "TMPDIR",
        "XDG_RUNTIME_DIR",
        "FONTCONFIG_PATH",
        "USER",
    ):
        assert not document._is_secret_env_name(name), name


def test_denial_shims_are_written_for_every_gs_name(tmp_path):
    shim_dir = tmp_path / ".nogs"
    document._write_ghostscript_denial_shims(shim_dir)
    for name in document._GS_BINARY_NAMES:
        shim = shim_dir / name
        assert shim.is_file(), name
        assert shim.read_text() == "#!/bin/sh\nexit 127\n"
        if os.name == "posix":
            assert shim.stat().st_mode & stat.S_IXUSR, f"{name} not executable"


def test_child_env_prepends_shims_and_drops_secrets(monkeypatch, tmp_path):
    shim_dir = tmp_path / ".nogs"
    real_gs_dir = str(tmp_path / "usr-bin")
    monkeypatch.setenv("PATH", os.pathsep.join([str(tmp_path / "venv"), real_gs_dir]))
    monkeypatch.setenv("JWT_SECRET", "super-secret-value")
    monkeypatch.setenv("HOME", "/home/appuser")

    document._write_ghostscript_denial_shims(shim_dir)
    env = document._soffice_child_env(shim_dir)

    # Shim dir is first on PATH; the real /usr/bin is still present after it.
    entries = env["PATH"].split(os.pathsep)
    assert entries[0] == str(shim_dir)
    assert real_gs_dir in entries  # /usr/bin kept — only gs is shadowed
    # Secrets dropped, non-secrets kept.
    assert "JWT_SECRET" not in env
    assert env.get("HOME") == "/home/appuser"
    # The app process environment is untouched.
    assert os.environ["JWT_SECRET"] == "super-secret-value"


def test_convert_via_libreoffice_runs_soffice_with_hardened_env(monkeypatch, tmp_path):
    """The routing guard the hardening turns on: ``soffice`` is invoked with a
    Ghostscript stub ahead of any real gs, app secrets stripped, documented
    flags, and no shell."""
    real_gs_dir = str(tmp_path / "usr-bin")
    fake_soffice = str(tmp_path / "soffice")
    monkeypatch.setenv("PATH", os.pathsep.join([str(tmp_path / "venv"), real_gs_dir]))
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_live_do_not_leak")

    def fake_which(cmd, path=None):
        if cmd == "soffice" and path is None:
            return fake_soffice
        return None

    monkeypatch.setattr(document.shutil, "which", fake_which)

    calls = {}

    def fake_run(argv, **kwargs):
        calls["argv"] = argv
        calls["kwargs"] = kwargs
        # The gs stub must exist on the child PATH at invocation time, ahead of
        # the real gs dir, so a child looking up gs by name hits the stub.
        shim_first = kwargs["env"]["PATH"].split(os.pathsep)[0]
        assert (Path(shim_first) / "gs").is_file(), "gs stub missing at call time"
        outdir = Path(argv[argv.index("--outdir") + 1])
        (outdir / f"{Path(argv[-1]).stem}.pdf").write_bytes(b"%PDF-1.7\n")
        return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")

    monkeypatch.setattr(document.subprocess, "run", fake_run)

    src = tmp_path / "in.docx"
    src.write_bytes(b"PK\x03\x04")  # the fake runner never reads it
    out = tmp_path / "out.pdf"

    document._convert_via_libreoffice(src, out, timeout_s=42)

    assert out.read_bytes().startswith(b"%PDF")

    argv = calls["argv"]
    assert argv[0] == fake_soffice
    assert "--headless" in argv
    assert "pdf:writer_pdf_Export" in argv

    kwargs = calls["kwargs"]
    assert kwargs["check"] is False
    assert kwargs["capture_output"] is True
    assert kwargs["timeout"] == 42
    assert kwargs.get("shell", False) is False  # run() defaults to no shell

    env = kwargs["env"]
    assert "STRIPE_SECRET_KEY" not in env  # secret stripped from the child
    assert real_gs_dir in env["PATH"].split(os.pathsep)  # /usr/bin kept intact
    # The staging dir (shims included) is cleaned up after the call.
    assert not (out.parent / f".soffice_{out.stem}").exists()
    # The app process keeps its secret and PATH.
    assert os.environ["STRIPE_SECRET_KEY"] == "sk_live_do_not_leak"


def test_building_child_env_does_not_mutate_the_process_and_stub_is_discoverable(tmp_path):
    """Building the child env leaves ``os.environ`` untouched (so FileMorph's
    own in-process gs lookup is unaffected), and on POSIX the stub resolves as
    ``gs`` — i.e. a child with the shim dir first on PATH would hit it."""
    before = dict(os.environ)
    shim_dir = tmp_path / ".nogs"
    document._write_ghostscript_denial_shims(shim_dir)
    document._soffice_child_env(shim_dir)
    assert dict(os.environ) == before
    if os.name == "posix":
        assert shutil.which("gs", path=str(shim_dir)) == str(shim_dir / "gs")
