# Support & Security

This document defines what response and patch commitments come with FileMorph.
It is written for three audiences:

- **Self-hosters** deciding what the difference is between running the free
  AGPL build and buying a Compliance Edition licence.
- **Compliance Edition prospects and customers** who need to understand the
  support model before there is a contract, and the exact wording once there is.
- **Procurement reviewers** assessing whether the upstream support and patch
  cadence is compatible with their requirements (EVB-IT, KRITIS, hospital B3S,
  Kanzlei IT policies).

> **Status.** Two different things live here, and only one of them is a standing
> commitment:
>
> - The **security-fix timeline** (below) is the project's existing, published
>   commitment. It applies to **every deployment**, free or paid, and is not
>   conditional on anything.
> - A **Compliance Edition support SLA** is **not yet a standing service
>   level**. The Compliance Edition is in its design-partner phase; until a
>   commercial agreement is signed there is no support SLA in force. The support
>   level — response windows, coverage hours, escalation — is set **individually
>   in each commercial agreement**. The framework further down describes the
>   *shape* such an agreement takes; it is not a published figure you can rely
>   on without a contract.

## Two things, kept separate

Do not conflate them:

| | **Security-fix timeline** | **Support SLA** |
|---|---|---|
| Applies to | **Everyone** — AGPL/free and paid alike | **Compliance Edition licensees**, per their agreement |
| Status | Published, standing commitment | Negotiated per agreement; no standing level yet (design-partner phase) |
| Measures | How fast a *confirmed vulnerability* gets a patched release | How fast a *human* acknowledges and starts work on your ticket |
| Defined by | [`SECURITY.md`](../SECURITY.md) + [`patch-policy.md`](./patch-policy.md) | The individual commercial agreement; this document gives the framework |
| Note | — | A paid SLA buys priority *attention*; it does not shorten the security-fix clock |

## What every deployment gets (AGPL / free)

Running the open-source build under AGPL-3.0 — self-hosted, unmodified or
forked — you get:

- **Public release notes, signed images, and an SBOM per release** — see
  [`patch-policy.md`](./patch-policy.md) and [`release-signing.md`](./release-signing.md).
- **GitHub Security Advisories** for Critical and High issues, out-of-band from
  the regular release cycle.
- **Best-effort community support** via GitHub issues and discussions. Bug
  reports with a reproduction are triaged; there is **no guaranteed response
  time**, no private channel, and no escalation path.
- **The vulnerability-disclosure process** in [`SECURITY.md`](../SECURITY.md)
  (acknowledgement target 72 h, triage target 7 days) — this applies to
  everyone, paid or not, because a vulnerability in the open-source code is a
  vulnerability for every deployment.

## Security-fix timeline (all users)

This is the existing published commitment from [`SECURITY.md`](../SECURITY.md)
and [`patch-policy.md`](./patch-policy.md), repeated here for the contrast.
After an issue is triaged and confirmed (severity by CVSS v3.x base score):

| Severity | CVSS | Patched release within |
|---|---|---|
| Critical | 9.0 – 10.0 | 7 days |
| High | 7.0 – 8.9 | 30 days |
| Medium | 4.0 – 6.9 | next regular release |
| Low | 0.1 – 3.9 | next regular release |

A *regular release* historically lands every 1–4 weeks. Self-hosters who pin to
a `vX.Y` line and cannot take the latest `main` tag can request a backport of a
Critical/High fix onto that line — contact `security@filemorph.io` with the
version; see [`patch-policy.md`](./patch-policy.md) for the release-line model.
(For Enterprise / KRITIS agreements, backports onto a fixed version line plus
offline-update tooling are part of the contract — see
[`COMMERCIAL-LICENSE.md`](../COMMERCIAL-LICENSE.md).)

## Compliance Edition support — the framework

> No standing SLA yet (design-partner phase). The points below describe what a
> commercial agreement *typically contains*, as a starting point for that
> conversation — not a service level in force today.

### What "support" covers

A licensed support relationship covers: deployment and upgrade questions,
configuration help, defect triage and fixes, **priority notification** of
security advisories (ahead of public disclosure, on request), and guidance on
the compliance artefacts you are relying on — the audit-log hash chain, the
CycloneDX SBOM, the cosign image signatures, the PDF/A-2b conformance gate, and
the [DPA template](./dpa-template.md) / [sub-processor list](./sub-processors.md).

