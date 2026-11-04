# SPDX-License-Identifier: AGPL-3.0-or-later
"""docker-compose.cloud.yml: the app's database login and the postgres
service's restrictions.

By default the app logs in as the superuser the postgres image creates. With
POSTGRES_APP_USER and POSTGRES_APP_PASSWORD in .env it logs in as a role that
is no superuser (docs/self-hosting.md, "Without the database superuser"). The
password falls back through a nested default, ``${A:-${B:-c}}``, so the
rendering test below runs Docker Compose itself: a Compose that read it
differently fails here, not on an installation. It skips where Docker Compose
is missing, except on CI.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parent.parent
_FILES = ("docker-compose.yml", "docker-compose.cloud.yml")


def _services() -> dict:
    text = (_ROOT / "docker-compose.cloud.yml").read_text(encoding="utf-8")
    return yaml.safe_load(text)["services"]


def test_postgres_keeps_only_the_capabilities_its_entrypoint_needs():
    postgres = _services()["postgres"]
    assert postgres["security_opt"] == ["no-new-privileges:true"]
    assert postgres["cap_drop"] == ["ALL"]
    # Not DAC_READ_SEARCH in place of DAC_OVERRIDE: with it, Docker's seccomp
    # profile allows open_by_handle_at.
    assert sorted(postgres["cap_add"]) == ["CHOWN", "DAC_OVERRIDE", "SETGID", "SETUID"]
    assert "privileged" not in postgres
    # max_connections (100) plus the server's own processes must fit.
    assert 128 <= postgres["pids_limit"] <= 1024
    assert postgres["ulimits"] == {"core": 0}


def test_the_app_container_gets_no_superuser_password():
    assert _services()["filemorph"]["environment"]["POSTGRES_PASSWORD"] == ""


def test_the_docs_section_the_compose_files_name_exists():
    docs = (_ROOT / "docs" / "self-hosting.md").read_text(encoding="utf-8")
    assert "### Without the database superuser" in docs
    for name in ("docker-compose.cloud.yml", ".github/workflows/ci.yml"):
        assert '"Without the database superuser"' in (_ROOT / name).read_text(encoding="utf-8")


def _compose() -> list[str] | None:
    docker = shutil.which("docker")
    if docker is None:
        return None
    probe = subprocess.run(
        [docker, "compose", "version"], capture_output=True, text=True, encoding="utf-8"
    )
    return [docker, "compose"] if probe.returncode == 0 else None


@pytest.mark.parametrize(
    ("env", "login"),
    [
        ({"POSTGRES_PASSWORD": "pw1"}, "filemorph:pw1"),
        (
            {
                "POSTGRES_PASSWORD": "pw1",
                "POSTGRES_APP_USER": "filemorph_app",
                "POSTGRES_APP_PASSWORD": "pw2",
            },
            "filemorph_app:pw2",
        ),
        ({}, "filemorph:changeme"),
    ],
    ids=["superuser", "app-role", "nothing-set"],
)
def test_compose_renders_the_database_login(tmp_path, env, login):
    compose = _compose()
    if compose is None:
        if os.environ.get("CI"):
            pytest.fail("Docker Compose is missing; on CI this test has to run")
        pytest.skip("Docker Compose is not installed")
    # Copies without a .env next to them: only `env` reaches the interpolation.
    for name in _FILES:
        shutil.copy(_ROOT / name, tmp_path / name)
    child = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("POSTGRES_", "COMPOSE_")) and k != "JWT_SECRET"
    }
    child.update({"JWT_SECRET": "x" * 32, **env})
    rendered = subprocess.run(
        [*compose, "-f", _FILES[0], "-f", _FILES[1], "config", "--format", "json"],
        cwd=tmp_path,
        env=child,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert rendered.returncode == 0, rendered.stderr
    environment = json.loads(rendered.stdout)["services"]["filemorph"]["environment"]
    assert environment["DATABASE_URL"] == f"postgresql+asyncpg://{login}@postgres/filemorph"
    assert environment["POSTGRES_PASSWORD"] == ""
