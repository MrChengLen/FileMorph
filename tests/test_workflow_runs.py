# SPDX-License-Identifier: AGPL-3.0-or-later
"""How the workflows run: on a pinned image, without queueing on main, and with
every check of the required job reported.

* ``ubuntu-latest`` moved from Ubuntu 24.04 to 26.04 in November 2026, job by
  job over several weeks, and the 26.04 image had no package by the name CI
  installed: the required check turned red with nothing changed in the
  repository (#309), and for a while a job could land on either image. Pinned,
  the image changes only with a pull request. deps-latest.yml keeps
  ``ubuntu-latest`` on purpose: its weekly run meets the next image first.
* CI grouped its runs per ref, so on main a merge's checks waited for the
  previous merge's: on 2026-11-04 the commit that was then deployed waited
  3 minutes. notify-ops.yml deploys main's tip only after its CI, so that wait
  was the deploy's.
* A failed check stopped lint-and-test at that step: a new advisory left the
  tests unrun 13 times in two weeks of October 2026, and nobody could tell
  whether a change passed them.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

_WORKFLOW_DIR = Path(__file__).resolve().parent.parent / ".github" / "workflows"
_PINNED = "ubuntu-26.04"
_CANARY = "deps-latest.yml"


def _workflow(name: str) -> dict:
    return yaml.safe_load((_WORKFLOW_DIR / name).read_text(encoding="utf-8"))


def _jobs() -> list[tuple[str, str, object]]:
    return [
        (path.name, name, job.get("runs-on"))
        for path in sorted(_WORKFLOW_DIR.glob("*.yml"))
        for name, job in yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"].items()
    ]


@pytest.mark.parametrize(("workflow", "job", "runner"), _jobs())
def test_every_job_pins_its_runner_image(workflow: str, job: str, runner: object) -> None:
    expected = "ubuntu-latest" if workflow == _CANARY else _PINNED
    assert runner == expected, (
        f"{workflow} job `{job}` runs on {runner!r}, not {expected!r}: every job pins "
        f"{_PINNED}, and only {_CANARY} follows ubuntu-latest, as the canary"
    )


def test_ci_on_main_runs_every_commit_at_once() -> None:
    """On main each commit is a concurrency group of its own and is never
    cancelled; a pull request's newer push still cancels its older runs."""
    concurrency = _workflow("ci.yml")["concurrency"]
    assert concurrency == {
        "group": (
            "ci-${{ github.workflow }}-"
            "${{ github.ref == 'refs/heads/main' && github.sha || github.ref }}"
        ),
        "cancel-in-progress": "${{ github.ref != 'refs/heads/main' }}",
    }, f"ci.yml: main's runs queue or get cancelled again: {concurrency}"


def test_a_failed_check_does_not_hide_the_ones_after_it() -> None:
    """After the install, every step of lint-and-test runs even when an earlier
    one failed, except the pip-audit and veraPDF steps: tests/test_supply_chain_hygiene.py
    allows them no `if:`, so they keep the default. The job fails either way."""
    steps = _workflow("ci.yml")["jobs"]["lint-and-test"]["steps"]
    ids = [step.get("id") for step in steps]
    assert "deps" in ids and "tests" in ids, "ci.yml: lint-and-test lost its `deps` or `tests` step"
    for step in steps[ids.index("deps") + 1 :]:
        label = f"ci.yml lint-and-test, step {step.get('name')!r}"
        run = step.get("run") or ""
        if (
            "pip-audit" in run
            or "verapdf_check.py" in run
            or "VERAPDF_IMAGE" in step.get("env", {})
        ):
            assert "if" not in step, (
                f"{label}: an audit or veraPDF step keeps the default condition"
            )
            continue
        condition = step.get("if", "")
        assert "!cancelled()" in condition or "failure()" in condition, (
            f"{label} runs under `if: {condition or 'success()'}`, so an earlier failed check "
            f"would skip it"
        )


_TESTS_LOG = """\
tests/test_a.py ....                                                     [100%]

============================ slowest 15 durations =============================
2.50s call     tests/test_a.py::test_slow
0.40s call     tests/test_a.py::test_medium
=========================== short test summary info ============================
SKIPPED [1] tests/test_a.py:10: needs Postgres
================== 3 passed, 1 skipped, 1 warning in 12.34s ===================
"""


