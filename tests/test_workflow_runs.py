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
