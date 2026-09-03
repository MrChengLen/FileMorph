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
    above don't rot.

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
    """Every lockfile entry carries a hash, compiled on the shipped Python.

    A lockfile is only valid for the Python version it was compiled on —
    environment markers resolve per version — so one compiled elsewhere can
    be uninstallable in the image. ``scripts/check_python_version.py`` is the
    CI gate for that; this is the regression guard for the posture itself.
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
    header = re.search(r"pip-compile with Python (\d+\.\d+)", text)
    assert header, (
        "requirements.lock has no `pip-compile with Python X.Y` header — it was "
        "not generated by pip-compile, so its provenance is unknown."
    )
    assert header.group(1) == version.group(1), (
        f"requirements.lock was compiled on Python {header.group(1)} but the image "
        f"ships {version.group(1)}. Regenerate it on the shipped version via the "
        f"deps-lock workflow; markers resolve differently per version."
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
