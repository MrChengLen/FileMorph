# SPDX-License-Identifier: AGPL-3.0-or-later
"""Trigger rules that a workflow could break without a failed run to show for it.

No workflow may wait for a ``release`` event.

``release.yml`` publishes every release with the built-in ``GITHUB_TOKEN``,
and GitHub starts no workflow runs for events that token causes (apart from
``workflow_dispatch`` and ``repository_dispatch``). A workflow triggered by
``on: release`` therefore never runs, and nothing reports it: no failed run,
just a missing release asset. It happened twice. ``sbom.yml`` left the v1.1.0
release without its SBOM until that step moved into ``release.yml``, and
``build-desktop.yml`` did not run once in five months before it was retired.

Work that follows a release belongs in ``release.yml`` itself, as a step or a
job with ``needs:``.

And ``notify-ops.yml`` may start a deploy only after a push or a manual run in
this repository, never after a run for a pull request, and only for main's
newest commit, once both the Docker and the CI workflow succeeded for it; see
``test_notify_ops_deploys_only_after_pushes_and_manual_runs``,
``test_notify_ops_dispatches_only_after_docker_and_ci_succeeded``,
``test_notify_ops_gate_lets_exactly_one_of_the_two_runs_dispatch`` and
``test_notify_ops_dispatch_names_the_commit``. The deploy pulls a moving image
tag, so docker.yml queues its builds per ref: see
``test_docker_builds_queue_per_ref_and_are_never_cancelled``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import NamedTuple

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


# notify-ops.yml's condition for starting a deploy, whitespace aside.
_DEPLOY_CONDITION = (
    "github.event.workflow_run.conclusion == 'success' && "
    "github.event.workflow_run.head_repository.full_name == github.repository && "
    "(github.event.workflow_run.event == 'push' || "
    "github.event.workflow_run.event == 'workflow_dispatch')"
)


def test_notify_ops_deploys_only_after_pushes_and_manual_runs() -> None:
    """notify-ops.yml starts a deploy only after a successful run of the
    workflows it listens for that a push or a manual dispatch started in this
    repository, on main. A run for a pull request, docker-pr.yml's among them,
    never leads to one. The trigger and the condition are pinned word for
    word: an edit to either changes what reaches production, so it should come
    with an edit here. Docker and CI both have to be listed: with Docker alone
    a merge that broke the tests reached production as soon as its image was
    built, and with CI alone nothing would wait for the image.
    """
    notify = yaml.safe_load((_WORKFLOW_DIR / "notify-ops.yml").read_text(encoding="utf-8"))
    trigger = notify.get("on", notify.get(True))["workflow_run"]
    assert trigger == {
        "workflows": ["Docker", "CI"],
        "types": ["completed"],
        "branches": ["main"],
    }, f"notify-ops.yml's workflow_run trigger changed: {trigger}"
    names = {
        (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("name")
        for path in _workflow_files()
    }
    for name in trigger["workflows"]:
        assert name in names, (
            f"notify-ops.yml listens for a workflow named {name!r}, but none is called "
            f"that: nothing would be deployed after a merge"
        )
    for name, job in notify["jobs"].items():
        condition = " ".join(str(job.get("if", "")).split())
        assert condition == _DEPLOY_CONDITION, (
            f"notify-ops.yml job `{name}` runs under `if: {condition}`, not the pinned "
            f"condition: {_DEPLOY_CONDITION}"
        )


def test_docker_builds_queue_per_ref_and_are_never_cancelled() -> None:
    """docker.yml builds one commit at a time per ref, so the image tags move in
    merge order.

    Two merges seconds apart used to build side by side, and the older build
    could finish last and take ``:latest`` and ``:office`` over (2026-09-26 and
    2026-09-28, among other days). A group per ref queues them: GitHub keeps one
    pending run and cancels it when a newer run queues, so the newest commit
    builds last. A running build is never cancelled: it pushes, signs and
    attests.
    """
    docker = yaml.safe_load((_WORKFLOW_DIR / "docker.yml").read_text(encoding="utf-8"))
    assert docker.get("concurrency") == {
        "group": "docker-${{ github.ref }}",
        "cancel-in-progress": False,
    }, f"docker.yml: builds no longer queue per ref, in order: {docker.get('concurrency')}"


def _notify_ops() -> dict:
    return yaml.safe_load((_WORKFLOW_DIR / "notify-ops.yml").read_text(encoding="utf-8"))


def _gate_and_dispatch_steps(notify: dict) -> tuple[dict, dict]:
    """The step that checks the other workflow, and the one that holds the PAT."""
    steps = notify["jobs"]["notify"]["steps"]
    gates = [step for step in steps if step.get("id") == "gate"]
    assert len(gates) == 1, "notify-ops.yml: expected one step with `id: gate`"
    holding = [step for step in steps if "secrets." in json.dumps(step)]
    assert len(holding) == 1, (
        f"notify-ops.yml: expected the dispatch to be the one step that reads a secret, "
        f"found {[step.get('name') for step in holding]}"
    )
    assert steps.index(gates[0]) < steps.index(holding[0]), (
        "notify-ops.yml: the gate has to come before the dispatch"
    )
    return gates[0], holding[0]


# The dispatch event's body: the event type the deploy side listens for, and the
# commit, built with jq so that nothing in it needs quoting by hand.
_DISPATCH_BODY = (
    """body=$(jq -n --arg sha "$SHA" """
    """'{event_type:"filemorph-published",client_payload:{sha:$sha}}')"""
)


def test_notify_ops_dispatches_only_after_docker_and_ci_succeeded() -> None:
    """notify-ops.yml's dispatch waits for the other workflow, and for main's tip.

    Either workflow finishing starts the job. Its first step, the gate, reads
    the other workflow's newest run for the same commit and lets the dispatch
    step run only when that run succeeded, this one finished later and the
    commit is still the tip of main, read from git: the deploy pulls a moving
    image tag, so a commit that main has moved past would roll out a newer,
    untested image. A commit whose tests failed is not deployed, and one that
    passed is deployed once. Pinned: the gate's inputs (the commit and the
    finishing time of the run that started the job; `github.sha` is stale for a
    re-run and must not be read), its read-only token, a timeout, that it asks
    for the runs of every workflow the trigger lists and reads the tip with
    `git ls-remote`, and that the dispatch is the only step with the PAT, after
    the gate, on its answer alone, and sends the commit.
    """
    notify = _notify_ops()
    assert notify["permissions"] == {}, "notify-ops.yml: no workflow-wide token permissions"
    job = notify["jobs"]["notify"]
    assert job["permissions"] == {"actions": "read"}, (
        f"notify-ops.yml: the job may read workflow runs and nothing else, not {job['permissions']}"
    )
    assert 0 < job.get("timeout-minutes", 0) <= 15, (
        "notify-ops.yml: a hung call should fail the job soon, not hold a runner for six hours"
    )
    gate, dispatch = _gate_and_dispatch_steps(notify)
    assert dispatch.get("if") == "steps.gate.outputs.dispatch == 'true'", (
        "notify-ops.yml: the dispatch has to run on the gate's answer alone"
    )
    assert gate["env"] == {
        "GH_TOKEN": "${{ github.token }}",
        "REPO": "${{ github.repository }}",
        "SHA": "${{ github.event.workflow_run.head_sha }}",
        "WORKFLOW": "${{ github.event.workflow_run.name }}",
        "UPDATED": "${{ github.event.workflow_run.updated_at }}",
    }, f"notify-ops.yml: the gate's inputs changed: {gate['env']}"
    assert "workflows/$file/runs?head_sha=$SHA" in gate["run"], (
        "notify-ops.yml: the gate no longer asks for the other workflow's runs for the commit"
    )
    assert 'git ls-remote "https://github.com/$REPO" refs/heads/main' in gate["run"], (
        "notify-ops.yml: the gate no longer reads the tip of main from git"
    )
    assert "GITHUB_SHA" not in gate["run"] and "github.sha" not in json.dumps(gate), (
        "notify-ops.yml: github.sha is main's tip when the run started, stale for a re-run; "
        "the gate has to read the tip live"
    )
    trigger = notify.get("on", notify.get(True))["workflow_run"]
    files = {
        (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("name"): path.name
        for path in _workflow_files()
    }
    for name in trigger["workflows"]:
        assert name in files, f"notify-ops.yml listens for {name!r}, but no workflow is called that"
        assert files[name] in gate["run"], (
            f"notify-ops.yml: the gate never asks for the runs of {files[name]} ({name}), "
            f"so a failure there would not hold the deploy back"
        )
    assert set(dispatch["env"]) == {"PAT", "SHA"}, (
        f"notify-ops.yml: the dispatch gets the PAT and the commit, not {set(dispatch['env'])}"
    )
    assert dispatch["env"]["SHA"] == "${{ github.event.workflow_run.head_sha }}", (
        "notify-ops.yml: the dispatch has to name the commit the run was for"
    )
    assert _DISPATCH_BODY in dispatch["run"] and '-d "$body"' in dispatch["run"], (
        "notify-ops.yml: the dispatch body changed; pinned: " + _DISPATCH_BODY
    )


# What the steps of notify-ops.yml do with the API's and git's answers, run for
# real in bash with stand-ins for `gh`, `git`, `curl` and `sleep` on the PATH. It
# needs bash and jq (GitHub's runners have both); a machine without them skips
# the tests, but a runner must not.
_REPO = "MrChengLen/FileMorph"
_SHA, _NEWER_SHA = "a" * 40, "b" * 40
_T1, _T2, _T3 = "2026-10-06T12:00:00Z", "2026-10-06T12:01:00Z", "2026-10-06T12:02:00Z"

# `gh api <path> --jq <program>`: the program runs over the canned runs of the
# workflow the path names, except that request number N gets answer.N.json if the
# case has one, or fails if it has an error.N: what the API does now and then,
# an empty list for a run that exists, a run that has just ended still shown as
# running, or a failed request.
_GH_STUB = r"""#!/usr/bin/env bash
set -o pipefail
case "$2" in
  */workflows/ci.yml/runs\?*) runs="$STUB_DIR/ci.json" ;;
  */workflows/docker.yml/runs\?*) runs="$STUB_DIR/docker.json" ;;
  *) echo "unexpected request: $2" >&2; exit 1 ;;
