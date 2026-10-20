#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Check the vendored browser code against the OSV advisory database.

pip-audit and Dependabot do not see the browser code vendored under
app/static/vendor/ (listed in its manifest.json), so this script asks OSV
(https://osv.dev, ecosystem npm) about every package@version the manifest
ships, plus the libraries a file's "bundles" field names.
Libraries built into a file but not named there are not checked.

Blocking like pip-audit: an advisory fails the check unless ACCEPTED lists it
for that package and version, with a reason and a review date. An acceptance
holds through its review date and fails again afterwards, so an exception
cannot outlive its reason unnoticed (docs/patch-policy.md).

Exit codes: 0 no advisory, or all accepted; 1 an advisory that is not
accepted or whose review date has passed; 2 the check could not run
(manifest unreadable, OSV unreachable, or an OSV answer that is paginated,
incomplete or malformed - never read as "no advisory").
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import urllib.request
from pathlib import Path

MANIFEST = Path(__file__).resolve().parents[1] / "app" / "static" / "vendor" / "manifest.json"
OSV_QUERYBATCH = "https://api.osv.dev/v1/querybatch"

# Advisories accepted for now: the package and version they hit, why they do
# not apply or cannot be fixed yet, and the date by which to look again.
_DOMPURIFY_IN_SWAGGER_UI = (
    "Bundled in Swagger UI 5.33.1 (/docs). Needs DOMPurify's IN_PLACE mode, "
    "which Swagger UI does not use. Fixed in swagger-ui-dist 5.34.0 "
    "(published 2026-10-19), adopted once it is two weeks old "
    "(maintainer decision 2026-10-20)."
)
ACCEPTED = [
    {
        "id": "GHSA-6688-9rhm-gjv2",
        "package": "dompurify",
        "version": "3.4.13",
        "reason": _DOMPURIFY_IN_SWAGGER_UI,
        "review_by": "2026-11-02",
    },
    {
        "id": "GHSA-p98j-92pf-mc4p",
        "package": "dompurify",
        "version": "3.4.13",
        "reason": _DOMPURIFY_IN_SWAGGER_UI,
        "review_by": "2026-11-02",
    },
]


def packages(manifest: dict) -> list[tuple[str, str]]:
    """Every distinct (package, version) the manifest names, bundles included."""
    found = set()
    for entry in manifest["files"]:
        found.add((entry["package"], entry["version"]))
        bundles = entry.get("bundles", {})
        if not isinstance(bundles, dict):
            raise ValueError(f"'bundles' of {entry['package']} is not an object")
        found.update(bundles.items())
    return sorted(found)


def query_osv(pkgs: list[tuple[str, str]]) -> dict[tuple[str, str], list[str]]:
    """Advisory ids per (package, version), from one OSV batch query.

    Raises ValueError for any answer that cannot be read as complete: a
    missing or short result list, a paginated result (next_page_token) or a
    malformed entry. A partial answer must never pass as "no advisory".
    """
    queries = [{"package": {"name": name, "ecosystem": "npm"}, "version": v} for name, v in pkgs]
    request = urllib.request.Request(
        OSV_QUERYBATCH,
        data=json.dumps({"queries": queries}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    results = payload.get("results") if isinstance(payload, dict) else None
    if not isinstance(results, list) or len(results) != len(pkgs):
        raise ValueError(f"OSV answer has no result list for the {len(pkgs)} queries")
    advisories = {}
    for (name, version), result in zip(pkgs, results):
        if not isinstance(result, dict) or result.get("next_page_token"):
            raise ValueError(f"OSV answer for {name}@{version} is paginated or malformed")
        vulns = result.get("vulns", [])
        if not isinstance(vulns, list) or not all(
            isinstance(vuln, dict) and isinstance(vuln.get("id"), str) for vuln in vulns
        ):
            raise ValueError(f"OSV answer for {name}@{version} is malformed")
        advisories[(name, version)] = sorted(vuln["id"] for vuln in vulns)
    return advisories


def run(manifest: dict, fetch, today: dt.date, accepted: list[dict]) -> tuple[int, list[str]]:
    """Exit code and report lines for one check."""
    try:
        pkgs = packages(manifest)
        findings = fetch(pkgs)
    except Exception as exc:  # noqa: BLE001 - fail closed: anything that stops the check is exit 2
        return 2, [f"ERROR: the check could not run: {exc!r}"]

    by_key = {(a["package"], a["version"], a["id"]): a for a in accepted}
    used: set[tuple[str, str, str]] = set()
    lines = ["Checked against OSV: " + ", ".join(f"{name}@{v}" for name, v in pkgs)]
    failing = []
    for (name, version), ids in sorted(findings.items()):
        for vuln_id in ids:
            where = f"{name}@{version}: {vuln_id} (https://osv.dev/vulnerability/{vuln_id})"
            acceptance = by_key.get((name, version, vuln_id))
            if acceptance is None:
                failing.append(f"FAIL: {where} is not accepted")
                continue
            used.add((name, version, vuln_id))
            review_by = dt.date.fromisoformat(acceptance["review_by"])
            if review_by < today:
                failing.append(f"FAIL: {where} review date {review_by} has passed")
            else:
                lines.append(f"accepted until {review_by}: {where} - {acceptance['reason']}")
    for name, version, vuln_id in sorted(set(by_key) - used):
        lines.append(
            f"note: {vuln_id} for {name}@{version} is no longer reported; remove it from ACCEPTED"
        )
    lines.extend(failing)
    return (1 if failing else 0), lines


def main() -> int:
    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"ERROR: could not read {MANIFEST}: {exc}", file=sys.stderr)
        return 2
    today = dt.datetime.now(dt.timezone.utc).date()
    code, lines = run(manifest, query_osv, today, ACCEPTED)
    for line in lines:
        print(line)
    return code


if __name__ == "__main__":
    sys.exit(main())
