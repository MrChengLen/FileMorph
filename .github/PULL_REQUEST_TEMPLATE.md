<!--
  Thanks for contributing to FileMorph! This checklist mirrors the project's
  standards. It is a reminder, not a hard gate — but the CI gates below
  (ruff, tests, pip-audit, gitleaks, scope-guard, veraPDF) WILL block the
  merge until they are green. See CONTRIBUTING.md for details.
-->

## Summary

<!-- What does this PR change, and why? Link any related issue. -->

## Type of change

- [ ] Bug fix (`fix:`)
- [ ] New feature (`feat:`)
- [ ] Documentation (`docs:`)
- [ ] Build / CI / chore (`build:` / `ci:` / `chore:`)
- [ ] Refactor (`refactor:`)

## Checklist

**Code quality (CI will enforce these):**
- [ ] `ruff check .` passes
- [ ] `ruff format --check .` passes
- [ ] `pytest tests/` passes locally
- [ ] New `.py` files carry the `# SPDX-License-Identifier: AGPL-3.0-or-later` header

**Tests & docs (reviewer will check these):**
- [ ] New behaviour has tests (at minimum one test per new converter / route)
- [ ] Docs updated **in the same PR** (`README.md`, `docs/*`) where user-visible behaviour changed
- [ ] `CHANGELOG.md` `[Unreleased]` updated for any user-visible change

**Scope & privacy (the repo is public):**
- [ ] No operations/secrets in the diff — no server paths, deploy hosts, secret *values*, or private personal data
- [ ] No business-internal/strategy content (those belong in the gitignored internal area, never in this public repo)
- [ ] No hardcoded SaaS specifics in app code (domain, prices, SMTP host, e-mail addresses) — read them from settings instead

**Templates (only if you touched `app/templates/*`):**
- [ ] No inline `onclick` / `onchange` / `onsubmit` / inline `<script>` — event handlers live in external `.js` via `addEventListener` (CSP)

**Network / cross-origin (only if you added or changed an upload route, subdomain, or cross-origin call) — the "quadruple-check":**
- [ ] CSP `connect-src` / `script-src` updated (`app/main.py::_build_csp_header`)
- [ ] `CORS_ORIGINS` semantics considered
- [ ] `expose_headers` updated for any response header read by client JS (`app/main.py`)
- [ ] `.env.example` + `docs/self-hosting.md` updated so the new knob is discoverable

## Test plan

<!--
  How did you verify this? Paste the relevant output, e.g.:
  - ruff check . — clean
  - pytest tests/ — N passed
  - manual steps you ran
-->
