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

Docker starts ``docker-compose.yml``'s health check the way it starts a
``docker exec`` command, with the container's environment. The check runs
curl, whose program is execute-only too, and runs it directly, without a shell
``appuser`` could read; with all capabilities dropped, as the Compose file
does, the process Docker starts it from can't read curl's program either.

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


@pytest.mark.parametrize("program", ["tini", "curl"])
def test_program_is_installed_execute_only(program):
    base = _stage("base")
    assert re.search(rf"^\s+{program}\b", base, re.M), f"the base stage does not install {program}"
    override = re.search(
        rf"dpkg-statoverride --update --add root root (\d{{4}}) /usr/bin/{program} &&", base
    )
    assert override, f"the base stage gives /usr/bin/{program} no mode of its own"
    assert override.group(1) == "0711", f"mode {override.group(1)}, not 0711 (execute-only)"


def test_compose_drops_all_capabilities_as_docker_pr_does():
    # With a capability such as CAP_DAC_OVERRIDE, the process Docker starts
    # the health check's curl from could read its program. docker-pr.yml
    # checks curl in a container started with these options.
    compose = yaml.safe_load((_REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    assert compose["services"]["filemorph"]["cap_drop"] == ["ALL"]
    workflow = (_REPO_ROOT / ".github" / "workflows" / "docker-pr.yml").read_text(encoding="utf-8")
    assert "--cap-drop ALL --security-opt no-new-privileges" in workflow


@pytest.mark.parametrize("compose", sorted(p.name for p in _REPO_ROOT.glob("docker-compose*.yml")))
def test_compose_keeps_the_health_check_non_dumpable(compose):
    # A shell (CMD-SHELL, or the test as a string) would run first, with the
    # container's environment and a program appuser can read; a capability
    # added back could let the process Docker starts curl from read curl's.
    services = yaml.safe_load((_REPO_ROOT / compose).read_text(encoding="utf-8"))["services"]
    service = services["filemorph"]
    assert "cap_add" not in service and "privileged" not in service, compose
    test = service.get("healthcheck", {}).get("test", ["CMD", "curl"])
    assert test[:2] == ["CMD", "curl"], f"{compose}: {test}"


@pytest.mark.parametrize("compose", sorted(p.name for p in _REPO_ROOT.glob("docker-compose*.yml")))
def test_compose_adds_no_init_of_its_own(compose):
    services = yaml.safe_load((_REPO_ROOT / compose).read_text(encoding="utf-8"))["services"]
    assert "init" not in services["filemorph"], (
        f"{compose}: Docker's init would run ahead of tini, and its environment is readable"
    )
