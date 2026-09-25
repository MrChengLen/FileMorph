# SPDX-License-Identifier: AGPL-3.0-or-later
"""Supply-chain hygiene regression guards (PR-S).

These tests pin the *posture* established in PR-S so a later edit can't
silently undo it:

  * every ``uses:`` in a GitHub Actions workflow is pinned to a 40-hex
    commit SHA (a mutable ``@v4`` tag is a supply-chain foothold —
    OpenSSF Scorecard "Pinned-Dependencies");
  * the Dockerfile base image is pinned by ``@sha256:`` digest, with the
    human-readable tag kept in a trailing comment so Dependabot's
    ``docker`` ecosystem can still propose bumps;
  * every workflow declares an explicit ``permissions:`` block (top-level
    or per-job) so ``GITHUB_TOKEN`` is least-privilege rather than the
    repo-wide default (OpenSSF Scorecard "Token-Permissions");
  * ``.github/dependabot.yml`` exists and covers all three ecosystems we
    pin manually (``pip`` / ``github-actions`` / ``docker``) so the pins
    above don't rot;
  * what CI tests, validates and publishes is the lockfile's dependency set —
    the test job installs with the lockfile as constraints, and the SBOM and
    veraPDF workflows install it the way the image does.

This is a tripwire, not a substitute for the server-side Scorecard run /
review: the per-job permissions check here is a heuristic (it asserts a
``permissions:`` key is *present*, not that every job in a multi-job
workflow carries one). The point is to catch a brand-new workflow added
with no permissions block at all, or a SHA pin reverted to a tag.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOW_DIR = _REPO_ROOT / ".github" / "workflows"
_DOCKERFILE = _REPO_ROOT / "Dockerfile"
_DEPENDABOT = _REPO_ROOT / ".github" / "dependabot.yml"
_LOCKFILE = _REPO_ROOT / "requirements.lock"

_SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
# `uses: owner/repo@ref` or `uses: owner/repo/path@ref`, tolerating a
# trailing `# vX.Y` comment after the ref. Local actions
# (`uses: ./.github/actions/foo`) have no `@ref` and are exempt — they're
# part of this repo, not a third party.
_USES_RE = re.compile(r"uses:\s*(?P<spec>[^@\s]+)@(?P<ref>[^\s#]+)")
_TOP_LEVEL_PERMISSIONS_RE = re.compile(r"^permissions:", re.MULTILINE)
_JOB_LEVEL_PERMISSIONS_RE = re.compile(r"^ {4}permissions:", re.MULTILINE)
# FROM line with a digest pin, e.g. `FROM python:3.12-slim@sha256:<64 hex>`.
_FROM_DIGEST_RE = re.compile(r"^FROM\s+\S+@sha256:[0-9a-f]{64}\b", re.MULTILINE)
_FROM_ANY_RE = re.compile(r"^FROM\s+\S+", re.MULTILINE)


def _workflow_files() -> list[Path]:
    files = sorted(_WORKFLOW_DIR.glob("*.yml")) + sorted(_WORKFLOW_DIR.glob("*.yaml"))
    assert files, f"no workflow files found under {_WORKFLOW_DIR}"
    return files


def _workflow_code(name: str) -> str:
    """A workflow's text without its comment lines, which quote old commands."""
    lines = (_WORKFLOW_DIR / name).read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in lines if not line.lstrip().startswith("#"))


def test_workflow_dir_exists() -> None:
    assert _WORKFLOW_DIR.is_dir(), f"{_WORKFLOW_DIR} missing"


@pytest.mark.parametrize("workflow", _workflow_files(), ids=lambda p: p.name)
def test_workflow_actions_are_sha_pinned(workflow: Path) -> None:
    text = workflow.read_text(encoding="utf-8")
    matches = list(_USES_RE.finditer(text))
    if not matches:
        # Workflows that only `run:` shell steps (e.g. notify-ops.yml) have
        # no third-party actions to pin — nothing to assert.
        pytest.skip(f"{workflow.name}: no `uses:` third-party actions")
    for m in matches:
        spec, ref = m.group("spec"), m.group("ref")
        # Local composite actions (`./.github/actions/...`) are first-party.
        if spec.startswith("./") or spec.startswith("."):
            continue
        assert _SHA40_RE.match(ref), (
            f"{workflow.name}: `uses: {spec}@{ref}` is not pinned to a "
            f"40-character commit SHA. Pin it (keep the `# vX.Y` comment for "
            f"Dependabot) — a mutable tag is a supply-chain foothold."
        )


