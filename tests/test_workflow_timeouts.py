# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every CI job has a time limit.

Without ``timeout-minutes`` a hanging step holds a runner for GitHub's default
six hours; a weekly dependency run once hung for 58 minutes before it failed.
Each job's limit is a few times its usual run, and at most 90 minutes.
"""

from pathlib import Path

import pytest
import yaml

from tests.test_workflow_triggers import _workflow_files


def _bad_limits(text: str) -> dict:
    """Jobs whose ``timeout-minutes`` is missing or not a whole number of 1–90."""
    jobs = yaml.safe_load(text)["jobs"]
    # A job that calls a reusable workflow takes no timeout of its own.
    limits = {name: job.get("timeout-minutes") for name, job in jobs.items() if "uses" not in job}
    return {name: m for name, m in limits.items() if not (isinstance(m, int) and 1 <= m <= 90)}


@pytest.mark.parametrize("workflow", _workflow_files(), ids=lambda path: path.name)
def test_every_job_has_a_time_limit(workflow: Path):
    bad = _bad_limits(workflow.read_text(encoding="utf-8"))
    assert not bad, f"{workflow.name}: timeout-minutes must be 1–90: {bad}"


def test_the_guard_can_fail():
    jobs = """
jobs:
  none: {runs-on: ubuntu-latest}
  quoted: {runs-on: ubuntu-latest, timeout-minutes: "30"}
  too-long: {runs-on: ubuntu-latest, timeout-minutes: 360}
  fine: {runs-on: ubuntu-latest, timeout-minutes: 30}
  reusable: {uses: ./.github/workflows/other.yml}
"""
    assert set(_bad_limits(jobs)) == {"none", "quoted", "too-long"}
