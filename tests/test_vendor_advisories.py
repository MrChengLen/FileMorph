# SPDX-License-Identifier: AGPL-3.0-or-later
"""scripts/check_vendor_advisories.py — the OSV check for vendored browser code.

pip-audit and Dependabot do not see the browser code vendored under
app/static/vendor/; this check covers it. These tests never touch the network: OSV is
replaced either by a fake ``fetch`` or by a patched ``urlopen`` that serves a
canned answer. CI runs the real check (ci.yml) on every build and weekly
(deps-latest.yml).
"""

from __future__ import annotations

import datetime as dt
import http.client  # IncompleteRead, raised by the fake urlopen below
import importlib.util
import io
import json
import re
import urllib.error
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location(
    "check_vendor_advisories", ROOT / "scripts" / "check_vendor_advisories.py"
)
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)

MANIFEST = {
    "files": [
        {"package": "swagger-ui-dist", "version": "5.33.1", "bundles": {"dompurify": "3.4.13"}},
        {"package": "swagger-ui-dist", "version": "5.33.1"},
        {"package": "chart.js", "version": "4.4.0"},
    ]
}
ACCEPTED = [
    {
        "id": "GHSA-aaaa",
        "package": "dompurify",
        "version": "3.4.13",
        "reason": "not reachable",
        "review_by": "2026-11-02",
    }
]
TODAY = dt.date(2026, 10, 20)


def _fetch(advisories):
    """A stand-in for OSV that reports ``advisories`` ({package: [ids]})."""

    def fetch(pkgs):
        return {pkg: advisories.get(pkg[0], []) for pkg in pkgs}

    return fetch


def _osv_answer(monkeypatch, answer, sent=None):
    """Make every urlopen call return ``answer`` (bytes, or a JSON-able value)."""

    def urlopen(request, timeout):
        if sent is not None:
            sent.append(json.loads(request.data))
        body = answer if isinstance(answer, bytes) else json.dumps(answer).encode()
        return io.BytesIO(body)

    monkeypatch.setattr(check.urllib.request, "urlopen", urlopen)


# ── the decision ────────────────────────────────────────────────────────────


def test_every_shipped_package_is_checked_once_bundled_ones_included():
    assert check.packages(MANIFEST) == [
        ("chart.js", "4.4.0"),
        ("dompurify", "3.4.13"),
        ("swagger-ui-dist", "5.33.1"),
    ]


def test_no_advisory_passes():
    code, lines = check.run(MANIFEST, _fetch({}), TODAY, [])
    assert code == 0
    assert "chart.js@4.4.0" in lines[0]


def test_an_advisory_that_is_not_accepted_fails():
    code, lines = check.run(MANIFEST, _fetch({"chart.js": ["GHSA-bbbb"]}), TODAY, ACCEPTED)
    assert code == 1
    assert any(line.startswith("FAIL:") and "GHSA-bbbb" in line for line in lines)


def test_an_accepted_advisory_passes_through_its_review_date():
    advisories = {"dompurify": ["GHSA-aaaa"]}
    code, lines = check.run(MANIFEST, _fetch(advisories), dt.date(2026, 11, 2), ACCEPTED)
    assert code == 0
    assert any("accepted until 2026-11-02" in line for line in lines)


def test_an_acceptance_fails_again_after_its_review_date():
    advisories = {"dompurify": ["GHSA-aaaa"]}
    code, lines = check.run(MANIFEST, _fetch(advisories), dt.date(2026, 11, 3), ACCEPTED)
    assert code == 1
    assert any("review date 2026-11-02 has passed" in line for line in lines)


def test_an_acceptance_only_covers_its_own_package():
    code, _lines = check.run(MANIFEST, _fetch({"chart.js": ["GHSA-aaaa"]}), TODAY, ACCEPTED)
    assert code == 1


def test_an_acceptance_only_covers_its_own_version():
    newer = {"files": [{"package": "x", "version": "1", "bundles": {"dompurify": "3.4.14"}}]}
    code, _lines = check.run(newer, _fetch({"dompurify": ["GHSA-aaaa"]}), TODAY, ACCEPTED)
    assert code == 1


