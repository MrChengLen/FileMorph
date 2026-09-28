# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Cloud Edition refuses to start with a public or short ``JWT_SECRET``.

With ``DATABASE_URL`` set the app runs user accounts, and every login is an
HS256 JWT signed with ``settings.jwt_secret``. The code default and the value
``docker-compose.cloud.yml`` used to fill in are published, so with either one
anyone who knows a user's id can sign a valid login token for that account.
Since PR #144 a self-built image no longer carries a ``.env``: a
``docker run`` that passed ``DATABASE_URL`` but not ``JWT_SECRET`` booted
with the default, and nothing said so.

The boot tests import ``app.main`` in a fresh interpreter, which is the first
thing an ASGI server does; this test session imported it long ago, without
``DATABASE_URL``. The Community Edition (no ``DATABASE_URL``) issues no
logins and keeps booting without ``JWT_SECRET``.
"""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from app.core.config import Settings, jwt_secret_error

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Importing the app only builds the engine; nothing connects to this.
_CLOUD_DB = "postgresql+asyncpg://filemorph:unused@127.0.0.1:1/filemorph"

# What docker-compose.cloud.yml filled in for an unset JWT_SECRET until 2026-09.
_OLD_COMPOSE_FALLBACK = "change-me-in-production-min-32-chars"


def _boot(tmp_path: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Import ``app.main`` in a fresh interpreter with exactly ``env`` on top.

    Runs in ``tmp_path`` so no developer ``.env`` is read, and drops any
    ``DATABASE_URL``/``JWT_SECRET`` the test runner itself carries.
    """
    child_env = {k: v for k, v in os.environ.items() if k not in ("DATABASE_URL", "JWT_SECRET")}
    child_env["PYTHONPATH"] = os.pathsep.join(
        filter(None, [str(_REPO_ROOT), os.environ.get("PYTHONPATH")])
    )
    child_env.update(env)
    return subprocess.run(
        [sys.executable, "-c", "import app.main"],
        cwd=tmp_path,
        env=child_env,
        capture_output=True,
        encoding="utf-8",
        timeout=180,
    )


def test_cloud_boot_without_jwt_secret_is_refused(tmp_path):
    """The PR #144 scenario: accounts on, ``JWT_SECRET`` never arrived.

    Exit code 3 is what uvicorn and gunicorn treat as a failed start: a
    multi-worker server then stops instead of restarting the workers forever.
    Without a traceback, the message can only come from the log line.
    """
    result = _boot(tmp_path, {"DATABASE_URL": _CLOUD_DB})

    assert result.returncode == 3, result.stderr
    assert "Refusing to start" in result.stderr
    assert "JWT_SECRET" in result.stderr


@pytest.mark.parametrize(
    "env",
    [
        pytest.param({}, id="community-edition-without-jwt-secret"),
        pytest.param(
            {"DATABASE_URL": _CLOUD_DB, "JWT_SECRET": secrets.token_urlsafe(32)},
            id="cloud-edition-with-random-secret",
        ),
    ],
)
def test_boot_succeeds(tmp_path, env):
    result = _boot(tmp_path, env)

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(Settings.model_fields["jwt_secret"].default, id="code-default"),
        pytest.param(_OLD_COMPOSE_FALLBACK, id="old-compose-fallback"),
        # docker run --env-file passes quotes and trailing spaces on verbatim.
        pytest.param(f'"{_OLD_COMPOSE_FALLBACK}"', id="quoted-placeholder"),
        pytest.param(f"{_OLD_COMPOSE_FALLBACK} ", id="placeholder-with-trailing-space"),
        pytest.param("x" * 31, id="31-characters"),
        pytest.param("", id="empty"),
    ],
)
def test_published_or_short_secret_is_rejected(value):
    assert jwt_secret_error(value) is not None


def test_other_secret_of_32_characters_is_accepted():
    assert jwt_secret_error("x" * 32) is None


def test_error_says_what_to_set_where_without_quoting_the_secret():
    value = "short-" + secrets.token_hex(4)

    error = jwt_secret_error(value)

    assert value not in error
    assert "JWT_SECRET" in error
    assert ".env.example" in error
    assert "docs/self-hosting.md" in error


def test_cloud_compose_overlay_has_no_jwt_secret_fallback():
    """A default here would put every compose deployment on a published secret.

    ``${JWT_SECRET:?…}`` makes ``docker compose`` stop with a message instead;
    a fallback of 32+ characters would even get past the app's own check.
    """
    compose = yaml.safe_load((_REPO_ROOT / "docker-compose.cloud.yml").read_text(encoding="utf-8"))
    value = compose["services"]["filemorph"]["environment"]["JWT_SECRET"]

    assert value.startswith("${JWT_SECRET:?"), value


def test_env_example_sets_no_jwt_secret():
    """Every Compose user copies ``.env.example`` to ``.env``, so a value there is
    public; this file is where the published default used to come from."""
    for line in (_REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "JWT_SECRET":
            assert not value.strip(), ".env.example must leave JWT_SECRET empty or commented"
