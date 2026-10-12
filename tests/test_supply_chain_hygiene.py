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
    repo-wide default (OpenSSF Scorecard "Token-Permissions"), and no job
    that runs on pull requests holds a write token or a secret;
  * ``.github/dependabot.yml`` exists and covers all three ecosystems we
    pin manually (``pip`` / ``github-actions`` / ``docker``) so the pins
    above don't rot;
  * what CI tests, validates and publishes is the lockfile's dependency set —
    the test job installs with the lockfile as constraints (the veraPDF gate is
    a step of it, so it validates those versions), and the SBOM workflows
    install it the way the image does; the jobs that recompile the lockfiles
    run the uv that requirements-dev.txt pins, hash-checked from
    requirements-uv.lock, and deps-lock.yml recompiles with read access only
    and pushes from a job that installs nothing;
  * the SBOM generator installs from its own hash-pinned lockfile, as wheels
    only, and in release.yml it runs in a job without write access — the job
    that holds ``contents: write`` installs nothing, restores no cache and
    keeps no credentials; no job holding a write token or a secret splices
    ``${{ }}`` into a script; the veraPDF validator image is pinned by
    digest; and the veraPDF gate is a step of the required ``lint-and-test``
    job, not a workflow of its own;
  * no job holding a write token or a secret restores or saves an Actions
    cache, docker.yml builds the image with ``no-cache: true``, and no buildx
    step anywhere uses a cache (no ``cache-from``/``cache-to``,
    ``cache-binary: false``);
  * docker.yml attests the SBOM to every image variant it pushes, by the
    digest its build step reports: the SBOM comes from sbom.yml's steps in a
    job that can only read, and the job that signs the attestation checks
    nothing out, installs nothing and runs only GitHub's own actions;
    docs/release-signing.md verifies it the way it is made;
  * only the slim image is tagged ``:latest``: docker.yml switches off
    metadata-action's automatic ``latest`` tag, which a release would
    otherwise add to the office image too.

This is a tripwire, not a substitute for the server-side Scorecard run /
review: the per-job permissions check here is a heuristic (it asserts a
``permissions:`` key is *present*, not that every job in a multi-job
workflow carries one). The point is to catch a brand-new workflow added
with no permissions block at all, or a SHA pin reverted to a tag.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOW_DIR = _REPO_ROOT / ".github" / "workflows"
_DOCKERFILE = _REPO_ROOT / "Dockerfile"
_DEPENDABOT = _REPO_ROOT / ".github" / "dependabot.yml"
_LOCKFILE = _REPO_ROOT / "requirements.lock"
_SBOM_MANIFEST = _REPO_ROOT / "requirements-sbom.txt"
_SBOM_LOCKFILE = _REPO_ROOT / "requirements-sbom.lock"
_REQUIREMENTS_DEV = _REPO_ROOT / "requirements-dev.txt"
_UV_LOCKFILE = _REPO_ROOT / "requirements-uv.lock"
# The `Install uv` step of every job that compiles a lockfile: the uv that
# requirements-dev.txt pins, from its hashed lockfile, as a wheel.
_UV_INSTALL = "pip install --require-hashes --only-binary :all: -r requirements-uv.lock"
# The steps release.yml and docker.yml copy from sbom.yml, the one that can be run.
_SBOM_STEPS = (
    "Install the image's dependency set",
    "Install CycloneDX generator",
    "Generate CycloneDX SBOM (JSON)",
)
_GENERATOR_INSTALL = "pip install --require-hashes --only-binary :all: -r requirements-sbom.lock"
# `pip install`, `"$VENV/bin/pip" install` and `python -m pip install`.
_PIP_INSTALL_RE = re.compile(r'\bpip"?\s+install\b')
# In a `run:` script: a package manager, a download, or the SBOM generator.
_INSTALLS_RE = re.compile(r'\b(?:pip[\d.]*|pipx|uvx?|npm|npx|curl|wget)"?\s|cyclonedx-py')
# The only actions that run in release.yml's job holding `contents: write`.
_RELEASE_WRITE_ACTIONS = (
    "actions/checkout@",
    "actions/download-artifact@",
    "softprops/action-gh-release@",
)
# The only actions that run in deps-lock.yml's job holding `contents: write`.
_DEPS_LOCK_WRITE_ACTIONS = ("actions/checkout@", "actions/download-artifact@")
# The only actions that run in a job that compiles a lockfile: any other could
# put a uv of its own first on PATH, ahead of the hash-checked one.
_COMPILE_JOB_ACTIONS = ("actions/checkout@", "actions/setup-python@", "actions/upload-artifact@")
# The events a pull request triggers.
_PULL_REQUEST_EVENTS = {
    "pull_request",
    "pull_request_review",
    "pull_request_review_comment",
    "pull_request_target",
}
# The only actions that run in docker.yml's job holding `attestations: write`,
# and the one command it runs: the registry login the attest action reads.
_ATTEST_ACTIONS = ("actions/download-artifact@", "actions/attest@")
_ATTEST_LOGIN = 'echo "$TOKEN" | docker login "$REGISTRY" --username "$ACTOR" --password-stdin'
_RELEASE_SIGNING_DOC = _REPO_ROOT / "docs" / "release-signing.md"

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
# `pip-audit ... -r <file>` (or `python -m pip_audit`, or `--requirement`), as
# CI runs it and the docs quote it: other flags may come first, and a trailing
# backslash may continue the line. The file name must end in a word character
# or hyphen, so a sentence's full stop is not captured.
_PIP_AUDIT_RE = re.compile(r"pip[-_]audit\b[^\n`]*?\s+(?:-r|--requirement)(?:\s+|=)([\w./-]*[\w-])")
# An image tag that starts with `v`, with or without the registry path in
# front (`filemorph:v1.2.3`, `filemorph:vX.Y.Z`). docker.yml pushes none.
_V_IMAGE_TAG_RE = re.compile(r"\bfilemorph:v", re.IGNORECASE)


def _workflow_files() -> list[Path]:
    files = sorted(_WORKFLOW_DIR.glob("*.yml")) + sorted(_WORKFLOW_DIR.glob("*.yaml"))
    assert files, f"no workflow files found under {_WORKFLOW_DIR}"
    return files


def _workflow_code(name: str) -> str:
    """A workflow's text without its comment lines, which quote old commands."""
    lines = (_WORKFLOW_DIR / name).read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in lines if not line.lstrip().startswith("#"))