def test_an_acceptance_no_longer_needed_is_reported_without_failing():
    code, lines = check.run(MANIFEST, _fetch({}), TODAY, ACCEPTED)
    assert code == 0
    assert any("no longer reported" in line and "GHSA-aaaa" in line for line in lines)


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param({"version": "1"}, id="no-package"),
        pytest.param({"package": "x", "version": "1", "bundles": None}, id="bundles-null"),
        pytest.param({"package": "x", "version": "1", "bundles": ["dompurify"]}, id="bundles-list"),
    ],
)
def test_a_broken_manifest_is_its_own_exit_code(entry):
    code, lines = check.run({"files": [entry]}, _fetch({}), TODAY, [])
    assert code == 2
    assert lines[0].startswith("ERROR:")


# ── the OSV answer: anything incomplete is an error, never "no advisory" ─────


def test_osv_is_asked_once_for_every_package_in_order(monkeypatch):
    sent = []
    _osv_answer(monkeypatch, {"results": [{}, {"vulns": [{"id": "GHSA-cccc"}]}, {}]}, sent)
    pkgs = check.packages(MANIFEST)
    assert check.query_osv(pkgs) == {
        ("chart.js", "4.4.0"): [],
        ("dompurify", "3.4.13"): ["GHSA-cccc"],
        ("swagger-ui-dist", "5.33.1"): [],
    }
    assert sent == [
        {
            "queries": [
                {"package": {"name": name, "ecosystem": "npm"}, "version": version}
                for name, version in pkgs
            ]
        }
    ]


@pytest.mark.parametrize(
    "answer",
    [
        pytest.param(b"<html>busy</html>", id="not-json"),
        pytest.param([], id="not-an-object"),
        pytest.param({}, id="no-results"),
        pytest.param({"results": "abc"}, id="results-not-a-list"),
        pytest.param({"results": [{}, {}]}, id="fewer-results-than-queries"),
        pytest.param({"results": [{}, {"next_page_token": "x"}, {}]}, id="paginated"),
        pytest.param({"results": [{}, {"vulns": None}, {}]}, id="vulns-null"),
        pytest.param({"results": [{}, {"vulns": [{}]}, {}]}, id="advisory-without-id"),
    ],
)
def test_an_incomplete_osv_answer_cannot_pass(monkeypatch, answer):
    _osv_answer(monkeypatch, answer)
    code, lines = check.run(MANIFEST, check.query_osv, TODAY, ACCEPTED)
    assert code == 2
    assert lines[0].startswith("ERROR:")


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(urllib.error.URLError("no route to host"), id="unreachable"),
        pytest.param(
            urllib.error.HTTPError(check.OSV_QUERYBATCH, 503, "Service Unavailable", None, None),
            id="http-503",
        ),
        pytest.param(http.client.IncompleteRead(b""), id="incomplete-read"),
    ],
)
def test_osv_failing_is_its_own_exit_code(monkeypatch, error):
    def urlopen(request, timeout):
        raise error

    monkeypatch.setattr(check.urllib.request, "urlopen", urlopen)
    code, lines = check.run(MANIFEST, check.query_osv, TODAY, ACCEPTED)
    assert code == 2
    assert lines[0].startswith("ERROR:")


# ── the real data ───────────────────────────────────────────────────────────


def test_every_acceptance_is_complete():
    for acceptance in check.ACCEPTED:
        assert acceptance["id"].startswith("GHSA-"), acceptance
        assert acceptance["package"] and acceptance["version"], acceptance
        assert acceptance["reason"] and acceptance["reason"].isascii(), acceptance
        dt.date.fromisoformat(acceptance["review_by"])


def test_the_manifest_names_the_dompurify_version_the_swagger_bundle_ships():
    manifest = json.loads(
        (ROOT / "app" / "static" / "vendor" / "manifest.json").read_text(encoding="utf-8")
    )
    bundle = next(e for e in manifest["files"] if e["path"] == "swagger-ui-bundle.js")
    banner = (ROOT / "app" / "static" / "vendor" / "swagger-ui-bundle.js.LICENSE.txt").read_text(
        encoding="utf-8"
    )
    assert bundle["bundles"]["dompurify"] == re.search(r"@license DOMPurify (\S+) ", banner)[1]


@pytest.mark.parametrize(
    "workflow, job",
    [("ci.yml", "lint-and-test"), ("deps-latest.yml", "vendor-advisories")],
)
def test_ci_runs_the_check(workflow, job):
    # Parsed, not grepped: a comment or another job mentioning the command
    # must not satisfy this.
    jobs = yaml.safe_load((ROOT / ".github" / "workflows" / workflow).read_text(encoding="utf-8"))[
        "jobs"
    ]
    runs = [step.get("run") for step in jobs[job]["steps"]]
    assert "python scripts/check_vendor_advisories.py" in runs