esac
echo x >> "$STUB_DIR/requests"
n=$(( $(wc -l < "$STUB_DIR/requests") ))
if [ -f "$STUB_DIR/error.$n" ]; then echo "error connecting to api.github.com" >&2; exit 1; fi
if [ -f "$STUB_DIR/answer.$n.json" ]; then runs="$STUB_DIR/answer.$n.json"; fi
jq -r "$4" "$runs" | tr -d '\r'
"""

# `git ls-remote https://github.com/<repo> refs/heads/main`, the only git call
# the gate may make: answers with $STUB_TIP, nothing if that is empty, and fails
# the way git does when it cannot reach the repository if it is "fail".
_GIT_STUB = r"""#!/usr/bin/env bash
if [ "$*" != "ls-remote https://github.com/$REPO refs/heads/main" ]; then
  echo "unexpected git call: $*" >&2; exit 2
fi
echo x >> "$STUB_DIR/tip-reads"
if [ "$STUB_TIP" = fail ]; then
  echo "fatal: could not read Username for 'https://github.com': terminal prompts disabled" >&2
  exit 128
fi
if [ -n "$STUB_TIP" ]; then printf '%s\trefs/heads/main\n' "$STUB_TIP"; fi
"""

# `curl` as the dispatch step calls it: keeps the request body, writes the
# response file it is told to and answers the status code `-w` asks for.
_CURL_STUB = r"""#!/usr/bin/env bash
out=
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift ;;
    -d) printf '%s' "$2" > "$STUB_DIR/body.json"; shift ;;
    -X|-H|-w) shift ;;
  esac
  shift
