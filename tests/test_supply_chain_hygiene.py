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
    veraPDF workflows install it the way the image does; the jobs that
    recompile the lockfiles run the uv that requirements-dev.txt pins;
  * the SBOM generator installs from its own hash-pinned lockfile, as wheels
    only, and in release.yml it runs in a job without write access — the job
    that holds ``contents: write`` installs nothing, restores no cache and
    keeps no credentials; no job holding a write token or a secret splices
    ``${{ }}`` into a script; and the veraPDF validator image is pinned by
    digest.

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
# The `Install uv` step of every job that compiles a lockfile: the one exact
# pin in requirements-dev.txt, as a wheel. An assignment first, so `bash -e`
# stops the step when the pin is missing — pip takes an empty argument as
# nothing to install and exits 0.
_UV_FROM_DEV = (
    "uv_pin=$(grep -oE '^uv==[0-9][0-9A-Za-z.!+-]*' requirements-dev.txt)",
    'pip install --only-binary :all: "$uv_pin"',
)
# The steps release.yml copies from sbom.yml, which is the one that can be run.
_SBOM_STEPS = (
    "Install the image's dependency set",
    "Install CycloneDX generator",
    "Generate CycloneDX SBOM (JSON)",
)
_GENERATOR_INSTALL = "pip install --require-hashes --only-binary :all: -r requirements-sbom.lock"
# `pip install`, `"$VENV/bin/pip" install` and `python -m pip install`.
_PIP_INSTALL_RE = re.compile(r'\bpip"?\s+install\b')
# In a `run:` script: a package manager, a download, or the SBOM generator.
_INSTALLS_RE = re.compile(r'\b(?:pip3?|pipx|uvx?|npm|npx|curl|wget)"?\s|cyclonedx-py')
# The only actions that run in release.yml's job holding `contents: write`.
_RELEASE_WRITE_ACTIONS = (
    "actions/checkout@",
    "actions/download-artifact@",
    "softprops/action-gh-release@",
)

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
    ``GITHUB_TOKEN`` (a PAT that triggers a deploy, say) counts as well.
    """
    permissions = job.get("permissions", workflow.get("permissions"))
    if permissions is None or permissions == "write-all":
        return True
    if isinstance(permissions, dict) and "write" in permissions.values():
        return True
    return bool(re.search(r"\bsecrets\.(?!GITHUB_TOKEN\b)", json.dumps([workflow.get("env"), job])))


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
    docs = [
        rel
        for rel in tracked
        if rel.endswith(".md")
        and ("/" not in rel or rel.startswith("docs/"))
        and rel != "CHANGELOG.md"
    ]
    stale = [
        f"{rel}: pip-audit -r {target}"
        for rel in docs
        for target in _PIP_AUDIT_RE.findall((_REPO_ROOT / rel).read_text(encoding="utf-8"))
        if target != _LOCKFILE.name
    ]
    assert not stale, (
        f"docs quote a pip-audit target other than {_LOCKFILE.name}, the file "
        f"CI audits and the image installs: {stale}"
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


@pytest.mark.parametrize("workflow", ["sbom.yml", "release.yml"])
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
        "requirements-sbom.lock missing, but sbom.yml and release.yml install from it — "
        "recompile it with the command in requirements-sbom.txt, or run the deps-lock workflow"
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
    """lockfile-drift and deps-lock read their uv version from requirements-dev.txt.

    Another uv release can write the same lockfile differently, so the drift
    gate, deps-lock and a local recompile have to run the same one. Dependabot
    bumps only requirements-dev.txt, and while the workflows typed their own
    version they were left behind twice: on 0.12.13 while it moved to 0.12.16,
    then on 0.12.16 while it moved to 0.12.19.
    """
    lines = _REQUIREMENTS_DEV.read_text(encoding="utf-8").splitlines()
    # `uv` itself, not uvicorn, uv_build or uv-anything.
    pins = [line.strip() for line in lines if re.match(r"uv(?![\w-])", line)]
    assert len(pins) == 1 and re.fullmatch(r"uv==\d+(\.\d+)+", pins[0]), (
        f"requirements-dev.txt must pin uv exactly once, as a bare `uv==X.Y.Z` — found {pins}"
    )
    expected = "\n".join(_UV_FROM_DEV)
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
            assert installs == [expected], (
                f"{path.name} job `{name}` compiles a lockfile, so its one `Install uv` step "
                f"must run exactly:\n{expected}"
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


def test_release_sbom_steps_match_sbom_workflow() -> None:
    """release.yml runs sbom.yml's SBOM steps verbatim, with the flags the
    locked generator accepts.

    release.yml only runs on a signed tag, so a mistake there would first show
    in a release. sbom.yml runs the same steps on every push to main and can
    be dispatched on a branch; keeping the two identical makes that run the
    test of the release path.
    """

    def named_steps(name: str) -> dict[str, dict]:
        jobs = _workflow(_WORKFLOW_DIR / name)["jobs"].values()
        return {step["name"]: step for job in jobs for step in _steps(job) if "name" in step}

    sbom, release = named_steps("sbom.yml"), named_steps("release.yml")
    for name in _SBOM_STEPS:
        assert name in sbom, f"sbom.yml has no step {name!r} — update this guard"
        assert name in release, f"release.yml has no step {name!r}"
        assert release[name].get("run") == sbom[name].get("run"), (
            f"release.yml and sbom.yml differ in step {name!r} — keep them identical"
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
            f"cyclonedx-bom {generator} no longer accepts --PEP-639 — drop it from sbom.yml "
            f"and release.yml, or both SBOM jobs fail"
        )


def test_verapdf_image_is_digest_pinned() -> None:
    """The veraPDF gate runs a validator image pinned by digest.

    ``verapdf/cli:latest`` moves with every veraPDF release, so the same commit
    could pass the gate one day and fail it the next. The tag stays in a
    comment so the next bump knows which release the digest is.
    """
    code = _workflow_code("verapdf.yml")
    refs = re.findall(r"verapdf/cli[^\s\"']*", code)
    assert refs, "verapdf.yml no longer runs verapdf/cli — update this guard"
    for ref in refs:
        assert re.fullmatch(r"verapdf/cli(:[\w.-]+)?@sha256:[0-9a-f]{64}", ref), (
            f"verapdf.yml runs `{ref}` — pin it by @sha256: digest"
        )
    text = (_WORKFLOW_DIR / "verapdf.yml").read_text(encoding="utf-8")
    assert re.search(r"#\s*verapdf/cli:v?\d", text), (
        "verapdf.yml: keep the pinned image's tag in a comment (`# verapdf/cli:vX.Y.Z`)"
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