### Severity model for a support ticket

This severity model is stable regardless of contract — it describes *your
incident*, not the CVSS of a vulnerability (the two scales are independent):

| Severity | Definition |
|---|---|
| **P1 — Critical** | A production deployment is down or unusable; a data-integrity problem; or a security incident in your running instance. |
| **P2 — High** | A core conversion/compression path or the API is broken with no workaround; severe degradation under normal load. |
| **P3 — Medium** | A defect with a viable workaround; a non-blocking bug; a configuration that behaves contrary to the docs. |
| **P4 — Low** | A question, a documentation gap, a cosmetic issue, or a feature request. |

### What a commercial agreement sets

Each agreement fixes its own figures; there is no published grid. Typically an
agreement specifies:

- **An acknowledgement / first-response window per severity** — "response" meaning
  a human acknowledges and begins triage, not "resolved". Resolution of a code
  defect then follows the security-fix timeline above (if it is a vulnerability)
  or the regular release cadence (if it is a functional bug). Higher tiers
  contract shorter windows.
- **Coverage hours** — by default business hours (Monday–Friday, working hours,
  Europe/Berlin, excluding German federal public holidays); extendable, up to
  24×7 for Enterprise / KRITIS.
- **A named contact and escalation path** — for Standard and above; for
  Enterprise / KRITIS the escalation sequence (contact, secondary contact,
  interval at each step) is written into the agreement, alongside the
  extras already named in [`COMMERCIAL-LICENSE.md`](../COMMERCIAL-LICENSE.md)
  (offline-update tooling, the dedicated reaction-time commitment,
  patch-backports onto a fixed version line).

### Channels

- **Email:** `support@filemorph.io` — for any licensed customer.
- **Dedicated contact:** named in the agreement for Standard and above; a named
  escalation path for Enterprise / KRITIS.
- **Security incidents** always *also* go through `security@filemorph.io` or a
  private [GitHub Security Advisory](https://github.com/MrChengLen/FileMorph/security/advisories/new),
  per [`SECURITY.md`](../SECURITY.md) — the security-disclosure process runs in
  parallel with, not instead of, any support arrangement.

## What support does not cover

- Writing your custom integration code (a citizen-portal embed, a closed-source
  wrapper) — guidance, yes; building it for you, no. The OEM tier covers
  white-label/embed redistribution rights, not bespoke development.
- Issues in third-party services your deployment uses — Hetzner, Stripe, Zoho,
  Cloudflare. Report those to the respective vendor; see
  [`sub-processors.md`](./sub-processors.md).
- Your operating system, container host, network, or hardware outside the
  FileMorph application.
- Performance tuning of your infrastructure (sizing, autoscaling, CDN config).
- 24×7 coverage unless explicitly contracted (Enterprise / KRITIS).
- Training and onboarding beyond the dedicated-onboarding scope of the
  Enterprise tier; ad-hoc training is available as a separate engagement.

## How to raise something

For a **suspected vulnerability** — anyone, paid or not — use the disclosure
channel in [`SECURITY.md`](../SECURITY.md): email `security@filemorph.io` or
open a private GitHub Security Advisory. That routes it correctly and starts the
security-fix clock.

For a **support request** under a commercial agreement, email
`support@filemorph.io` (or your dedicated contact) with:

- Your licence reference / organisation name.
- The severity you believe applies (P1–P4) and why.
- The FileMorph version (release tag or commit hash) and how it is deployed
  (container, behind which reverse proxy, Community vs. configured Cloud
  features).
- A description of the problem and, for a defect, a reproduction or the
  relevant structured log lines (no file contents needed — FileMorph does not
  log them).

Prospective customers wanting to discuss what an agreement would look like:
`licensing@filemorph.io` — see [`COMMERCIAL-LICENSE.md`](../COMMERCIAL-LICENSE.md).

## See also

- [`SECURITY.md`](../SECURITY.md) — vulnerability disclosure policy (all users).
- [`patch-policy.md`](./patch-policy.md) — release lines, versioning, patch
  timelines, dependency hygiene, signing.
- [`incident-response.md`](./incident-response.md) — what happens after a
  vulnerability is confirmed.
- [`security-overview.md`](./security-overview.md) — the controls each patch
  operates against.
- [`COMMERCIAL-LICENSE.md`](../COMMERCIAL-LICENSE.md) — the Compliance Edition
  tiers and what each includes.