done
if [ -n "$out" ]; then echo '{}' > "$out"; fi
printf 204
"""

_SLEEP_STUB = '#!/usr/bin/env bash\necho "$*" >> "$STUB_DIR/sleeps"\n'


def _run(
    number: int,
    updated: str,
    *,
    status: str = "completed",
    conclusion: str = "success",
    event: str = "push",
    branch: str = "main",
    repo: str = _REPO,
) -> dict:
    """The fields of a workflow run that the gate reads."""
    return {
        "run_number": number,
        "status": status,
        "conclusion": conclusion if status == "completed" else None,
        "updated_at": updated,
        "event": event,
        "head_branch": branch,
        "head_repository": {"full_name": repo},
    }


def _starts_notify_job(run: dict) -> bool:
    """The trigger's branch filter and the job's `if`, which the gate never sees."""
    return (
        run["head_branch"] == "main"
        and run["head_repository"]["full_name"] == _REPO
        and run["event"] in ("push", "workflow_dispatch")
        and run["conclusion"] == "success"
    )


def _need(tool: str) -> str:
    found = shutil.which(tool)
    if found is None:
        reason = f"`{tool}` is not installed, which the tests of notify-ops.yml's steps run"
        if os.environ.get("GITHUB_ACTIONS"):
            pytest.fail(f"{reason}; GitHub's runners have it, so this must not be skipped there")
        pytest.skip(reason)
    return found


def _count(folder: Path, name: str) -> int:
    path = folder / name
    return len(path.read_text(encoding="utf-8").splitlines()) if path.exists() else 0


def _step_environment(folder: Path, **inputs: str) -> dict[str, str]:
    """The stand-ins first on the PATH, and the inputs the step is given; nothing
    GitHub-specific is inherited, so a step that read `GITHUB_SHA` would get the
    stale value set here, not the one of the runner the tests run on."""
    inherited = {k: v for k, v in os.environ.items() if not k.startswith(("GITHUB_", "GH_"))}
    return {
        **inherited,
        "PATH": f"{folder}{os.pathsep}{os.environ['PATH']}",
        "STUB_DIR": folder.as_posix(),
        "REPO": _REPO,
        "SHA": _SHA,
        "GITHUB_SHA": "0" * 40,
        **inputs,
    }


def _install(folder: Path, **tools: str) -> None:
    folder.mkdir()
    for name, content in tools.items():
        (folder / name).write_text(content, encoding="utf-8", newline="\n")
        (folder / name).chmod(0o755)


def _write_json(path: Path, runs: list[dict]) -> None:
    path.write_text(json.dumps({"workflow_runs": runs}), encoding="utf-8", newline="\n")


class _Gate(NamedTuple):
    outcome: str  # "dispatch", "skip" (no deploy from this run) or "error" (the step fails)
    stdout: str
    stderr: str
    requests: int  # asks of the API
    sleeps: int
    tip_reads: int


def _gate(
    bash: str,
    folder: Path,
    workflow: str,
    updated: str,
    docker: list[dict],
    ci: list[dict],
    earlier: list[list[dict] | str],
    tip: str,
) -> _Gate:
    """Run the gate when `workflow` has finished at `updated`, with main at `tip`
    ("fail" for a git that cannot reach the repository). `earlier` are the
    answers its first requests get before the real ones: a run list, or "error"."""
    gate, _ = _gate_and_dispatch_steps(_notify_ops())
    _install(folder, gh=_GH_STUB, git=_GIT_STUB, sleep=_SLEEP_STUB)
    _write_json(folder / "docker.json", docker)
    _write_json(folder / "ci.json", ci)
    for number, answer in enumerate(earlier, 1):
        if answer == "error":
            (folder / f"error.{number}").write_text("", encoding="utf-8", newline="\n")
        else:
            _write_json(folder / f"answer.{number}.json", answer)
    output = folder / "github_output"
    output.write_text("", encoding="utf-8", newline="\n")
    env = _step_environment(
        folder,
        WORKFLOW=workflow,
        UPDATED=updated,
        STUB_TIP=tip,
        GITHUB_OUTPUT=output.as_posix(),
    )
    done = subprocess.run(
        [bash, "-e", "-o", "pipefail", "-c", gate["run"]],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if done.returncode != 0:
        outcome = "error"
    elif output.read_text(encoding="utf-8").strip() == "dispatch=true":
        outcome = "dispatch"
    else:
        outcome = "skip"
    return _Gate(
        outcome,
        done.stdout,
        done.stderr,
        _count(folder, "requests"),
        _count(folder, "sleeps"),
        _count(folder, "tip-reads"),
    )


def _case(
    case_id: str,
    docker: list[dict],
    ci: list[dict],
    expected: tuple[str, str],
    *,
    earlier: dict[str, list[list[dict] | str]] | None = None,
    tip: str = _SHA,
    message: str | None = None,
) -> object:
    return pytest.param(docker, ci, earlier or {}, tip, expected, message, id=case_id)


_FAILS = ["error", "error", "error"]
# Docker runs, CI runs, what each notify run sees, in answers to its first
# requests, instead of the real ones, where main stands (the commit itself, unless
# stated) and what the notify run started by Docker and the one started by CI
# do. "-": that workflow has no successful run on main for the job to start from.
# Wherever both succeeded and main still stands at the commit, exactly one of the
# two dispatches. `message` is a line that one of them must print.
_GATE_CASES = [
    _case("ci-finishes-last", [_run(1, _T1)], [_run(1, _T2)], ("skip", "dispatch")),
    _case("docker-finishes-last", [_run(1, _T2)], [_run(1, _T1)], ("dispatch", "skip")),
    _case("same-second", [_run(1, _T1)], [_run(1, _T1)], ("dispatch", "skip")),
    _case(
        "ci-still-running",
        [_run(1, _T1)],
        [_run(1, _T2, status="in_progress")],
        ("skip", "-"),
        message=f"::warning::No deploy: CI in_progress for {_SHA}",
    ),
    _case(
        "ci-failed",
        [_run(1, _T1)],
        [_run(1, _T2, conclusion="failure")],
        ("skip", "-"),
        message=f"::warning::No deploy: CI completed/failure for {_SHA}",
    ),
    _case(
        "ci-cancelled",
        [_run(1, _T1)],
        [_run(1, _T2, conclusion="cancelled")],
        ("skip", "-"),
        message=f"::warning::No deploy: CI completed/cancelled for {_SHA}",
    ),
    _case(
        "docker-failed",
        [_run(1, _T1, conclusion="failure")],
        [_run(1, _T2)],
        ("-", "skip"),
        message=f"::warning::No deploy: Docker completed/failure for {_SHA}",
    ),
    _case("no-ci-run", [_run(1, _T1)], [], ("error", "-"), message="::error::No "),
    # A green run that must not count as this commit's CI: the newest run of any
    # kind would be it (newer than the real, unfinished one), and it would let
    # Docker dispatch (older than the Docker run).
    *[
        _case(
            name,
            [_run(1, _T3)],
            [_run(1, _T1, status="in_progress"), _run(2, _T2, **other)],
            ("skip", "-"),
            message=f"::warning::No deploy: CI in_progress for {_SHA}",
        )
        for name, other in (
            ("ci-run-for-a-pull-request", {"event": "pull_request"}),
            ("ci-run-from-another-repository", {"repo": "someone/FileMorph"}),
            ("ci-run-on-another-branch", {"branch": "feature"}),
        )
    ],
    _case(
        "manual-docker-rebuild-after-ci",
        [_run(1, _T1), _run(2, _T3, event="workflow_dispatch")],
        [_run(1, _T2)],
        ("dispatch", "skip"),
    ),
    _case(
        "empty-twice-then-run",
        [_run(1, _T1)],
        [_run(1, _T2)],
        ("skip", "dispatch"),
        earlier={"Docker": [[], []], "CI": [[], []]},
    ),
    _case(
        "empty-three-times",
        [_run(1, _T1)],
        [_run(1, _T2)],
        ("error", "error"),
        earlier={"Docker": [[], [], []], "CI": [[], [], []]},
        message="::error::No ",
    ),
    # CI ended first; when Docker, the last to finish, asks, CI still shows as running.
    _case(
        "ci-has-just-ended",
        [_run(1, _T2)],
        [_run(1, _T1)],
        ("dispatch", "skip"),
        earlier={"Docker": [[_run(1, _T1, status="in_progress")]]},
    ),
    _case(
        "request-fails-once-then-run",
        [_run(1, _T1)],
        [_run(1, _T2)],
        ("skip", "dispatch"),
        earlier={"Docker": ["error"], "CI": ["error"]},
    ),
    _case(
        "request-fails-three-times",
        [_run(1, _T1)],
        [_run(1, _T2)],
        ("error", "error"),
        earlier={"Docker": _FAILS, "CI": _FAILS},
        message="::error::No ",
    ),
    # Main has moved on: the last to finish does not dispatch, whichever it is.
    _case(
        "main-has-moved-on-ci-last",
        [_run(1, _T1)],
        [_run(1, _T2)],
        ("skip", "skip"),
        tip=_NEWER_SHA,
        message=f"main has moved on to {_NEWER_SHA}; that commit's own runs deploy it.",
    ),
    _case(
        "main-has-moved-on-docker-last",
        [_run(1, _T2)],
        [_run(1, _T1)],
        ("skip", "skip"),
        tip=_NEWER_SHA,
        message=f"main has moved on to {_NEWER_SHA}; that commit's own runs deploy it.",
    ),
    # Main's tip cannot be read: the last to finish fails the step, visibly.
    *[
        _case(
            f"tip-{name}-{last}-last",
            [_run(1, _T1 if last == "ci" else _T2)],
            [_run(1, _T2 if last == "ci" else _T1)],
            ("skip", "error") if last == "ci" else ("error", "skip"),
            tip=tip,
            message="::error::Could not read the tip of main",
        )
        for name, tip in (("unreachable", "fail"), ("empty", ""), ("garbled", "not-a-commit"))
        for last in ("ci", "docker")
    ],
]


@pytest.mark.parametrize(("docker", "ci", "earlier", "tip", "expected", "message"), _GATE_CASES)
def test_notify_ops_gate_lets_exactly_one_of_the_two_runs_dispatch(
    tmp_path: Path,
    docker: list[dict],
    ci: list[dict],
    earlier: dict[str, list[list[dict] | str]],
    tip: str,
    expected: tuple[str, str],
    message: str | None,
) -> None:
    """Docker's and CI's completions each start a notify run; of the two, the
    one whose workflow finished later dispatches, whatever order they run in,
    and none does while the other workflow is unfinished or failed, when the
    only run of it that looks green is not a push or a manual dispatch on main
    in this repository (a pull request tests a merge result, not the commit),
    or when main has moved on from the commit: the newer commit's own runs
    deploy it, and the image tag the deploy pulls may be theirs. A request
    that fails, or a run the API shows as missing, or as unfinished a moment
    after it ended, is asked for again; a run that stays missing, and a tip of
    main that cannot be read, fail the step instead of skipping the deploy
    unseen, and a deploy that is held back says so in a warning.
    """
    bash, _ = _need("bash"), _need("jq")
    results: dict[str, _Gate | None] = {}
    for workflow, own in (("Docker", docker), ("CI", ci)):
        started_by = [run for run in own if _starts_notify_job(run)]
        if not started_by:
            results[workflow] = None
            continue
        finished = max(started_by, key=lambda run: run["run_number"])["updated_at"]
        results[workflow] = _gate(
            bash,
            tmp_path / workflow,
            workflow,
            finished,
            docker,
            ci,
            earlier.get(workflow, []),
            tip,
        )
    ran = {workflow: gate for workflow, gate in results.items() if gate}
    transcript = "".join(
        f"\n--- notify run started by {workflow}: {gate.outcome}\nstdout:\n{gate.stdout}"
        f"stderr:\n{gate.stderr}"
        for workflow, gate in ran.items()
    )
    outcomes = tuple(gate.outcome if gate else "-" for gate in results.values())
    assert outcomes == expected, f"(Docker, CI) notify runs: {outcomes}, not {expected}{transcript}"
    if message:
        assert any(message in gate.stdout for gate in ran.values()), (
            f"no notify run printed {message!r}{transcript}"
        )
    for workflow, gate in ran.items():
        assert 1 <= gate.requests <= 3 and gate.sleeps == gate.requests - 1, (
            f"{workflow}: {gate.requests} requests and {gate.sleeps} sleeps; it asks at most "
            f"three times and sleeps only between asks, not after the last{transcript}"
        )
        assert gate.tip_reads <= 1, f"{workflow} read main's tip {gate.tip_reads} times{transcript}"
        if gate.outcome == "error":
            assert "::error::" in gate.stdout, (
                f"{workflow}: the step failed without an ::error:: line{transcript}"
            )


def test_notify_ops_dispatch_names_the_commit(tmp_path: Path) -> None:
    """The dispatch's body carries the event type the deploy side listens for and
    the commit the checks passed for, as JSON that jq builds, so that a deploy
    can pin to the commit."""
    bash, _ = _need("bash"), _need("jq")
    _, dispatch = _gate_and_dispatch_steps(_notify_ops())
    folder = tmp_path / "dispatch"
    _install(folder, curl=_CURL_STUB)
    env = _step_environment(folder, PAT="placeholder")
    done = subprocess.run(
        [bash, "-e", "-o", "pipefail", "-c", dispatch["run"]],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert done.returncode == 0, f"the dispatch step failed:\n{done.stdout}\n{done.stderr}"
    body = json.loads((folder / "body.json").read_text(encoding="utf-8"))
    assert body == {"event_type": "filemorph-published", "client_payload": {"sha": _SHA}}, body
