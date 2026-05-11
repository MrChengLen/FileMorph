# SPDX-License-Identifier: AGPL-3.0-or-later
"""Regression guard for the .githooks/pre-commit + .githooks/pre-push allow/deny regexes (H4).

The two scope-guard hooks share three regexes — ``ALLOW_RE``, ``FORBIDDEN_PATHS``,
and ``INTERNAL_PATHS`` — that decide whether content-pattern checks fire and
whether a file is hard-blocked. Silent regressions in these regexes are the
worst kind: a hook that lets a leak through (FN) is dangerous, but a hook
that suddenly blocks every i18n update (FP) is just as bad — the developer
gets a rejection on every push, blames their content, doesn't realise the
allowlist itself has drifted.

This test extracts each regex literally from the hook script, compiles it
with Python's ``re`` (POSIX ERE is a subset of Python regex for the patterns
we use here), and pins the contract:

- Files that MUST be allowed (locale/*.po, the impressum/privacy/terms HTML
  templates, ``.env.example``, the public DPA template, etc.) match
  ``ALLOW_RE``. A future commit that drops one of these silently breaks
  the corresponding workflow (i18n update, GDPR doc edit, ...).
- Files that MUST be forbidden in the public repo (``CLAUDE.md`` at root,
  ``compose.prod.yml``, ``runbooks/...``, ``docs-internal/...``) match
  ``FORBIDDEN_PATHS``.
- Internal docs that MUST land in ``docs-internal/`` (admin-cockpit,
  email-setup, runbook, marketing-plan, ...) match ``INTERNAL_PATHS``.

The pre-commit and pre-push hooks share the same regex strings; the test
also enforces that they stay in sync, since drift between them would let
``--no-verify`` bypass the local hook AND defeat the pre-push backstop.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PRE_COMMIT = REPO / ".githooks" / "pre-commit"
PRE_PUSH = REPO / ".githooks" / "pre-push"


def _extract_var(script: str, var: str) -> str:
    """Pull the single-quoted assignment for ``var`` out of the shell script.

    The hooks declare each pattern as a one-line ``VAR='regex'`` assignment;
    we match exactly that and return the regex (without surrounding quotes).
    Multi-line values would defeat this — keep the hook formatting tight.
    """
    m = re.search(rf"^{re.escape(var)}='([^']+)'", script, re.MULTILINE)
    if m is None:
        raise AssertionError(f"could not find {var}= assignment in hook script")
    return m.group(1)


@pytest.fixture(scope="module")
def hooks() -> dict[str, dict[str, str]]:
    """Load both hook scripts and extract the three regexes from each."""
    pre_commit_text = PRE_COMMIT.read_text(encoding="utf-8")
    pre_push_text = PRE_PUSH.read_text(encoding="utf-8")
    return {
        "pre-commit": {
            "ALLOW_RE": _extract_var(pre_commit_text, "ALLOW_RE"),
            "FORBIDDEN_PATHS": _extract_var(pre_commit_text, "FORBIDDEN_PATHS"),
            "INTERNAL_PATHS": _extract_var(pre_commit_text, "INTERNAL_PATHS"),
        },
        "pre-push": {
            "ALLOW_RE": _extract_var(pre_push_text, "ALLOW_RE"),
            "FORBIDDEN_PATHS": _extract_var(pre_push_text, "FORBIDDEN_PATHS"),
            "INTERNAL_PATHS": _extract_var(pre_push_text, "INTERNAL_PATHS"),
        },
    }


# ── Drift between the two hooks ─────────────────────────────────────────────


def test_pre_commit_and_pre_push_regexes_stay_in_sync(hooks):
    """If the two hooks drift, ``--no-verify`` defeats the local hook and
    the pre-push backstop scans against a different rule set, leaving
    real gaps. Treat the three regexes as a single source of truth."""
    for var in ("ALLOW_RE", "FORBIDDEN_PATHS", "INTERNAL_PATHS"):
        assert hooks["pre-commit"][var] == hooks["pre-push"][var], (
            f"{var} drifted between pre-commit and pre-push — keep them identical."
        )


# ── ALLOW_RE: paths that MUST be content-scanning-exempt ────────────────────


@pytest.mark.parametrize(
    "path",
    [
        # Locale catalogues — extracted mechanically from impressum/privacy/
        # terms templates which carry the operator's business address. Must stay
        # allowed or every pybabel update is rejected by the hook.
        "locale/de/LC_MESSAGES/messages.po",
        "locale/en/LC_MESSAGES/messages.po",
        "locale/messages.pot",
        "locale/de/LC_MESSAGES/messages.mo",
        # Public legal templates that intentionally contain the operator's
        # business address.
        "app/templates/impressum.html",
        "app/templates/privacy.html",
        "app/templates/terms.html",
        # GDPR / DPA / commercial documents — public, but contain the
        # business address by design.
        "COMMERCIAL-LICENSE.md",
        "docs/gdpr-account-deletion-design.md",
        "docs/api-usage-guide.md",
        "docs/self-hosting.md",
        "docs/dpa-template.md",
        # Public Cloud-Edition email-setup walkthrough — placeholder
        # .env-style SMTP credential lines would otherwise trip the
        # SECRET_ASSIGN content scanner.
        "docs/email-setup.md",
        # Hook scripts and CI workflow self-edits.
        ".githooks/pre-commit",
        ".githooks/pre-push",
        ".github/workflows/scope-guard.yml",
        # Repository-wide manifests that may carry contact info.
        "CHANGELOG.md",
        ".env.example",
        # docs-internal/ is forbidden in PUBLIC commits but content checks
        # don't apply to it (it never lands here at all). Listing it here
        # is for completeness — the FORBIDDEN_PATHS match below blocks it.
        "docs-internal/anything.md",
    ],
)
def test_allow_re_includes_required_path(hooks, path):
    pattern = re.compile(hooks["pre-commit"]["ALLOW_RE"])
    assert pattern.match(path), (
        f"{path} should be in ALLOW_RE — content-pattern scans would otherwise "
        "block legitimate updates (i18n catalogues, address-bearing legal pages, ...)."
    )


@pytest.mark.parametrize(
    "path",
    [
        # Application code: must NOT be allowed; pattern scans must run.
        "app/main.py",
        "app/api/routes/billing.py",
        "app/templates/dashboard.html",
        # Random doc: not address-bearing → no exemption.
        "README.md",
        "docs/threat-model.md",
        # Anything outside the allowlist's literal entries.
        "scripts/i18n.py",
    ],
)
def test_allow_re_excludes_normal_files(hooks, path):
    pattern = re.compile(hooks["pre-commit"]["ALLOW_RE"])
    assert not pattern.match(path), (
        f"{path} should NOT be in ALLOW_RE — content-pattern scans must run on it."
    )


# ── FORBIDDEN_PATHS: ops-only filenames that must never land in public ──────


@pytest.mark.parametrize(
    "path",
    [
        "compose.prod.yml",
        "deploy.sh",
        ".env.production",
        ".env.production.example",
        "CLAUDE.md",
        "runbooks/architecture-two-repo.md",
        "runbooks/anything-else.md",
        "docs-internal/whatever.md",
    ],
)
def test_forbidden_paths_blocks_ops_artifacts(hooks, path):
    pattern = re.compile(hooks["pre-commit"]["FORBIDDEN_PATHS"])
    assert pattern.search(path), (
        f"{path} should match FORBIDDEN_PATHS — ops-only artifact must never land in public repo."
    )


@pytest.mark.parametrize(
    "path",
    [
        # Public docker-compose for self-hosters.
        "compose.yml",
        # Deploy script in scripts/ is fine (only top-level deploy.sh is forbidden).
        "scripts/deploy.py",
        # Public env example.
        ".env.example",
        # Application code — must not be forbidden.
        "app/main.py",
        # Public docs.
        "docs/self-hosting.md",
    ],
)
def test_forbidden_paths_does_not_block_public_artifacts(hooks, path):
    pattern = re.compile(hooks["pre-commit"]["FORBIDDEN_PATHS"])
    assert not pattern.search(path), (
        f"{path} should NOT match FORBIDDEN_PATHS — public asset incorrectly blocked."
    )


# ── INTERNAL_PATHS: docs/ files that must move to docs-internal/ ────────────


@pytest.mark.parametrize(
    "path",
    [
        "docs/admin-cockpit.md",
        "docs/open-tasks.md",
        "docs/filemorph-io-runbook.md",
        "docs/marketing-plan.md",
        "docs/seo-strategy.md",
        "docs/business-case.md",
        "docs/claims-audit.md",
        "docs/launch-gate-snapshot.md",
        "docs/launch-readiness-tracker.md",
        "docs/seo-audit.md",
        "docs/user-acquisition-strategy.md",
        "docs/requirements-v2.md",
        "docs/sprint-5-multi-file-plan.md",
    ],
)
def test_internal_paths_redirects_business_docs(hooks, path):
    pattern = re.compile(hooks["pre-commit"]["INTERNAL_PATHS"])
    assert pattern.match(path), (
        f"{path} should match INTERNAL_PATHS — business/ops doc must land in docs-internal/."
    )


@pytest.mark.parametrize(
    "path",
    [
        # Public docs the self-hoster needs.
        "docs/self-hosting.md",
        "docs/api-reference.md",
        "docs/api-usage-guide.md",
        "docs/threat-model.md",
        "docs/security-overview.md",
        "docs/sub-processors.md",
        "docs/dpa-template.md",
        "docs/gdpr-account-deletion-design.md",
        # Reclassified from internal → public when the
        # deployment-agnostic Self-Hoster walkthrough was added.
        "docs/email-setup.md",
    ],
)
def test_internal_paths_keeps_public_docs(hooks, path):
    pattern = re.compile(hooks["pre-commit"]["INTERNAL_PATHS"])
    assert not pattern.match(path), (
        f"{path} should NOT match INTERNAL_PATHS — public doc incorrectly redirected."
    )
