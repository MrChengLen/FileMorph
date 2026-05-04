# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for ``scripts/scope_review.py`` — the soft advisory layer.

Pins the rule semantics so that a pattern regression (or the rule list
silently drifting) trips CI rather than disappearing into a dev's local
hook output. Doesn't drive the actual git-diff parser — that's covered
implicitly by ``_staged_added_lines`` running against real diffs in CI.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# scripts/ isn't a package; import scope_review.py directly.
_SPEC = importlib.util.spec_from_file_location(
    "scope_review", Path("scripts/scope_review.py").resolve()
)
assert _SPEC and _SPEC.loader
scope_review = importlib.util.module_from_spec(_SPEC)
sys.modules["scope_review"] = scope_review
_SPEC.loader.exec_module(scope_review)


def _scan(lines: list[tuple[str, int, str]]) -> list[scope_review.Finding]:
    return scope_review._scan(lines)


# ── Positive cases — the patterns we want to flag ────────────────────────────


def test_hardcoded_saas_url_is_flagged():
    findings = _scan([("app/api/routes/billing.py", 1, '    url = "https://filemorph.io"')])
    assert len(findings) == 1
    assert findings[0].rule.label == "hardcoded SaaS URL"


def test_jsonld_typed_block_is_flagged():
    findings = _scan(
        [("app/core/jsonld.py", 1, '    {"@type": "WebApplication", "name": "FileMorph"}')]
    )
    assert any(f.rule.label == "JSON-LD structured-data block" for f in findings)


def test_pricing_route_is_flagged():
    findings = _scan([("app/api/routes/seo.py", 1, '    routes.append(("/pricing", "0.8"))')])
    assert any(f.rule.label == "Stripe-gated route" for f in findings)


def test_hardcoded_price_is_flagged():
    findings = _scan([("app/templates/pricing.html", 1, "    <span>€7/mo</span>")])
    assert any(f.rule.label == "hardcoded price/currency" for f in findings)


def test_smtp_host_is_flagged():
    findings = _scan([("app/core/email.py", 1, '    host = "smtp.zoho.eu"')])
    assert any(f.rule.label == "hardcoded SMTP host" for f in findings)


def test_saas_email_is_flagged():
    findings = _scan([("app/core/auth.py", 1, '    sender = "no-reply@filemorph.io"')])
    assert any(f.rule.label == "hardcoded SaaS email address" for f in findings)


def test_ipv4_literal_is_flagged():
    findings = _scan([("app/main.py", 1, '    host = "203.0.113.42"')])
    assert any(f.rule.label == "literal IPv4 address" for f in findings)


# ── Exempt paths — patterns are allowed in these places ───────────────────────


def test_readme_is_exempt_from_saas_url_rule():
    findings = _scan([("README.md", 1, "Visit https://filemorph.io to try the hosted version.")])
    assert findings == []


def test_docs_md_is_exempt():
    findings = _scan([("docs/self-hosting.md", 1, "Upstream: https://filemorph.io")])
    assert findings == []


def test_tests_directory_is_exempt():
    findings = _scan([("tests/test_x.py", 1, 'assert "https://filemorph.io" in body')])
    assert findings == []


def test_base_html_template_is_exempt_for_legitimate_upstream_links():
    """``base.html`` carries the GitHub-link in nav/footer — that's expected."""
    findings = _scan(
        [("app/templates/base.html", 1, '    <a href="https://filemorph.io">Upstream</a>')]
    )
    assert findings == []


# ── Output formatting ────────────────────────────────────────────────────────


def test_format_with_no_findings_states_clean():
    out = scope_review._format([])
    assert "No App-repo/Ops-repo concerns" in out


def test_format_with_findings_includes_route_guidance():
    """Each finding must show the App-repo vs. Ops-repo routing guidance —
    that's the whole point of the tool: making the routing decision visible
    at commit time."""
    findings = _scan([("app/api/routes/billing.py", 1, '    url = "https://filemorph.io"')])
    out = scope_review._format(findings)
    assert "App-repo" in out and "Ops-repo" in out
    assert "fix:" in out
    assert "why:" in out


# ── main() exit code ──────────────────────────────────────────────────────────


def test_main_returns_zero_even_with_findings(monkeypatch):
    """The advisory layer never blocks. Exit code must stay 0 regardless of
    findings — the hard scope-guard is the only blocker."""

    def fake_lines() -> list[tuple[str, int, str]]:
        return [("app/api/routes/billing.py", 1, '    url = "https://filemorph.io"')]

    monkeypatch.setattr(scope_review, "_staged_added_lines", fake_lines)
    assert scope_review.main() == 0
