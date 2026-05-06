# Security policy

FileMorph takes security seriously. This document describes how to report a
vulnerability and what response you can expect. The same policy is mirrored at
[`/security`](https://github.com/MrChengLen/FileMorph/blob/main/app/templates/security.html)
in any running deployment, and discoverable via
[`/.well-known/security.txt`](https://datatracker.ietf.org/doc/html/rfc9116) on
each instance.

## Supported versions

We provide security fixes for the latest minor release on the `main` branch.
Older tags receive fixes only when the issue is critical and the upgrade path
is non-trivial; otherwise users are expected to upgrade.

## Reporting a vulnerability

**Preferred channel:** open a private
[GitHub Security Advisory](https://github.com/MrChengLen/FileMorph/security/advisories/new)
on this repository. This routes the report directly to the maintainers, lets
us coordinate a CVE if needed, and gives us a private place to discuss a fix
before disclosure.

**Alternative channel:** email `security@filemorph.io`. Encrypted mail is
welcome — request our PGP key at the same address. Please do not file
vulnerability reports as public GitHub issues.

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
| Medium / low | bundled into the next regular release |

We publish an advisory once a fixed release is available and credit the
reporter unless they request otherwise.

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
