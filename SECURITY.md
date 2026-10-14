# Security policy

FileMorph takes security seriously. This document describes how to report a
vulnerability and what response you can expect. The same policy is mirrored at
[`/security`](https://github.com/MrChengLen/FileMorph/blob/main/app/templates/security.html)
in any running deployment, and discoverable via
[`/.well-known/security.txt`](https://datatracker.ietf.org/doc/html/rfc9116) on
each instance.

## Supported versions

The newest tagged release is v1.2.0 (October 2026); the one before it is
v1.1.0 (2026-06-01). Security fixes are made on the `main` branch first; the
`latest` and `office` container images are rebuilt from `main` on every merge,
and the next tagged release carries the fixes. Self-hosters pinned to an
older `vX.Y` line can request a backport of a Critical or High fix onto that
line (write to `security@filemorph.io` with the version, see
[`docs/support-sla.md`](docs/support-sla.md)); otherwise users are expected to
upgrade to the newest release or `main`.

## Reporting a vulnerability

**Email `security@filemorph.io`.** Encrypted mail is welcome — request our PGP
key at the same address. Please do not file vulnerability reports as public
GitHub issues.

### What to include

- A description of the vulnerability and its potential impact.
- Steps to reproduce, with any required configuration or input files.
- Affected version (commit hash or release tag if known).
- Whether the issue has already been disclosed publicly elsewhere.

## Our response

| Stage | Target |
|---|---|
| Acknowledgement | within 72 hours of receipt |
| Initial triage + severity | within 7 days |
| Critical fix released | within 7 days of triage |
| High-severity fix released | within 30 days |
| Medium / low | fixed on `main`; part of the next tagged release |

We publish an advisory once a fixed release is available and credit the
reporter unless they request otherwise.

These targets apply to **vulnerability reports from anyone**, paid or not.
Compliance Edition licensees can additionally contract a **support SLA** for
non-security issues (deployment, configuration, defects) — the framework is in
[`docs/support-sla.md`](docs/support-sla.md), the figures are set per agreement.
A paid SLA buys priority *attention*; it does not change the security-fix clock
above, which applies to everyone.

## Scope

**In scope:**

- The FileMorph application source in this repository.
- Official Docker images and release artifacts published by the maintainers.
- Documented API endpoints and the bundled web UI.

**Out of scope:**

- Third-party services FileMorph depends on (Stripe, Zoho, Cloudflare,
  Hetzner). Please report to those vendors directly.
- Issues that require physical access to a self-hosted server, or social
  engineering of an operator.
- Reports generated only by automated scanners without a working
  proof-of-concept.
- Self-hoster-specific deployment misconfiguration not caused by our defaults
  or documentation.

## Safe harbour

Good-faith research in line with this policy will not result in legal action
from the FileMorph project. Please avoid privacy violations, service
disruption, and destruction of data; test against your own self-hosted
instance whenever possible.