@pytest.mark.parametrize("workflow", _workflow_files(), ids=lambda p: p.name)
def test_workflow_declares_permissions(workflow: Path) -> None:
    text = workflow.read_text(encoding="utf-8")
    has_top = bool(_TOP_LEVEL_PERMISSIONS_RE.search(text))
    has_job = bool(_JOB_LEVEL_PERMISSIONS_RE.search(text))
    assert has_top or has_job, (
        f"{workflow.name}: no `permissions:` block (top-level or per-job). "
        f"Declare least-privilege scopes for GITHUB_TOKEN — default to "
        f"`permissions:\\n  contents: read` and widen only where a step "
        f"genuinely needs it."
    )


def test_dockerfile_base_image_is_digest_pinned() -> None:
    text = _DOCKERFILE.read_text(encoding="utf-8")
    from_lines = _FROM_ANY_RE.findall(text)
    assert from_lines, "Dockerfile has no FROM line"
    assert _FROM_DIGEST_RE.search(text), (
        "Dockerfile base image is not pinned by @sha256: digest. Pin it and "
        "keep the tag in a comment on the line directly above (e.g. "
        "`# Pinned to python:3.12-slim`\\n`FROM python:3.12-slim@sha256:<digest> "
        "AS builder`) so Dependabot's docker ecosystem can still propose "
        "digest bumps."
    )
    # The Dependabot docker updater reads the tag-comment either inline on the
    # FROM line OR on the line directly above it. Dockerfile syntax does NOT
    # support trailing comments on directives — BuildKit counts a trailing
    # `# tag` as a fourth argument and rejects the FROM with `FROM requires
    # either one or three arguments`. The preceding-line form is therefore the
    # only one that works with both BuildKit and Dependabot; either form
    # satisfies this guard, but in practice we use the preceding-line form.
    lines = text.splitlines()
    from_idx = next(i for i, line in enumerate(lines) if line.startswith("FROM "))
    from_line = lines[from_idx]
    prev_line = lines[from_idx - 1] if from_idx > 0 else ""
    has_inline_comment = "#" in from_line
    has_preceding_comment = prev_line.lstrip().startswith("#")
    assert has_inline_comment or has_preceding_comment, (
        "digest-pinned FROM line must carry a `# <tag>` comment — either inline "
        "on the FROM line or on the line directly above it — so Dependabot "
        "knows which tag the digest maps to. Note: Dockerfile syntax does not "
        "allow trailing comments on directives; use the preceding-line form."
    )


def test_dockerfile_installs_from_the_hash_pinned_lockfile() -> None:
    """The image must install from ``requirements.lock``, not the manifest.

    ``requirements.txt`` carries ``>=`` constraints, so installing from it
    makes every build pull whatever is newest — no reproducibility, and the
    lockfile's hashes guard nothing. That was the state until the lockfile
    had drifted four packages behind without anyone noticing, because nothing
    consumed it and nothing compared it.
    """
    text = _DOCKERFILE.read_text(encoding="utf-8")
    install_lines = [
        line for line in text.splitlines() if "pip install" in line and "requirements" in line
    ]
    assert install_lines, "Dockerfile installs no requirements file at all"
    for line in install_lines:
        assert "requirements.lock" in line, (
            f"Dockerfile installs from the manifest rather than the lockfile: "
            f"{line.strip()!r}. Use `pip install --require-hashes -r "
            f"requirements.lock` — requirements.txt only states minimum "
            f"versions, so builds from it are not reproducible."
        )
        assert "--require-hashes" in line, (
            f"lockfile install is missing --require-hashes: {line.strip()!r}. "
            f"Without it pip will happily install an unhashed or unpinned "
            f"requirement, which defeats the point of the lockfile."
        )


def test_lockfile_is_hash_pinned_and_matches_the_image_python() -> None:
    """Every lockfile entry carries a hash, resolved for the shipped Python.

    A lockfile is only valid for the Python version it targets — environment
    markers resolve per version — so one resolved elsewhere can be
    uninstallable in the image. ``uv pip compile --python-version`` records
    the target in the header, which is what this reads.
    ``scripts/check_python_version.py`` is the CI gate; this is the
    regression guard for the posture itself.
    """
    assert _LOCKFILE.is_file(), (
        "requirements.lock missing, but the Dockerfile installs from it. "
        "Regenerate it with the deps-lock workflow."
    )
    text = _LOCKFILE.read_text(encoding="utf-8")
    assert "--hash=sha256:" in text, (
        "requirements.lock carries no hashes — regenerate it with "
        "`pip-compile --generate-hashes`, or --require-hashes in the "
        "Dockerfile will reject it."
    )
    shipped = _FROM_DIGEST_RE.search(_DOCKERFILE.read_text(encoding="utf-8"))
    assert shipped, "Dockerfile has no digest-pinned FROM line"
    version = re.search(r"python:(\d+\.\d+)-slim", shipped.group(0))
    assert version, "could not read the Python version from the Dockerfile FROM line"
    header = re.search(r"--python-version[= ](\d+\.\d+)", text)
    assert header, (
        "requirements.lock records no `--python-version X.Y` — it was not produced "
        "by `uv pip compile --python-version`, so which interpreter it is valid "
        "for is unknown."
    )
    assert header.group(1) == version.group(1), (
        f"requirements.lock targets Python {header.group(1)} but the image ships "
        f"{version.group(1)}. Regenerate it for the shipped version; markers "
        f"resolve differently per version."
    )


