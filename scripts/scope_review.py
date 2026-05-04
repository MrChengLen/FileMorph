# SPDX-License-Identifier: AGPL-3.0-or-later
"""Active scope-review on staged changes — App-repo vs. Ops-repo advisory.

Complements the hard scope-guard in ``.githooks/pre-commit`` (which BLOCKS
forbidden paths and ops-only patterns) with a SOFT advisory that surfaces
*subtle* scope drift: content that compiles, lints, and ships fine but
quietly assumes the upstream SaaS deployment (filemorph.io). A self-hoster
running the OSS image with these defaults inherits our SaaS URL in their
structured data, sees Stripe-gated routes they can't serve, etc.

Output is intentionally informational — exit-code 0 always — because the
user wants *visibility* before a commit, not yet another hard gate. The
existing 4-layer scope-guard remains the enforcement boundary; this tool
is a final "did you mean to ship this on the public OSS repo?" prompt.

Each finding states the App-repo vs. Ops-repo routing rationale explicitly,
so the user can answer "which repo should this go in?" at glance time, not
hunt for the rule in CLAUDE.md.

Invoked from ``.githooks/pre-commit`` after the hard-gate checks pass.
Run manually: ``python scripts/scope_review.py``.
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    """A single advisory pattern.

    ``pattern`` matches an added line. ``label`` is shown next to the file:line.
    ``why`` is the reason this is a scope concern. ``route`` answers
    'App-repo (OSS) or Ops-repo (SaaS)?' explicitly. ``fix`` is the suggested
    code-level remediation.
    """

    pattern: re.Pattern[str]
    label: str
    why: str
    route: str
    fix: str


# Files that are *expected* to mention filemorph.io etc. — the upstream
# repo URL appears legitimately in these places (link from a self-hoster's
# README to the canonical project, license headers referencing the
# upstream repo, the og-image generator's GitHub-target footer).
EXEMPT_PATHS = re.compile(
    r"^(README\.md|CLAUDE\.md|COMMERCIAL-LICENSE\.md|CHANGELOG\.md|"
    r"docs/.*\.md|tests/.*|app/templates/(impressum|privacy|terms)\.html|"
    r"app/templates/base\.html|"  # nav/footer linking to upstream is expected
    r"scripts/scope_review\.py|\.githooks/.*)$"
)


RULES: list[Rule] = [
    Rule(
        pattern=re.compile(r"https?://(www\.)?filemorph\.io"),
        label="hardcoded SaaS URL",
        why=(
            "this URL points at the upstream SaaS — a self-hoster running "
            "the OSS image inherits our domain in whatever surface this "
            "renders to (JSON-LD, redirect target, email link, og-image)"
        ),
        route=(
            "→ App-repo OK only if this is in a docstring or a comment "
            "linking to the upstream project. → Ops-repo if it's the "
            "deployment URL. In code, use settings.app_base_url instead"
        ),
        fix="source from settings.app_base_url or templates.env.globals['app_base_url']",
    ),
    Rule(
        pattern=re.compile(r'"@type"\s*:\s*"(WebApplication|SoftwareApplication|Organization)"'),
        label="JSON-LD structured-data block",
        why=(
            "structured data must point at the *deployment's* canonical "
            "origin, not the upstream SaaS — Google attributes Knowledge "
            "Graph entries to whatever URL is in the 'url' field"
        ),
        route=(
            "→ App-repo with deployment-agnostic builder (e.g. "
            "build_site_jsonld(settings.app_base_url)). → never hardcode"
        ),
        fix="use a function that takes app_base_url, called at startup in main.py",
    ),
    Rule(
        pattern=re.compile(r'["\']/(pricing|upgrade|billing/checkout|billing/portal)["\']'),
        label="Stripe-gated route",
        why=(
            "this route only works when stripe_secret_key is configured. "
            "On a Stripe-less self-host it 404s or shows an inert page — "
            "indexing it in a sitemap or linking it from nav misleads users"
        ),
        route=(
            "→ App-repo OK if guarded by `if settings.stripe_secret_key`. "
            "→ if always-on, it's an Ops-repo concern (filemorph.io-only)"
        ),
        fix="wrap with `if settings.stripe_secret_key:` or feature-flag the link",
    ),
    Rule(
        pattern=re.compile(r"€\s*\d+(\.\d+)?\s*/\s*(mo|month|yr|year)", re.IGNORECASE),
        label="hardcoded price/currency",
        why=(
            "pricing is SaaS-specific; baking it into templates locks the "
            "deployment to EUR and to our specific tier amounts"
        ),
        route=(
            "→ App-repo OK only on /pricing page (which is itself "
            "Stripe-gated). → Ops-repo if it's marketing copy"
        ),
        fix="read from settings or a config dict, not a literal in the template",
    ),
    Rule(
        pattern=re.compile(r"smtp\.(zoho|gmail|sendgrid|mailgun)\."),
        label="hardcoded SMTP host",
        why=(
            "SMTP host is per-deployment config — a self-hoster will use "
            "their own provider, not ours"
        ),
        route="→ App-repo never. → Ops-repo or settings.smtp_host only",
        fix="read from settings.smtp_host",
    ),
    Rule(
        pattern=re.compile(r"\bhetzner\b|\bCX\d{2}\b|\bFrankfurt\b", re.IGNORECASE),
        label="Hetzner/EU-hosting reference",
        why=(
            "deployment infrastructure is Ops-specific. Marketing claims "
            "about EU-hosting belong in the README/landing copy, not in "
            "behavioural code"
        ),
        route=(
            "→ App-repo OK in README/landing copy as positioning. → "
            "Ops-repo if it's a code-path assumption (server-class, region)"
        ),
        fix="if marketing copy: leave in README only. If config: move to Ops",
    ),
    Rule(
        pattern=re.compile(r"\b(no-reply|hallo|admin|support)@filemorph\.io\b"),
        label="hardcoded SaaS email address",
        why=(
            "From/Reply-To addresses are deployment-specific — a self-"
            "hoster's outbound mail must use their own domain"
        ),
        route="→ App-repo never as a literal. → Ops-repo or settings.smtp_*",
        fix="source from settings.smtp_from_email / settings.smtp_reply_to",
    ),
    Rule(
        pattern=re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
        label="literal IPv4 address",
        why=(
            "IPs are server/operations-specific — appearing in app code "
            "almost always means a hardcoded prod host snuck in"
        ),
        route="→ Ops-repo. → App-repo only as test fixture (127.0.0.1, 0.0.0.0)",
        fix="if not a localhost loopback, move to env var / settings / Ops-repo",
    ),
]


@dataclass(frozen=True)
class Finding:
    file: str
    line_no: int
    line: str
    rule: Rule


def _staged_added_lines() -> list[tuple[str, int, str]]:
    """Return ``(file, line_no, line)`` for every '+' line in the staged diff.

    Uses ``git diff --cached -U0`` for tight hunks, then walks the unified-diff
    headers to track the current file + line number. Skips '+++' file-header
    lines and binary-file diffs.
    """
    proc = subprocess.run(
        ["git", "diff", "--cached", "-U0", "--no-color", "--diff-filter=ACM"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return []

    out: list[tuple[str, int, str]] = []
    current_file: str | None = None
    current_line = 0

    for raw in proc.stdout.splitlines():
        if raw.startswith("+++ b/"):
            current_file = raw[6:]
            current_line = 0
            continue
        if raw.startswith("+++") or raw.startswith("---"):
            continue
        if raw.startswith("@@"):
            # @@ -a,b +c,d @@ — capture the +c (start line on the new side)
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", raw)
            current_line = int(m.group(1)) if m else 0
            continue
        if raw.startswith("+") and current_file is not None:
            out.append((current_file, current_line, raw[1:]))
            current_line += 1
        elif raw.startswith(" ") and current_file is not None:
            current_line += 1
    return out


def _scan(lines: list[tuple[str, int, str]]) -> list[Finding]:
    findings: list[Finding] = []
    for path, lineno, line in lines:
        if EXEMPT_PATHS.match(path):
            continue
        for rule in RULES:
            if rule.pattern.search(line):
                findings.append(Finding(path, lineno, line.rstrip(), rule))
    return findings


def _format(findings: list[Finding]) -> str:
    if not findings:
        return (
            "[scope-review] No App-repo/Ops-repo concerns spotted in staged "
            "diff. (Hard scope-guard ran in pre-commit; this is the soft "
            "advisory layer.)\n"
        )
    parts: list[str] = [
        f"[scope-review] {len(findings)} advisory finding"
        f"{'s' if len(findings) != 1 else ''} on staged changes:",
        "",
        "  Question to ask: 'Should this content ship to every self-hoster",
        "  via the public OSS repo, or is it filemorph.io-specific?'",
        "",
    ]
    for f in findings:
        parts.extend(
            [
                f"  {f.file}:{f.line_no}  {f.rule.label}",
                f"    + {f.line.strip()}",
                f"    why:   {f.rule.why}",
                f"    route: {f.rule.route}",
                f"    fix:   {f.rule.fix}",
                "",
            ]
        )
    parts.append(
        "[scope-review] Informational only — the commit will proceed. "
        "Override findings as needed; bypass with `--no-verify` only when "
        "explicitly authorized."
    )
    return "\n".join(parts) + "\n"


def main() -> int:
    findings = _scan(_staged_added_lines())
    sys.stderr.write(_format(findings))
    # Always exit 0 — this layer is advisory, not enforcement.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