def _workflow(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _steps(job: dict) -> list[dict]:
    return job.get("steps") or []


def _privileged(job: dict, workflow: dict) -> bool:
    """Whether a job holds a write token or a secret.

    Job-level ``permissions:`` replace the workflow's; neither means the
    repository default applies, which can be write-all. A secret other than
    ``GITHUB_TOKEN`` (a PAT that triggers a deploy, say) counts as well, in
    whatever form an expression reads it (``secrets.X``, ``secrets['X']``,
    ``toJSON(secrets)``), and so does a reusable-workflow call's ``secrets:``.
    """
    permissions = job.get("permissions", workflow.get("permissions"))
    if permissions is None or permissions == "write-all":
        return True
    if isinstance(permissions, dict) and "write" in permissions.values():
        return True
    if "secrets" in job:
        return True
    expressions = re.findall(r"\$\{\{(.*?)\}\}", json.dumps([workflow.get("env"), job]))
    # Context names are case-insensitive in expressions: `SECRETS.X` reads a secret too.
    return any(
        re.search(r"\bsecrets\b(?!\s*\.\s*GITHUB_TOKEN\b)", expression, re.IGNORECASE)
        for expression in expressions
    )


def _lock_entries(lockfile: Path) -> list[str]:
    """A lockfile's requirements, one line each: continuations joined, comments dropped."""
    joined = re.sub(r"\\\n", " ", lockfile.read_text(encoding="utf-8"))
    return [
        " ".join(line.split())
        for line in joined.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _lock_pins(lockfile: Path) -> dict[str, str]:
    """``{canonical name: version}`` for every ``name==version`` entry."""
    pins = {}
    for entry in _lock_entries(lockfile):
        found = re.match(r"([A-Za-z0-9._-]+)==(\S+)", entry)
        if found:
            pins[canonicalize_name(found.group(1))] = found.group(2)
    return pins


def _lock_python_version(lockfile: Path) -> str | None:
    found = re.search(r"--python-version[= ](\d+\.\d+)", lockfile.read_text(encoding="utf-8"))
    return found.group(1) if found else None


def _tracked_docs() -> list[str]:
    """The public docs: tracked Markdown at the top level and under docs/,
    CHANGELOG.md aside."""
    if not (_REPO_ROOT / ".git").exists():
        pytest.skip("not a git checkout (e.g. an unpacked release tarball)")
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "--", "*.md"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    ).stdout.split("\0")
    return [
        rel
        for rel in tracked
        if rel.endswith(".md")
        and ("/" not in rel or rel.startswith("docs/"))
        and rel != "CHANGELOG.md"
    ]


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


def test_ci_audits_the_lockfile_the_image_installs() -> None:
    """CI's pip-audit scans ``requirements.lock``, not the manifest.

    Auditing ``requirements.txt`` checks a dependency set nobody ships: its
    ``>=`` constraints resolve to the newest releases at audit time, so a CVE
    in an older version the image still carries would go unreported.
    """
    text = (_WORKFLOW_DIR / "ci.yml").read_text(encoding="utf-8")
    # Comment lines may quote an old command; only executed lines count.
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    targets = set(_PIP_AUDIT_RE.findall(code))
    assert targets, (
        "ci.yml runs no `pip-audit -r ...` step, but the public docs describe "
        "one as a blocking CVE gate."
    )
    assert targets == {_LOCKFILE.name}, (
        f"ci.yml audits {sorted(targets)}, but the image installs "
        f"{_LOCKFILE.name}. Audit the lockfile — it is what reaches production."
    )


def test_docs_quote_the_lockfile_as_the_pip_audit_target() -> None:
    """Every ``pip-audit -r`` command in the public docs names the lockfile.

    When CI moved to the lockfile (2026-09-09), four docs — the DPA's TOM
    annex among them — kept quoting ``pip-audit -r requirements.txt`` for more
    than two weeks. Only tracked files count: a checkout can hold untracked
    local notes (e.g. a gitignored CLAUDE.md). CHANGELOG.md records history
    and is not checked.
    """
    stale = [
        f"{rel}: pip-audit -r {target}"
        for rel in _tracked_docs()
        for target in _PIP_AUDIT_RE.findall((_REPO_ROOT / rel).read_text(encoding="utf-8"))
        if target != _LOCKFILE.name
    ]
    assert not stale, (
        f"docs quote a pip-audit target other than {_LOCKFILE.name}, the file "
        f"CI audits and the image installs: {stale}"
    )


def test_docs_name_no_v_prefixed_image_tag() -> None:
    """No public doc names a ``filemorph:v…`` image tag: docker.yml pushes none.

    docker.yml tags the release images with metadata-action's semver patterns
    ``{{version}}`` and ``{{major}}.{{minor}}``, which drop the Git tag's
    ``v``: tag ``v1.2.3`` pushes the version tags ``1.2.3``, ``1.2``,
    ``1.2.3-office`` and ``1.2-office``. docs/patch-policy.md had readers
    ``cosign verify`` a ``:vX.Y.Z`` image, a command that failed for every
    release.
    """
    stale = [
        f"{rel}:{number}: {line.strip()}"
        for rel in _tracked_docs()
        for number, line in enumerate(
            (_REPO_ROOT / rel).read_text(encoding="utf-8").splitlines(), start=1
        )
        if _V_IMAGE_TAG_RE.search(line)
    ]
    assert not stale, (
        "docs name an image tag starting with `v`, which docker.yml never pushes — "
        f"release images are tagged `X.Y.Z` and `X.Y.Z-office`: {stale}"
    )


# The docs hold no `filemorph:v…` any more, so the test above never meets one;
# this keeps the pattern catching the placeholder the bug used, not only a digit.
@pytest.mark.parametrize(
    ("line", "stale"),
    [
        ("cosign verify ghcr.io/mrchenglen/filemorph:vX.Y.Z \\", True),
        ("docker pull ghcr.io/mrchenglen/filemorph:v1.2.3-office", True),
        ("verify `filemorph:v1.2.3`", True),
        ("cosign verify ghcr.io/mrchenglen/filemorph:X.Y.Z \\", False),
        ("--source-ref refs/tags/v1.2.3", False),
        ("sbom/filemorph-v1.2.3.cdx.json", False),
    ],
    ids=["placeholder", "version", "short-name", "fixed", "git-ref", "sbom-file"],
)
def test_v_image_tag_pattern_recognises_any_v_tag(line: str, stale: bool) -> None:
    assert bool(_V_IMAGE_TAG_RE.search(line)) is stale


def test_lockfile_is_hash_pinned_and_matches_the_image_python() -> None:
    """Every lockfile entry carries a hash, resolved for the shipped Python.

    A lockfile is only valid for the Python version it targets — environment
    markers resolve per version — so one resolved elsewhere can be
    uninstallable in the image. ``uv pip compile --python-version`` records
    the target in the header, which is what this reads.
    ``scripts/check_python_version.py`` is the CI gate; this is the
    regression guard for the posture itself.

    Each entry must be an exact, hashed pin and nothing else. deps-lock
    commits what a job running third-party code compiled, and lockfile-drift,
    the gate that would notice a stray ``--extra-index-url`` or URL
    requirement, is not a required check; this test runs in one.
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
    for entry in _lock_entries(_LOCKFILE):
        assert re.fullmatch(r"[A-Za-z0-9._-]+==\S+( --hash=sha256:[0-9a-f]{64})+", entry), (
            f"requirements.lock: `{entry.split()[0]}` is not an exact, hashed pin — an option "
            f"such as --extra-index-url, or a URL, lets the image install from elsewhere"
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
    warning in ``deps-latest.yml``, not the gate. The veraPDF fixture is built
    in this job, so it gets the shipped pikepdf too.
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


@pytest.mark.parametrize("workflow", ["sbom.yml", "release.yml", "docker.yml"])
def test_workflow_installs_what_the_image_ships(workflow: str) -> None:
    """The SBOM lists the image's dependency set.

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


@pytest.mark.parametrize("workflow", ["sbom.yml", "release.yml", "docker.yml"])
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


@pytest.mark.parametrize("workflow", ["sbom.yml", "release.yml", "docker.yml"])
def test_sbom_generator_installs_from_its_hashed_lockfile(workflow: str) -> None:
    """Every pip install in the SBOM workflows is hash-checked, and the
    generator comes from requirements-sbom.lock, as wheels only.

    It used to be ``pip install "cyclonedx-bom>=5,<6"``: about thirty packages,
    unpinned and unhashed, whichever releases PyPI served on the day — in
    release.yml inside the job that held ``contents: write``. Wheels only,
    because building an sdist pulls build dependencies pip does not hash-check.
    """
    installs = [
        line.strip()
        for line in _workflow_code(workflow).splitlines()
        if _PIP_INSTALL_RE.search(line)
    ]
    assert installs, f"{workflow} installs nothing with pip — update this guard"
    for line in installs:
        assert "--require-hashes" in line, f"{workflow}: `{line}` is not hash-checked"
    assert any(_GENERATOR_INSTALL in line for line in installs), (
        f"{workflow} does not run `{_GENERATOR_INSTALL}` — the SBOM generator must come "
        f"from its lockfile, hash-checked and as wheels only"
    )


def test_sbom_generator_lockfile_is_hash_pinned() -> None:
    """requirements-sbom.lock pins every package with a hash, satisfies
    requirements-sbom.txt, and targets the shipped Python.

    ``--require-hashes`` rejects an unpinned or unhashed entry too, but only
    once the SBOM workflows run — on main, or for release.yml at release time;
    this catches a hand edit in its PR. The lockfile must also still satisfy
    requirements-sbom.txt, which Dependabot edits: ``lockfile-drift`` notices
    that too, but it is not a required check, and this test runs in one. The
    Python version must be the one requirements.lock targets (the image's, see
    the lockfile test above), because the SBOM jobs run the generator on it.
    """
    assert _SBOM_LOCKFILE.is_file(), (
        "requirements-sbom.lock missing, but sbom.yml, release.yml and docker.yml install from "
        "it — recompile it with the command in requirements-sbom.txt, or run the deps-lock "
        "workflow"
    )
    for entry in _lock_entries(_SBOM_LOCKFILE):
        assert re.fullmatch(r"[A-Za-z0-9._-]+==\S+( --hash=sha256:[0-9a-f]{64})+", entry), (
            f"requirements-sbom.lock: `{entry.split()[0]}` is not an exact, hashed pin"
        )
    pins = _lock_pins(_SBOM_LOCKFILE)
    for line in _SBOM_MANIFEST.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        wanted = Requirement(line)
        pinned = pins.get(canonicalize_name(wanted.name))
        assert pinned and wanted.specifier.contains(pinned, prereleases=True), (
            f"requirements-sbom.lock pins {wanted.name} {pinned}, but requirements-sbom.txt "
            f"asks for {wanted.specifier} — recompile the lockfile (deps-lock workflow)"
        )
    assert _lock_python_version(_SBOM_LOCKFILE) == _lock_python_version(_LOCKFILE), (
        "requirements-sbom.lock is compiled for a different Python than requirements.lock — "
        "recompile both for the shipped version (deps-lock workflow)"
    )


@pytest.mark.parametrize("lockfile", [_LOCKFILE, _SBOM_LOCKFILE], ids=lambda p: p.name)
def test_lockfile_jobs_run_the_recorded_compile_command(lockfile: Path) -> None:
    """lockfile-drift and deps-lock run the command in the lockfile's header.

    uv writes its invocation into the header, so the drift gate only agrees
    with the committed file if it runs that command verbatim, and deps-lock
    only reproduces the file if it does too.
    """
    lines = lockfile.read_text(encoding="utf-8").splitlines()
    command = lines[1].lstrip("# ").strip() if len(lines) > 1 else ""
    assert command.startswith("uv pip compile"), f"{lockfile.name} has no uv header"
    for workflow in ("ci.yml", "deps-lock.yml"):
        assert command in _workflow_code(workflow), (
            f"{workflow} does not run `{command}`, the command {lockfile.name} records"
        )


def test_lockfile_jobs_install_the_uv_requirements_dev_pins() -> None:
    """lockfile-drift and deps-lock install the uv requirements-dev.txt pins,
    hash-checked, from requirements-uv.lock.

    Another uv release can write the same lockfile differently, so the drift
    gate, deps-lock and a local recompile have to run the same one. Dependabot
    bumps only requirements-dev.txt, and while the workflows typed their own
    version they were left behind twice: on 0.12.13 while it moved to 0.12.16,
    then on 0.12.16 while it moved to 0.12.19. The hashes make pip refuse a
    file added to that release later — a wheel it would prefer, say — where
    the lockfiles are written, so requirements-uv.lock has to follow every
    bump of the pin, and this fails until it does. Nothing else in those jobs
    may install or fetch: only the actions in ``_COMPILE_JOB_ACTIONS`` run
    there (a setup-uv step would put its own uv first on PATH), and every
    install is a hash-checked ``pip install``, with nothing chained to it.
    """
    lines = _REQUIREMENTS_DEV.read_text(encoding="utf-8").splitlines()
    # `uv` itself, not uvicorn, uv_build or uv-anything.
    pins = [line.strip() for line in lines if re.match(r"uv(?![\w-])", line)]
    assert len(pins) == 1 and re.fullmatch(r"uv==\d+(\.\d+)+", pins[0]), (
        f"requirements-dev.txt must pin uv exactly once, as a bare `uv==X.Y.Z` — found {pins}"
    )
    assert _UV_LOCKFILE.is_file(), (
        "requirements-uv.lock missing, but the lockfile jobs install uv from it — "
        "regenerate it with the command in requirements-dev.txt"
    )
    entries = _lock_entries(_UV_LOCKFILE)
    assert len(entries) == 1 and re.fullmatch(
        r"uv==\S+( --hash=sha256:[0-9a-f]{64})+", entries[0]
    ), f"requirements-uv.lock must pin uv alone, exactly and with its hashes — found {entries}"
    locked = entries[0].split()[0]
    assert locked == pins[0], (
        f"requirements-dev.txt pins {pins[0]}, but requirements-uv.lock holds {locked} — "
        f"regenerate it with the command in requirements-dev.txt"
    )
    for path in _workflow_files():
        assert not re.search(r"\buv==\d", _workflow_code(path.name)), (
            f"{path.name} pins its own uv version, which Dependabot never bumps — "
            f"install it the way ci.yml's lockfile-drift job does"
        )
        for name, job in _workflow(path)["jobs"].items():
            steps = _steps(job)
            if not any("uv pip compile" in (step.get("run") or "") for step in steps):
                continue
            installs = [
                (step.get("run") or "").strip()
                for step in steps
                if step.get("name") == "Install uv"
            ]
            assert installs == [_UV_INSTALL], (
                f"{path.name} job `{name}` compiles a lockfile, so its one `Install uv` step "
                f"must run exactly `{_UV_INSTALL}`"
            )
            for step in steps:
                uses = step.get("uses")
                assert not uses or str(uses).startswith(_COMPILE_JOB_ACTIONS), (
                    f"{path.name} job `{name}` compiles a lockfile, yet runs `{uses}` — only "
                    f"{', '.join(_COMPILE_JOB_ACTIONS)} run there"
                )
                for line in (step.get("run") or "").splitlines():
                    line = line.strip()
                    if not _INSTALLS_RE.search(line):
                        continue
                    alone = not re.search(r"[;&|`]|\$\(", line)
                    allowed = line.startswith("uv pip compile ") or bool(
                        _PIP_INSTALL_RE.search(line) and "--require-hashes" in line
                    )
                    assert alone and allowed, (
                        f"{path.name} job `{name}` compiles a lockfile, yet runs `{line}` — only "
                        f"`uv pip compile` and a hash-checked `pip install` run there, each as a "
                        f"command of its own"
                    )


def test_deps_lock_pushes_from_a_job_that_installs_nothing() -> None:
    """deps-lock.yml compiles with read access only and pushes from a job that
    installs nothing.

    Its single job used to install uv, recompile the lockfiles and
    test-install them next to ``contents: write`` and a checkout that kept
    its credentials. ``compile`` now does all of that read-only, without a
    cache or stored credentials, and hands the lockfiles over as an artifact.
    ``commit`` runs no package manager or download, uses only the actions in
    ``_DEPS_LOCK_WRITE_ACTIONS``, unpacks the artifact outside its checkout
    and takes the two lockfiles out of it by name — a ``cp -r`` of the whole
    artifact could bring a ``.git/config`` whose next ``git`` call runs code
    next to the token.
    """
    workflow = _workflow(_WORKFLOW_DIR / "deps-lock.yml")
    jobs = workflow["jobs"]
    compiling = [
        name
        for name, job in jobs.items()
        if any("uv pip compile" in (step.get("run") or "") for step in _steps(job))
    ]
    pushing = [name for name, job in jobs.items() if _privileged(job, workflow)]
    assert compiling == ["compile"] and pushing == ["commit"], (
        f"deps-lock.yml: expected `compile` to recompile the lockfiles and only `commit` to "
        f"hold a write token or a secret; found {compiling} and {pushing}"
    )
    compile_job, commit_job = jobs["compile"], jobs["commit"]
    for step in _steps(compile_job):
        uses, inputs = str(step.get("uses", "")), step.get("with") or {}
        assert not uses.startswith("actions/cache") and not any("cache" in k for k in inputs), (
            f"deps-lock.yml job `compile`, step {step.get('name') or uses!r}: restores a cache, "
            f"and the lockfiles it writes get committed"
        )
        if uses.startswith("actions/checkout@"):
            assert inputs.get("persist-credentials") is False, (
                "deps-lock.yml job `compile`: checkout without `persist-credentials: false`"
            )
    assert commit_job.get("needs") in ("compile", ["compile"]), (
        "deps-lock.yml: `commit` must wait for `compile`"
    )
    for step in _steps(commit_job):
        label = step.get("name") or step.get("uses")
        assert not _INSTALLS_RE.search(step.get("run") or ""), (
            f"deps-lock.yml job `commit` can push, yet step {label!r} installs, fetches or "
            f"runs third-party packages. Do that in `compile`."
        )
        uses = step.get("uses")
        assert not uses or str(uses).startswith(_DEPS_LOCK_WRITE_ACTIONS), (
            f"deps-lock.yml job `commit` can push, yet runs `{uses}` — only "
            f"{', '.join(_DEPS_LOCK_WRITE_ACTIONS)} run next to its token"
        )

    def artifact_inputs(job: dict, action: str) -> dict:
        found = [step for step in _steps(job) if str(step.get("uses", "")).startswith(action)]
        assert len(found) == 1, f"deps-lock.yml: expected one {action.rstrip('@')} step"
        return found[0].get("with") or {}

    handed = artifact_inputs(compile_job, "actions/upload-artifact@")
    received = artifact_inputs(commit_job, "actions/download-artifact@")
    assert received.get("name") == handed.get("name"), (
        "deps-lock.yml: `commit` must download the artifact `compile` uploads, by its name"
    )
    assert str(received.get("path", "")).startswith("${{ runner.temp }}/"), (
        "deps-lock.yml: unpack the artifact under ${{ runner.temp }}, outside the checkout, "
        "so nothing in it can replace a file git or `commit` reads"
    )
    folder = str(received["path"]).removeprefix("${{ runner.temp }}/")
    script = "\n".join(step.get("run") or "" for step in _steps(commit_job))
    taken = re.findall(r'RUNNER_TEMP\}?"?/' + re.escape(folder) + r'/?([^\s"\']*)', script)
    assert sorted(taken) == ["requirements-sbom.lock", "requirements.lock"], (
        f"deps-lock.yml: `commit` must take requirements.lock and requirements-sbom.lock out "
        f"of the artifact by name, and nothing else — found {taken}"
    )


def test_release_installs_nothing_where_it_can_write() -> None:
    """In release.yml, a job holding a write token installs and fetches nothing.

    The image's dependency set and the SBOM generator are over a hundred
    packages. Run next to ``contents: write`` they could swap the tarball,
    forge IMAGE_DIGEST.txt or use the token; so the ``sbom`` job reads and
    generates, and the publish job writes, runs no package manager or
    download, and uses only the actions in ``_RELEASE_WRITE_ACTIONS``.
    """
    workflow = _workflow(_WORKFLOW_DIR / "release.yml")
    jobs = workflow["jobs"]
    assert any(
        "cyclonedx-py" in (step.get("run") or "") for job in jobs.values() for step in _steps(job)
    ), "release.yml no longer generates an SBOM — update this guard"
    for name, job in jobs.items():
        if not _privileged(job, workflow):
            continue
        for step in _steps(job):
            label = step.get("name") or step.get("uses")
            assert not _INSTALLS_RE.search(step.get("run") or ""), (
                f"release.yml job `{name}` can write, yet step {label!r} installs, fetches "
                f"or runs third-party packages. Do that in a read-only job and hand the "
                f"result over as an artifact."
            )
            uses = step.get("uses")
            assert not uses or str(uses).startswith(_RELEASE_WRITE_ACTIONS), (
                f"release.yml job `{name}` can write, yet runs `{uses}` — only "
                f"{', '.join(_RELEASE_WRITE_ACTIONS)} run next to its token"
            )


def test_release_publish_fails_closed() -> None:
    """The SBOM lands in a directory of its own, and a missing attachment stops
    the release instead of publishing without it.

    Both only come into play on a tag, where nothing can be tried first.
    """
    job = _workflow(_WORKFLOW_DIR / "release.yml")["jobs"]["verify-and-publish"]
    inputs = {step.get("name"): step.get("with") or {} for step in _steps(job)}
    assert inputs.get("Download the SBOM", {}).get("path") == "sbom", (
        "release.yml: download the SBOM into `sbom/`, apart from what the publish job "
        "builds and reads"
    )
    publish = inputs.get("Publish release", {})
    assert publish.get("fail_on_unmatched_files") is True, (
        "release.yml: without `fail_on_unmatched_files: true` a missing SBOM only warns, "
        "and the release goes out without it"
    )
    files = [line.strip() for line in str(publish.get("files")).splitlines()]
    assert "sbom/filemorph-${{ github.ref_name }}.cdx.json" in files, (
        "release.yml does not publish the SBOM by its exact name from `sbom/`"
    )


@pytest.mark.parametrize("workflow", ["release.yml", "sbom.yml"])
def test_sbom_workflows_restore_no_cache_and_keep_no_credentials(workflow: str) -> None:
    """The SBOM workflows neither restore a cache nor leave a token in the checkout.

    Code running on main can write the shared pip cache (Actions cache
    poisoning), and ``--require-hashes`` does not cover all of it (see
    sbom.yml). sbom.yml rehearses release.yml's SBOM steps, so it runs them
    the same way. Neither pushes — ``git verify-tag`` and ``git archive`` are
    local, the release goes through the API — so no checkout needs to keep
    its credentials.
    """
    for name, job in _workflow(_WORKFLOW_DIR / workflow)["jobs"].items():
        for step in _steps(job):
            uses, inputs = str(step.get("uses", "")), step.get("with") or {}
            label = step.get("name") or uses
            assert not uses.startswith("actions/cache"), (
                f"{workflow} job `{name}` restores a cache ({uses})"
            )
            assert not any("cache" in key for key in inputs), (
                f"{workflow} job `{name}`, step {label!r}: a cache input "
                f"({', '.join(key for key in inputs if 'cache' in key)})"
            )
            if uses.startswith("actions/checkout@"):
                assert inputs.get("persist-credentials") is False, (
                    f"{workflow} job `{name}`: checkout without `persist-credentials: false`"
                )


@pytest.mark.parametrize("workflow", _workflow_files(), ids=lambda p: p.name)
def test_privileged_jobs_keep_expressions_out_of_scripts(workflow: Path) -> None:
    """No job holding a write token or a secret gets ``${{ }}`` in a script.

    The runner pastes the expression's value into the script text before bash
    parses it. A tag or branch name — git allows ``$(``, backticks and ``;``
    in both — or a step output derived from one then runs as shell code next
    to the token (CWE-78). Pass the value through ``env:`` and quote it.
    """
    parsed = _workflow(workflow)
    for name, job in (parsed.get("jobs") or {}).items():
        if not _privileged(job, parsed):
            continue
        for step in _steps(job):
            assert "${{" not in (step.get("run") or ""), (
                f"{workflow.name} job `{name}`, step {step.get('name')!r}: an expression "
                f"inside `run:` in a job with a write token or a secret — pass it through "
                f"`env:` instead"
            )


@pytest.mark.parametrize("workflow", _workflow_files(), ids=lambda p: p.name)
def test_pull_request_jobs_hold_no_write_token_or_secret(workflow: Path) -> None:
    """A job that a pull request triggers holds neither a write token nor a secret.

    It runs, or can check out, the pull request's code: ci.yml runs its tests,
    docker-pr.yml builds its Dockerfile. Without ``packages: write`` and
    ``id-token: write`` the image check cannot push to GHCR or sign. For a pull
    request from a fork GitHub withholds both anyway, except under
    ``pull_request_target``; branches in this repository get what the workflow
    declares.
    """
    parsed = _workflow(workflow)
    on = parsed.get("on", parsed.get(True))
    triggers = {on} if isinstance(on, str) else set(on or ())
    if not triggers & _PULL_REQUEST_EVENTS:
        pytest.skip(f"{workflow.name} is not triggered by pull requests")
    for name, job in parsed["jobs"].items():
        assert not _privileged(job, parsed), (
            f"{workflow.name} job `{name}` runs on pull requests with a write token or a "
            f"secret. Keep it read-only; publishing belongs in a workflow that runs after merge."
        )


# The workflows only ever read GITHUB_TOKEN through `secrets.`, so the tests
# above never meet the other forms; this keeps _privileged able to see them.
@pytest.mark.parametrize(
    ("job", "privileged"),
    [
        ({"env": {"T": "${{ secrets.PAT }}"}}, True),
        ({"env": {"T": "${{ secrets['PAT'] }}"}}, True),
        ({"env": {"T": "${{ toJSON(secrets) }}"}}, True),
        ({"env": {"T": "${{ SECRETS.PAT }}"}}, True),
        ({"uses": "./.github/workflows/reusable.yml", "secrets": "inherit"}, True),
        ({"env": {"T": "${{ secrets.GITHUB_TOKEN }}"}}, False),
        ({"steps": [{"name": "Plant canary secrets", "run": "true"}]}, False),
    ],
    ids=["dot", "index", "toJSON", "upper-case", "inherit", "github-token", "prose"],
)
def test_privileged_recognises_secrets_in_any_form(job: dict, privileged: bool) -> None:
    assert _privileged(job, {"permissions": {"contents": "read"}}) is privileged


@pytest.mark.parametrize("workflow", _workflow_files(), ids=lambda p: p.name)
def test_privileged_jobs_restore_no_cache(workflow: Path) -> None:
    """No job holding a write token or a secret restores or saves an Actions cache.

    Every job that runs on main can write that cache, whatever its
    ``permissions:`` say — the cache token can be read from the runner
    process — and jobs there install PyPI releases that no lockfile pins
    (ci.yml's lint-and-test, deps-latest.yml). Whatever a privileged job
    restored, one of them could have planted. Until PR #170 docker.yml
    restored BuildKit's layer cache on tag and main builds, next to
    ``packages: write`` and the signing identity.

    Only inputs written in the workflow count, and a cache input may only
    switch caching off: ``no-cache: true``, or ``false`` for the others. An
    action that caches by default (setup-buildx's ``cache-binary``,
    setup-qemu's ``cache-image``) needs that switch written down.
    """
    parsed = _workflow(workflow)
    for name, job in (parsed.get("jobs") or {}).items():
        if not _privileged(job, parsed):
            continue
        for step in _steps(job):
            uses, inputs = str(step.get("uses", "")), step.get("with") or {}
            label = step.get("name") or uses
            assert not uses.startswith("actions/cache"), (
                f"{workflow.name} job `{name}` holds a write token or a secret, yet "
                f"restores a cache ({uses})"
            )
            for key, value in inputs.items():
                off = value is True if key == "no-cache" else value is False
                assert "cache" not in key or off, (
                    f"{workflow.name} job `{name}`, step {label!r}: `{key}: {value}` in a job "
                    f"with a write token or a secret — a cache input may only switch caching off"
                )


def test_image_build_turns_caching_off() -> None:
    """docker.yml builds with ``no-cache: true`` and never caches buildx itself.

    The test above only sees cache inputs that are written down; this one pins
    the two the image build needs. BuildKit takes a cached layer without
    re-running its step, so a planted entry for ``pip install
    --require-hashes -r requirements.lock`` would put packages no hash was
    checked against into an image that is then signed and deployed. And
    setup-buildx-action caches a buildx binary it downloads unless told not
    to, so the signing job would run whatever that cache held.
    """
    steps = [
        step
        for job in _workflow(_WORKFLOW_DIR / "docker.yml")["jobs"].values()
        for step in _steps(job)
    ]
    switches = {
        "docker/build-push-action@": ("no-cache", True),
        "docker/setup-buildx-action@": ("cache-binary", False),
    }
    for action, (key, value) in switches.items():
        found = [step for step in steps if str(step.get("uses", "")).startswith(action)]
        assert found, f"docker.yml no longer uses {action.rstrip('@')} — update this guard"
        for step in found:
            assert (step.get("with") or {}).get(key) is value, (
                f"docker.yml step {step.get('name')!r}: set `{key}: {str(value).lower()}`"
            )


@pytest.mark.parametrize("workflow", _workflow_files(), ids=lambda p: p.name)
def test_buildx_actions_restore_no_cache(workflow: Path) -> None:
    """No build-push-action step uses a BuildKit cache, and no setup-buildx-action
    step caches buildx.

    docker.yml no longer writes a layer cache, so whatever a ``cache-from``
    found would be stale or planted by a job on main. Even in docker-pr.yml,
    which pushes nothing, it would let the smoke test pass on layers the pull
    request never built. A buildx binary setup-buildx-action downloads goes
    through the Actions cache unless ``cache-binary: false`` says otherwise.
    """
    for name, job in (_workflow(workflow).get("jobs") or {}).items():
        for step in _steps(job):
            uses, inputs = str(step.get("uses", "")), step.get("with") or {}
            label = f"{workflow.name} job `{name}`, step {step.get('name')!r}"
            if uses.startswith("docker/build-push-action@"):
                cached = [key for key in ("cache-from", "cache-to") if key in inputs]
                assert not cached, (
                    f"{label}: {' and '.join(cached)} — nothing writes a BuildKit cache "
                    f"that can be trusted"
                )
            if uses.startswith("docker/setup-buildx-action@"):
                assert inputs.get("cache-binary") is False, f"{label}: set `cache-binary: false`"


@pytest.mark.parametrize("workflow", ["release.yml", "docker.yml"])
def test_sbom_steps_match_sbom_workflow(workflow: str) -> None:
    """release.yml and docker.yml run sbom.yml's SBOM steps verbatim, with the
    flags the locked generator accepts.

    Neither can be tried before it counts: release.yml runs on a signed tag,
    and docker.yml pushes the images it builds, so a mistake would first show
    in a release or on main. sbom.yml runs the same steps when it is
    dispatched on a branch; keeping them identical makes that run the test of
    both paths.
    """

    def named_steps(name: str) -> dict[str, dict]:
        jobs = _workflow(_WORKFLOW_DIR / name)["jobs"].values()
        return {step["name"]: step for job in jobs for step in _steps(job) if "name" in step}

    sbom, copy = named_steps("sbom.yml"), named_steps(workflow)
    for name in _SBOM_STEPS:
        assert name in sbom, f"sbom.yml has no step {name!r} — update this guard"
        assert name in copy, f"{workflow} has no step {name!r}"
        assert copy[name].get("run") == sbom[name].get("run"), (
            f"{workflow} and sbom.yml differ in step {name!r} — keep them identical"
        )
    generate = sbom["Generate CycloneDX SBOM (JSON)"]["run"]
    generator = Version(_lock_pins(_SBOM_LOCKFILE)[canonicalize_name("cyclonedx-bom")])
    if generator.major < 7:
        assert "--PEP-639" in generate, (
            f"cyclonedx-bom {generator} runs without --PEP-639: it then ignores the "
            f"License-Expression field, and packages that declare their licence only there "
            f"are listed without one (30 of 78 at c13ed52, FastAPI and Pydantic among them)"
        )
    else:
        assert "--PEP-639" not in generate, (
            f"cyclonedx-bom {generator} no longer accepts --PEP-639 — drop it from sbom.yml, "
            f"release.yml and docker.yml, or every SBOM job fails"
        )


def test_docker_attests_the_sbom_to_every_image_it_pushes() -> None:
    """docker.yml binds the SBOM to each image variant by the digest it pushed.

    release.yml can only look an image up by tag, best effort, a minute after
    the tag push; an attestation has to name exactly what was built, pushed
    and signed, which is the digest the build step reports. The legs of a
    matrix share one set of job outputs, so each variant needs an output of
    its own: one name for both would hand both attestations whichever digest
    was written last. The attestation also goes to GHCR, and it runs on every
    build, main as well as tags (a decision of 2026-09-28), so ``:latest``
    carries one too: no ``if:`` may skip either job or a step of it, and no
    ``continue-on-error`` may let the run, and with it the deploy, succeed
    without an attestation. The SBOM crosses over by file name, and none of
    this can be tried before it runs on main, so the names have to line up
    here.
    """
    jobs = _workflow(_WORKFLOW_DIR / "docker.yml")["jobs"]
    build = jobs["build-and-push"]
    targets = [leg["target"] for leg in build["strategy"]["matrix"]["include"]]
    outputs = build.get("outputs") or {}
    for target in targets:
        value = str(outputs.get(f"digest-{target}", ""))
        assert "steps.build.outputs.digest" in value and f"'{target}'" in value, (
            f"docker.yml: build-and-push must output `digest-{target}`, the build step's "
            f"digest set by the {target} leg only"
        )

    attesting = [
        name
        for name, job in jobs.items()
        if any(str(step.get("uses", "")).startswith("actions/attest@") for step in _steps(job))
    ]
    assert attesting == ["attest-sbom"], (
        f"docker.yml: expected one job running actions/attest, `attest-sbom`; found {attesting}"
    )
    sbom_jobs = [
        name
        for name, job in jobs.items()
        if any("cyclonedx-py" in (step.get("run") or "") for step in _steps(job))
    ]
    assert len(sbom_jobs) == 1, (
        f"docker.yml: expected one job generating the SBOM, found {sbom_jobs}"
    )
    job, sbom = jobs["attest-sbom"], jobs[sbom_jobs[0]]
    needs = job.get("needs") or []
    needs = [needs] if isinstance(needs, str) else needs
    assert {"build-and-push", sbom_jobs[0]} <= set(needs), (
        f"docker.yml: `attest-sbom` must need build-and-push and {sbom_jobs[0]}, it needs {needs}"
    )
    for name in ("attest-sbom", sbom_jobs[0]):
        for part in (jobs[name], *_steps(jobs[name])):
            assert "if" not in part and not part.get("continue-on-error"), (
                f"docker.yml job `{name}`: an `if:` or `continue-on-error` lets a build push "
                f"images without an attestation — it runs on every build, main as well as tags"
            )
    attested = (job.get("strategy") or {}).get("matrix", {}).get("target") or []
    assert sorted(attested) == sorted(targets), (
        f"docker.yml: `attest-sbom` must cover every image variant built, {targets}"
    )

    attest = next(s for s in _steps(job) if str(s.get("uses", "")).startswith("actions/attest@"))
    inputs = attest.get("with") or {}
    assert inputs.get("subject-digest") == (
        "${{ needs.build-and-push.outputs[format('digest-{0}', matrix.target)] }}"
    ), "docker.yml: attest each variant's digest as build-and-push reported it"
    assert inputs.get("subject-name") == "${{ env.REGISTRY }}/${{ env.IMAGE_NAME }}", (
        "docker.yml: the attestation's subject is the image name the build pushed, without a tag"
    )
    assert inputs.get("push-to-registry") is True, (
        "docker.yml: push the attestation to GHCR (`push-to-registry: true`)"
    )

    generate = next(s for s in _steps(sbom) if s.get("name") == "Generate CycloneDX SBOM (JSON)")
    output = re.search(r'--output-file "([^"]+)"', generate.get("run") or "")
    assert output, 'docker.yml: the SBOM step no longer writes `--output-file "…"`'
    version = str((generate.get("env") or {}).get("VERSION"))
    file_name = output.group(1).replace("${VERSION}", version)
    upload = next(
        s for s in _steps(sbom) if str(s.get("uses", "")).startswith("actions/upload-artifact@")
    )
    download = next(
        s for s in _steps(job) if str(s.get("uses", "")).startswith("actions/download-artifact@")
    )
    handed = upload.get("with") or {}
    received = download.get("with") or {}
    assert handed.get("path") == file_name and handed.get("if-no-files-found") == "error", (
        f"docker.yml: upload exactly `{file_name}`, and fail if it is missing"
    )
    assert received.get("name") == handed.get("name") and received.get("path") == "sbom", (
        "docker.yml: download the SBOM artifact by its name into `sbom/`, a directory of its own"
    )
    assert inputs.get("sbom-path") == f"sbom/{file_name}", (
        f"docker.yml: attest `sbom/{file_name}`, the file the SBOM job generated"
    )


def test_docker_attestation_runs_apart_from_third_party_code() -> None:
    """docker.yml's attesting job installs nothing; the SBOM job can only read.

    A signed attestation vouches for the SBOM inside it. Generating that SBOM
    installs the image's dependency set and the generator — over a hundred
    packages — so that job holds read access only and no secret, restores no
    cache and keeps no credentials. The job that can sign and push checks
    nothing out, uses only ``_ATTEST_ACTIONS``, like release.yml's publish
    job, and runs one command, the registry login: a pattern of forbidden
    commands would miss ``apt-get`` or ``docker run``. Its permissions are
    exactly what attesting to GHCR needs, and no other job may attest.
    """
    workflow = _workflow(_WORKFLOW_DIR / "docker.yml")
    jobs = workflow["jobs"]
    can_attest = [
        name
        for name, job in jobs.items()
        if (job.get("permissions") or {}).get("attestations") == "write"
    ]
    assert can_attest == ["attest-sbom"], (
        f"docker.yml: only `attest-sbom` may hold `attestations: write`, found {can_attest}"
    )
    job = jobs["attest-sbom"]
    assert job["permissions"] == {
        "attestations": "write",
        "id-token": "write",
        "packages": "write",
    }, f"docker.yml: `attest-sbom` holds {job['permissions']}"
    runs = [step["run"].strip() for step in _steps(job) if "run" in step]
    assert runs == [_ATTEST_LOGIN], (
        f"docker.yml job `attest-sbom` can sign and push, so it runs only `{_ATTEST_LOGIN}`; "
        f"found {runs}"
    )
    for step in _steps(job):
        uses = step.get("uses")
        assert not uses or str(uses).startswith(_ATTEST_ACTIONS), (
            f"docker.yml job `attest-sbom` runs `{uses}` — only "
            f"{', '.join(_ATTEST_ACTIONS)} run next to its tokens"
        )

    for name, sbom in jobs.items():
        if not any("cyclonedx-py" in (step.get("run") or "") for step in _steps(sbom)):
            continue
        assert sbom.get("permissions") == {"contents": "read"}, (
            f"docker.yml job `{name}` runs third-party code, so it may only read"
        )
        assert not _privileged(sbom, workflow), (
            f"docker.yml job `{name}` runs third-party code, so it may hold no secret"
        )
        for step in _steps(sbom):
            uses, inputs = str(step.get("uses", "")), step.get("with") or {}
            assert not uses.startswith("actions/cache") and not any("cache" in k for k in inputs), (
                f"docker.yml job `{name}`, step {step.get('name') or uses!r}: restores a cache, "
                f"and the SBOM it generates gets attested"
            )
            if uses.startswith("actions/checkout@"):
                assert inputs.get("persist-credentials") is False, (
                    f"docker.yml job `{name}`: checkout without `persist-credentials: false`"
                )


def test_docs_verify_the_sbom_attestation_as_docker_yml_makes_it() -> None:
    """docs/release-signing.md verifies the attestation the way it is made, and
    says what the SBOM leaves out.

    ``gh attestation verify`` looks for SLSA provenance unless told otherwise,
    so without ``--predicate-type https://cyclonedx.org/bom`` the documented
    command fails on every image. The workflow it names as signer has to be
    the one that attests. And the SBOM lists the Python packages from
    requirements.lock only: without saying that the image's Debian packages
    are not in it, the attestation reads as a complete inventory.
    """
    text = _RELEASE_SIGNING_DOC.read_text(encoding="utf-8")
    section = re.search(r"^## Verifying the SBOM attestation\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert section, "docs/release-signing.md has no `## Verifying the SBOM attestation` section"
    body = section.group(1)
    blocks = "\n".join(re.findall(r"```bash\n(.*?)```", body, re.S))
    commands = [
        " ".join(match.replace("\\\n", " ").split())
        for match in re.findall(r"gh attestation verify(?:[^\n]*\\\n)*[^\n]*", blocks)
    ]
    assert commands, "docs/release-signing.md shows no `gh attestation verify` command"
    for command in commands:
        assert "--predicate-type https://cyclonedx.org/bom" in command, (
            f"`{command}` fails: without `--predicate-type https://cyclonedx.org/bom`, gh looks "
            f"for SLSA provenance, which docker.yml does not attest"
        )
        signer = re.search(
            r"--signer-workflow MrChengLen/FileMorph/\.github/workflows/(\S+)", command
        )
        assert signer and (_WORKFLOW_DIR / signer.group(1)).is_file(), (
            f"`{command}` names no workflow of this repository as `--signer-workflow`"
        )
        assert "actions/attest@" in _workflow_code(signer.group(1)), (
            f"`{command}`: {signer.group(1)} does not attest — name the workflow that does"
        )
    assert "requirements.lock" in body and "Debian" in body, (
        "docs/release-signing.md: say that the SBOM covers requirements.lock's Python packages "
        "only, not the image's Debian packages"
    )


def test_only_the_slim_image_is_tagged_latest() -> None:
    """docker.yml tags the slim image ``:latest``, and only the slim image.

    metadata-action adds a ``latest`` tag of its own when a ``type=semver``
    entry matches a release tag (``flavor: latest=auto``, its default), and
    a tag entry's ``suffix=`` does not reach that tag: on a release both
    variants pushed ``:latest``, and whichever finished last kept it —
    usually the office image, the slower build. With ``latest=false`` the
    ``type=raw`` entry that names ``latest`` for the unsuffixed base leg is
    the only source of ``:latest``, so that entry and that leg have to stay.
    The flavor is pinned whole: the action skips only lines that start with
    ``#`` and unquotes CSV fields, so a looser match could pass a flavor it
    reads differently.
    """
    job = _workflow(_WORKFLOW_DIR / "docker.yml")["jobs"]["build-and-push"]
    legs = {leg["target"]: leg.get("suffix") for leg in job["strategy"]["matrix"]["include"]}
    assert legs.get("base") == "", (
        f"docker.yml: the `latest` entry is meant for the `base` leg, the slim image without "
        f"a suffix; the matrix has {legs}"
    )
    steps = [s for s in _steps(job) if str(s.get("uses", "")).startswith("docker/metadata-action@")]
    assert steps, "docker.yml no longer uses docker/metadata-action — update this guard"
    raw_latest = "type=raw,value=${{ matrix.target == 'base' && 'latest' || 'office' }}"
    for step in steps:
        inputs = step.get("with") or {}
        assert str(inputs.get("flavor", "")).strip() == "latest=false", (
            f"docker.yml step {step.get('name')!r}: `flavor:` must be exactly `latest=false` "
            f"(this guard pins it whole) — without it, a release tags the office image "
            f"`:latest` as well"
        )
        latest = [
            line.strip()
            for line in str(inputs.get("tags", "")).splitlines()
            # As in the action, only a line starting with "#" is a comment; an
            # indented "# type=raw,value=latest" is a tag for both images.
            if "latest" in line and not line.startswith("#")
        ]
        assert latest == [raw_latest], (
            f"docker.yml step {step.get('name')!r}: `:latest` comes from one `type=raw` entry, "
            f"for the base leg only; found {latest}"
        )


def test_verapdf_image_is_digest_pinned() -> None:
    """The veraPDF gate runs a validator image pinned by digest.

    ``verapdf/cli:latest`` moves with every veraPDF release, so the same commit
    could pass the gate one day and fail it the next. The tag stays in a
    comment so the next bump knows which release the digest is.
    """
    code = _workflow_code("ci.yml")
    refs = re.findall(r"verapdf/cli[^\s\"']*", code)
    assert refs, "ci.yml no longer runs verapdf/cli — update this guard"
    for ref in refs:
        assert re.fullmatch(r"verapdf/cli(:[\w.-]+)?@sha256:[0-9a-f]{64}", ref), (
            f"ci.yml runs `{ref}` — pin it by @sha256: digest"
        )
    text = (_WORKFLOW_DIR / "ci.yml").read_text(encoding="utf-8")
    assert re.search(r"#\s*verapdf/cli:v?\d", text), (
        "ci.yml: keep the pinned image's tag in a comment (`# verapdf/cli:vX.Y.Z`)"
    )


def test_verapdf_gate_is_part_of_the_required_lint_and_test_job() -> None:
    """The PDF/A-2b conformance gate is a step of ``lint-and-test``.

    ``lint-and-test`` is one of the status checks that merging into ``main``
    requires. The gate used to be a workflow of its own, ``verapdf.yml``: it
    ran on every pull request and nothing required it, while the README and
    the pricing page advertise a veraPDF CI gate. Its two steps, building the
    fixture and validating it, therefore stay in that job, and neither may be
    skipped (``if:``) or allowed to fail (``continue-on-error``).
    """
    jobs = _workflow(_WORKFLOW_DIR / "ci.yml")["jobs"]
    gate = [
        (name, step)
        for name, job in jobs.items()
        for step in _steps(job)
        if "verapdf_check.py" in (step.get("run") or "")
        or "VERAPDF_IMAGE" in (step.get("env") or {})
    ]
    assert len(gate) == 2 and {name for name, _ in gate} == {"lint-and-test"}, (
        f"ci.yml: the veraPDF fixture and validation steps must both be in `lint-and-test`, "
        f"the required check; found them in {[name for name, _ in gate]}"
    )
    assert not jobs["lint-and-test"].get("continue-on-error"), (
        "ci.yml: `lint-and-test` is marked continue-on-error, which lets the veraPDF gate fail"
    )
    assert "if" not in jobs["lint-and-test"], (
        "ci.yml: `lint-and-test` has a job-level `if:`; a skipped required job counts as passed"
    )
    for name, step in gate:
        assert "if" not in step and not step.get("continue-on-error"), (
            f"ci.yml job `{name}`, step {step.get('name')!r}: an `if:` or `continue-on-error` "
            f"lets a merge through without the veraPDF verdict"
        )
        if "VERAPDF_IMAGE" in (step.get("env") or {}):
            run = step.get("run") or ""
            assert "--flavour 2b" in run and "|| true" not in run, (
                f"ci.yml step {step.get('name')!r}: the validator must check PDF/A-2b "
                "and its exit code must fail the step"
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


def test_dependabot_ignores_sit_on_live_caps() -> None:
    """Every pip ``ignore`` range in dependabot.yml matches a cap in requirements*.txt.

    A held-back major (``versions: [">=70"]``) is only right while the matching
    cap (``<70``) is in place. Left behind after the port lifts the cap, the
    ignore would freeze the package silently: no pull request, no red CI.
    """
    pip = next(
        update
        for update in yaml.safe_load(_DEPENDABOT.read_text(encoding="utf-8"))["updates"]
        if update["package-ecosystem"] == "pip"
    )
    caps: dict[str, set[str]] = {}
    for path in _REPO_ROOT.glob("requirements*.txt"):
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line and not line.startswith("-"):
                req = Requirement(line)
                caps[canonicalize_name(req.name)] = {str(spec) for spec in req.specifier}
    for entry in pip.get("ignore", []):
        for version_range in entry["versions"]:
            cap = "<" + version_range.removeprefix(">=")
            assert cap in caps.get(canonicalize_name(entry["dependency-name"]), set()), (
                f"dependabot.yml ignores {entry['dependency-name']} {version_range}, but no "
                f"requirements*.txt caps it {cap}: drop the ignore together with the cap"
            )