def test_ci_tests_run_against_the_locked_versions() -> None:
    """lint-and-test installs with the lockfile as constraints.

    requirements-dev.txt pulls in requirements.txt, whose ``>=`` ranges
    resolve to the newest releases — that is how CI came to test SQLAlchemy
    2.1.0 while the image shipped 2.0.52. The unpinned install is the early
    warning in ``deps-latest.yml``, not the gate.
    """
    text = _workflow_code("ci.yml")
    installs = [
        line.strip()
        for line in text.splitlines()
        if re.search(r"pip install .*-r requirements(-dev)?\.txt", line)
    ]
    assert installs, "ci.yml no longer installs requirements-dev.txt — update this guard"
    for line in installs:
        assert re.search(r"\s-c\s", line), (
            f"ci.yml installs a manifest without constraints: {line!r}. "
            f"Tests would run against the newest releases, not what the image ships."
        )
    assert re.search(r"requirements\.lock.*>.*constraints", text), (
        "ci.yml's constraints are no longer derived from requirements.lock"
    )


def test_deps_latest_mirrors_lint_and_test() -> None:
    """deps-latest differs from lint-and-test only in the pinning.

    Otherwise a system package or pytest option added to ci.yml alone turns the
    weekly run red, and its header tells the reader to blame an upstream
    release.
    """
    ci, latest = _workflow_code("ci.yml"), _workflow_code("deps-latest.yml")
    for pattern in (r"apt-get install -y .*", r"pytest tests/.*"):
        assert re.findall(pattern, latest) == re.findall(pattern, ci), (
            f"deps-latest.yml and ci.yml disagree on `{pattern}` — keep them in step"
        )


@pytest.mark.parametrize("workflow", ["sbom.yml", "release.yml", "verapdf.yml"])
def test_workflow_installs_what_the_image_ships(workflow: str) -> None:
    """The SBOM lists, and veraPDF validates, the image's dependency set.

    Installing requirements.txt resolves its ``>=`` ranges to the newest
    releases: the SBOM published from main listed 19 of the 77 shipped
    packages at versions the image does not contain.
    """
    text = _workflow_code(workflow)
    assert "install --require-hashes -r requirements.lock" in text, (
        f"{workflow} does not install requirements.lock the way the Dockerfile does"
    )
    assert not re.search(r"-r requirements(-dev)?\.txt", text), (
        f"{workflow} installs the manifest — its `>=` ranges resolve to versions "
        f"the image does not ship. Install requirements.lock with --require-hashes."
    )


@pytest.mark.parametrize("workflow", ["sbom.yml", "release.yml"])
def test_sbom_describes_the_lockfile_venv_only(workflow: str) -> None:
    """``cyclonedx-py environment`` reads the lockfile venv, not its own.

    Without an interpreter argument it describes the Python it runs in, which
    holds the generator too: 28 packages of its own in the SBOM, and a
    ``packaging`` its install had downgraded below the shipped version.
    """
    text = _workflow_code(workflow)
    target = re.search(r'cyclonedx-py environment\s+"?([^\s"\\]+)/bin/python', text)
    assert target, f"{workflow}: cyclonedx-py environment is not given a venv to describe"
    venv = re.escape(target.group(1))
    assert re.search(venv + r'/bin/pip"? install --require-hashes -r requirements\.lock', text), (
        f"{workflow}: the venv the SBOM describes is not the one requirements.lock is installed into"
    )
    assert len(re.findall(venv + r'/bin/pip"? install', text)) == 1, (
        f"{workflow}: something besides requirements.lock is installed into the SBOM's venv"
    )


def test_dependabot_config_covers_all_pinned_ecosystems() -> None:
    assert _DEPENDABOT.is_file(), (
        ".github/dependabot.yml missing — the manual SHA/digest pins will rot "
        "without an automated bump PR cadence."
    )
    text = _DEPENDABOT.read_text(encoding="utf-8")
    for ecosystem in ("pip", "github-actions", "docker"):
        assert f'package-ecosystem: "{ecosystem}"' in text, (
            f"dependabot.yml does not configure the `{ecosystem}` ecosystem — "
            f"we SHA/digest-pin it manually, so it must have a Dependabot entry."
        )
