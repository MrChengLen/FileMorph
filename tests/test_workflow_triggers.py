# SPDX-License-Identifier: AGPL-3.0-or-later
"""No workflow may wait for a ``release`` event.

``release.yml`` publishes every release with the built-in ``GITHUB_TOKEN``,
and GitHub starts no workflow runs for events that token causes (apart from
``workflow_dispatch`` and ``repository_dispatch``). A workflow triggered by
``on: release`` therefore never runs, and nothing reports it: no failed run,
just a missing release asset. It happened twice. ``sbom.yml`` left the v1.1.0
release without its SBOM until that step moved into ``release.yml``, and
``build-desktop.yml`` did not run once in five months before it was retired.

Work that follows a release belongs in ``release.yml`` itself, as a step or a
job with ``needs:``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_WORKFLOW_DIR = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def _workflow_files() -> list[Path]:
    files = sorted(_WORKFLOW_DIR.glob("*.yml")) + sorted(_WORKFLOW_DIR.glob("*.yaml"))
    assert files, f"no workflow files found under {_WORKFLOW_DIR}"
    return files


def _triggers(workflow: Path) -> set[str]:
    spec = yaml.safe_load(workflow.read_text(encoding="utf-8")) or {}
    # YAML 1.1 reads the bare key `on` as the boolean True.
    on = spec.get("on", spec.get(True))
    assert on, f"{workflow.name}: no `on:` triggers found"
    if isinstance(on, str):
        return {on}
    return set(on)


@pytest.mark.parametrize("workflow", _workflow_files(), ids=lambda p: p.name)
def test_no_workflow_triggers_on_release(workflow: Path) -> None:
    assert "release" not in _triggers(workflow), (
        f"{workflow.name} triggers on `release`, which never fires here: "
        f"release.yml publishes releases with GITHUB_TOKEN, and GitHub starts "
        f"no workflow runs for that token's events. Move the work into "
        f"release.yml as a step or a `needs:` job."
    )


# No workflow in the repo triggers on `release` any more, so the test above
# never exercises the detection path; this keeps the guard able to fail.
@pytest.mark.parametrize(
    "on",
    [
        "on: release",
        "on: [push, release]",
        "on:\n  release:\n    types: [published]",
        '"on":\n  release:',
    ],
    ids=["string", "list", "mapping", "quoted-on"],
)
def test_triggers_detects_release(tmp_path: Path, on: str) -> None:
    workflow = tmp_path / "workflow.yml"
    workflow.write_text(f"{on}\njobs: {{}}\n", encoding="utf-8", newline="\n")
    assert "release" in _triggers(workflow)