def test_the_summary_lists_each_check_the_counts_and_the_slowest_tests(tmp_path: Path) -> None:
    """lint-and-test's Summary step, run for real: one row per check with its
    result, pytest's final line, and only the durations under "Slowest tests"
    (pytest prints the skip list right after them, with no blank line between)."""
    tools = {tool: shutil.which(tool) for tool in ("bash", "jq")}
    if None in tools.values():
        reason = f"needs bash and jq, which GitHub's runners have: {tools}"
        if os.environ.get("GITHUB_ACTIONS"):
            pytest.fail(reason)
        pytest.skip(reason)
    steps = _workflow("ci.yml")["jobs"]["lint-and-test"]["steps"]
    (summary_step,) = [step for step in steps if step.get("name") == "Summary"]
    (tmp_path / "tests.log").write_text(_TESTS_LOG, encoding="utf-8", newline="\n")
    summary = tmp_path / "summary.md"
    env = {
        **os.environ,
        "STEPS": json.dumps({"deps": {"outcome": "success"}, "lint": {"outcome": "failure"}}),
        "RUNNER_TEMP": tmp_path.as_posix(),
        "GITHUB_STEP_SUMMARY": summary.as_posix(),
    }
    done = subprocess.run(
        [tools["bash"], "-e", "-c", summary_step["run"]],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert done.returncode == 0, done.stderr
    text = summary.read_text(encoding="utf-8")
    assert "| deps | ✅ passed |" in text and "| lint | ❌ failed |" in text, text
    assert "**Tests:** 3 passed, 1 skipped, 1 warning in 12.34s" in text, text
    details = text.split("<details>", 1)[1].split("</details>", 1)[0]
    assert "2.50s call" in details and "0.40s call" in details, details
    assert "SKIPPED" not in details and "passed" not in details, details


def test_no_checkout_keeps_the_workflow_token_but_the_one_that_pushes() -> None:
    """actions/checkout leaves the job's token where git finds it (a file that
    .git/config includes) unless told not to, and every later step can read it.
    Only deps-lock.yml's `commit` job pushes (the recompiled lockfiles), so only
    it keeps the default."""
    paths = sorted(_WORKFLOW_DIR.glob("*.y*ml"))
    assert paths, f"no workflow files in {_WORKFLOW_DIR}"
    for path in paths:
        for name, job in yaml.safe_load(path.read_text(encoding="utf-8"))["jobs"].items():
            for step in job.get("steps") or []:
                if not str(step.get("uses", "")).startswith("actions/checkout@"):
                    continue
                keeps = (step.get("with") or {}).get("persist-credentials", True)
                expected = (path.name, name) == ("deps-lock.yml", "commit")
                assert keeps is expected, (
                    f"{path.name} job `{name}`: checkout with persist-credentials "
                    f"{keeps!r}; only deps-lock.yml's `commit` job, which pushes, keeps it"
                )


def _docker_steps() -> list[dict]:
    return _workflow("docker.yml")["jobs"]["build-and-push"]["steps"]


def _run_step(script: str, env: dict[str, str]) -> subprocess.CompletedProcess:
    bash = shutil.which("bash")
    if bash is None:
        if os.environ.get("GITHUB_ACTIONS"):
            pytest.fail("bash is missing, which GitHub's runners have")
        pytest.skip("needs bash")
    return subprocess.run(
        [bash, "-e", "-c", script],
        env={**os.environ, **env},
        capture_output=True,
        text=True,
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("ref", "refused"),
    [
        ("refs/heads/main", False),
        ("refs/heads/Main", True),
        ("refs/heads/pr-anything", True),
        ("refs/tags/v1.5.0", True),
    ],
)
def test_docker_refuses_a_manual_run_off_main_before_anything_else(ref: str, refused: bool) -> None:
    """The tags are unconditional, so a manual run off main would publish that
    ref as :latest and :office. The guard is the first step, runs for manual
    runs only, and compares in bash: GitHub's expressions ignore case."""
    guard = _docker_steps()[0]
    assert guard.get("if") == "github.event_name == 'workflow_dispatch'", guard
    done = _run_step(guard["run"], {"GITHUB_REF": ref})
    assert (done.returncode != 0) is refused, (ref, done.stdout, done.stderr)


def test_docker_installs_cosign_before_it_pushes() -> None:
    """An install that fails after the push leaves the moving tags on an
    unsigned image (2026-10-08 and -12)."""
    steps = _docker_steps()
    names = [step.get("name") for step in steps]
    ids = [step.get("id") for step in steps]
    assert names.index("Install cosign") < ids.index("build"), names


@pytest.mark.parametrize(("failures", "calls", "ok"), [(0, 1, True), (2, 3, True), (3, 3, False)])
def test_docker_signs_each_image_once_by_digest(
    tmp_path: Path, failures: int, calls: int, ok: bool
) -> None:
    """One signature per image, by its digest, on the lower-cased repository;
    three tries, as signing once failed on a bad OIDC answer (2026-10-21). The
    summary names the exact identity the docs verify against."""
    (sign,) = [step for step in _docker_steps() if step.get("name", "").startswith("Sign")]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stubs = {
        "cosign": (
            'echo "$*" >> "$STUB/calls"\nn=$(wc -l < "$STUB/calls")\n[ "$n" -gt "$FAILURES" ]\n'
        ),
        "sleep": 'echo "$*" >> "$STUB/sleeps"\n',
    }
    for name, body in stubs.items():
        stub = bin_dir / name
        stub.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8", newline="\n")
        stub.chmod(0o755)
    digest = "sha256:" + "a" * 64
    summary = tmp_path / "summary.md"
    done = _run_step(
        sign["run"],
        {
            "PATH": f"{bin_dir.as_posix()}{os.pathsep}{os.environ['PATH']}",
            "STUB": tmp_path.as_posix(),
            "FAILURES": str(failures),
            "IMAGE": "ghcr.io/MrChengLen/FileMorph",
            "DIGEST": digest,
            "TAGS": "ghcr.io/mrchenglen/filemorph:latest\nghcr.io/mrchenglen/filemorph:sha-abc1234",
            "TARGET": "base",
            "GITHUB_REPOSITORY": "MrChengLen/FileMorph",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_STEP_SUMMARY": summary.as_posix(),
        },
    )
    assert (done.returncode == 0) is ok, (done.stdout, done.stderr)
    made = (tmp_path / "calls").read_text(encoding="utf-8").splitlines()
    assert made == [f"sign --yes ghcr.io/mrchenglen/filemorph@{digest}"] * calls, made
    if ok:
        text = summary.read_text(encoding="utf-8")
        assert f"cosign verify ghcr.io/mrchenglen/filemorph@{digest}" in text, text
        assert (
            "--certificate-identity 'https://github.com/MrChengLen/FileMorph/"
            ".github/workflows/docker.yml@refs/heads/main'" in text
        ), text
