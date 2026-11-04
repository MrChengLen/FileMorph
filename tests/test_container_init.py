# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Docker image runs under an init whose environment stays out of reach.

tini runs as PID 1 and starts ``entrypoint.sh``, which hands over to uvicorn
with ``exec``: tini passes the container's signals on to uvicorn and reaps
child processes that end after their parent. Like the app, it holds the
container's environment, the app's secrets with it. The app marks itself
non-dumpable (``app/main.py``); tini has no such setting, so its program is
execute-only for ``appuser``: the kernel makes a process non-dumpable when it
runs a program its user can't read, and ``env`` starts it without the
capabilities the container's first process holds. Docker's own init (``init: true``) would
run as PID 1 ahead of tini with the same environment, and its program is
readable.

The built image is checked in ``.github/workflows/docker-pr.yml``; these tests
keep the files it is built and started from in line with it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DOCKERFILE = (_REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")


def _stage(name: str) -> str:
    """The Dockerfile's stage ``name``, up to the next ``FROM``."""
    match = re.search(rf"^FROM \S+ AS {name}$(.*?)(?=^FROM |\Z)", _DOCKERFILE, re.M | re.S)
    assert match, f"Dockerfile: no stage {name!r}"
    return match.group(1)


def test_the_image_starts_entrypoint_sh_under_tini():
    # In the base stage, which the office stage builds on, and nowhere else.
    # Through env: the container's first process may hold CAP_DAC_OVERRIDE,
    # which would let it read tini's program; env, once it runs, holds none.
    assert re.findall(r"^ENTRYPOINT .*$", _DOCKERFILE, re.M) == [
        'ENTRYPOINT ["/usr/bin/env", "--", "/usr/bin/tini", "-e", "143", "--", "/app/entrypoint.sh"]'
    ]
    assert re.search(r"^ENTRYPOINT ", _stage("base"), re.M)
    # With exec, uvicorn takes over the shell's process: as tini's child, it
    # gets the signals tini passes on.
    script = (_REPO_ROOT / "entrypoint.sh").read_text(encoding="utf-8").splitlines()
    commands = [line for line in script if line.strip() and not line.lstrip().startswith("#")]
    assert commands[-1].startswith("exec uvicorn "), commands[-1]


def test_tini_is_installed_execute_only():
    base = _stage("base")
    assert re.search(r"^\s+tini\b", base, re.M), "the base stage does not install tini"
    override = re.search(
        r"dpkg-statoverride --update --add root root (\d{4}) /usr/bin/tini &&", base
    )
    assert override, "the base stage gives /usr/bin/tini no mode of its own"
    assert override.group(1) == "0711", f"mode {override.group(1)}, not 0711 (execute-only)"


@pytest.mark.parametrize("compose", sorted(p.name for p in _REPO_ROOT.glob("docker-compose*.yml")))
def test_compose_adds_no_init_of_its_own(compose):
    services = yaml.safe_load((_REPO_ROOT / compose).read_text(encoding="utf-8"))["services"]
    assert "init" not in services["filemorph"], (
        f"{compose}: Docker's init would run ahead of tini, and its environment is readable"
    )
